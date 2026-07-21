"""Hard financial-stress regime labels for the BVAR regime overlay."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


class RegimeLabelingError(RuntimeError):
    """Raised when hard regime labels cannot be built."""


@dataclass(frozen=True)
class RegimeLabels:
    quarters: list[str]
    labels: np.ndarray
    proxy: np.ndarray
    proxy_components: dict[str, list[float]]
    thresholds: dict[str, float]
    stress_episodes: list[dict[str, str]]
    stress_count: int
    stress_fraction: float


def label_regimes(
    history: pd.DataFrame,
    *,
    residual_quarters: list[str],
    config: dict[str, Any],
) -> RegimeLabels:
    frame = _quarterly_frame(history)
    required = {"credit_spread", "nfci"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RegimeLabelingError(f"history missing variables for regime labeling: {missing}")

    residual_index = pd.PeriodIndex(residual_quarters, freq="Q")
    missing_quarters = [str(quarter) for quarter in residual_index if quarter not in frame.index]
    if missing_quarters:
        raise RegimeLabelingError(
            "history missing residual quarters needed for regime labels: "
            f"{missing_quarters[:5]}{'...' if len(missing_quarters) > 5 else ''}"
        )
    aligned = frame.loc[residual_index].copy()
    full_credit = frame["credit_spread"].astype(float)
    credit = aligned["credit_spread"].astype(float)
    nfci = aligned["nfci"].astype(float)
    spread_change_1q = credit.diff()

    spread_level_pctile = float(config["spread_level_pctile"])
    spread_level_threshold = float(np.percentile(full_credit.dropna(), spread_level_pctile))
    spread_change_threshold = float(config["spread_change_threshold"])
    nfci_threshold = float(config["nfci_threshold"])
    stress_min_conditions = int(config.get("stress_min_conditions", 2))
    if not 1 <= stress_min_conditions <= 3:
        raise RegimeLabelingError("stress_min_conditions must be between 1 and 3")

    conditions = pd.DataFrame(
        {
            "spread_level_high": credit > spread_level_threshold,
            "spread_change_high": spread_change_1q > spread_change_threshold,
            "nfci_high": nfci > nfci_threshold,
        },
        index=aligned.index,
    ).fillna(False)
    stress = conditions.sum(axis=1) >= stress_min_conditions
    labels = stress.astype(int).to_numpy(dtype=int)
    min_stress = int(config["regime_min_stress_quarters"])
    stress_count = int(np.sum(labels))
    if stress_count < min_stress:
        raise RegimeLabelingError(
            f"Only {stress_count} stress quarters labeled; need at least "
            f"regime_min_stress_quarters={min_stress}."
        )

    full_proxy, full_components = composite_stress_proxy(frame, config=config)
    full_proxy_series = pd.Series(full_proxy, index=frame.index)
    proxy = full_proxy_series.loc[residual_index].to_numpy(dtype=float)
    components = {
        key: [
            float(value)
            for value in pd.Series(values, index=frame.index).loc[residual_index].to_numpy(dtype=float)
        ]
        for key, values in full_components.items()
    }
    episodes = contiguous_stress_episodes(residual_quarters, labels)
    return RegimeLabels(
        quarters=[str(quarter) for quarter in residual_index],
        labels=labels,
        proxy=proxy,
        proxy_components=components,
        thresholds={
            "spread_level_pctile": spread_level_pctile,
            "spread_level_threshold": spread_level_threshold,
            "spread_change_threshold": spread_change_threshold,
            "nfci_threshold": nfci_threshold,
            "stress_min_conditions": float(stress_min_conditions),
        },
        stress_episodes=episodes,
        stress_count=stress_count,
        stress_fraction=float(stress_count / max(1, len(labels))),
    )


def composite_stress_proxy(
    frame: pd.DataFrame,
    *,
    config: dict[str, Any],
) -> tuple[np.ndarray, dict[str, list[float]]]:
    clean = _quarterly_frame(frame)
    required = {"credit_spread", "nfci"}
    missing = sorted(required - set(clean.columns))
    if missing:
        raise RegimeLabelingError(f"history missing proxy variables: {missing}")
    credit = clean["credit_spread"].astype(float)
    nfci = clean["nfci"].astype(float)
    spread_change_4q = credit - credit.shift(4)
    components = {
        "credit_spread_level": _zscore(credit),
        "credit_spread_change_4q": _zscore(spread_change_4q),
        "nfci": _zscore(nfci),
    }
    weights = proxy_weights_from_config(config)
    proxy = np.zeros(len(clean), dtype=float)
    total_weight = 0.0
    for name, values in components.items():
        weight = float(weights.get(name, 1.0))
        proxy += weight * values
        total_weight += abs(weight)
    if total_weight <= 0:
        raise RegimeLabelingError("regime proxy weights must not all be zero")
    proxy = proxy / total_weight
    proxy = np.nan_to_num(proxy, nan=0.0, posinf=0.0, neginf=0.0)
    return proxy, {key: [float(value) for value in values] for key, values in components.items()}


def proxy_for_state(
    current_state: np.ndarray,
    lag4_state: np.ndarray,
    *,
    variable_order: list[str],
    proxy_means: dict[str, float],
    proxy_stds: dict[str, float],
    weights: dict[str, float],
) -> float:
    index = {variable: pos for pos, variable in enumerate(variable_order)}
    for variable in ["credit_spread", "nfci"]:
        if variable not in index:
            raise RegimeLabelingError(f"simulation state missing {variable} for regime proxy")
    values = {
        "credit_spread_level": float(current_state[index["credit_spread"]]),
        "credit_spread_change_4q": float(
            current_state[index["credit_spread"]] - lag4_state[index["credit_spread"]]
        ),
        "nfci": float(current_state[index["nfci"]]),
    }
    total_weight = sum(abs(float(value)) for value in weights.values())
    if total_weight <= 0:
        raise RegimeLabelingError("regime proxy weights must not all be zero")
    proxy = 0.0
    for name, raw_value in values.items():
        std = max(float(proxy_stds[name]), 1e-12)
        proxy += float(weights.get(name, 1.0)) * ((raw_value - float(proxy_means[name])) / std)
    return float(proxy / total_weight)


def contiguous_stress_episodes(
    quarters: list[str],
    labels: np.ndarray,
) -> list[dict[str, str]]:
    episodes: list[dict[str, str]] = []
    start: str | None = None
    previous: str | None = None
    for quarter, label in zip(quarters, labels):
        if int(label) == 1 and start is None:
            start = quarter
        if int(label) == 0 and start is not None:
            assert previous is not None
            episodes.append({"start": start, "end": previous})
            start = None
        previous = quarter
    if start is not None:
        episodes.append({"start": start, "end": quarters[-1]})
    return episodes


def proxy_scalers(frame: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    clean = _quarterly_frame(frame)
    credit = clean["credit_spread"].astype(float)
    values = {
        "credit_spread_level": credit,
        "credit_spread_change_4q": credit - credit.shift(4),
        "nfci": clean["nfci"].astype(float),
    }
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for name, series in values.items():
        finite = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
        if finite.size < 2:
            raise RegimeLabelingError(f"not enough observations to scale proxy component {name}")
        means[name] = float(np.mean(finite))
        std = float(np.std(finite, ddof=1))
        stds[name] = std if std > 0 and np.isfinite(std) else 1.0
    return means, stds


def proxy_weights_from_config(config: dict[str, Any]) -> dict[str, float]:
    raw = config.get("regime_proxy_weights") or {}
    if not isinstance(raw, dict):
        raise RegimeLabelingError("regime_proxy_weights must be a mapping")
    return {
        "credit_spread_level": float(raw.get("credit_spread_level", 1.0)),
        "credit_spread_change_4q": float(raw.get("credit_spread_change_4q", 1.0)),
        "nfci": float(raw.get("nfci", 1.0)),
    }


def _quarterly_frame(frame: pd.DataFrame) -> pd.DataFrame:
    clean = frame.copy()
    if not isinstance(clean.index, pd.PeriodIndex):
        clean.index = pd.PeriodIndex(clean.index, freq="Q")
    return clean.sort_index()


def _zscore(series: pd.Series) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce")
    mean = float(values.mean(skipna=True))
    std = float(values.std(skipna=True))
    if not np.isfinite(std) or std <= 0:
        std = 1.0
    out = ((values - mean) / std).to_numpy(dtype=float)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
