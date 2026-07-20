"""Tail diagnostics for BVAR ensemble simulations."""
from __future__ import annotations

from typing import Any, TextIO

import numpy as np
import pandas as pd


def compute_tail_diagnostics(
    paths: np.ndarray,
    *,
    variable_order: list[str],
    anchor_values: dict[str, float],
    historical_sample: pd.DataFrame,
    horizon: int,
) -> dict[str, Any]:
    if paths.ndim != 3:
        raise ValueError(f"paths must have shape (n_paths, horizon, n_vars); got {paths.shape}")
    if horizon < 1 or horizon > paths.shape[1]:
        raise ValueError(f"horizon {horizon} incompatible with paths shape {paths.shape}")
    diagnostics: dict[str, Any] = {}
    for index, variable in enumerate(variable_order):
        anchor = float(anchor_values[variable])
        ensemble_changes = paths[:, horizon - 1, index] - anchor
        historical_series = historical_sample[variable].dropna()
        historical_changes = (historical_series - historical_series.shift(horizon)).dropna()
        if historical_changes.empty:
            raise ValueError(f"not enough historical changes for tail diagnostics: {variable}")
        ensemble_stats = _stats(ensemble_changes)
        historical_stats = _stats(historical_changes.to_numpy(dtype=float))
        flag = ensemble_stats["p99"] > historical_stats["max"]
        diagnostics[variable] = {
            "ensemble": ensemble_stats,
            "historical": historical_stats,
            "flag_ensemble_p99_exceeds_historical_max": bool(flag),
        }
    return diagnostics


def print_tail_diagnostics(
    diagnostics: dict[str, Any],
    *,
    stream: TextIO,
) -> None:
    print("Tail diagnostics: ensemble K-quarter changes vs historical changes", file=stream)
    for variable, payload in diagnostics.items():
        ensemble = payload["ensemble"]
        historical = payload["historical"]
        flag = " FLAG:p99>hist_max" if payload.get("flag_ensemble_p99_exceeds_historical_max") else ""
        print(
            f"  {variable:<16} "
            f"ens p50={ensemble['p50']:+.3f} p90={ensemble['p90']:+.3f} "
            f"p99={ensemble['p99']:+.3f} max={ensemble['max']:+.3f} | "
            f"hist p50={historical['p50']:+.3f} p90={historical['p90']:+.3f} "
            f"p99={historical['p99']:+.3f} max={historical['max']:+.3f}{flag}",
            file=stream,
        )


def tail_flags(diagnostics: dict[str, Any]) -> list[str]:
    return [
        variable
        for variable, payload in diagnostics.items()
        if payload.get("flag_ensemble_p99_exceeds_historical_max")
    ]


def compute_horizon_dispersion(
    paths: np.ndarray,
    *,
    variable_order: list[str],
) -> dict[str, Any]:
    if paths.ndim != 3:
        raise ValueError(f"paths must have shape (n_paths, horizon, n_vars); got {paths.shape}")
    out: dict[str, Any] = {}
    for index, variable in enumerate(variable_order):
        series = paths[:, :, index]
        std_by_quarter = np.std(series, axis=0, ddof=1)
        p10 = np.percentile(series, 10, axis=0)
        p90 = np.percentile(series, 90, axis=0)
        width_by_quarter = p90 - p10
        out[variable] = {
            "std_by_quarter": [float(value) for value in std_by_quarter],
            "p10_p90_width_by_quarter": [float(value) for value in width_by_quarter],
            "widens_std": bool(std_by_quarter[-1] > std_by_quarter[0])
            if len(std_by_quarter) > 1
            else False,
            "widens_p10_p90": bool(width_by_quarter[-1] > width_by_quarter[0])
            if len(width_by_quarter) > 1
            else False,
            "std_change_first_to_last": float(std_by_quarter[-1] - std_by_quarter[0]),
            "p10_p90_width_change_first_to_last": float(width_by_quarter[-1] - width_by_quarter[0]),
        }
    return out


def compute_regime_overlay_diagnostics(
    paths: np.ndarray,
    *,
    variable_order: list[str],
    ever_stress: np.ndarray | None,
    entered_stress: np.ndarray | None,
    stress_quarters: np.ndarray | None,
) -> dict[str, Any] | None:
    if ever_stress is None or stress_quarters is None:
        return None
    if paths.ndim != 3:
        raise ValueError(f"paths must have shape (n_paths, horizon, n_vars); got {paths.shape}")
    if len(ever_stress) != paths.shape[0]:
        raise ValueError("regime ever_stress length does not match path count")
    if len(stress_quarters) != paths.shape[0]:
        raise ValueError("regime stress_quarters length does not match path count")
    credit_index = variable_order.index("credit_spread") if "credit_spread" in variable_order else None
    split: dict[str, Any] | None = None
    if credit_index is not None:
        terminal = paths[:, -1, credit_index]
        ever_mask = np.asarray(ever_stress, dtype=bool)
        split = {
            "ever_stress": _split_stats(terminal[ever_mask]),
            "stayed_calm": _split_stats(terminal[~ever_mask]),
        }
    return {
        "fraction_entered_stress": (
            float(np.mean(entered_stress))
            if entered_stress is not None
            else None
        ),
        "fraction_ever_stress": float(np.mean(ever_stress)),
        "avg_quarters_in_stress": float(np.mean(stress_quarters)),
        "credit_spread_terminal_by_regime_path": split,
    }


def garch_fallback_flags(garch_diagnostics: dict[str, Any] | None) -> list[str]:
    if not garch_diagnostics:
        return []
    return list(garch_diagnostics.get("fallback_variables", []) or [])


def _split_stats(values: np.ndarray) -> dict[str, Any]:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        return {"count": 0}
    return {
        "count": int(clean.size),
        "p50": float(np.percentile(clean, 50)),
        "p90": float(np.percentile(clean, 90)),
        "p99": float(np.percentile(clean, 99)),
        "max": float(np.max(clean)),
    }


def _stats(values: np.ndarray) -> dict[str, float]:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if clean.size == 0:
        raise ValueError("cannot compute diagnostics on empty/non-finite values")
    return {
        "p50": float(np.percentile(clean, 50)),
        "p90": float(np.percentile(clean, 90)),
        "p99": float(np.percentile(clean, 99)),
        "max": float(np.max(clean)),
    }
