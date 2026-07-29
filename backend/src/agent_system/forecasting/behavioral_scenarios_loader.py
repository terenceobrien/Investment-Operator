"""Typed loader for behavioral scenario taxonomy artifacts.

These artifacts define the behavioral scenario spine used by the shadow BVAR
ensemble. They are taxonomy/configuration only: scenario probabilities are model
outputs and must never appear in behavioral_scenarios.yaml.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agent_system.forecasting.scenario_classifier.signatures import (
    SignatureError,
    default_handoff_dir,
    newest_handoff_path,
)
from src.agent_system.paths import agent_system_data_root
from src.agent_system.services.scenario_translation import BEHAVIORAL_SCENARIO_IDS


logger = logging.getLogger(__name__)

EXPECTED_BEHAVIORAL_SCENARIO_IDS = tuple(BEHAVIORAL_SCENARIO_IDS)
_PROBABILITY_KEYS = {
    "probability",
    "probabilities",
    "prior_probability",
    "scenario_probability",
    "scenario_probabilities",
    "scenario_probabilities_blended",
    "scenario_probabilities_deterministic",
}


class BehavioralScenarioLoaderError(RuntimeError):
    """Raised when behavioral scenario artifacts are invalid."""


class BehavioralScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    macro_configuration: dict[str, Any]
    definition: str
    classifier_signature_ref: str
    frbus_template: str
    factor_implications: dict[str, Any]
    preferred_exposures: list[str] = Field(default_factory=list)
    vulnerable_exposures: list[str] = Field(default_factory=list)
    narrative_lineage: list[str] = Field(default_factory=list)
    historical_analogues: list[Any] = Field(default_factory=list)
    market_returns: dict[str, Any]
    theme_returns: dict[str, Any]


class CurrentConditions(BaseModel):
    model_config = ConfigDict(extra="allow")

    current_regime_read: dict[str, Any]
    transition_catalysts: dict[str, Any]
    within_regime_tilts: dict[str, Any] = Field(default_factory=dict)
    operator_prior_note: str | None = None

    @model_validator(mode="after")
    def _validate_references(self) -> "CurrentConditions":
        valid = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
        read = self.current_regime_read
        for key in ("primary_behavioral_scenario", "secondary_behavioral_scenario"):
            value = read.get(key)
            if value is not None and value not in valid:
                raise ValueError(f"current_regime_read.{key} references unknown scenario '{value}'")
        for value in read.get("tail_watch") or []:
            if value not in valid:
                raise ValueError(f"current_regime_read.tail_watch references unknown scenario '{value}'")
        for tilt_id, payload in self.within_regime_tilts.items():
            if not isinstance(payload, dict):
                raise ValueError(f"within_regime_tilts.{tilt_id} must be a mapping")
            applies_within = payload.get("applies_within")
            if not isinstance(applies_within, list) or not applies_within:
                raise ValueError(f"within_regime_tilts.{tilt_id}.applies_within must be a non-empty list")
            unknown = [item for item in applies_within if item not in valid]
            if unknown:
                raise ValueError(
                    f"within_regime_tilts.{tilt_id}.applies_within references unknown scenarios {unknown}"
                )
        return self


def default_behavioral_scenarios_path() -> Path:
    config_path = Path(__file__).resolve().parents[1] / "config" / "behavioral_scenarios.yaml"
    if config_path.is_file():
        return config_path
    return agent_system_data_root() / "scenarios" / "behavioral_scenarios.yaml"


def default_current_conditions_path() -> Path:
    config_path = Path(__file__).resolve().parents[1] / "config" / "current_conditions.yaml"
    if config_path.is_file():
        return config_path
    return agent_system_data_root() / "scenarios" / "current_conditions.yaml"


def load_behavioral_scenarios(path: str | Path | None = None) -> dict[str, BehavioralScenario]:
    source = Path(path) if path is not None else default_behavioral_scenarios_path()
    payload = _read_yaml_mapping(source)
    scenarios_payload = payload.get("scenarios")
    if not isinstance(scenarios_payload, dict):
        raise BehavioralScenarioLoaderError(f"{source} missing required 'scenarios' mapping")
    _assert_no_probability_keys(scenarios_payload, source)

    actual_ids = set(scenarios_payload)
    expected_ids = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    if actual_ids != expected_ids:
        raise BehavioralScenarioLoaderError(
            f"{source} must contain exactly behavioral scenarios {sorted(expected_ids)}; "
            f"missing={sorted(expected_ids - actual_ids)} extra={sorted(actual_ids - expected_ids)}"
        )

    scenarios: dict[str, BehavioralScenario] = {}
    for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS:
        raw = scenarios_payload.get(scenario_id)
        if not isinstance(raw, dict):
            raise BehavioralScenarioLoaderError(f"{source} scenario '{scenario_id}' must be a mapping")
        try:
            scenarios[scenario_id] = BehavioralScenario.model_validate({"id": scenario_id, **raw})
        except Exception as exc:
            raise BehavioralScenarioLoaderError(
                f"{source} scenario '{scenario_id}' is invalid: {exc}"
            ) from exc
    return scenarios


def load_current_conditions(path: str | Path | None = None) -> CurrentConditions:
    source = Path(path) if path is not None else default_current_conditions_path()
    payload = _read_yaml_mapping(source)
    required = {"current_regime_read", "transition_catalysts", "within_regime_tilts", "operator_prior_note"}
    missing = sorted(required - set(payload))
    if missing:
        raise BehavioralScenarioLoaderError(f"{source} missing required blocks: {missing}")
    try:
        return CurrentConditions.model_validate(payload)
    except Exception as exc:
        raise BehavioralScenarioLoaderError(f"{source} current conditions are invalid: {exc}") from exc


def scenario_metadata(
    scenarios: dict[str, BehavioralScenario],
) -> dict[str, dict[str, Any]]:
    return {
        scenario_id: {
            "label": scenario.label,
            "macro_configuration": scenario.macro_configuration,
        }
        for scenario_id, scenario in scenarios.items()
    }


def resolve_classifier_signature_ref(
    classifier_signature_ref: str,
    *,
    handoff_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve a frbus_handoff::<scenario_id> reference if a handoff is available."""

    prefix = "frbus_handoff::"
    if not classifier_signature_ref.startswith(prefix):
        logger.warning("Unsupported classifier_signature_ref: %s", classifier_signature_ref)
        return None
    scenario_id = classifier_signature_ref.removeprefix(prefix)
    directory = Path(handoff_dir) if handoff_dir is not None else default_handoff_dir()
    try:
        handoff_path = newest_handoff_path(directory)
        payload = json.loads(handoff_path.read_text(encoding="utf-8"))
        scenario = (payload.get("scenarios") or {}).get(scenario_id)
        if not isinstance(scenario, dict):
            logger.warning(
                "FRB/US handoff %s has no scenario '%s'; leaving signature unresolved",
                handoff_path,
                scenario_id,
            )
            return None
        return {
            "handoff_file": str(handoff_path),
            "baseline_data_fingerprint": payload.get("baseline_data_fingerprint"),
            "map_version": payload.get("map_version"),
            "scenario_id": scenario_id,
            "deltas_vs_baseline": scenario.get("deltas_vs_baseline"),
        }
    except (OSError, json.JSONDecodeError, SignatureError) as exc:
        logger.warning(
            "Could not resolve %s against latest FRB/US handoff: %s",
            classifier_signature_ref,
            exc,
        )
        return None


