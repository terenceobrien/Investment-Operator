"""Path-validity bounds for BVAR ensemble simulation."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
)


class BoundsError(RuntimeError):
    """Raised when registry bounds are absent or invalid for simulation."""


@dataclass
class ValidityStats:
    rejections: int = 0
    redraws: int = 0
    clips: int = 0
    per_variable_violations: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rejections": int(self.rejections),
            "redraws": int(self.redraws),
            "clips": int(self.clips),
            "per_variable_violations": {
                key: int(value)
                for key, value in sorted(self.per_variable_violations.items())
            },
        }


def bounds_for_variables(
    registry: VariableRegistry,
    variable_order: list[str],
) -> dict[str, tuple[float, float]]:
    bounds: dict[str, tuple[float, float]] = {}
    missing: list[str] = []
    for variable in variable_order:
        spec = registry.get(variable)
        if spec.bounds is None:
            missing.append(variable)
        else:
            bounds[variable] = spec.bounds
    if missing:
        raise BoundsError(
            "Missing registry bounds for spine variables: "
            f"{', '.join(missing)}. Add bounds: [lo, hi] in state_vector.yaml."
        )
    return bounds


def validate_registry_bounds(registry: VariableRegistry) -> dict[str, tuple[float, float]]:
    return bounds_for_variables(registry, registry.spine_variable_names())


def find_violations(
    path: np.ndarray,
    variable_order: list[str],
    bounds: dict[str, tuple[float, float]],
) -> dict[str, int]:
    array = np.asarray(path, dtype=float)
    if array.ndim != 2:
        raise BoundsError(f"path must have shape (horizon, n_vars); got {array.shape}")
    if array.shape[1] != len(variable_order):
        raise BoundsError(
            f"path variable dimension {array.shape[1]} does not match "
            f"variable order length {len(variable_order)}"
        )
    violations: dict[str, int] = {}
    for index, variable in enumerate(variable_order):
        if variable not in bounds:
            raise BoundsError(f"bounds missing for variable '{variable}'")
        lo, hi = bounds[variable]
        mask = (array[:, index] < lo) | (array[:, index] > hi)
        count = int(np.sum(mask))
        if count:
            violations[variable] = count
    return violations


def clip_path_to_bounds(
    path: np.ndarray,
    variable_order: list[str],
    bounds: dict[str, tuple[float, float]],
) -> np.ndarray:
    clipped = np.asarray(path, dtype=float).copy()
    for index, variable in enumerate(variable_order):
        lo, hi = bounds[variable]
        clipped[:, index] = np.clip(clipped[:, index], lo, hi)
    return clipped


def add_violations(stats: ValidityStats, violations: dict[str, int]) -> None:
    for variable, count in violations.items():
        stats.per_variable_violations[variable] = (
            stats.per_variable_violations.get(variable, 0) + int(count)
        )
