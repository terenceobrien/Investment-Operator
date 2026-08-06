"""Coherent macro scenario source for research-cycle orchestration.

This module is the keystone for the narrative-v0 to behavioral-v1 rebase. It
returns scenario probabilities, scenario definitions, and the current-condition
read as one validated payload so the live cycle cannot accidentally pair
probabilities from one taxonomy with scenario definitions from another.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    CurrentConditions,
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
    default_behavioral_scenarios_path,
    default_current_conditions_path,
    load_behavioral_scenarios,
    load_current_conditions,
)
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    artifact_candidate_paths,
    default_bvar_cache_dir,
)
from src.agent_system.forecasting.macro_forecast_shadow import cycle_date_to_asof_quarter
from src.agent_system.macro.loader import (
    DEFAULT_CURRENT_REGIME_PATH,
    load_current_priorities,
    load_current_regime_yaml,
)
from src.agent_system.scenarios.loader import current_path, load_current_scenarios
from src.agent_system.scenarios.types import (
    DEFAULT_SCENARIO_PRIORS,
    FactorImplications,
    Scenario,
    ScenarioSet,
)
from src.agent_system.schemas.macro_forecast import MacroForecastResult
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.regime import EdgeDecayHorizon, ResearchPriority


NARRATIVE_SCENARIO_IDS = tuple(DEFAULT_SCENARIO_PRIORS)
KNOWN_TAXONOMY_IDS = {
    "narrative_v0": set(NARRATIVE_SCENARIO_IDS),
    "behavioral_v1": set(EXPECTED_BEHAVIORAL_SCENARIO_IDS),
}


class MacroScenarioSourceError(RuntimeError):
    """Raised when a coherent macro scenario source cannot be built."""


@dataclass(frozen=True)
class CurrentConditionsView:
    taxonomy: str
    as_of: str | None = None
    regime_id_basis: str | None = None
    current_regime_read: dict[str, Any] = field(default_factory=dict)
    tail_watch: list[str] = field(default_factory=list)
    transition_catalysts: dict[str, Any] = field(default_factory=dict)
    within_regime_tilts: dict[str, Any] = field(default_factory=dict)
    operator_prior_note: str | None = None
    source_path: str | None = None


@dataclass(frozen=True)
class MacroScenarioSourceConfig:
    macro_forecast_source: str = "ensemble"
    narrative_macro_forecast_dir: str | Path | None = None
    current_regime_path: str | Path | None = None
    bvar_cache_dir: str | Path | None = None
    behavioral_scenarios_path: str | Path | None = None
    current_conditions_path: str | Path | None = None
    analogue_evidence_enabled: bool = True

    def __post_init__(self) -> None:
        if self.macro_forecast_source not in {"narrative", "ensemble"}:
            raise MacroScenarioSourceError(
                "macro_forecast_source must be 'narrative' or 'ensemble'; "
                f"got {self.macro_forecast_source!r}"
            )
        if not isinstance(self.analogue_evidence_enabled, bool):
            raise MacroScenarioSourceError(
                "analogue_evidence_enabled must be true/false; "
                f"got {self.analogue_evidence_enabled!r}"
            )


@dataclass(frozen=True)
class MacroScenarioSource:
    taxonomy: str
    scenario_probabilities: dict[str, float]
    scenario_set: ScenarioSet
    current_conditions: CurrentConditionsView
    seed_research_priorities: list[ResearchPriority] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        known_ids = KNOWN_TAXONOMY_IDS.get(self.taxonomy)
        if known_ids is None:
            raise MacroScenarioSourceError(
                f"unknown macro scenario taxonomy {self.taxonomy!r}; "
                f"expected one of {sorted(KNOWN_TAXONOMY_IDS)}"
            )
        probability_ids = set(self.scenario_probabilities)
        scenario_ids = {scenario.id for scenario in self.scenario_set.scenarios}
        if probability_ids != scenario_ids:
            raise MacroScenarioSourceError(
                "macro scenario source desync: probability ids do not match scenario_set ids; "
                f"probability_ids={sorted(probability_ids)}, scenario_set_ids={sorted(scenario_ids)}"
            )
        if probability_ids != known_ids:
            raise MacroScenarioSourceError(
                f"macro scenario source desync: taxonomy {self.taxonomy} expects "
                f"{sorted(known_ids)} but got {sorted(probability_ids)}"
            )
        total = sum(float(value) for value in self.scenario_probabilities.values())
        if abs(total - 1.0) > 1e-9:
            raise MacroScenarioSourceError(
                f"macro scenario probabilities must sum to 1.0 within 1e-9 for {self.taxonomy}; got {total:.12f}"
            )
        foreign_seed_ids = sorted(
            {
                scenario_id
                for priority in self.seed_research_priorities
                for scenario_id in priority.source_scenario_ids
                if scenario_id not in known_ids
            }
        )
        if foreign_seed_ids:
            raise MacroScenarioSourceError(
                f"macro scenario source seed-priority taxonomy leak: taxonomy {self.taxonomy} "
                f"cannot carry source_scenario_ids={foreign_seed_ids}"
            )


def default_research_cycle_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "research_cycle.yaml"


def load_macro_scenario_source_config(
    path: str | Path | None = None,
    *,
    macro_forecast_source: str | None = None,
) -> MacroScenarioSourceConfig:
    config_path = Path(path) if path is not None else default_research_cycle_config_path()
    payload: dict[str, Any] = {}
    if config_path.is_file():
        with config_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise MacroScenarioSourceError(f"research cycle config must contain a mapping: {config_path}")
        payload.update(raw)
    env_source = os.getenv("MACRO_FORECAST_SOURCE")
    if env_source:
        payload["macro_forecast_source"] = env_source
    if macro_forecast_source is not None:
        payload["macro_forecast_source"] = macro_forecast_source
    config = MacroScenarioSourceConfig(**payload)
    return config


def get_macro_scenario_source(
    *,
    cycle_date: str,
    config: MacroScenarioSourceConfig | Mapping[str, Any] | Any | None = None,
) -> MacroScenarioSource:
    source_config = _coerce_config(config)
    source = source_config.macro_forecast_source
    if source == "ensemble":
        return _build_behavioral_source(cycle_date, source_config)
    if source == "narrative":
        return _build_narrative_source(cycle_date, source_config)
    raise MacroScenarioSourceError(f"unknown macro_forecast_source {source!r}")


def preflight_ensemble_source(
    *,
    cycle_date: str,
    config: MacroScenarioSourceConfig | Mapping[str, Any] | Any | None = None,
) -> dict[str, Any]:
    """Validate ensemble-mode artifacts and behavioral coverage before a cycle.

    This intentionally hard-errors on missing or stale artifacts. It does not
    fall back to narrative; rollback is an explicit macro_forecast_source switch.
    """

    source_config = replace(_coerce_config(config), macro_forecast_source="ensemble")
    expected_asof = cycle_date_to_asof_quarter(cycle_date)
    macro_source = get_macro_scenario_source(
        cycle_date=cycle_date,
        config=source_config,
    )
    actual_asof = macro_source.provenance.get("ensemble_forecast_asof_quarter")
    if actual_asof and actual_asof != expected_asof:
        raise MacroScenarioSourceError(
            "ensemble forecast anchor mismatch: "
            f"cycle_date={cycle_date} expects {expected_asof}, "
            f"but artifact reports {actual_asof}. Run the ensemble forecast for {expected_asof}."
        )
    _validate_behavioral_theme_coverage()
    _validate_behavioral_compatibility()
    return {
        "ok": True,
        "cycle_date": cycle_date,
        "expected_asof_quarter": expected_asof,
        "taxonomy": macro_source.taxonomy,
        "scenario_ids": sorted(macro_source.scenario_probabilities),
        "scenario_probability_sum": sum(macro_source.scenario_probabilities.values()),
        "ensemble_forecast_path": macro_source.provenance.get("ensemble_forecast_path"),
        "ensemble_generated_at": macro_source.provenance.get("ensemble_generated_at"),
        "regime_model": macro_source.provenance.get("regime_model"),
        "vol_model": macro_source.provenance.get("vol_model"),
        "shock_dist": macro_source.provenance.get("shock_dist"),
        "behavioral_scenarios_path": macro_source.provenance.get("behavioral_scenarios_path"),
        "current_conditions_path": macro_source.provenance.get("current_conditions_path"),
    }


def validate_seed_priorities_match_taxonomy(
    priorities: list[ResearchPriority],
    taxonomy: str,
) -> None:
    """Hard-error if seed-priority scenario ids leak across taxonomies."""

    known_ids = KNOWN_TAXONOMY_IDS.get(taxonomy)
    if known_ids is None:
        raise MacroScenarioSourceError(f"unknown macro scenario taxonomy {taxonomy!r}")
    foreign = sorted(
        {
            scenario_id
            for priority in priorities
            for scenario_id in priority.source_scenario_ids
            if scenario_id not in known_ids
        }
    )
    if foreign:
        raise MacroScenarioSourceError(
            f"seed priorities contain scenario ids outside {taxonomy}: {foreign}"
        )


def regime_curation_payload_from_macro_source(
    macro_source: MacroScenarioSource,
) -> dict[str, Any]:
    """Build the curation payload consumed by the generic regime adapter.

    The payload is coherent with the active taxonomy: scenario probabilities
    always come from ``macro_source``, while qualitative regime-read fields come
    from that same source's current-conditions view.
    """

    validate_seed_priorities_match_taxonomy(
        macro_source.seed_research_priorities,
        macro_source.taxonomy,
    )
    if macro_source.taxonomy == "narrative_v0":
        source_path = macro_source.current_conditions.source_path
        payload = load_current_regime_yaml(Path(source_path) if source_path else None)
        payload = dict(payload)
        payload.setdefault("scenario_taxonomy", "narrative_v0")
        payload["scenario_probabilities"] = dict(macro_source.scenario_probabilities)
        return payload
    if macro_source.taxonomy == "behavioral_v1":
        return _behavioral_curation_payload(macro_source)
    raise MacroScenarioSourceError(
        f"cannot build curation payload for unknown taxonomy {macro_source.taxonomy!r}"
    )


def load_latest_narrative_macro_forecast_result(
    reports_dir: str | Path | None = None,
) -> tuple[MacroForecastResult, Path] | None:
    root = Path(reports_dir) if reports_dir is not None else _default_narrative_macro_forecast_dir()
    try:
        candidates = sorted(
            root.glob("macro_forecast_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            return None
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                return MacroForecastResult.model_validate(payload), path
            except Exception:
                continue
        return None
    except Exception:
        return None


def scenario_probabilities_from_macro_forecast(
    result: MacroForecastResult,
) -> dict[str, float] | None:
    probabilities = (
        result.scenario_probabilities_blended
        or (
            result.historical_calibration.blended_scenario_probabilities
            if result.historical_calibration is not None
            else None
        )
        or result.scenario_probabilities
    )
    if probabilities:
        return {scenario_id: float(value) for scenario_id, value in probabilities.items()}
    return None


def _coerce_config(
    config: MacroScenarioSourceConfig | Mapping[str, Any] | Any | None,
) -> MacroScenarioSourceConfig:
    if config is None:
        return load_macro_scenario_source_config()
    if isinstance(config, MacroScenarioSourceConfig):
        return config
    if isinstance(config, Mapping):
        return MacroScenarioSourceConfig(**dict(config))
    values = {
        field_name: getattr(config, field_name)
        for field_name in MacroScenarioSourceConfig.__dataclass_fields__
        if hasattr(config, field_name)
    }
    if not values:
        raise MacroScenarioSourceError(
            "config must be a MacroScenarioSourceConfig, mapping, or object with "
            "macro_forecast_source"
        )
    return MacroScenarioSourceConfig(**values)


def _build_narrative_source(
    cycle_date: str,
    config: MacroScenarioSourceConfig,
) -> MacroScenarioSource:
    raise MacroScenarioSourceError(
        "macro_forecast_source=narrative is retired by the two_source_v1 rewire; "
        "use macro_forecast_source=ensemble with behavioral_v1 BVAR soft probabilities."
    )
    loaded = load_latest_narrative_macro_forecast_result(config.narrative_macro_forecast_dir)
    if loaded is None:
        raise MacroScenarioSourceError(
            "macro_forecast_source=narrative but no readable narrative macro forecast "
            "JSON was found; run the narrative macro forecast or set macro_forecast_source=ensemble explicitly."
        )
    forecast_result, forecast_path = loaded
    probabilities = scenario_probabilities_from_macro_forecast(forecast_result)
    if not probabilities:
        raise MacroScenarioSourceError(
            f"narrative macro forecast has no scenario probabilities: {forecast_path}"
        )
    scenario_set = load_current_scenarios()
    if scenario_set is None:
        raise MacroScenarioSourceError(
            "macro_forecast_source=narrative but current_scenarios.yaml was not found "
            "or was empty"
        )
    current_regime_path = (
        Path(config.current_regime_path)
        if config.current_regime_path is not None
        else DEFAULT_CURRENT_REGIME_PATH
    )
    current_conditions = _narrative_current_conditions_view(current_regime_path)
    seed_priorities = load_current_priorities(current_regime_path)
    return MacroScenarioSource(
        taxonomy="narrative_v0",
        scenario_probabilities=probabilities,
        scenario_set=scenario_set,
        current_conditions=current_conditions,
        seed_research_priorities=seed_priorities,
        provenance={
            "macro_forecast_source": "narrative",
            "cycle_date": cycle_date,
            "narrative_forecast_path": str(forecast_path),
            "narrative_forecast_asof_date": str(forecast_result.asof_date),
            "current_scenarios_path": str(current_path()),
            "current_regime_path": str(current_regime_path),
        },
    )


def _behavioral_curation_payload(
    macro_source: MacroScenarioSource,
) -> dict[str, Any]:
    read = macro_source.current_conditions.current_regime_read
    scenario_by_id = {scenario.id: scenario for scenario in macro_source.scenario_set.scenarios}
    primary = str(read.get("primary_behavioral_scenario") or "")
    secondary = str(read.get("secondary_behavioral_scenario") or "")
    primary_label = scenario_by_id.get(primary).label if primary in scenario_by_id else primary
    secondary_label = scenario_by_id.get(secondary).label if secondary in scenario_by_id else secondary
    summary = str(read.get("narrative_summary") or "")
    tail_watch = list(macro_source.current_conditions.tail_watch)
    probability = float(macro_source.scenario_probabilities.get(primary, 0.0))
    key_drivers = _behavioral_key_drivers(macro_source)
    return {
        "scenario_taxonomy": "behavioral_v1",
        "regime_id": primary or macro_source.current_conditions.regime_id_basis or "behavioral_regime",
        "regime_label": primary_label or "Behavioral macro regime",
        "regime_call_confidence": max(0.0, min(1.0, probability)),
        "regime_call_confidence_note": (
            "Generated from the active ensemble scenario probability for the operator-designated "
            "primary behavioral scenario."
        ),
        "headline": (
            f"{primary_label} leads the operator read"
            + (f"; {secondary_label} is secondary." if secondary_label else ".")
        ),
        "summary": summary,
        "risk_summary": _behavioral_risk_summary(macro_source),
        "scenario_probabilities": dict(macro_source.scenario_probabilities),
        "analogue_evidence": macro_source.provenance.get("analogue_evidence"),
        "mixture_decomposition": macro_source.provenance.get("analogue_evidence"),
        "probability_decomposition": macro_source.provenance.get("probability_decomposition"),
        "key_drivers": key_drivers,
        "portfolio_implications": _behavioral_portfolio_implications(macro_source),
        "best_positioned": _behavioral_exposures(macro_source, "preferred"),
        "most_vulnerable": _behavioral_exposures(macro_source, "vulnerable"),
        "falsifiers": _behavioral_falsifiers(macro_source),
        "seed_research_priorities": [
            _priority_to_adapter_payload(priority)
            for priority in macro_source.seed_research_priorities
        ],
        "tail_watch": tail_watch,
    }


def _build_behavioral_source(
    cycle_date: str,
    config: MacroScenarioSourceConfig,
) -> MacroScenarioSource:
    asof_quarter = cycle_date_to_asof_quarter(cycle_date)
    forecast_path, forecast_payload = _load_latest_ensemble_forecast_for_asof(
        asof_quarter,
        bvar_cache_dir=config.bvar_cache_dir,
    )
    artifact_asof_quarter = forecast_payload.get("asof_quarter")
    if artifact_asof_quarter is not None and str(artifact_asof_quarter) != asof_quarter:
        raise MacroScenarioSourceError(
            "ensemble forecast artifact anchor mismatch: "
            f"cycle_date={cycle_date} expects {asof_quarter}, "
            f"but {forecast_path} reports asof_quarter={artifact_asof_quarter}. "
            f"Run the frozen ensemble forecast for {asof_quarter}."
        )
    ensemble_probabilities = {
        str(key): float(value)
        for key, value in (forecast_payload.get("scenario_probabilities_soft") or {}).items()
    }
    if not ensemble_probabilities:
        raise MacroScenarioSourceError(
            f"ensemble forecast artifact has no scenario_probabilities_soft: {forecast_path}"
        )
    probabilities, analogue_report = _apply_analogue_evidence_stage(
        ensemble_probabilities,
        asof_quarter=asof_quarter,
        enabled=config.analogue_evidence_enabled,
    )

    behavioral_path = (
        Path(config.behavioral_scenarios_path)
        if config.behavioral_scenarios_path is not None
        else default_behavioral_scenarios_path()
    )
    conditions_path = (
        Path(config.current_conditions_path)
        if config.current_conditions_path is not None
        else default_current_conditions_path()
    )
    behavioral_scenarios = load_behavioral_scenarios(behavioral_path)
    current_conditions = load_current_conditions(conditions_path)
    scenario_set = _behavioral_scenario_set(
        behavioral_scenarios,
        probabilities,
        forecast_payload=forecast_payload,
        behavioral_path=behavioral_path,
    )
    conditions_view = _behavioral_current_conditions_view(
        current_conditions,
        conditions_path,
    )
    seed_priorities = _behavioral_seed_research_priorities(
        behavioral_scenarios,
        probabilities,
        conditions_view,
        forecast_payload=forecast_payload,
    )
    probability_decomposition = {
        "bvar_soft": dict(ensemble_probabilities),
        "ensemble_posteriors": dict(ensemble_probabilities),
        "analogue_mixture": analogue_report,
        "analogue_evidence": analogue_report,
        "post_analogue": dict(probabilities),
        "operator_priors": {
            "status": "not_applied_in_macro_scenario_source",
            "operator_prior_note": current_conditions.operator_prior_note,
            "probabilities_before": dict(probabilities),
            "probabilities_after": dict(probabilities),
        },
        "final_distribution": dict(probabilities),
    }
    return MacroScenarioSource(
        taxonomy="behavioral_v1",
        scenario_probabilities=probabilities,
        scenario_set=scenario_set,
        current_conditions=conditions_view,
        seed_research_priorities=seed_priorities,
        provenance={
            "macro_forecast_source": "ensemble",
            "cycle_date": cycle_date,
            "asof_quarter": asof_quarter,
            "scenario_probabilities_bvar_soft": dict(ensemble_probabilities),
            "scenario_probabilities_post_analogue": dict(probabilities),
            "analogue_evidence": analogue_report,
            "probability_decomposition": probability_decomposition,
            "ensemble_forecast_path": str(forecast_path),
            "ensemble_forecast_asof_quarter": forecast_payload.get("asof_quarter"),
            "ensemble_generated_at": forecast_payload.get("generated_at"),
            "regime_model": forecast_payload.get("regime_model"),
            "vol_model": forecast_payload.get("vol_model"),
            "shock_dist": forecast_payload.get("shock_dist"),
            "posterior_artifact": forecast_payload.get("posterior_artifact"),
            "posterior_artifact_fingerprint": forecast_payload.get("posterior_artifact_fingerprint"),
            "garch_artifact": forecast_payload.get("garch_artifact"),
            "regime_artifact": forecast_payload.get("regime_artifact"),
            "handoff_fingerprint": forecast_payload.get("handoff_fingerprint"),
            "handoff_file": forecast_payload.get("handoff_file"),
            "model_limitations": forecast_payload.get("model_limitations") or {},
            "behavioral_scenarios_path": str(behavioral_path),
            "current_conditions_path": str(conditions_path),
            "behavioral_scenarios_generated_at": _yaml_field(behavioral_path, "generated_at"),
            "current_conditions_as_of": _yaml_field(conditions_path, "as_of"),
        },
    )


def _apply_analogue_evidence_stage(
    ensemble_probabilities: Mapping[str, float],
    *,
    asof_quarter: str,
    enabled: bool,
) -> tuple[dict[str, float], dict[str, Any]]:
    if not enabled:
        from src.agent_system.forecasting.scenario_classifier.analogue_evidence import (
            disabled_analogue_evidence_report,
        )

        probabilities = {str(key): float(value) for key, value in ensemble_probabilities.items()}
        return probabilities, disabled_analogue_evidence_report(probabilities)

    from src.agent_system.forecasting.scenario_classifier.analogue_evidence import (
        apply_analogue_mixture,
        compute_analogue_evidence,
        load_analogue_evidence_config,
    )

    evidence = compute_analogue_evidence(query_date=asof_quarter)
    evidence_config = load_analogue_evidence_config()
    return apply_analogue_mixture(
        ensemble_probabilities,
        evidence,
        alpha=evidence_config.mixture_alpha,
    )


def _default_narrative_macro_forecast_dir() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "data"
        / "agent_system"
        / "reports"
        / "macro_forecasts"
    )


def _narrative_current_conditions_view(path: Path) -> CurrentConditionsView:
    payload = load_current_regime_yaml(path)
    read = {
        "regime_id": payload.get("regime_id"),
        "regime_label": payload.get("regime_label"),
        "headline": payload.get("headline"),
        "summary": payload.get("summary"),
        "risk_summary": payload.get("risk_summary"),
        "regime_call_confidence": payload.get("regime_call_confidence"),
        "regime_call_confidence_note": payload.get("regime_call_confidence_note"),
    }
    return CurrentConditionsView(
        taxonomy="narrative_v0",
        regime_id_basis=str(payload.get("regime_id") or ""),
        current_regime_read={key: value for key, value in read.items() if value is not None},
        transition_catalysts={
            "key_drivers": payload.get("key_drivers") or [],
            "falsifiers": payload.get("falsifiers") or [],
        },
        operator_prior_note=payload.get("regime_call_confidence_note"),
        source_path=str(path),
    )


def _behavioral_current_conditions_view(
    current_conditions: CurrentConditions,
    path: Path,
) -> CurrentConditionsView:
    read = dict(current_conditions.current_regime_read)
    return CurrentConditionsView(
        taxonomy="behavioral_v1",
        as_of=str(_yaml_field(path, "as_of") or ""),
        regime_id_basis=str(_yaml_field(path, "regime_id_basis") or ""),
        current_regime_read=read,
        tail_watch=[str(item) for item in (read.get("tail_watch") or [])],
        transition_catalysts=dict(current_conditions.transition_catalysts),
        within_regime_tilts=dict(current_conditions.within_regime_tilts),
        operator_prior_note=current_conditions.operator_prior_note,
        source_path=str(path),
    )


def _behavioral_seed_research_priorities(
    scenarios: Mapping[str, Any],
    probabilities: Mapping[str, float],
    conditions: CurrentConditionsView,
    *,
    forecast_payload: Mapping[str, Any],
) -> list[ResearchPriority]:
    read = conditions.current_regime_read
    primary = str(read.get("primary_behavioral_scenario") or "")
    secondary = str(read.get("secondary_behavioral_scenario") or "")
    tail_watch = [str(item) for item in conditions.tail_watch]
    designation_rank = {
        scenario_id: rank
        for rank, scenario_id in enumerate([primary, secondary, *tail_watch])
        if scenario_id
    }
    meaningful = {
        scenario_id
        for scenario_id, probability in probabilities.items()
        if float(probability) >= 0.05
    }
    meaningful.update(designation_rank)
    valid_ids = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    ordered_ids = sorted(
        (scenario_id for scenario_id in meaningful if scenario_id in valid_ids),
        key=lambda scenario_id: (
            designation_rank.get(scenario_id, 99),
            -float(probabilities.get(scenario_id, 0.0)),
            scenario_id,
        ),
    )[:5]
    priorities: list[ResearchPriority] = []
    for rank, scenario_id in enumerate(ordered_ids, 1):
        scenario = scenarios[scenario_id]
        designation = _behavioral_designation(scenario_id, primary, secondary, tail_watch)
        probability = float(probabilities.get(scenario_id, 0.0))
        preferred = ", ".join(scenario.preferred_exposures[:4]) or "preferred exposures"
        vulnerable = ", ".join(scenario.vulnerable_exposures[:4]) or "vulnerable exposures"
        questions = [
            f"Which themes have direct positive exposure to {scenario.label} without relying on stale narrative scenario ids?",
            f"Where are preferred exposures ({preferred}) showing bottom-up confirmation?",
            f"Which vulnerable exposures ({vulnerable}) are beginning to break or de-rate?",
        ]
        questions.extend(_catalyst_questions(conditions, scenario_id))
        priorities.append(
            ResearchPriority(
                theme=f"{scenario.label} behavioral scenario validation",
                rationale=(
                    f"{scenario.label} is a {designation} scenario in the active behavioral macro source "
                    f"with ensemble probability {probability:.1%}. The seed exists to validate whether "
                    "bottom-up evidence and market behavior confirm the same behavioral path."
                ),
                edge_hypothesis=(
                    f"The market may be under- or over-pricing the transition into {scenario.label}. "
                    f"Research should test whether preferred exposures such as {preferred} offer cleaner "
                    f"risk/reward than vulnerable exposures such as {vulnerable}, using behavioral scenario "
                    "ids rather than the retired narrative taxonomy."
                ),
                sub_questions=list(dict.fromkeys(questions))[:6],
                priority_rank=rank,
                expected_edge_decay=EdgeDecayHorizon.QUARTERS,
                supporting_evidence=[
                    DerivedEvidence(
                        claim=(
                            f"Behavioral seed priority derived from ensemble probability "
                            f"{probability:.1%} and current_conditions designation '{designation}'."
                        ),
                        supports=True,
                        computation="macro_scenario_source behavioral seed-priority builder",
                        upstream_claims=[
                            str(forecast_payload.get("posterior_artifact") or "bvar ensemble forecast"),
                            conditions.source_path or "current_conditions.yaml",
                        ],
                    )
                ],
                source_theme_id=f"behavioral::{scenario_id}",
                source_scenario_ids=[scenario_id],
                source_macro_forecast_id=str(forecast_payload.get("generated_at") or ""),
            )
        )
    return priorities


def _behavioral_designation(
    scenario_id: str,
    primary: str,
    secondary: str,
    tail_watch: list[str],
) -> str:
    if scenario_id == primary:
        return "primary"
    if scenario_id == secondary:
        return "secondary"
    if scenario_id in tail_watch:
        return "tail_watch"
    return "probability_weighted"


def _catalyst_questions(
    conditions: CurrentConditionsView,
    scenario_id: str,
) -> list[str]:
    questions: list[str] = []
    for key, payload in conditions.transition_catalysts.items():
        if not isinstance(payload, Mapping):
            continue
        text = json.dumps(payload, sort_keys=True).lower()
        if scenario_id not in text:
            continue
        confirm = payload.get("confirm")
        invalidate = payload.get("invalidate")
        if isinstance(confirm, list) and confirm:
            questions.append(f"Are confirming catalysts appearing: {str(confirm[0])[:180]}?")
        if isinstance(invalidate, list) and invalidate:
            questions.append(f"What would invalidate this path: {str(invalidate[0])[:180]}?")
    return questions


def _priority_to_adapter_payload(priority: ResearchPriority) -> dict[str, Any]:
    payload = priority.model_dump(mode="json")
    payload.pop("id", None)
    payload.pop("created_at", None)
    payload.pop("schema_version", None)
    return payload


def _behavioral_key_drivers(macro_source: MacroScenarioSource) -> list[dict[str, str]]:
    drivers: list[dict[str, str]] = []
    read = macro_source.current_conditions.current_regime_read
    for label, scenario_id in (
        ("Primary behavioral scenario", read.get("primary_behavioral_scenario")),
        ("Secondary behavioral scenario", read.get("secondary_behavioral_scenario")),
    ):
        if scenario_id:
            drivers.append(
                {
                    "name": label,
                    "status": str(scenario_id),
                    "explanation": (
                        f"Operator current-conditions read identifies {scenario_id} while "
                        f"the ensemble probability is "
                        f"{float(macro_source.scenario_probabilities.get(str(scenario_id), 0.0)):.1%}."
                    ),
                }
            )
    if macro_source.current_conditions.tail_watch:
        drivers.append(
            {
                "name": "Tail watch",
                "status": ", ".join(macro_source.current_conditions.tail_watch),
                "explanation": "Current conditions annotate these behavioral scenarios as live tails to monitor.",
            }
        )
    catalysts = macro_source.current_conditions.transition_catalysts
    for key, payload in list(catalysts.items())[:3]:
        drivers.append(
            {
                "name": str(key).replace("_", " ").title(),
                "status": "transition catalyst",
                "explanation": _compact_text(payload, default="Behavioral transition catalyst."),
            }
        )
    return drivers[:6]


def _behavioral_risk_summary(macro_source: MacroScenarioSource) -> str:
    tails = macro_source.current_conditions.tail_watch
    limitations = macro_source.provenance.get("model_limitations") or {}
    parts: list[str] = []
    if tails:
        parts.append("Tail watch: " + ", ".join(tails) + ".")
    detail = limitations.get("detail")
    if detail:
        parts.append(str(detail))
    return " ".join(parts) or "Monitor behavioral scenario transition catalysts and ensemble margin."


def _behavioral_portfolio_implications(macro_source: MacroScenarioSource) -> list[str]:
    items: list[str] = []
    for scenario_id in _top_behavioral_ids(macro_source, limit=3):
        scenario = next((item for item in macro_source.scenario_set.scenarios if item.id == scenario_id), None)
        if scenario is None:
            continue
        items.append(
            f"{scenario.label}: {scenario.factor_implications.equities}"
        )
    note = macro_source.current_conditions.operator_prior_note
    if note:
        items.append(str(note)[:500])
    return items[:6]


def _behavioral_exposures(macro_source: MacroScenarioSource, side: str) -> list[str]:
    behavioral_path = macro_source.provenance.get("behavioral_scenarios_path")
    try:
        scenarios = load_behavioral_scenarios(Path(str(behavioral_path)) if behavioral_path else None)
    except Exception:
        scenarios = {}
    exposures: list[str] = []
    attr = "preferred_exposures" if side == "preferred" else "vulnerable_exposures"
    for scenario_id in _top_behavioral_ids(macro_source, limit=3):
        scenario = scenarios.get(scenario_id)
        if scenario is not None:
            exposures.extend(getattr(scenario, attr))
    return list(dict.fromkeys(item for item in exposures if item))[:10]


def _behavioral_falsifiers(macro_source: MacroScenarioSource) -> list[dict[str, str]]:
    falsifiers: list[dict[str, str]] = []
    for payload in macro_source.current_conditions.transition_catalysts.values():
        if not isinstance(payload, Mapping):
            continue
        invalidate = payload.get("invalidate")
        if not isinstance(invalidate, list):
            continue
        for condition in invalidate:
            falsifiers.append(
                {
                    "condition": str(condition),
                    "observable_in": "data_series",
                    "check_frequency": "weekly",
                }
            )
            if len(falsifiers) >= 10:
                return falsifiers
    return falsifiers


def _top_behavioral_ids(
    macro_source: MacroScenarioSource,
    *,
    limit: int,
) -> list[str]:
    return [
        scenario_id
        for scenario_id, _probability in sorted(
            macro_source.scenario_probabilities.items(),
            key=lambda item: -float(item[1]),
        )[:limit]
    ]


def _compact_text(value: Any, *, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True)
    return text[:1000] if text else default


def _behavioral_scenario_set(
    scenarios: Mapping[str, Any],
    probabilities: Mapping[str, float],
    *,
    forecast_payload: Mapping[str, Any],
    behavioral_path: Path,
) -> ScenarioSet:
    scenario_models: list[Scenario] = []
    for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS:
        scenario = scenarios[scenario_id]
        scenario_models.append(
            Scenario(
                id=scenario_id,
                label=scenario.label,
                probability=float(probabilities.get(scenario_id, 0.0)),
                description=scenario.definition,
                factor_implications=_factor_implications(scenario.factor_implications, scenario_id),
                catalysts_that_confirm=[],
                catalysts_that_invalidate=[],
            )
        )
    generated_at = _parse_generated_at(
        _yaml_field(behavioral_path, "generated_at")
        or forecast_payload.get("generated_at")
    )
    horizon_quarters = forecast_payload.get("horizon_quarters")
    horizon_months = int(horizon_quarters) * 3 if horizon_quarters is not None else 12
    return ScenarioSet(
        schema_version=str(_yaml_field(behavioral_path, "schema_version") or "2.0"),
        generated_at=generated_at,
        regime_id_basis=str(_yaml_field(behavioral_path, "taxonomy") or "behavioral"),
        horizon_months=horizon_months,
        scenarios=scenario_models,
    )


def _factor_implications(payload: Mapping[str, Any], scenario_id: str) -> FactorImplications:
    required = ("rates", "equities", "dollar", "credit", "commodities")
    missing = [key for key in required if key not in payload or payload.get(key) in (None, "")]
    if missing:
        raise MacroScenarioSourceError(
            f"behavioral_scenarios.yaml scenario {scenario_id!r} missing factor_implications keys: {missing}"
        )
    return FactorImplications(
        rates=_stringify_implication(payload["rates"]),
        equities=_stringify_implication(payload["equities"]),
        dollar=_stringify_implication(payload["dollar"]),
        credit=_stringify_implication(payload["credit"]),
        commodities=_stringify_implication(payload["commodities"]),
    )


def _stringify_implication(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True)


def _load_latest_ensemble_forecast_for_asof(
    asof_quarter: str,
    *,
    bvar_cache_dir: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    candidates = artifact_candidate_paths(
        f"forecast_{asof_quarter}_*.json",
        bvar_cache_dir=bvar_cache_dir,
    )
    if not candidates:
        cache_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
        raise MacroScenarioSourceError(
            "macro_forecast_source=ensemble but no BVAR forecast artifact was found for "
            f"{asof_quarter} under {cache_dir}. Run the frozen ensemble forecast for this anchor first."
        )
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("scenario_probabilities_soft"):
            return path, payload
    raise MacroScenarioSourceError(
        f"No readable BVAR forecast artifact with scenario_probabilities_soft was found for {asof_quarter}"
    )


def _validate_behavioral_theme_coverage() -> None:
    from src.agent_system.forecasting.theme_exposure_matrix import (
        SCENARIO_THEME_EXPOSURES_BEHAVIORAL,
        SCENARIO_THEME_EXPOSURES_NARRATIVE,
    )

    narrative_themes = {
        theme
        for exposures in SCENARIO_THEME_EXPOSURES_NARRATIVE.values()
        for theme in exposures
    }
    missing = [
        (scenario_id, theme)
        for scenario_id, exposures in SCENARIO_THEME_EXPOSURES_BEHAVIORAL.items()
        for theme in sorted(narrative_themes)
        if exposures.get(theme) is None
    ]
    if missing:
        preview = ", ".join(f"{scenario}:{theme}" for scenario, theme in missing[:12])
        raise MacroScenarioSourceError(
            "behavioral theme exposure matrix has missing coverage for narrative-covered "
            f"themes ({len(missing)} entries). First missing entries: {preview}"
        )


def _validate_behavioral_compatibility() -> None:
    from src.agent_system.services.scenario_compatibility import scenario_correlation_matrix

    matrix = scenario_correlation_matrix("behavioral_v1")
    expected = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    if set(matrix) != expected:
        raise MacroScenarioSourceError(
            "behavioral scenario compatibility matrix has wrong scenario ids; "
            f"expected={sorted(expected)} got={sorted(matrix)}"
        )
    off_diagonal_values = [
        float(value)
        for scenario_id, row in matrix.items()
        for other_id, value in row.items()
        if scenario_id != other_id
    ]
    if not off_diagonal_values or all(abs(value) <= 1e-9 for value in off_diagonal_values):
        raise MacroScenarioSourceError(
            "behavioral scenario compatibility matrix is degenerate; all off-diagonal "
            "correlations are zero"
        )


def _yaml_field(path: Path, key: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh)
    except Exception:
        return None
    if isinstance(payload, dict):
        return payload.get(key)
    return None


def _parse_generated_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.now(timezone.utc)
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.fromisoformat(str(value)[:10])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
