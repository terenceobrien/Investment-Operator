"""Deterministic scenario path classifier."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry
from src.agent_system.forecasting.scenario_classifier.scaling import ScaleSet
from src.agent_system.forecasting.scenario_classifier.signatures import (
    ScenarioSignatures,
)


class ClassifierError(RuntimeError):
    """Raised when classifier inputs are inconsistent."""


class ScenarioClassifier:
    def __init__(
        self,
        registry: VariableRegistry,
        signatures: ScenarioSignatures,
        scales: ScaleSet,
        config: dict[str, Any],
        *,
        include_only: list[str] | None = None,
        exclude: list[str] | None = None,
        robust: bool = False,
    ) -> None:
        if include_only and exclude:
            raise ClassifierError("include_only and exclude are mutually exclusive")
        self.registry = registry
        self.signatures = signatures
        self.scales = scales
        self.config = dict(config)
        self.robust = robust
        self.scenario_ids = list(signatures.scenario_ids)
        self.full_variable_order = list(signatures.active_variables)
        self.active_variables = self._select_variables(include_only, exclude)
        self._full_indices = [
            self.full_variable_order.index(variable)
            for variable in self.active_variables
        ]
        self.kernel_sigma = float(self.config.get("kernel_sigma", 1.0))
        if self.kernel_sigma <= 0:
            raise ClassifierError("kernel_sigma must be positive")
        self._scale_vector = np.asarray(
            [
                self.scales.scale_for(variable, robust=robust)
                for variable in self.active_variables
            ],
            dtype=float,
        )
        self._signature_matrix = signatures.matrix[:, :, self._full_indices]
        if self._signature_matrix.shape[1] != scales.horizon_quarters:
            raise ClassifierError(
                "signature K does not match scales K: "
                f"{self._signature_matrix.shape[1]} vs {scales.horizon_quarters}"
            )

    def classify(
        self,
        paths: np.ndarray,
        path_ids: list[Any] | None = None,
    ) -> pd.DataFrame:
        path_array = self._normalize_paths(paths)
        n_paths = path_array.shape[0]
        if path_ids is None:
            path_ids = list(range(n_paths))
        if len(path_ids) != n_paths:
            raise ClassifierError(
                f"path_ids length {len(path_ids)} does not match n_paths {n_paths}"
            )

        scaled_paths = path_array / self._scale_vector.reshape(1, 1, -1)
        scaled_signatures = self._signature_matrix / self._scale_vector.reshape(1, 1, -1)
        diff = scaled_paths[:, None, :, :] - scaled_signatures[None, :, :, :]
        distances = np.sqrt(np.sum(diff * diff, axis=(2, 3)))
        assigned_indices = np.argmin(distances, axis=1)

        rows: list[dict[str, Any]] = []
        for row_index, path_id in enumerate(path_ids):
            row: dict[str, Any] = {"path_id": path_id}
            for scenario_index, scenario_id in enumerate(self.scenario_ids):
                row[f"distance_{scenario_id}"] = float(distances[row_index, scenario_index])
            sorted_distances = np.sort(distances[row_index])
            best = float(sorted_distances[0])
            second = float(sorted_distances[1]) if len(sorted_distances) > 1 else best
            assigned = self.scenario_ids[int(assigned_indices[row_index])]
            row["assigned"] = assigned
            row["margin"] = second - best
            soft = self._soft_assign(distances[row_index])
            for scenario_id, probability in zip(self.scenario_ids, soft):
                row[f"soft_{scenario_id}"] = float(probability)
            rows.append(row)

        result = pd.DataFrame(rows)
        metadata = self._metadata()
        result.attrs["metadata"] = metadata
        try:
            object.__setattr__(result, "metadata", metadata)
        except Exception:
            pass
        return result

    def variable_contributions(self, path: np.ndarray) -> pd.DataFrame:
        raw_path = np.asarray(path, dtype=float)
        if raw_path.ndim != 2:
            raise ClassifierError(
                f"path must have shape (K, n_vars) for contributions; got {raw_path.shape}"
            )
        path_array = self._normalize_paths(raw_path.reshape(1, *raw_path.shape))[0]
        scaled_path = path_array / self._scale_vector.reshape(1, -1)
        scaled_signatures = self._signature_matrix / self._scale_vector.reshape(1, 1, -1)
        rows: list[dict[str, Any]] = []
        for scenario_index, scenario_id in enumerate(self.scenario_ids):
            squared = (scaled_path - scaled_signatures[scenario_index]) ** 2
            for variable_index, variable in enumerate(self.active_variables):
                rows.append(
                    {
                        "scenario": scenario_id,
                        "variable": variable,
                        "contribution": float(np.sum(squared[:, variable_index])),
                    }
                )
        return pd.DataFrame(rows)

    def _normalize_paths(self, paths: np.ndarray) -> np.ndarray:
        path_array = np.asarray(paths, dtype=float)
        if path_array.ndim != 3:
            raise ClassifierError(
                f"paths must have shape (n_paths, K, n_vars); got {path_array.shape}"
            )
        expected_k = self.scales.horizon_quarters
        if path_array.shape[1] != expected_k:
            raise ClassifierError(
                f"paths K={path_array.shape[1]} does not match classifier K={expected_k}"
            )
        if path_array.shape[2] == len(self.full_variable_order):
            path_array = path_array[:, :, self._full_indices]
        elif path_array.shape[2] != len(self.active_variables):
            raise ClassifierError(
                f"paths variable dimension {path_array.shape[2]} does not match "
                f"active variables ({len(self.active_variables)}) or full signature "
                f"variables ({len(self.full_variable_order)})"
            )
        if not np.isfinite(path_array).all():
            raise ClassifierError("paths contain non-finite values")
        return path_array

    def _select_variables(
        self,
        include_only: list[str] | None,
        exclude: list[str] | None,
    ) -> list[str]:
        available = set(self.full_variable_order)
        if include_only:
            selected = [_clean_variable_name(value) for value in include_only]
            missing = [variable for variable in selected if variable not in available]
            if missing:
                raise ClassifierError(
                    f"include_only references variables not active in handoff: {missing}"
                )
            return _require_nonempty(selected, "include_only")
        if exclude:
            excluded = {_clean_variable_name(value) for value in exclude}
            missing = sorted(excluded - available)
            if missing:
                raise ClassifierError(f"exclude references variables not active in handoff: {missing}")
            selected = [
                variable
                for variable in self.full_variable_order
                if variable not in excluded
            ]
            return _require_nonempty(selected, "exclude")
        return list(self.full_variable_order)

    def _soft_assign(self, distances: np.ndarray) -> np.ndarray:
        weights = np.exp(-((distances ** 2) / (2.0 * self.kernel_sigma ** 2)))
        total = float(np.sum(weights))
        if total <= 0 or not np.isfinite(total):
            return np.ones_like(weights) / len(weights)
        return weights / total

    def _metadata(self) -> dict[str, Any]:
        metadata = self.signatures.metadata
        metadata.update(
            {
                "active_variables": list(self.active_variables),
                "full_signature_variables": list(self.full_variable_order),
                "scales_file": str(self.scales.path),
                "scales_fit_timestamp": self.scales.fit_timestamp,
                "scaling": "mad" if self.robust else "std",
                "kernel_sigma": self.kernel_sigma,
            }
        )
        return metadata


def _clean_variable_name(value: str) -> str:
    clean = str(value).strip()
    if not clean:
        raise ClassifierError("empty variable name")
    return clean


def _require_nonempty(values: list[str], label: str) -> list[str]:
    if not values:
        raise ClassifierError(f"{label} leaves no active variables")
    return values
