"""
src/analysis/analogues.py

Historical analogue engine — finds the closest past market states
to today's conditions and returns enriched detail for each.

Drop into: backend/src/analysis/analogues.py
Data file: backend/data/backtest_master_file.csv
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence
import numpy as np
import pandas as pd

from .detailed_analogue_similarity import (
    FeatureSpec,
    compute_detailed_similarity,
    result_to_dict,
)

# ── Config ────────────────────────────────────────────────────────────────────

import os


def _candidate_data_paths() -> List[Path]:
    backend_dir = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[3]
    env_path = os.environ.get("RESEARCH_DATA_PATH")
    paths: List[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.extend([
        backend_dir / "data" / "operator_research_v3.csv",
        backend_dir / "data" / "backtest_master_file.csv",
        repo_root / "data" / "operator_research_v3.csv",
        repo_root / "data" / "backtest_master_file.csv",
    ])
    return paths


def _resolve_data_path() -> Path:
    for path in _candidate_data_paths():
        if path.exists():
            return path
    # Return preferred v3 path for a clear error if none exists.
    return _candidate_data_paths()[0]


DATA_PATH = _resolve_data_path()

SCORE_BINS   = [0, 35, 45, 55, 65, 75, 101]
SCORE_LABELS = ["<35", "35-45", "45-55", "55-65", "65-75", ">75"]

VIX_BINS   = [0, 15, 20, 25, 35, 999]
VIX_LABELS = ["<15", "15-20", "20-25", "25-35", ">35"]

SECTOR_MAP = {
    "ret_XLB_1d": "Materials",
    "ret_XLC_1d": "Comm Svcs",
    "ret_XLE_1d": "Energy",
    "ret_XLF_1d": "Financials",
    "ret_XLI_1d": "Industrials",
    "ret_XLK_1d": "Technology",
    "ret_XLP_1d": "Staples",
    "ret_XLRE_1d": "Real Estate",
    "ret_XLU_1d": "Utilities",
    "ret_XLV_1d": "Health Care",
    "ret_XLY_1d": "Discretionary",
}

TACTICAL_FORWARD_HORIZONS = ["1d", "5d", "10d"]
MACRO_FORWARD_HORIZONS = ["21d", "63d", "126d", "252d"]
FORWARD_RETURN_HORIZONS = TACTICAL_FORWARD_HORIZONS + MACRO_FORWARD_HORIZONS
FORWARD_RETURN_COLUMNS = {
    "1d": "fwd_ret_cc_1d",
    "5d": "fwd_ret_cc_5d",
    "10d": "fwd_ret_cc_10d",
    "21d": "fwd_ret_cc_21d",
    "63d": "fwd_ret_cc_63d",
    "126d": "fwd_ret_cc_126d",
    "252d": "fwd_ret_cc_252d",
}
MACRO_RISK_COLUMNS = {
    "21d": ("fwd_21d_max_drawdown_pct", "fwd_21d_max_upside_pct"),
    "63d": ("fwd_63d_max_drawdown_pct", "fwd_63d_max_upside_pct"),
    "126d": ("fwd_126d_max_drawdown_pct", "fwd_126d_max_upside_pct"),
    "252d": ("fwd_252d_max_drawdown_pct", "fwd_252d_max_upside_pct"),
}
MACRO_RISK_UNAVAILABLE_WARNING = (
    "Macro-horizon drawdown/upside columns unavailable; only return-distribution risk shown."
)
DEFAULT_SHOCK_WINDOWS: List[Dict[str, str]] = [
    {
        "name": "covid_crash",
        "start_date": "2020-02-19",
        "end_date": "2020-04-30",
        "default_action": "exclude_forward_window_overlap",
    }
]
HORIZON_BUSINESS_DAYS = {
    "1d": 1,
    "5d": 5,
    "10d": 10,
    "21d": 21,
    "63d": 63,
    "126d": 126,
    "252d": 252,
}

_df_cache: Optional[pd.DataFrame] = None


def _normalize_shock_windows(
    shock_windows: Optional[Sequence[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    windows = list(shock_windows) if shock_windows is not None else list(DEFAULT_SHOCK_WINDOWS)
    normalized: List[Dict[str, Any]] = []
    for idx, window in enumerate(windows):
        name = str(window.get("name") or f"shock_window_{idx + 1}")
        start = pd.to_datetime(window.get("start_date"), errors="coerce")
        end = pd.to_datetime(window.get("end_date"), errors="coerce")
        if pd.isna(start) or pd.isna(end):
            continue
        if end < start:
            start, end = end, start
        normalized.append(
            {
                "name": name,
                "start_date": pd.Timestamp(start).strftime("%Y-%m-%d"),
                "end_date": pd.Timestamp(end).strftime("%Y-%m-%d"),
                "default_action": str(window.get("default_action") or "exclude_forward_window_overlap"),
            }
        )
    return normalized


def _forward_window(date_value: Any, horizon: str) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    days = HORIZON_BUSINESS_DAYS.get(str(horizon).lower())
    if days is None:
        return None
    date = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(date):
        return None
    start = pd.Timestamp(date) + pd.tseries.offsets.BDay(1)
    end = pd.Timestamp(date) + pd.tseries.offsets.BDay(days)
    return pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()


def forward_window_overlaps_shock(
    analogue_date: Any,
    horizon: str,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
) -> bool:
    window = _forward_window(analogue_date, horizon)
    if window is None:
        return False
    fwd_start, fwd_end = window
    for shock in _normalize_shock_windows(shock_windows):
        shock_start = pd.Timestamp(shock["start_date"])
        shock_end = pd.Timestamp(shock["end_date"])
        if fwd_start <= shock_end and fwd_end >= shock_start:
            return True
    return False


def shock_overlap_horizons(
    analogue_date: Any,
    horizons: Optional[Sequence[str]] = None,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[str]:
    return [
        horizon
        for horizon in (list(horizons) if horizons is not None else FORWARD_RETURN_HORIZONS)
        if forward_window_overlaps_shock(analogue_date, horizon, shock_windows)
    ]


def shock_window_diagnostics_for_analogues(
    analogues: Sequence[Dict[str, Any]],
    horizons: Optional[Sequence[str]] = None,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
    shock_window_mode: Literal["exclude", "downweight", "tag_only"] = "exclude",
) -> Dict[str, Any]:
    horizons = list(horizons) if horizons is not None else list(FORWARD_RETURN_HORIZONS)
    windows = _normalize_shock_windows(shock_windows)
    tagged: Dict[str, List[str]] = {horizon: [] for horizon in horizons}
    excluded: Dict[str, List[str]] = {horizon: [] for horizon in horizons}
    for analogue in analogues:
        date = analogue.get("date")
        if not date:
            continue
        for horizon in horizons:
            if not forward_window_overlaps_shock(date, horizon, windows):
                continue
            date_text = str(date)
            if date_text not in tagged[horizon]:
                tagged[horizon].append(date_text)
            if shock_window_mode == "exclude" and analogue.get("forward_returns", {}).get(horizon) is not None:
                excluded[horizon].append(date_text)
    return {
        "enabled": bool(windows),
        "mode": shock_window_mode,
        "windows": windows,
        "tagged_dates_by_horizon": {h: sorted(v) for h, v in tagged.items() if v},
        "excluded_dates_by_horizon": {h: sorted(v) for h, v in excluded.items() if v},
        "rows_tagged_by_horizon": {h: len(v) for h, v in tagged.items()},
        "rows_excluded_by_horizon": {h: len(v) for h, v in excluded.items()},
    }


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_df() -> pd.DataFrame:
    global _df_cache, DATA_PATH
    if _df_cache is not None:
        return _df_cache

    if not DATA_PATH.exists():
        DATA_PATH = _resolve_data_path()
    if not DATA_PATH.exists():
        tried = ", ".join(str(p) for p in _candidate_data_paths())
        raise FileNotFoundError(
            f"Historical analogue research data not found. Tried: {tried}"
        )

    df = pd.read_csv(DATA_PATH)
    required = {"date", "signal_time", "score_total"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            f"Historical analogue research data at {DATA_PATH} is missing required columns: {missing}"
        )

    df = df[df["signal_time"] == "close"].copy()
    if df.empty:
        raise ValueError(f"Historical analogue research data at {DATA_PATH} has no close signal rows")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["score_delta"] = df["score_total"].diff()

    df["score_bucket"] = pd.cut(
        df["score_total"], bins=SCORE_BINS, labels=SCORE_LABELS, right=False
    )
    df["vix_bucket"] = pd.cut(
        df["vix_level"], bins=VIX_BINS, labels=VIX_LABELS, right=False
    )

    _df_cache = df
    return df


# ── Similarity scoring ────────────────────────────────────────────────────────

def _similarity_score(row: pd.Series, inputs: Dict[str, Any]) -> float:
    """
    Compute a 0-100 similarity score between a historical row and current inputs.
    Lower is more similar (like a distance metric).
    """
    penalties = 0.0

    # Score distance (most important — weight 40%)
    score_diff = abs(row["score_total"] - inputs["score_total"])
    penalties += score_diff * 0.4

    # VIX distance (weight 25%)
    if inputs.get("vix_level") and pd.notna(row.get("vix_level")):
        vix_diff = abs(row["vix_level"] - inputs["vix_level"])
        penalties += vix_diff * 0.25

    # Sectors green distance (weight 15%)
    if inputs.get("sectors_green") is not None and pd.notna(row.get("sectors_green")):
        breadth_diff = abs(row["sectors_green"] - inputs["sectors_green"])
        penalties += breadth_diff * 1.5  # scale: 0-11 range

    # Score delta direction match (weight 20%)
    if inputs.get("score_delta") is not None and pd.notna(row.get("score_delta")):
        # Penalize if delta direction mismatches
        same_direction = (
            (inputs["score_delta"] > 3 and row["score_delta"] > 3) or
            (inputs["score_delta"] < -3 and row["score_delta"] < -3) or
            (abs(inputs["score_delta"]) <= 3 and abs(row["score_delta"]) <= 3)
        )
        if not same_direction:
            penalties += 8.0

    return round(float(penalties), 2)


# ── Forward path builder ──────────────────────────────────────────────────────

def _forward_path(df: pd.DataFrame, date: pd.Timestamp, days: int = 21) -> List[Dict]:
    spy = df[["date", "spy_close"]].set_index("date")
    future = spy[spy.index > date].head(days)
    if future.empty:
        return []
    base_rows = spy[spy.index == date]
    if base_rows.empty:
        return []
    base = float(base_rows.iloc[0]["spy_close"])
    if base == 0:
        return []
    return [
        {
            "date": d.strftime("%Y-%m-%d"),
            "ret_pct": round((float(p) / base - 1) * 100, 3),
        }
        for d, p in zip(future.index, future["spy_close"])
    ]


# ── Per-date enrichment ───────────────────────────────────────────────────────

def _enrich_row(row: pd.Series, df: pd.DataFrame, similarity: float) -> Dict[str, Any]:
    date = row["date"]
    fwd_path = _forward_path(df, date, days=21)

    # Sector returns for this date
    sectors = {}
    for col, name in SECTOR_MAP.items():
        val = row.get(col)
        if pd.notna(val):
            sectors[name] = round(float(val) * 100, 2)

    # Score components
    components = {}
    for layer in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        val = row.get(f"layer_{layer}")
        if pd.notna(val):
            components[layer] = round(float(val), 2)
    # Fallback to v1 components if v2 not present
    if not components:
        for comp in ["risk_on", "trend_strength", "vol_mood", "participation", "leadership_clarity"]:
            val = row.get(f"comp__{comp}")
            if pd.notna(val):
                components[comp] = round(float(val), 2)

    def _pct(val):
        return round(float(val) * 100, 2) if pd.notna(val) else None

    def _f(val, d=2):
        return round(float(val), d) if pd.notna(val) else None

    forward_returns = {
        horizon: _pct(row.get(column))
        for horizon, column in FORWARD_RETURN_COLUMNS.items()
    }
    risk_profile = {
        "max_drawdown_5d": _pct(row.get("fwd_5d_max_drawdown_pct")),
        "max_upside_5d": _pct(row.get("fwd_5d_max_upside_pct")),
    }
    for horizon, (drawdown_col, upside_col) in MACRO_RISK_COLUMNS.items():
        risk_profile[f"max_drawdown_{horizon}"] = _pct(row.get(drawdown_col))
        risk_profile[f"max_upside_{horizon}"] = _pct(row.get(upside_col))

    return {
        "date": date.strftime("%Y-%m-%d"),
        "similarity_score": similarity,
        "score_total": _f(row["score_total"], 1),
        "confidence": _f(row.get("confidence"), 1),
        "environment": str(row.get("environment", "")),
        "score_delta": _f(row.get("score_delta"), 1),
        "vix_level": _f(row.get("vix_level"), 1),
        "vix_z_20d": _f(row.get("vix_z_20d"), 2),
        "sectors_green": int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
        "dispersion": _f(row.get("dispersion"), 4),
        "spy_close": _f(row.get("spy_close"), 2),
        "score_components": components,
        "sector_returns": sectors,
        "forward_returns": forward_returns,
        "risk_profile": risk_profile,
        "forward_path": fwd_path,
        "layer_agreement": _f(row.get("layer_agreement"), 2),
        "environment_drivers": [],  # not stored per-row in CSV
    }


# ── Aggregate stats ───────────────────────────────────────────────────────────

def _empty_horizon_stats(n: int, *, weight_sum: float | None = None) -> Dict[str, Any]:
    stats: Dict[str, Any] = {
        "n": int(n),
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
    if weight_sum is not None:
        stats["weight_sum"] = round(float(weight_sum), 3)
    return stats


def _available_and_missing_horizons(columns: Sequence[str]) -> tuple[List[str], List[str]]:
    column_set = set(columns)
    available = [
        horizon
        for horizon, column in FORWARD_RETURN_COLUMNS.items()
        if column in column_set
    ]
    missing = [
        horizon
        for horizon, column in FORWARD_RETURN_COLUMNS.items()
        if column not in column_set
    ]
    return available, missing


def _column_warnings(missing_horizons: Sequence[str]) -> List[str]:
    return [
        f"Forward return column {FORWARD_RETURN_COLUMNS[horizon]} unavailable; {horizon} stats set to n=0."
        for horizon in missing_horizons
        if horizon in FORWARD_RETURN_COLUMNS
    ]


def _risk_distribution_stats(values: List[float], horizon: str) -> Dict[str, Any]:
    if not values:
        return {
            f"win_rate_{horizon}": None,
            f"median_up_{horizon}": None,
            f"median_down_{horizon}": None,
            f"expected_value_{horizon}": None,
            f"worst_forward_return_{horizon}": None,
            f"p10_forward_return_{horizon}": None,
            f"p90_forward_return_{horizon}": None,
        }

    arr = np.array(values, dtype=float)
    up = arr[arr > 0]
    down = arr[arr <= 0]
    win_rate = float((arr > 0).mean())
    median_up = float(np.median(up)) if len(up) else 0.0
    median_down = float(np.median(down)) if len(down) else 0.0
    expected_value = (win_rate * median_up) + ((1.0 - win_rate) * median_down)
    return {
        f"win_rate_{horizon}": round(win_rate * 100.0, 1),
        f"median_up_{horizon}": round(median_up, 2),
        f"median_down_{horizon}": round(median_down, 2),
        f"expected_value_{horizon}": round(float(expected_value), 2),
        f"worst_forward_return_{horizon}": round(float(arr.min()), 2),
        f"p10_forward_return_{horizon}": round(float(np.percentile(arr, 10)), 2),
        f"p90_forward_return_{horizon}": round(float(np.percentile(arr, 90)), 2),
        # Backward-compatible alias, now explicitly derived from forward returns.
        f"worst_drawdown_{horizon}": round(float(arr.min()), 2),
    }


def _aggregate_stats(
    analogues: List[Dict],
    data_columns: Sequence[str] | None = None,
    *,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
    shock_window_mode: Literal["exclude", "downweight", "tag_only"] = "exclude",
) -> Dict[str, Any]:
    shock_diagnostics = shock_window_diagnostics_for_analogues(
        analogues,
        horizons=FORWARD_RETURN_HORIZONS,
        shock_windows=shock_windows,
        shock_window_mode=shock_window_mode,
    )

    def _is_excluded_for_horizon(analogue: Dict[str, Any], horizon: str) -> bool:
        if shock_window_mode != "exclude":
            return False
        return forward_window_overlaps_shock(analogue.get("date"), horizon, shock_diagnostics.get("windows") or [])

    def _horizon_stats(key: str) -> Dict:
        vals = [
            a.get("forward_returns", {}).get(key)
            for a in analogues
            if a.get("forward_returns", {}).get(key) is not None and not _is_excluded_for_horizon(a, key)
        ]
        if len(vals) < 3:
            return _empty_horizon_stats(len(vals))
        arr = np.array(vals)
        return {
            "n": len(arr),
            "median": round(float(np.median(arr)), 2),
            "mean": round(float(arr.mean()), 2),
            "pct_positive": round(float((arr > 0).mean() * 100), 1),
            "p10": round(float(np.percentile(arr, 10)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
            "worst": round(float(arr.min()), 2),
            "best":  round(float(arr.max()), 2),
            "distribution": [round(float(v), 2) for v in sorted(arr)],
        }

    if data_columns is None:
        available_horizons, missing_horizons = list(FORWARD_RETURN_HORIZONS), []
    else:
        available_horizons, missing_horizons = _available_and_missing_horizons(data_columns)
    warnings = _column_warnings(missing_horizons)

    drawdowns = [
        a.get("risk_profile", {}).get("max_drawdown_5d")
        for a in analogues
        if a.get("risk_profile", {}).get("max_drawdown_5d") is not None
    ]
    upsides = [
        a.get("risk_profile", {}).get("max_upside_5d")
        for a in analogues
        if a.get("risk_profile", {}).get("max_upside_5d") is not None
    ]

    risk = {}
    if drawdowns and upsides:
        med_dd = abs(np.median(drawdowns))
        med_up = np.median(upsides)

        risk["median_max_drawdown_5d"] = round(float(np.median(drawdowns)), 2)
        risk["median_max_upside_5d"] = round(float(med_up), 2)

        # Raw reward/risk (unweighted, based on 5d max range)
        risk["reward_risk_ratio"] = round(float(med_up / med_dd), 2) if med_dd > 0 else None

    available_macro_risk_horizons = []
    for horizon in MACRO_FORWARD_HORIZONS:
        fwd_vals = [
            a.get("forward_returns", {}).get(horizon)
            for a in analogues
            if a.get("forward_returns", {}).get(horizon) is not None and not _is_excluded_for_horizon(a, horizon)
        ]
        risk.update(_risk_distribution_stats(fwd_vals, horizon))

        horizon_drawdowns = [
            a.get("risk_profile", {}).get(f"max_drawdown_{horizon}")
            for a in analogues
            if a.get("risk_profile", {}).get(f"max_drawdown_{horizon}") is not None
            and not _is_excluded_for_horizon(a, horizon)
        ]
        horizon_upsides = [
            a.get("risk_profile", {}).get(f"max_upside_{horizon}")
            for a in analogues
            if a.get("risk_profile", {}).get(f"max_upside_{horizon}") is not None
            and not _is_excluded_for_horizon(a, horizon)
        ]
        if horizon_drawdowns and horizon_upsides:
            available_macro_risk_horizons.append(horizon)
            risk[f"median_max_drawdown_{horizon}"] = round(float(np.median(horizon_drawdowns)), 2)
            risk[f"median_max_upside_{horizon}"] = round(float(np.median(horizon_upsides)), 2)

    risk["drawdown_upside_available_horizons"] = available_macro_risk_horizons
    if not available_macro_risk_horizons:
        warnings.append(MACRO_RISK_UNAVAILABLE_WARNING)

    # Environment transition counts
    env_counts = {}
    for a in analogues:
        e = a.get("environment", "Unknown")
        env_counts[e] = env_counts.get(e, 0) + 1

    forward_returns = {
        horizon: _horizon_stats(horizon)
        for horizon in FORWARD_RETURN_HORIZONS
    }
    return {
        "n_analogues": len(analogues),
        "forward_returns": forward_returns,
        "tactical_forward_returns": {
            horizon: forward_returns[horizon]
            for horizon in TACTICAL_FORWARD_HORIZONS
        },
        "macro_forward_returns": {
            horizon: forward_returns[horizon]
            for horizon in MACRO_FORWARD_HORIZONS
        },
        "risk_profile": risk,
        "environment_distribution": env_counts,
        "available_horizons": available_horizons,
        "missing_horizons": missing_horizons,
        "horizon_sample_sizes": {
            horizon: int(stats.get("n") or 0)
            for horizon, stats in forward_returns.items()
        },
        "shock_window_diagnostics": shock_diagnostics,
        "warnings": warnings,
    }


# ── Main public function ──────────────────────────────────────────────────────

def _candidate_pool(
    df: pd.DataFrame,
    *,
    environment: str,
    score_total: float,
    vix_level: Optional[float],
    sectors_green: Optional[int],
    score_delta: Optional[float],
    top_n: int,
    min_score_window: float,
    exclude_before: Optional[str],
) -> pd.DataFrame:
    inputs = {
        "environment": environment,
        "score_total": score_total,
        "vix_level": vix_level,
        "sectors_green": sectors_green,
        "score_delta": score_delta,
    }
    exclude_dt = pd.to_datetime(exclude_before) if exclude_before else None
    pool = df[df["environment"] == environment].copy()
    if exclude_dt is not None:
        pool = pool[pool["date"] < exclude_dt]
    pool = pool[
        (pool["score_total"] >= score_total - min_score_window) &
        (pool["score_total"] <= score_total + min_score_window)
    ]
    if pool.empty:
        pool = df[
            (df["score_total"] >= score_total - min_score_window) &
            (df["score_total"] <= score_total + min_score_window)
        ].copy()
        if exclude_dt is not None:
            pool = pool[pool["date"] < exclude_dt]
    pool = pool.copy()
    pool["_similarity"] = pool.apply(
        lambda row: _similarity_score(row, inputs),
        axis=1,
    )
    return pool.nsmallest(max(1, int(top_n)), "_similarity")


def _group_similarity_summary(analogues: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, List[float]] = {}
    missing: Dict[str, int] = {}
    used: Dict[str, int] = {}
    for analogue in analogues:
        for group in (analogue.get("group_match_summary") or {}).get("group_results", []):
            name = str(group.get("group"))
            if group.get("similarity") is not None:
                grouped.setdefault(name, []).append(float(group["similarity"]))
            used[name] = used.get(name, 0) + int(group.get("features_used") or 0)
            missing[name] = missing.get(name, 0) + int(group.get("features_missing") or 0)
    out: Dict[str, Any] = {}
    for group, values in grouped.items():
        features_used = used.get(group, 0)
        features_missing = missing.get(group, 0)
        total = features_used + features_missing
        out[group] = {
            "avg_similarity": round(float(np.mean(values)), 2) if values else None,
            "features_used": features_used,
            "features_missing": features_missing,
            "coverage": round(features_used / total, 3) if total else 0.0,
        }
    return dict(sorted(out.items()))


def get_historical_analogues_v2(
    current_features: Dict[str, Any],
    environment: str,
    score_total: float,
    vix_level: Optional[float] = None,
    sectors_green: Optional[int] = None,
    score_delta: Optional[float] = None,
    top_n: int = 50,
    candidate_pool_n: int = 300,
    min_score_window: float = 20.0,
    exclude_before: Optional[str] = None,
    feature_specs: Optional[List[FeatureSpec]] = None,
    group_weights: Optional[Dict[str, float]] = None,
    mode: Literal["rerank", "blend", "replace"] = "blend",
    v1_weight: float = 0.40,
    v2_weight: float = 0.60,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
    shock_window_mode: Literal["exclude", "downweight", "tag_only"] = "exclude",
) -> Dict[str, Any]:
    """Find analogues using broad-state candidates plus detailed raw-input similarity."""

    df = _load_df()
    candidate_n = max(int(top_n), int(candidate_pool_n))
    top = _candidate_pool(
        df,
        environment=environment,
        score_total=score_total,
        vix_level=vix_level,
        sectors_green=sectors_green,
        score_delta=score_delta,
        top_n=candidate_n,
        min_score_window=min_score_window,
        exclude_before=exclude_before,
    )

    warnings: List[str] = []
    enriched: List[Dict[str, Any]] = []
    total_weight = max(v1_weight + v2_weight, 1e-9)
    v1_w = v1_weight / total_weight
    v2_w = v2_weight / total_weight
    for _, row in top.iterrows():
        v1_distance = float(row["_similarity"])
        v1_similarity = max(0.0, 100.0 - v1_distance)
        detailed = compute_detailed_similarity(
            current_features,
            row,
            feature_specs=feature_specs,
            group_weights=group_weights,
        )
        warnings.extend(detailed.warnings)
        if mode in {"replace", "rerank"}:
            blended_similarity = detailed.overall_similarity
        else:
            blended_similarity = (v1_w * v1_similarity) + (v2_w * detailed.overall_similarity)
        analogue = _enrich_row(row, df, similarity=round(100.0 - blended_similarity, 2))
        group_summary = result_to_dict(detailed)
        group_results = group_summary.get("group_results", [])
        sorted_groups = sorted(
            group_results,
            key=lambda item: float(item.get("similarity") or 0.0),
            reverse=True,
        )
        features_used = int(group_summary.get("features_used") or 0)
        features_missing = len(group_summary.get("features_missing") or [])
        total_features = features_used + features_missing
        analogue.update(
            {
                "v1_similarity": round(v1_similarity, 2),
                "detailed_similarity": detailed.overall_similarity,
                "blended_similarity": round(float(blended_similarity), 2),
                "detailed_distance": detailed.overall_distance,
                "group_match_summary": group_summary,
                "strongest_matching_groups": [item["group"] for item in sorted_groups[:3]],
                "weakest_matching_groups": [item["group"] for item in sorted_groups[-3:]][::-1],
                "feature_coverage": {
                    "features_used": features_used,
                    "features_missing": features_missing,
                    "coverage": round(features_used / total_features, 3) if total_features else 0.0,
                },
            }
        )
        enriched.append(analogue)

    enriched.sort(key=lambda item: item.get("blended_similarity") or 0.0, reverse=True)
    analogues = enriched[:top_n]
    aggregate = _aggregate_stats(
        analogues,
        data_columns=df.columns,
        shock_windows=shock_windows,
        shock_window_mode=shock_window_mode,
    )
    group_summary = _group_similarity_summary(analogues)
    detailed_values = [float(a.get("detailed_similarity")) for a in analogues if a.get("detailed_similarity") is not None]
    blended_values = [float(a.get("blended_similarity")) for a in analogues if a.get("blended_similarity") is not None]

    return {
        "analogues": analogues,
        "aggregate_stats": aggregate,
        "inputs": {
            "environment": environment,
            "score_total": score_total,
            "vix_level": vix_level,
            "sectors_green": sectors_green,
            "score_delta": score_delta,
        },
        "conditions_matched": f"environment={environment} · score≈{score_total:.0f} · detailed_similarity={mode}",
        "analogue_version": "v2_detailed",
        "candidate_pool_n": int(len(top)),
        "v1_weight": round(v1_w, 3),
        "v2_weight": round(v2_w, 3),
        "average_detailed_similarity": round(float(np.mean(detailed_values)), 2) if detailed_values else None,
        "average_blended_similarity": round(float(np.mean(blended_values)), 2) if blended_values else None,
        "group_similarity_summary": group_summary,
        "feature_coverage_summary": {
            "features_used": int(sum((a.get("feature_coverage") or {}).get("features_used") or 0 for a in analogues)),
            "features_missing": int(sum((a.get("feature_coverage") or {}).get("features_missing") or 0 for a in analogues)),
        },
        "shock_window_diagnostics": aggregate.get("shock_window_diagnostics") or {},
        "warnings": list(dict.fromkeys([*(aggregate.get("warnings") or []), *warnings])),
        "available_horizons": list(aggregate.get("available_horizons") or []),
        "missing_horizons": list(aggregate.get("missing_horizons") or []),
    }


def get_historical_analogues(
    environment: str,
    score_total: float,
    vix_level: Optional[float] = None,
    sectors_green: Optional[int] = None,
    score_delta: Optional[float] = None,
    confidence: Optional[float] = None,
    top_n: int = 15,
    min_score_window: float = 15.0,
    exclude_before: Optional[str] = None,
    shock_windows: Optional[Sequence[Dict[str, Any]]] = None,
    shock_window_mode: Literal["exclude", "downweight", "tag_only"] = "exclude",
) -> Dict[str, Any]:
    """
    Find the top_n most similar historical market states and return
    enriched detail for each plus aggregate statistics.

    Args:
        environment:      Current environment classification
        score_total:      0-100 composite score
        vix_level:        Current VIX level
        sectors_green:    Number of positive sectors (0-11)
        score_delta:      Today's score minus yesterday's
        confidence:       0-100 confidence reading
        top_n:            Number of analogues to return (default 15)
        min_score_window: Minimum score distance window (default ±15)
        exclude_before:   Exclude candidate rows with date >= this ISO date

    Returns:
        {
          analogues: [...],          # enriched per-date details, ranked by similarity
          aggregate_stats: {...},    # distribution stats across all analogues
          inputs: {...},             # echo of inputs for reference
          conditions_matched: str,   # human-readable description
        }
    """
    df = _load_df()

    inputs = {
        "environment": environment,
        "score_total": score_total,
        "vix_level": vix_level,
        "sectors_green": sectors_green,
        "score_delta": score_delta,
        "confidence": confidence,
    }

    top = _candidate_pool(
        df,
        environment=environment,
        score_total=score_total,
        vix_level=vix_level,
        sectors_green=sectors_green,
        score_delta=score_delta,
        top_n=top_n,
        min_score_window=min_score_window,
        exclude_before=exclude_before,
    )

    # ── Enrich each row ──
    analogues = [
        _enrich_row(row, df, float(row["_similarity"]))
        for _, row in top.iterrows()
    ]

    # ── Sort by date descending (most recent first) for display ──
    analogues.sort(key=lambda x: x["date"], reverse=True)

    # ── Aggregate stats ──
    agg = _aggregate_stats(
        analogues,
        data_columns=df.columns,
        shock_windows=shock_windows,
        shock_window_mode=shock_window_mode,
    )

    # ── Conditions description ──
    conditions = [f"environment={environment}", f"score≈{score_total:.0f}"]
    if vix_level is not None:
        vb = pd.cut([vix_level], bins=VIX_BINS, labels=VIX_LABELS, right=False)[0]
        conditions.append(f"vix={vb}")
    if sectors_green is not None:
        conditions.append(f"breadth={'strong' if sectors_green >= 6 else 'weak'}")
    if score_delta is not None:
        if score_delta < -3:
            conditions.append("score_deteriorating")
        elif score_delta > 3:
            conditions.append("score_improving")

    return {
        "analogues": analogues,
        "aggregate_stats": agg,
        "inputs": inputs,
        "conditions_matched": " · ".join(conditions),
        "shock_window_diagnostics": agg.get("shock_window_diagnostics") or {},
        "warnings": list(agg.get("warnings") or []),
        "available_horizons": list(agg.get("available_horizons") or []),
        "missing_horizons": list(agg.get("missing_horizons") or []),
    }


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = get_historical_analogues(
        environment="Mixed / Neutral",
        score_total=54.2,
        vix_level=25.8,
        sectors_green=5,
        score_delta=-8.0,
        top_n=10,
    )

    print(f"Found {result['aggregate_stats']['n_analogues']} analogues")
    print(f"Conditions: {result['conditions_matched']}")
    print()
    print("Top 5 most recent:")
    for a in result["analogues"][:5]:
        fwd = a["forward_returns"]
        print(
            f"  {a['date']}  score={a['score_total']:.0f}  "
            f"vix={a['vix_level']}  "
            f"1d={fwd['1d']:+.2f}%  5d={fwd['5d']:+.2f}%  "
            f"21d={fwd['21d']:+.2f}%  "
            f"similarity={a['similarity_score']}"
        )
    print()
    print("Aggregate 5d stats:")
    s5 = result["aggregate_stats"]["forward_returns"]["5d"]
    print(f"  median={s5['median']:+.2f}%  %pos={s5['pct_positive']:.0f}%  "
          f"p25={s5['p25']:+.2f}%  p75={s5['p75']:+.2f}%")

# Note: set RESEARCH_DATA_PATH env var if running outside the backend folder:
# export RESEARCH_DATA_PATH=/path/to/backend/data/backtest_master_file.csv
