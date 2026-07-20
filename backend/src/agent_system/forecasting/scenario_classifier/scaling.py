"""Scale fitting and loading for scenario-classifier distance space."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.agent_system.forecasting.scenario_classifier.data import (
    ClassifierDataError,
    default_cache_dir,
    load_transformed_history,
)
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry


class ScaleError(RuntimeError):
    """Raised when scale artifacts are absent or invalid."""


@dataclass(frozen=True)
class ScaleSet:
    horizon_quarters: int
    variables: dict[str, dict[str, Any]]
    path: Path
    fit_timestamp: str | None = None

    def scale_for(self, variable: str, *, robust: bool = False) -> float:
        payload = self.variables.get(variable)
        if not isinstance(payload, dict):
            raise ScaleError(f"scales artifact missing variable '{variable}'")
        if robust:
            mad = _positive_float(payload.get("mad"))
            if mad is None:
                raise ScaleError(f"MAD scale missing or zero for variable '{variable}'")
            return 1.4826 * mad
        std = _positive_float(payload.get("std"))
        if std is None:
            raise ScaleError(f"standard-deviation scale missing or zero for variable '{variable}'")
        return std


def fit_scales(
    registry: VariableRegistry,
    *,
    horizon_quarters: int,
    cache_dir: str | Path | None = None,
) -> ScaleSet:
    if horizon_quarters < 1:
        raise ScaleError("horizon_quarters must be positive")
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    variables: dict[str, dict[str, Any]] = {}
    for spec in registry.signature_variables():
        try:
            series = load_transformed_history(
                registry,
                spec,
                cache_dir=target_dir,
            )
        except ClassifierDataError as exc:
            raise ScaleError(str(exc)) from exc
        changes = (series - series.shift(horizon_quarters)).dropna()
        if len(changes) < 8:
            raise ScaleError(
                f"not enough history to fit scales for {spec.name}: "
                f"{len(changes)} K-quarter changes"
            )
        std = float(changes.std(ddof=1))
        median = float(changes.median())
        mad = float((changes - median).abs().median())
        if not np.isfinite(std) or std <= 0:
            raise ScaleError(f"zero or non-finite std for variable '{spec.name}'")
        if not np.isfinite(mad) or mad <= 0:
            raise ScaleError(f"zero or non-finite MAD for variable '{spec.name}'")
        variables[spec.name] = {
            "std": std,
            "mad": mad,
            "change_count": int(len(changes)),
            "history_start": str(series.index.min()),
            "history_end": str(series.index.max()),
        }

    payload = {
        "fit_timestamp": _utc_now(),
        "horizon_quarters": int(horizon_quarters),
        "variables": variables,
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    path = scales_path(target_dir)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ScaleSet(
        horizon_quarters=horizon_quarters,
        variables=variables,
        path=path,
        fit_timestamp=payload["fit_timestamp"],
    )


def load_scales(
    *,
    horizon_quarters: int,
    cache_dir: str | Path | None = None,
) -> ScaleSet:
    target_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    path = scales_path(target_dir)
    if not path.is_file():
        raise ScaleError(f"Missing scales artifact {path}; run fit-scales first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ScaleError(f"Could not parse scales artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ScaleError(f"scales artifact must contain a JSON object: {path}")
    artifact_k = payload.get("horizon_quarters")
    try:
        artifact_k_int = int(artifact_k)
    except (TypeError, ValueError) as exc:
        raise ScaleError(f"scales artifact missing valid horizon_quarters: {path}") from exc
    if artifact_k_int != int(horizon_quarters):
        raise ScaleError(
            f"scales artifact K={artifact_k} does not match run K={horizon_quarters}; "
            "rerun fit-scales with the requested horizon."
        )
    variables = payload.get("variables")
    if not isinstance(variables, dict) or not variables:
        raise ScaleError(f"scales artifact contains no variables: {path}")
    return ScaleSet(
        horizon_quarters=artifact_k_int,
        variables=variables,
        path=path,
        fit_timestamp=payload.get("fit_timestamp")
        if isinstance(payload.get("fit_timestamp"), str)
        else None,
    )


def scales_path(cache_dir: Path) -> Path:
    return cache_dir / "scales.json"


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number) or number <= 0:
        return None
    return number


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
