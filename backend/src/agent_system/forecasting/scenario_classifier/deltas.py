"""Shared path-to-delta construction for scenario classification."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd


BASELINE_MODES = {"t0_change", "trailing_trend"}
TRAILING_TREND_LOOKBACK_QUARTERS = 8


class DeltaConstructionError(RuntimeError):
    """Raised when a classifier path cannot be converted to baseline deltas."""


def to_baseline_deltas(
    path_values: np.ndarray,
    *,
    variables: Sequence[str],
    anchor_history: pd.DataFrame | Mapping[str, pd.Series],
    anchor_quarter: str | pd.Period,
    baseline_mode: str,
) -> np.ndarray:
    """Convert future path levels to classifier deltas.

    ``path_values`` may be shaped ``(K, n_vars)`` or ``(n_paths, K, n_vars)``.
    For ``trailing_trend``, the trend is fit on the eight quarters immediately
    before the anchor quarter and extrapolated across the K future quarters.
    """
    if baseline_mode not in BASELINE_MODES:
        raise DeltaConstructionError(
            f"unknown baseline_mode '{baseline_mode}'. Valid modes: {sorted(BASELINE_MODES)}"
        )
    variable_order = [str(variable).strip() for variable in variables]
    if not variable_order or any(not variable for variable in variable_order):
        raise DeltaConstructionError("variables must be a non-empty sequence")

    raw = np.asarray(path_values, dtype=float)
    squeeze = False
    if raw.ndim == 2:
        raw = raw.reshape(1, *raw.shape)
        squeeze = True
    if raw.ndim != 3:
        raise DeltaConstructionError(
            f"path_values must have shape (K, n_vars) or (n_paths, K, n_vars); got {raw.shape}"
        )
    if raw.shape[2] != len(variable_order):
        raise DeltaConstructionError(
            f"path_values variable dimension {raw.shape[2]} does not match variables "
            f"({len(variable_order)})"
        )
    if not np.isfinite(raw).all():
        raise DeltaConstructionError("path_values contain non-finite values")

    anchor = parse_quarter(anchor_quarter)
    history = normalize_history_frame(anchor_history, variable_order)
    baseline = baseline_matrix(
        history,
        variables=variable_order,
        anchor_quarter=anchor,
        horizon_quarters=raw.shape[1],
        baseline_mode=baseline_mode,
    )
    deltas = raw - baseline.reshape(1, *baseline.shape)
    return deltas[0] if squeeze else deltas


def baseline_matrix(
    history: pd.DataFrame,
    *,
    variables: Sequence[str],
    anchor_quarter: str | pd.Period,
    horizon_quarters: int,
    baseline_mode: str,
) -> np.ndarray:
    """Return the K x n variable baseline levels for a mode."""
    if horizon_quarters < 1:
        raise DeltaConstructionError("horizon_quarters must be positive")
    if baseline_mode not in BASELINE_MODES:
        raise DeltaConstructionError(
            f"unknown baseline_mode '{baseline_mode}'. Valid modes: {sorted(BASELINE_MODES)}"
        )
    anchor = parse_quarter(anchor_quarter)
    variable_order = [str(variable).strip() for variable in variables]
    history = normalize_history_frame(history, variable_order)

    out = np.zeros((horizon_quarters, len(variable_order)), dtype=float)
    for variable_index, variable in enumerate(variable_order):
        series = history[variable]
        if baseline_mode == "t0_change":
            anchor_value = series_value(series, anchor, variable)
            out[:, variable_index] = anchor_value
        else:
            for offset in range(1, horizon_quarters + 1):
                out[offset - 1, variable_index] = trailing_trend_value(
                    series,
                    anchor,
                    offset,
                    variable,
                )
    return out


def normalize_history_frame(
    history: pd.DataFrame | Mapping[str, pd.Series],
    variables: Sequence[str],
) -> pd.DataFrame:
    """Return a quarterly PeriodIndex frame containing all requested variables."""
    variable_order = [str(variable).strip() for variable in variables]
    if isinstance(history, pd.DataFrame):
        frame = history.copy()
    else:
        series_by_name: dict[str, pd.Series] = {}
        for variable in variable_order:
            series = history.get(variable)
            if series is None:
                raise DeltaConstructionError(
                    f"missing transformed history for variable '{variable}'"
                )
            series_by_name[variable] = pd.to_numeric(series, errors="coerce")
        frame = pd.concat(series_by_name, axis=1)

    missing = [variable for variable in variable_order if variable not in frame.columns]
    if missing:
        raise DeltaConstructionError(f"history missing variables: {missing}")
    frame = frame[variable_order].copy()
    if not isinstance(frame.index, pd.PeriodIndex):
        try:
            frame.index = pd.PeriodIndex(frame.index, freq="Q")
        except Exception as exc:
            raise DeltaConstructionError("history index must be convertible to quarterly periods") from exc
    return frame.sort_index()


def parse_quarter(value: str | pd.Period) -> pd.Period:
    if isinstance(value, pd.Period):
        return pd.Period(value, freq="Q")
    try:
        return pd.Period(str(value), freq="Q")
    except Exception as exc:
        raise DeltaConstructionError(f"invalid quarter '{value}'") from exc


def series_value(series: pd.Series, quarter: pd.Period, variable: str) -> float:
    if not isinstance(series.index, pd.PeriodIndex):
        series = series.copy()
        series.index = pd.PeriodIndex(series.index, freq="Q")
    if quarter not in series.index:
        raise DeltaConstructionError(f"missing {variable} history for quarter {quarter}")
    value = series.loc[quarter]
    if pd.isna(value):
        raise DeltaConstructionError(f"non-finite {variable} value for quarter {quarter}")
    return float(value)


def trailing_trend_value(
    series: pd.Series,
    anchor_quarter: pd.Period,
    offset: int,
    variable: str,
) -> float:
    if offset < 1:
        raise DeltaConstructionError("trailing_trend offset must be positive")
    quarters = [
        anchor_quarter - step
        for step in range(TRAILING_TREND_LOOKBACK_QUARTERS, 0, -1)
    ]
    values = [series_value(series, quarter, variable) for quarter in quarters]
    x = np.arange(len(values), dtype=float)
    y = np.asarray(values, dtype=float)
    if not np.isfinite(y).all():
        raise DeltaConstructionError(
            f"non-finite values in trailing trend window for {variable}"
        )
    slope, intercept = np.polyfit(x, y, 1)
    return float(intercept + slope * (TRAILING_TREND_LOOKBACK_QUARTERS + offset))
