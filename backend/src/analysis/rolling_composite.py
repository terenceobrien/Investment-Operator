"""
Rolling composite historical analogue engine.

Runs the existing single-day analogue lookup across a recent window of market
states, applies exponential recency weights, pools repeated historical matches,
and returns weighted forward-path statistics.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from . import analogues as analogues_mod
from .analogues import (
    MACRO_FORWARD_HORIZONS,
    MACRO_RISK_UNAVAILABLE_WARNING,
    TACTICAL_FORWARD_HORIZONS,
    get_historical_analogues_v2,
    get_historical_analogues,
    forward_window_overlaps_shock,
    _load_df,
    shock_window_diagnostics_for_analogues,
)
from .detailed_analogue_similarity import FeatureSpec


CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "analogue_lookups"
CSV_MTIME_STAMP = CACHE_DIR / ".csv_mtime"
ANALOGUE_CACHE_VERSION = "forward_horizons_v2"
JSON_FIELDS = {"forward_path", "environment_drivers"}
NESTED_PREFIXES = ("forward_returns", "risk_profile", "score_components", "sector_returns")
FORWARD_RETURN_HORIZONS = TACTICAL_FORWARD_HORIZONS + MACRO_FORWARD_HORIZONS
DEFAULT_MACRO_HORIZONS = list(MACRO_FORWARD_HORIZONS)
FLAT_FORWARD_RETURN_DAYS = (1, 5, 21, 63, 126)


def weighted_percentile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    """
    Compute the weighted q-th percentile (q in [0, 100]).
    Sort values, compute cumulative normalized weight, interpolate at q/100.
    """
    if len(values) == 0:
        return float("nan")
    sorter = np.argsort(values)
    values_sorted = values[sorter]
    weights_sorted = weights[sorter]
    cum_weights = np.cumsum(weights_sorted)
    total = cum_weights[-1]
    if total == 0:
        return float("nan")
    cum_norm = (cum_weights - 0.5 * weights_sorted) / total
    return float(np.interp(q / 100.0, cum_norm, values_sorted))


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or pd.isna(value):
            return None
        out = float(value)
        return out if np.isfinite(out) else None
    except Exception:
        return None


def _cache_date_path(date_str: str) -> Path:
    return CACHE_DIR / f"{date_str}.parquet"


def _master_csv_mtime() -> str:
    path = analogues_mod.DATA_PATH
    if not path.exists():
        return f"missing:{ANALOGUE_CACHE_VERSION}"
    return f"{path.stat().st_mtime_ns}:{ANALOGUE_CACHE_VERSION}"


def _ensure_disk_cache_current() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    current = _master_csv_mtime()
    previous = CSV_MTIME_STAMP.read_text(encoding="utf-8").strip() if CSV_MTIME_STAMP.exists() else None
    if previous == current:
        return

    for path in CACHE_DIR.glob("*.parquet"):
        try:
            path.unlink()
        except Exception:
            pass
    CSV_MTIME_STAMP.write_text(current, encoding="utf-8")
    _lookup_for_date.cache_clear()


def _flatten_analogue(row: Dict[str, Any]) -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in row.items():
        if key in JSON_FIELDS:
            flat[f"{key}_json"] = json.dumps(value, default=str)
        elif isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{key}.{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


def _unflatten_analogue(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in row.items():
        if not isinstance(value, (list, dict)):
            try:
                if pd.isna(value):
                    value = None
            except Exception:
                pass
        if key.endswith("_json"):
            target = key[:-5]
            try:
                out[target] = json.loads(value) if value else []
            except Exception:
                out[target] = []
            continue

        if "." in key:
            prefix, sub_key = key.split(".", 1)
            if prefix in NESTED_PREFIXES:
                out.setdefault(prefix, {})[sub_key] = value
                continue
        out[key] = value

    for prefix in ("forward_returns", "risk_profile", "score_components", "sector_returns"):
        out.setdefault(prefix, {})
    out.setdefault("forward_path", [])
    out.setdefault("environment_drivers", [])
    return out


def _load_disk_cache(date_str: str) -> Optional[List[Dict[str, Any]]]:
    _ensure_disk_cache_current()
    path = _cache_date_path(date_str)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        return [_unflatten_analogue(row) for row in df.to_dict(orient="records")]
    except Exception:
        return None


def _save_disk_cache(date_str: str, analogues: List[Dict[str, Any]]) -> None:
    _ensure_disk_cache_current()
    path = _cache_date_path(date_str)
    try:
        rows = [_flatten_analogue(a) for a in analogues]
        pd.DataFrame(rows).to_parquet(path, index=False)
    except Exception:
        # Cache failures should never block the endpoint.
        pass


@lru_cache(maxsize=512)
def _lookup_for_date(
    lookup_date: str,
    environment: str,
    score_total: float,
    vix_level: Optional[float],
    sectors_green: Optional[int],
    score_delta: Optional[float],
    top_n: int,
    exclude_before: str,
) -> Tuple[Dict[str, Any], ...]:
    cached = _load_disk_cache(lookup_date)
    if cached is not None:
        return tuple(cached)

    result = get_historical_analogues(
        environment=environment,
        score_total=score_total,
        vix_level=vix_level,
        sectors_green=sectors_green,
        score_delta=score_delta,
        top_n=top_n,
        exclude_before=exclude_before,
    )
    analogues = result.get("analogues") or []
    _save_disk_cache(lookup_date, analogues)
    return tuple(analogues)


def _resolve_asof_date(df: pd.DataFrame, asof_date: Optional[str]) -> pd.Timestamp:
    dates = df["date"].sort_values()
    if asof_date is None:
        return pd.Timestamp(dates.iloc[-1])

    requested = pd.to_datetime(asof_date)
    eligible = dates[dates <= requested]
    if eligible.empty:
        raise ValueError(f"No trading day on or before asof_date={asof_date}")
    return pd.Timestamp(eligible.iloc[-1])


def _forward_return_pct_from_adjusted_close(
    df: pd.DataFrame,
    date: Any,
    days: int,
) -> Optional[float]:
    """Compute SPY forward return using the available adjusted-close series."""
    if "spy_close" not in df.columns:
        return None
    date_ts = pd.to_datetime(date, errors="coerce")
    if pd.isna(date_ts):
        return None

    prices = df[["date", "spy_close"]].dropna().sort_values("date").reset_index(drop=True)
    if prices.empty:
        return None

    matches = prices.index[prices["date"] >= date_ts].tolist()
    if not matches:
        return None
    start_idx = int(matches[0])
    future_idx = start_idx + int(days)
    if future_idx >= len(prices):
        return None

    start_price = _safe_float(prices.iloc[start_idx].get("spy_close"))
    future_price = _safe_float(prices.iloc[future_idx].get("spy_close"))
    if start_price is None or future_price is None or start_price == 0:
        return None
    return round((future_price / start_price - 1.0) * 100.0, 2)


def _shock_adjusted_weight(
    analogue: Dict[str, Any],
    horizon: str,
    weight: Any,
    *,
    shock_windows: Optional[List[Dict[str, Any]]] = None,
    shock_window_mode: str = "exclude",
) -> Optional[float]:
    base_weight = _safe_float(weight)
    if base_weight is None:
        return None
    overlaps = forward_window_overlaps_shock(analogue.get("date"), horizon, shock_windows)
    if not overlaps or shock_window_mode == "tag_only":
        return base_weight
    if shock_window_mode == "downweight":
        return base_weight * 0.25
    return None


def _weighted_horizon_stats(
    analogues: List[Dict[str, Any]],
    key: str,
    *,
    shock_windows: Optional[List[Dict[str, Any]]] = None,
    shock_window_mode: str = "exclude",
) -> Dict[str, Any]:
    pairs = [
        (
            a.get("forward_returns", {}).get(key),
            _shock_adjusted_weight(
                a,
                key,
                a.get("composite_weight"),
                shock_windows=shock_windows,
                shock_window_mode=shock_window_mode,
            ),
        )
        for a in analogues
        if a.get("forward_returns", {}).get(key) is not None
    ]
    pairs = [(value, weight) for value, weight in pairs if weight is not None]
    if not pairs:
        return {
            "n": 0,
            "weight_sum": 0.0,
            "median": None,
            "mean": None,
            "pct_positive": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "worst": None,
            "best": None,
        }

    values = np.array([float(v) for v, _ in pairs], dtype=float)
    weights = np.array([float(w) for _, w in pairs], dtype=float)
    total_w = float(weights.sum())
    if total_w <= 0:
        return {
            "n": len(values),
            "weight_sum": 0.0,
            "median": None,
            "mean": None,
            "pct_positive": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "worst": None,
            "best": None,
        }

    return {
        "n": int(len(values)),
        "weight_sum": round(total_w, 3),
        "median": round(weighted_percentile(values, weights, 50), 2),
        "mean": round(float(np.average(values, weights=weights)), 2),
        "pct_positive": round(float(weights[values > 0].sum() / total_w * 100.0), 1),
        "p10": round(weighted_percentile(values, weights, 10), 2),
        "p25": round(weighted_percentile(values, weights, 25), 2),
        "p75": round(weighted_percentile(values, weights, 75), 2),
        "p90": round(weighted_percentile(values, weights, 90), 2),
        "worst": round(float(values.min()), 2),
        "best": round(float(values.max()), 2),
    }


def _weighted_median_from_pairs(pairs: List[Tuple[Optional[float], Optional[float]]]) -> Optional[float]:
    clean = [(float(v), float(w)) for v, w in pairs if v is not None and w is not None]
    if not clean:
        return None
    values = np.array([x[0] for x in clean], dtype=float)
    weights = np.array([x[1] for x in clean], dtype=float)
    if weights.sum() <= 0:
        return None
    return round(weighted_percentile(values, weights, 50), 2)


def _weighted_forward_return_risk(
    analogues: List[Dict[str, Any]],
    horizon: str,
    *,
    shock_windows: Optional[List[Dict[str, Any]]] = None,
    shock_window_mode: str = "exclude",
) -> Dict[str, Any]:
    pairs = [
        (
            a.get("forward_returns", {}).get(horizon),
            _shock_adjusted_weight(
                a,
                horizon,
                a.get("composite_weight"),
                shock_windows=shock_windows,
                shock_window_mode=shock_window_mode,
            ),
        )
        for a in analogues
        if a.get("forward_returns", {}).get(horizon) is not None
    ]
    pairs = [(value, weight) for value, weight in pairs if weight is not None]
    if not pairs:
        return {
            f"win_rate_{horizon}": None,
            f"median_up_{horizon}": None,
            f"median_down_{horizon}": None,
            f"expected_value_{horizon}": None,
            f"worst_forward_return_{horizon}": None,
            f"p10_forward_return_{horizon}": None,
            f"p90_forward_return_{horizon}": None,
        }

    values = np.array([float(v) for v, _ in pairs], dtype=float)
    weights = np.array([float(w) for _, w in pairs], dtype=float)
    total_w = float(weights.sum())
    if total_w <= 0:
        return {
            f"win_rate_{horizon}": None,
            f"median_up_{horizon}": None,
            f"median_down_{horizon}": None,
            f"expected_value_{horizon}": None,
            f"worst_forward_return_{horizon}": None,
            f"p10_forward_return_{horizon}": None,
            f"p90_forward_return_{horizon}": None,
        }

    up_mask = values > 0
    win_rate = float(weights[up_mask].sum() / total_w)
    loss_rate = 1.0 - win_rate
    median_up = weighted_percentile(values[up_mask], weights[up_mask], 50) if up_mask.any() else 0.0
    median_down = weighted_percentile(values[~up_mask], weights[~up_mask], 50) if (~up_mask).any() else 0.0
    return {
        f"win_rate_{horizon}": round(win_rate * 100.0, 1),
        f"median_up_{horizon}": round(float(median_up), 2),
        f"median_down_{horizon}": round(float(median_down), 2),
        f"expected_value_{horizon}": round(float(win_rate * median_up + loss_rate * median_down), 2),
        f"worst_forward_return_{horizon}": round(float(values.min()), 2),
        f"p10_forward_return_{horizon}": round(weighted_percentile(values, weights, 10), 2),
        f"p90_forward_return_{horizon}": round(weighted_percentile(values, weights, 90), 2),
        # Backward-compatible alias, now explicitly derived from forward returns.
        f"worst_drawdown_{horizon}": round(float(values.min()), 2),
    }


def _weighted_aggregate_stats(
    analogues: List[Dict[str, Any]],
    macro_horizons: Optional[List[str]] = None,
    *,
    shock_windows: Optional[List[Dict[str, Any]]] = None,
    shock_window_mode: str = "exclude",
) -> Dict[str, Any]:
    macro_horizons = macro_horizons or DEFAULT_MACRO_HORIZONS
    shock_diagnostics = shock_window_diagnostics_for_analogues(
        analogues,
        horizons=FORWARD_RETURN_HORIZONS,
        shock_windows=shock_windows,
        shock_window_mode=shock_window_mode,  # type: ignore[arg-type]
    )
    normalized_shock_windows = shock_diagnostics.get("windows") or []
    forward = {
        horizon: _weighted_horizon_stats(
            analogues,
            horizon,
            shock_windows=normalized_shock_windows,
            shock_window_mode=shock_window_mode,
        )
        for horizon in FORWARD_RETURN_HORIZONS
    }

    drawdown_med = _weighted_median_from_pairs([
        (a.get("risk_profile", {}).get("max_drawdown_5d"), a.get("composite_weight"))
        for a in analogues
    ])
    upside_med = _weighted_median_from_pairs([
        (a.get("risk_profile", {}).get("max_upside_5d"), a.get("composite_weight"))
        for a in analogues
    ])

    risk: Dict[str, Any] = {
        "median_max_drawdown_5d": drawdown_med,
        "median_max_upside_5d": upside_med,
    }
    if drawdown_med is not None and upside_med is not None and abs(drawdown_med) > 0:
        risk["reward_risk_ratio"] = round(float(upside_med / abs(drawdown_med)), 2)

    available_macro_risk_horizons: List[str] = []
    for horizon in macro_horizons:
        risk.update(
            _weighted_forward_return_risk(
                analogues,
                horizon,
                shock_windows=normalized_shock_windows,
                shock_window_mode=shock_window_mode,
            )
        )
        drawdown_h = _weighted_median_from_pairs([
            (
                a.get("risk_profile", {}).get(f"max_drawdown_{horizon}"),
                _shock_adjusted_weight(
                    a,
                    horizon,
                    a.get("composite_weight"),
                    shock_windows=normalized_shock_windows,
                    shock_window_mode=shock_window_mode,
                ),
            )
            for a in analogues
        ])
        upside_h = _weighted_median_from_pairs([
            (
                a.get("risk_profile", {}).get(f"max_upside_{horizon}"),
                _shock_adjusted_weight(
                    a,
                    horizon,
                    a.get("composite_weight"),
                    shock_windows=normalized_shock_windows,
                    shock_window_mode=shock_window_mode,
                ),
            )
            for a in analogues
        ])
        if drawdown_h is not None and upside_h is not None:
            available_macro_risk_horizons.append(horizon)
            risk[f"median_max_drawdown_{horizon}"] = drawdown_h
            risk[f"median_max_upside_{horizon}"] = upside_h
    risk["drawdown_upside_available_horizons"] = available_macro_risk_horizons

    warnings: List[str] = []
    if not available_macro_risk_horizons:
        warnings.append(MACRO_RISK_UNAVAILABLE_WARNING)

    env_dist: Dict[str, float] = {}
    for analogue in analogues:
        env = str(analogue.get("environment") or "Unknown")
        env_dist[env] = env_dist.get(env, 0.0) + float(analogue.get("composite_weight") or 0.0)

    available_horizons = [
        horizon
        for horizon, stats in forward.items()
        if int(stats.get("n") or 0) > 0
    ]
    return {
        "n_analogues": len(analogues),
        "forward_returns": forward,
        "tactical_forward_returns": {
            horizon: forward[horizon]
            for horizon in TACTICAL_FORWARD_HORIZONS
        },
        "macro_forward_returns": {
            horizon: forward[horizon]
            for horizon in macro_horizons
            if horizon in forward
        },
        "risk_profile": risk,
        "environment_distribution": {k: round(v, 3) for k, v in sorted(env_dist.items())},
        "available_horizons": available_horizons,
        "missing_horizons": [],
        "horizon_sample_sizes": {
            horizon: int(stats.get("n") or 0)
            for horizon, stats in forward.items()
        },
        "shock_window_diagnostics": shock_diagnostics,
        "warnings": warnings,
    }


def _effective_sample_size(analogues: List[Dict[str, Any]]) -> float:
    weights = np.array(
        [float(a.get("composite_weight") or 0.0) for a in analogues],
        dtype=float,
    )
    if len(weights) == 0 or float(np.square(weights).sum()) <= 0:
        return 0.0
    return round(float(np.square(weights.sum()) / np.square(weights).sum()), 2)


def _summarize_detailed_groups(analogues: List[Dict[str, Any]]) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {}
    for analogue in analogues:
        weight = float(analogue.get("composite_weight") or 1.0)
        for group in (analogue.get("group_match_summary") or {}).get("group_results", []):
            name = str(group.get("group"))
            entry = groups.setdefault(
                name,
                {
                    "weighted_similarity": 0.0,
                    "weight": 0.0,
                    "features_used": 0,
                    "features_missing": 0,
                    "top_features_used": [],
                    "top_features_missing": [],
                },
            )
            similarity = _safe_float(group.get("similarity"))
            if similarity is not None:
                entry["weighted_similarity"] += similarity * weight
                entry["weight"] += weight
            entry["features_used"] += int(group.get("features_used") or 0)
            entry["features_missing"] += int(group.get("features_missing") or 0)
            for feature_id in group.get("top_matched_features") or []:
                if feature_id not in entry["top_features_used"]:
                    entry["top_features_used"].append(feature_id)
            for feature_id in group.get("missing_feature_ids") or []:
                if feature_id not in entry["top_features_missing"]:
                    entry["top_features_missing"].append(feature_id)
    summary: Dict[str, Any] = {}
    for group, entry in groups.items():
        total_features = entry["features_used"] + entry["features_missing"]
        summary[group] = {
            "avg_similarity": round(entry["weighted_similarity"] / entry["weight"], 2) if entry["weight"] else None,
            "features_used": int(entry["features_used"]),
            "features_missing": int(entry["features_missing"]),
            "coverage": round(entry["features_used"] / total_features, 3) if total_features else 0.0,
            "top_features_used": entry["top_features_used"][:3],
            "top_features_missing": entry["top_features_missing"][:3],
        }
    return dict(sorted(summary.items()))


def _conditions_summary(window: pd.DataFrame) -> str:
    env = str(window["environment"].mode().iloc[0]) if not window["environment"].mode().empty else "Mixed"
    first_score = _safe_float(window.iloc[0].get("score_total"))
    last_score = _safe_float(window.iloc[-1].get("score_total"))
    mean_score = float(window["score_total"].mean())
    min_score = float(window["score_total"].min())
    max_score = float(window["score_total"].max())

    vix = pd.to_numeric(window.get("vix_level"), errors="coerce")
    vix_text = "VIX unavailable"
    if vix.notna().any():
        vix_text = f"VIX avg {vix.mean():.1f}, range {vix.min():.1f}-{vix.max():.1f}"

    trajectory = "sideways"
    if first_score is not None and last_score is not None:
        delta = last_score - first_score
        if delta > 3:
            trajectory = "improving"
        elif delta < -3:
            trajectory = "deteriorating"

    return (
        f"{env}; score avg {mean_score:.0f}, range {min_score:.0f}-{max_score:.0f}; "
        f"{vix_text}; score trajectory {trajectory}"
    )


def get_rolling_composite(
    asof_date: Optional[str] = None,
    lookback_days: int = 30,
    half_life: int = 30,
    top_n_per_lookup: int = 15,
    pool_top_n: int = 50,
    current_state_lookup_weight: float = 1.0,
    exclude_recent_days: int = 60,
    macro_horizons: Optional[List[str]] = None,
    use_detailed_similarity: bool = False,
    current_features: Optional[Dict[str, Any]] = None,
    feature_specs: Optional[List[FeatureSpec]] = None,
    group_weights: Optional[Dict[str, float]] = None,
    v1_weight: float = 0.40,
    v2_weight: float = 0.60,
    candidate_pool_n: int = 300,
    exclude_shock_windows: bool = True,
    shock_window_mode: str = "exclude",
    shock_windows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    df = _load_df()
    if df.empty:
        raise ValueError("Historical analogue dataset is empty")

    lookback_days = max(1, int(lookback_days))
    half_life = max(1, int(half_life))
    top_n_per_lookup = max(1, int(top_n_per_lookup))
    pool_top_n = max(1, int(pool_top_n))
    current_state_lookup_weight = max(1.0, float(current_state_lookup_weight))

    asof_ts = _resolve_asof_date(df, asof_date)
    window = df[df["date"] <= asof_ts].tail(lookback_days).copy()
    if window.empty:
        raise ValueError(f"No lookback window available for asof_date={asof_ts.date()}")

    exclude_before_ts = asof_ts - pd.Timedelta(days=exclude_recent_days)
    exclude_before = exclude_before_ts.strftime("%Y-%m-%d")

    anchor_ts = pd.Timestamp(window["date"].max())
    raw_weights = []
    for dt in window["date"]:
        days_back = max(0, int((anchor_ts - pd.Timestamp(dt)).days))
        raw_weights.append(current_state_lookup_weight * math.exp(-math.log(2) * days_back / half_life))
    weights = np.array(raw_weights, dtype=float)
    if weights.sum() <= 0:
        weights = np.ones(len(window), dtype=float)
        weights[-1] = current_state_lookup_weight
    lookup_weights = [
        {
            "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
            "weight": round(float(weight), 6),
        }
        for dt, weight in zip(window["date"], weights)
    ]

    pooled: Dict[str, Dict[str, Any]] = {}
    detailed_lookup_summaries: List[Dict[str, Any]] = []
    warnings: List[str] = []
    active_shock_windows = shock_windows if exclude_shock_windows else []
    for (_, row), lookup_weight in zip(window.iterrows(), weights):
        lookup_date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
        if use_detailed_similarity and current_features:
            lookup_result = get_historical_analogues_v2(
                current_features=current_features,
                environment=str(row.get("environment") or "Mixed / Neutral"),
                score_total=float(row.get("score_total")),
                vix_level=_safe_float(row.get("vix_level")),
                sectors_green=int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
                score_delta=_safe_float(row.get("score_delta")),
                top_n=top_n_per_lookup,
                candidate_pool_n=candidate_pool_n,
                exclude_before=exclude_before,
                feature_specs=feature_specs,
                group_weights=group_weights,
                mode="blend",
                v1_weight=v1_weight,
                v2_weight=v2_weight,
                shock_windows=active_shock_windows,
                shock_window_mode=shock_window_mode,  # type: ignore[arg-type]
            )
            analogues = tuple(lookup_result.get("analogues") or [])
            warnings.extend(str(item) for item in (lookup_result.get("warnings") or []))
            detailed_lookup_summaries.append(
                {
                    "average_detailed_similarity": lookup_result.get("average_detailed_similarity"),
                    "average_blended_similarity": lookup_result.get("average_blended_similarity"),
                    "group_similarity_summary": lookup_result.get("group_similarity_summary") or {},
                }
            )
        else:
            analogues = _lookup_for_date(
                lookup_date,
                str(row.get("environment") or "Mixed / Neutral"),
                float(row.get("score_total")),
                _safe_float(row.get("vix_level")),
                int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
                _safe_float(row.get("score_delta")),
                top_n_per_lookup,
                exclude_before,
            )
        for analogue in analogues:
            analogue_date = str(analogue.get("date"))
            if not analogue_date:
                continue
            similarity_factor = 1.0
            if use_detailed_similarity:
                similarity_factor = max(0.05, float(analogue.get("blended_similarity") or 0.0) / 100.0)
            entry = pooled.setdefault(analogue_date, {"weight_sum": 0.0, "rows": []})
            entry["weight_sum"] += float(lookup_weight) * similarity_factor
            entry["rows"].append(dict(analogue))

    sorted_pool = sorted(
        ((date, data["weight_sum"], data["rows"][0]) for date, data in pooled.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    n_unique = len(sorted_pool)

    output_analogues: List[Dict[str, Any]] = []
    for _, weight_sum, analogue in sorted_pool[:pool_top_n]:
        row = dict(analogue)
        row["composite_weight"] = round(float(weight_sum), 3)
        for days in FLAT_FORWARD_RETURN_DAYS:
            row[f"forward_return_{days}d"] = _forward_return_pct_from_adjusted_close(
                df,
                row.get("date"),
                days,
            )
        output_analogues.append(row)

    macro_horizons = macro_horizons or DEFAULT_MACRO_HORIZONS
    aggregate_stats = _weighted_aggregate_stats(
        output_analogues,
        macro_horizons=macro_horizons,
        shock_windows=active_shock_windows,
        shock_window_mode=shock_window_mode,
    )
    detailed_values = [
        float(item.get("detailed_similarity"))
        for item in output_analogues
        if item.get("detailed_similarity") is not None
    ]
    blended_values = [
        float(item.get("blended_similarity"))
        for item in output_analogues
        if item.get("blended_similarity") is not None
    ]
    group_summary = _summarize_detailed_groups(output_analogues) if use_detailed_similarity else {}
    sorted_groups = sorted(
        group_summary.items(),
        key=lambda item: float(item[1].get("avg_similarity") or 0.0),
        reverse=True,
    )
    coverage_values = [
        float((a.get("feature_coverage") or {}).get("coverage"))
        for a in output_analogues
        if (a.get("feature_coverage") or {}).get("coverage") is not None
    ]
    missing_important = [
        group
        for group, values in group_summary.items()
        if float(values.get("coverage") or 0.0) < 0.4
    ]
    warnings.extend(str(item) for item in (aggregate_stats.get("warnings") or []))

    return {
        "asof_date": asof_ts.strftime("%Y-%m-%d"),
        "analogue_version": "v2_detailed" if use_detailed_similarity and current_features else "v1_broad_state",
        "lookback_days": int(lookback_days),
        "half_life": int(half_life),
        "current_state_lookup_weight": round(float(current_state_lookup_weight), 3),
        "macro_horizons": list(macro_horizons),
        "n_lookups": int(len(window)),
        "lookup_weights": lookup_weights,
        "n_unique_analogues": int(n_unique),
        "n_pooled": int(len(output_analogues)),
        "analogues": output_analogues,
        "aggregate_stats": aggregate_stats,
        "shock_window_diagnostics": aggregate_stats.get("shock_window_diagnostics") or {},
        "macro_forward_returns": aggregate_stats.get("macro_forward_returns", {}),
        "average_detailed_similarity": round(float(np.mean(detailed_values)), 2) if detailed_values else None,
        "average_blended_similarity": round(float(np.mean(blended_values)), 2) if blended_values else None,
        "group_similarity_summary": group_summary,
        "feature_coverage_summary": {
            "average_coverage": round(float(np.mean(coverage_values)), 3) if coverage_values else None,
            "n_analogues_with_coverage": len(coverage_values),
        },
        "strongest_match_groups": [group for group, _ in sorted_groups[:3]],
        "weakest_match_groups": [group for group, _ in sorted_groups[-3:]][::-1],
        "missing_important_features": missing_important,
        "effective_sample_size": _effective_sample_size(output_analogues),
        "warnings": list(dict.fromkeys(warnings)),
        "methodology_notes": [
            "The current/as-of market state is assigned full analogue lookup weight. Prior lookback days are included to capture path context and are exponentially downweighted.",
        ],
        "conditions_summary": _conditions_summary(window),
    }


if __name__ == "__main__":
    result = get_rolling_composite()
    print(f"asof_date: {result['asof_date']}")
    print(f"n_lookups: {result['n_lookups']}, n_unique: {result['n_unique_analogues']}, n_pooled: {result['n_pooled']}")
    print(f"conditions: {result['conditions_summary']}")
    print()
    print("Top 5 analogues by composite weight:")
    for a in result["analogues"][:5]:
        print(f"  {a['date']}  weight={a['composite_weight']:.2f}  score={a['score_total']:.0f}  env={a['environment']}")
    print()
    print("5d aggregate (weighted):")
    s5 = result["aggregate_stats"]["forward_returns"]["5d"]
    print(f"  median={s5['median']:+.2f}%  pct_pos={s5['pct_positive']:.0f}%")
    print()
    print("21d aggregate (weighted):")
    s21 = result["aggregate_stats"]["forward_returns"]["21d"]
    risk = result["aggregate_stats"]["risk_profile"]
    print(f"  median={s21['median']:+.2f}%  win_rate={risk.get('win_rate_21d')}%  EV={risk.get('expected_value_21d')}")
