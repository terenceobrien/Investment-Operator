"""FRB/US handoff signature loading for the scenario classifier."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
    VariableSpec,
)
from src.agent_system.paths import agent_system_data_root


SCENARIO_IDS = [
    "expansion_disinflation",
    "late_cycle_expansion",
    "inflation_shock",
    "stagflation",
    "growth_scare_no_credit",
    "credit_led_recession",
]

MISSING_RBBBP_WARNING = (
    "WARNING: loaded FRB/US handoff lacks rbbbp_pct. Classification will run "
    "without the credit_spread signature variable, and the two "
    "credit-differentiated episodes will likely fail. Regenerate the FRB/US "
    "handoff after adding rbbbp_pct to extract_paths."
)


class SignatureError(RuntimeError):
    """Raised when FRB/US signatures cannot be loaded."""


@dataclass(frozen=True)
class ScenarioSignatures:
    scenario_ids: list[str]
    active_variables: list[str]
    signature_maps: dict[str, str]
    matrix: np.ndarray
    handoff_path: Path
    baseline_data_fingerprint: str | None
    map_version: str | None
    generated_at: str | None
    horizon_quarters: int
    missing_credit_spread: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "scenario_ids": self.scenario_ids,
            "active_variables": self.active_variables,
            "signature_maps": self.signature_maps,
            "handoff_file": str(self.handoff_path),
            "baseline_data_fingerprint": self.baseline_data_fingerprint,
            "map_version": self.map_version,
            "generated_at": self.generated_at,
            "horizon_quarters": self.horizon_quarters,
            "missing_credit_spread": self.missing_credit_spread,
            "warnings": list(self.warnings),
        }


def default_handoff_dir() -> Path:
    return agent_system_data_root() / "frbus_handoffs"


def load_latest_signatures(
    registry: VariableRegistry,
    *,
    handoff_dir: str | Path | None = None,
    horizon_quarters: int = 4,
) -> ScenarioSignatures:
    directory = Path(handoff_dir) if handoff_dir is not None else default_handoff_dir()
    handoff_path = newest_handoff_path(directory)
    return load_signatures_from_handoff(
        registry,
        handoff_path=handoff_path,
        horizon_quarters=horizon_quarters,
    )


def newest_handoff_path(directory: str | Path) -> Path:
    path = Path(directory)
    if not path.is_dir():
        raise SignatureError(f"FRB/US handoff directory not found: {path}")
    candidates = sorted(
        path.glob("frbus_scenario_paths_*.json"),
        key=lambda item: (item.stat().st_mtime, item.name),
        reverse=True,
    )
    if not candidates:
        raise SignatureError(
            f"No FRB/US handoff JSON found in {path}; expected frbus_scenario_paths_*.json"
        )
    return candidates[0]


def load_signatures_from_handoff(
    registry: VariableRegistry,
    *,
    handoff_path: str | Path,
    horizon_quarters: int = 4,
) -> ScenarioSignatures:
    path = Path(handoff_path)
    if not path.is_file():
        raise SignatureError(f"FRB/US handoff JSON not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SignatureError(f"Could not parse FRB/US handoff JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SignatureError(f"FRB/US handoff must contain a JSON object: {path}")

    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict):
        raise SignatureError(f"FRB/US handoff missing scenarios mapping: {path}")
    missing_scenarios = [sid for sid in SCENARIO_IDS if sid not in scenarios]
    if missing_scenarios:
        raise SignatureError(
            f"FRB/US handoff {path} missing scenarios: {missing_scenarios}"
        )
    if horizon_quarters < 1:
        raise SignatureError("horizon_quarters must be positive")

    signature_variables = registry.signature_variables()
    active_specs, missing_credit_spread, warnings = _active_signature_specs(
        signature_variables,
        scenarios,
        path,
    )
    if not active_specs:
        raise SignatureError(f"No active signature variables after handoff validation: {path}")

    matrices: list[np.ndarray] = []
    for scenario_id in SCENARIO_IDS:
        scenario_payload = scenarios[scenario_id]
        deltas = scenario_payload.get("deltas_vs_baseline")
        if not isinstance(deltas, dict):
            raise SignatureError(
                f"scenario '{scenario_id}' missing deltas_vs_baseline in {path}"
            )
        scenario_rows: list[list[float]] = []
        for quarter_offset in range(1, horizon_quarters + 1):
            row: list[float] = []
            for spec in active_specs:
                key = spec.signature_map
                if key is None:
                    raise SignatureError(f"variable '{spec.name}' has no signature_map")
                values = deltas.get(key)
                if not isinstance(values, list):
                    raise SignatureError(
                        f"scenario '{scenario_id}' missing signature key '{key}' "
                        f"for variable '{spec.name}' in {path}"
                    )
                if quarter_offset >= len(values):
                    raise SignatureError(
                        f"scenario '{scenario_id}' key '{key}' has only {len(values)} "
                        f"quarters; need index {quarter_offset} for K={horizon_quarters}"
                    )
                value = values[quarter_offset]
                if value is None or not np.isfinite(float(value)):
                    raise SignatureError(
                        f"scenario '{scenario_id}' key '{key}' has non-finite value "
                        f"at quarter offset {quarter_offset} in {path}"
                    )
                row.append(float(value))
            scenario_rows.append(row)
        matrices.append(np.asarray(scenario_rows, dtype=float))

    return ScenarioSignatures(
        scenario_ids=list(SCENARIO_IDS),
        active_variables=[spec.name for spec in active_specs],
        signature_maps={spec.name: spec.signature_map or "" for spec in active_specs},
        matrix=np.stack(matrices, axis=0),
        handoff_path=path,
        baseline_data_fingerprint=_optional_string(payload.get("baseline_data_fingerprint")),
        map_version=_optional_string(payload.get("map_version")),
        generated_at=_optional_string(payload.get("generated_at")),
        horizon_quarters=horizon_quarters,
        missing_credit_spread=missing_credit_spread,
        warnings=tuple(warnings),
    )


def _active_signature_specs(
    specs: list[VariableSpec],
    scenarios: dict[str, Any],
    handoff_path: Path,
) -> tuple[list[VariableSpec], bool, list[str]]:
    active: list[VariableSpec] = []
    missing_credit_spread = False
    warnings: list[str] = []
    for spec in specs:
        key = spec.signature_map
        if key is None:
            raise SignatureError(f"signature variable '{spec.name}' has no signature_map")
        missing = _scenarios_missing_key(scenarios, key)
        if missing:
            if key == "rbbbp_pct":
                missing_credit_spread = True
                warnings.append(MISSING_RBBBP_WARNING)
                continue
            raise SignatureError(
                f"FRB/US handoff {handoff_path} missing signature key '{key}' "
                f"for variable '{spec.name}' in scenarios {missing}"
            )
        active.append(spec)
    return active, missing_credit_spread, warnings


def _scenarios_missing_key(scenarios: dict[str, Any], key: str) -> list[str]:
    missing: list[str] = []
    for scenario_id in SCENARIO_IDS:
        payload = scenarios.get(scenario_id)
        deltas = payload.get("deltas_vs_baseline") if isinstance(payload, dict) else None
        if not isinstance(deltas, dict) or key not in deltas:
            missing.append(scenario_id)
    return missing


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