def resolve_scenario_correlation_ref(
    scenario_correlation_ref: str | None = None,
    *,
    classifier_cache_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Resolve classifier_cache::scenario_signature_correlation lazily.

    Stage 2 does not currently persist a dedicated correlation matrix, so this
    resolver returns cache provenance if the cache is present and logs a warning
    otherwise. The interface is intentionally stable for the future rebase.
    """

    ref = scenario_correlation_ref or _scenario_correlation_ref_from_default_yaml()
    if not ref:
        return None
    if ref != "classifier_cache::scenario_signature_correlation":
        logger.warning("Unsupported scenario_correlation_ref: %s", ref)
        return None
    cache_dir = Path(classifier_cache_dir) if classifier_cache_dir is not None else agent_system_data_root() / "classifier_cache"
    manifest = cache_dir / "cache_manifest.json"
    scales = cache_dir / "scales.json"
    if not manifest.is_file() or not scales.is_file():
        logger.warning(
            "Could not resolve %s: missing classifier cache manifest/scales under %s",
            ref,
            cache_dir,
        )
        return None
    return {
        "ref": ref,
        "classifier_cache_dir": str(cache_dir),
        "cache_manifest": str(manifest),
        "scales": str(scales),
    }


def _scenario_correlation_ref_from_default_yaml() -> str | None:
    try:
        payload = _read_yaml_mapping(default_behavioral_scenarios_path())
    except BehavioralScenarioLoaderError:
        return None
    value = payload.get("scenario_correlation_ref")
    return str(value) if value else None


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BehavioralScenarioLoaderError(f"behavioral artifact not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise BehavioralScenarioLoaderError(f"could not parse YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise BehavioralScenarioLoaderError(f"{path} must contain a YAML mapping")
    return payload


def _assert_no_probability_keys(value: Any, source: Path, *, path: str = "scenarios") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            if key_text.lower() in _PROBABILITY_KEYS:
                raise BehavioralScenarioLoaderError(
                    f"{source} contains forbidden probability field at {path}.{key_text}; "
                    "behavioral_scenarios.yaml is taxonomy-only"
                )
            _assert_no_probability_keys(nested, source, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_no_probability_keys(nested, source, path=f"{path}[{index}]")
