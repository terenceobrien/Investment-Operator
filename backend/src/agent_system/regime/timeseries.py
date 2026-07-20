"""Time-series DataFrame builder for regime state history.

Loads regime states from the storage backend and flattens them into a pandas
DataFrame indexed by date. This is the canonical interface for analysis,
visualization, or backtests that need regime data over time.

Usage:
    from src.agent_system.regime.timeseries import load_regime_timeseries

    df = load_regime_timeseries()
    df = load_regime_timeseries(start_date="2024-01-01")
    df = load_regime_timeseries(
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.agent_system.storage.repository import load_regime_states_range


FLAT_COLUMNS = [
    "asof_date",
    "score_total",
    "score_prior",
    "score_delta",
    "environment",
    "confidence",
    "layer_agreement",
    "horizon",
    "layer_monetary",
    "layer_credit",
    "layer_volatility",
    "layer_breadth",
    "layer_positioning",
    "dq_monetary",
    "dq_credit",
    "dq_volatility",
    "dq_breadth",
    "dq_positioning",
    "status_monetary",
    "status_credit",
    "status_volatility",
    "status_breadth",
    "status_positioning",
    "vix_level",
    "vix_term_slope",
    "hy_spread_level",
    "net_liquidity_z",
    "pct_above_200d",
    "avg_dist_from_200d",
    "sectors_green",
]


def _flatten_state(state: dict) -> dict:
    """Flatten a single regime state dict into a DataFrame row."""

    row = {col: None for col in FLAT_COLUMNS}

    for col in FLAT_COLUMNS:
        if col in state:
            row[col] = state[col]

    layer_dq = state.get("layer_data_quality", {}) or {}
    layer_status = state.get("layer_statuses", {}) or {}
    for layer in ("monetary", "credit", "volatility", "breadth", "positioning"):
        if layer in layer_dq:
            row[f"dq_{layer}"] = layer_dq[layer]
        if layer in layer_status:
            row[f"status_{layer}"] = layer_status[layer]

    return row


def load_regime_timeseries(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load regime states between dates and return a flat DataFrame."""

    start = start_date or "1970-01-01"
    end = end_date or datetime.utcnow().strftime("%Y-%m-%d")

    states = load_regime_states_range(start, end)
    if not states:
        df = pd.DataFrame(columns=FLAT_COLUMNS)
        df.index = pd.DatetimeIndex([], name="asof_date")
        return df

    rows = [_flatten_state(state) for state in states]
    df = pd.DataFrame(rows)
    df["asof_date"] = pd.to_datetime(df["asof_date"])
    df = df.set_index("asof_date").sort_index()
    return df


def load_regime_state_signals(asof_date: str) -> dict[str, list[str]]:
    """Load just the per-layer signal strings for one date."""

    from src.agent_system.storage.repository import load_regime_state

    state = load_regime_state(asof_date)
    if not state:
        return {}
    return state.get("layer_signals", {})


def load_full_regime_state(asof_date: str) -> Optional[dict]:
    """Load the complete regime state dict for one date."""

    from src.agent_system.storage.repository import load_regime_state

    return load_regime_state(asof_date)


def latest_state_summary() -> Optional[dict]:
    """Return a flat dict summary of the most recent regime state."""

    df = load_regime_timeseries()
    if df.empty:
        return None
    latest = df.iloc[-1].to_dict()
    latest["asof_date"] = df.index[-1].strftime("%Y-%m-%d")
    return latest


def environment_runs(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Identify contiguous runs of the same environment label."""

    df = load_regime_timeseries(start_date=start_date, end_date=end_date)
    columns = [
        "start_date",
        "end_date",
        "environment",
        "n_days",
        "avg_composite",
        "composite_change",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)

    env = df["environment"].fillna("")
    changed = env != env.shift()
    run_id = changed.cumsum()

    runs = []
    for _rid, group in df.groupby(run_id):
        if group.empty:
            continue
        environment = group["environment"].iloc[0]
        if not environment:
            continue
        composite_start = group["score_total"].iloc[0]
        composite_end = group["score_total"].iloc[-1]
        composite_mean = group["score_total"].mean()
        runs.append(
            {
                "start_date": group.index[0].strftime("%Y-%m-%d"),
                "end_date": group.index[-1].strftime("%Y-%m-%d"),
                "environment": environment,
                "n_days": len(group),
                "avg_composite": (
                    round(composite_mean, 2) if pd.notna(composite_mean) else None
                ),
                "composite_change": (
                    round(composite_end - composite_start, 2)
                    if pd.notna(composite_end) and pd.notna(composite_start)
                    else None
                ),
            }
        )

    return pd.DataFrame(runs, columns=columns)


def percentile_context(
    column: str,
    asof_date: Optional[str] = None,
    lookback_days: int = 365,
) -> Optional[dict]:
    """Compute a value's percentile position within a recent window."""

    end = asof_date or datetime.utcnow().strftime("%Y-%m-%d")
    start = (
        datetime.strptime(end, "%Y-%m-%d") - timedelta(days=lookback_days)
    ).strftime("%Y-%m-%d")

    df = load_regime_timeseries(start_date=start, end_date=end)
    if df.empty or column not in df.columns:
        return None

    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None

    current = series.iloc[-1]
    if pd.isna(current):
        return None

    percentile = float((series <= current).mean() * 100)

    return {
        "column": column,
        "current_value": float(current),
        "percentile": round(percentile, 1),
        "window_min": float(series.min()),
        "window_max": float(series.max()),
        "window_mean": float(series.mean()),
        "n_observations": int(len(series)),
        "asof_date": end,
    }
