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
from .analogues import get_historical_analogues, _load_df


CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "analogue_lookups"
CSV_MTIME_STAMP = CACHE_DIR / ".csv_mtime"
JSON_FIELDS = {"forward_path", "environment_drivers"}
NESTED_PREFIXES = ("forward_returns", "risk_profile", "score_components", "sector_returns")


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
        return "missing"
    return str(path.stat().st_mtime_ns)


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


def _weighted_horizon_stats(analogues: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    pairs = [
        (a.get("forward_returns", {}).get(key), a.get("composite_weight"))
        for a in analogues
        if a.get("forward_returns", {}).get(key) is not None and a.get("composite_weight") is not None
    ]
    if not pairs:
        return {"n": 0}

    values = np.array([float(v) for v, _ in pairs], dtype=float)
    weights = np.array([float(w) for _, w in pairs], dtype=float)
    total_w = float(weights.sum())
    if total_w <= 0:
        return {"n": len(values), "weight_sum": 0.0}

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


def _weighted_aggregate_stats(analogues: List[Dict[str, Any]]) -> Dict[str, Any]:
    forward = {
        "1d": _weighted_horizon_stats(analogues, "1d"),
        "5d": _weighted_horizon_stats(analogues, "5d"),
        "10d": _weighted_horizon_stats(analogues, "10d"),
        "21d": _weighted_horizon_stats(analogues, "21d"),
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
        "median_max_drawdown_21d": drawdown_med,
        "median_max_upside_21d": upside_med,
    }
    if drawdown_med is not None and upside_med is not None and abs(drawdown_med) > 0:
        risk["reward_risk_ratio"] = round(float(upside_med / abs(drawdown_med)), 2)

    fwd_21 = [
        (a.get("forward_returns", {}).get("21d"), a.get("composite_weight"))
        for a in analogues
        if a.get("forward_returns", {}).get("21d") is not None and a.get("composite_weight") is not None
    ]
    if fwd_21:
        values = np.array([float(v) for v, _ in fwd_21], dtype=float)
        weights = np.array([float(w) for _, w in fwd_21], dtype=float)
        total_w = float(weights.sum())
        if total_w > 0:
            up_mask = values > 0
            win_rate = float(weights[up_mask].sum() / total_w)
            loss_rate = 1.0 - win_rate
            median_up = weighted_percentile(values[up_mask], weights[up_mask], 50) if up_mask.any() else 0.0
            median_dn = weighted_percentile(values[~up_mask], weights[~up_mask], 50) if (~up_mask).any() else 0.0
            risk["win_rate_21d"] = round(win_rate * 100.0, 1)
            risk["median_up_21d"] = round(float(median_up), 2)
            risk["median_down_21d"] = round(float(median_dn), 2)
            risk["expected_value_21d"] = round(float(win_rate * median_up + loss_rate * median_dn), 2)
            risk["worst_drawdown_21d"] = round(float(values.min()), 2)

    env_dist: Dict[str, float] = {}
    for analogue in analogues:
        env = str(analogue.get("environment") or "Unknown")
        env_dist[env] = env_dist.get(env, 0.0) + float(analogue.get("composite_weight") or 0.0)

    return {
        "n_analogues": len(analogues),
        "forward_returns": forward,
        "risk_profile": risk,
        "environment_distribution": {k: round(v, 3) for k, v in sorted(env_dist.items())},
    }


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
    exclude_recent_days: int = 60,
) -> Dict[str, Any]:
    df = _load_df()
    if df.empty:
        raise ValueError("Historical analogue dataset is empty")

    lookback_days = max(1, int(lookback_days))
    half_life = max(1, int(half_life))
    top_n_per_lookup = max(1, int(top_n_per_lookup))
    pool_top_n = max(1, int(pool_top_n))

    asof_ts = _resolve_asof_date(df, asof_date)
    window = df[df["date"] <= asof_ts].tail(lookback_days).copy()
    if window.empty:
        raise ValueError(f"No lookback window available for asof_date={asof_ts.date()}")

    exclude_before_ts = asof_ts - pd.Timedelta(days=exclude_recent_days)
    exclude_before = exclude_before_ts.strftime("%Y-%m-%d")

    raw_weights = []
    for dt in window["date"]:
        days_back = max(0, int((asof_ts - pd.Timestamp(dt)).days))
        raw_weights.append(math.exp(-math.log(2) * days_back / half_life))
    weights = np.array(raw_weights, dtype=float)
    weights = weights * (len(window) / weights.sum()) if weights.sum() > 0 else np.ones(len(window))

    pooled: Dict[str, Dict[str, Any]] = {}
    for (_, row), lookup_weight in zip(window.iterrows(), weights):
        lookup_date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
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
            entry = pooled.setdefault(analogue_date, {"weight_sum": 0.0, "rows": []})
            entry["weight_sum"] += float(lookup_weight)
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
        output_analogues.append(row)

    return {
        "asof_date": asof_ts.strftime("%Y-%m-%d"),
        "lookback_days": int(lookback_days),
        "half_life": int(half_life),
        "n_lookups": int(len(window)),
        "n_unique_analogues": int(n_unique),
        "n_pooled": int(len(output_analogues)),
        "analogues": output_analogues,
        "aggregate_stats": _weighted_aggregate_stats(output_analogues),
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
