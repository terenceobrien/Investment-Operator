"""Standalone runner for Macro Forecast Engine v1."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.forecasting.current_regime_export import (
    build_current_regime_handoff_from_macro_source,
    save_current_regime_yaml,
)
from src.agent_system.forecasting.behavioral_scenarios_loader import (
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
)
from src.agent_system.forecasting.bvar_ensemble.estimation import default_bvar_cache_dir
from src.agent_system.forecasting.input_signals import (
    build_forecast_input_set,
)
from src.agent_system.forecasting.research_agenda_builder import (
    build_research_priorities_from_theme_forecasts,
)
from src.agent_system.forecasting.scenario_classifier.analogue_evidence import (
    apply_analogue_mixture,
    compute_analogue_evidence,
    load_analogue_evidence_config,
)
from src.agent_system.forecasting.scenario_classifier.analogue_fan import (
    compute_analogue_fan,
    write_fan_result,
)
from src.agent_system.forecasting.scenario_classifier.analogue_fan_charts import (
    render_fan_charts,
)
from src.agent_system.forecasting.theme_exposure_matrix import (
    rank_factors,
    rank_sectors,
    rank_themes,
)
from src.agent_system.forecasting.macro_scenario_source import (
    MacroScenarioSourceConfig,
    get_macro_scenario_source,
)
from src.agent_system.scenarios.types import ScenarioSet
from src.agent_system.schemas.macro_forecast import (
    ForecastInterpretation,
    HistoricalCalibrationConfig,
    InputDedupeConfig,
    MacroForecastResult,
    MacroInputSignal,
    ProbabilityShifter,
    ScenarioProbabilityConfig,
)
from src.agent_system.schemas.regime import RegimeState


DEFAULT_REPORTS_DIR = "data/agent_system/reports/macro_forecasts"
TWO_SOURCE_REWIRE_MESSAGE = (
    "retired by the two_source_v1 rewire: macro probabilities now come only from "
    "BVAR scenario_probabilities_soft plus directional analogue evidence mixture."
)


class MacroForecastRunnerError(RuntimeError):
    """Raised when the two-source runner cannot produce a coherent forecast."""


@dataclass(frozen=True)
class BVARForecastArtifact:
    soft_probabilities: dict[str, float]
    provenance: dict[str, Any]
    payload: dict[str, Any]
    path: Path
    asof_quarter: str
    generated_at: str


class MacroForecastRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asof_date: str | None = None
    horizon: Literal["1m", "3m", "6m", "1y"] = "3m"

    input_mode: Literal["hybrid", "layer_only", "raw_only"] = "hybrid"
    raw_inputs_enabled: bool = True
    volatility_enabled: bool = True
    layer_summary_base_weight: float = Field(default=0.60, ge=0.0, le=1.0)
    raw_component_modifier_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    max_raw_modifier_ratio: float = Field(default=0.50, ge=0.0, le=2.0)

    bvar_cache_dir: str | None = None
    allow_stale_bvar: bool = False

    save_docx: bool = True
    reports_dir: str = DEFAULT_REPORTS_DIR
    docx_output: str | None = None
    save_json: bool = True
    json_output: str | None = None
    save_current_regime_yaml: bool = True
    current_regime_output: str | None = None
    overwrite_current_regime: bool = False

    debug: bool = False

    def dedupe_config(self) -> InputDedupeConfig:
        mode = self.input_mode if self.raw_inputs_enabled else "layer_only"
        return InputDedupeConfig(
            mode=mode,
            layer_summary_base_weight=self.layer_summary_base_weight,
            raw_component_modifier_weight=self.raw_component_modifier_weight if self.raw_inputs_enabled else 0.0,
            raw_component_cap_ratio=self.max_raw_modifier_ratio,
            max_raw_modifier_ratio=self.max_raw_modifier_ratio,
            include_volatility_layer=self.volatility_enabled,
            include_volatility_raw_components=self.volatility_enabled and self.raw_inputs_enabled,
        )

    def historical_config(self) -> HistoricalCalibrationConfig:
        raise MacroForecastRunnerError(
            f"HistoricalCalibrationConfig is {TWO_SOURCE_REWIRE_MESSAGE}"
        )


def default_scenario_set() -> ScenarioSet:
    raise MacroForecastRunnerError(
        f"default_scenario_set as a prior source is {TWO_SOURCE_REWIRE_MESSAGE}"
    )


def default_scenario_mapping_horizon_for_forecast_horizon(horizon: str) -> str:
    normalized = str(horizon or "").strip().lower()
    mapping = {
        "1m": "21d",
        "1mo": "21d",
        "1month": "21d",
        "3m": "63d",
        "3mo": "63d",
        "3month": "63d",
        "6m": "126d",
        "6mo": "126d",
        "6month": "126d",
        "1y": "252d",
        "12m": "252d",
        "1yr": "252d",
        "1year": "252d",
    }
    return mapping.get(normalized, "63d")


def _parse_horizon_list(value: str) -> list[str]:
    horizons = [item.strip().lower() for item in str(value).split(",") if item.strip()]
    return horizons or ["21d", "63d", "126d", "252d"]


def load_latest_bvar_forecast(
    bvar_cache_dir: str | Path | None = None,
    *,
    allow_stale: bool = False,
) -> BVARForecastArtifact:
    """Load the newest behavioral-v1 BVAR forecast artifact by generated_at."""

    cache_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    candidates = list(cache_dir.glob("forecast_*.json"))
    if not candidates:
        raise MacroForecastRunnerError(
            f"no BVAR forecast_*.json artifacts found under {cache_dir}; rebuild with: "
            f"{_bvar_rebuild_command(_current_calendar_quarter_text())}"
        )
    payloads: list[tuple[datetime, Path, dict[str, Any]]] = []
    errors: list[str] = []
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise MacroForecastRunnerError("artifact JSON root is not an object")
            generated_at = _parse_generated_at(payload.get("generated_at"), path=path)
            payloads.append((generated_at, path, payload))
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    if not payloads:
        raise MacroForecastRunnerError(
            "no readable BVAR forecast artifacts found; errors: " + "; ".join(errors[:5])
        )
    generated_at_dt, path, payload = max(payloads, key=lambda item: item[0])
    soft = _validate_bvar_soft_probabilities(payload, path=path)
    classifier_metadata = payload.get("classifier_metadata")
    if not isinstance(classifier_metadata, Mapping):
        raise MacroForecastRunnerError(f"BVAR artifact missing classifier_metadata: {path}")
    map_version = str(classifier_metadata.get("map_version") or "")
    if not map_version.startswith("behavioral-v1"):
        raise MacroForecastRunnerError(
            f"BVAR classifier_metadata.map_version mismatch in {path}: "
            f"expected behavioral-v1*, got {map_version!r}"
        )
    metadata_ids = {str(item) for item in (classifier_metadata.get("scenario_ids") or [])}
    expected_ids = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    if metadata_ids != expected_ids:
        raise MacroForecastRunnerError(
            f"BVAR classifier_metadata.scenario_ids mismatch in {path}: "
            f"missing={sorted(expected_ids - metadata_ids)} unknown={sorted(metadata_ids - expected_ids)}"
        )
    asof_quarter = str(payload.get("asof_quarter") or "")
    if not asof_quarter:
        raise MacroForecastRunnerError(f"BVAR artifact missing asof_quarter: {path}")
    _parse_quarter(asof_quarter)
    current_quarter = _current_calendar_quarter_text()
    warnings: list[str] = []
    if asof_quarter != current_quarter:
        age = _quarter_distance(asof_quarter, current_quarter)
        warning = (
            f"STALE BVAR forecast: artifact asof_quarter={asof_quarter}, "
            f"current_calendar_quarter={current_quarter}, age_quarters={age}. "
            f"Rebuild with: {_bvar_rebuild_command(current_quarter)}"
        )
        if not allow_stale:
            raise MacroForecastRunnerError(warning + " Or rerun with --allow-stale-bvar.")
        warnings.append(warning)
    provenance = {
        "path": str(path),
        "generated_at": str(payload.get("generated_at")),
        "asof_quarter": asof_quarter,
        "handoff_fingerprint": payload.get("handoff_fingerprint"),
        "model_limitations": payload.get("model_limitations") or {},
        "classifier_metadata": dict(classifier_metadata),
        "warnings": warnings,
        "soft_probabilities": dict(soft),
        "soft_probability_sum": float(sum(soft.values())),
    }
    return BVARForecastArtifact(
        soft_probabilities=soft,
        provenance=provenance,
        payload=payload,
        path=path,
        asof_quarter=asof_quarter,
        generated_at=generated_at_dt.isoformat(),
    )


def _validate_bvar_soft_probabilities(
    payload: Mapping[str, Any],
    *,
    path: Path,
) -> dict[str, float]:
    raw = payload.get("scenario_probabilities_soft")
    if not isinstance(raw, Mapping):
        raise MacroForecastRunnerError(f"BVAR artifact missing scenario_probabilities_soft: {path}")
    expected_ids = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    actual_ids = {str(key) for key in raw}
    if actual_ids != expected_ids:
        raise MacroForecastRunnerError(
            f"BVAR scenario_probabilities_soft scenario set mismatch in {path}: "
            f"missing={sorted(expected_ids - actual_ids)} unknown={sorted(actual_ids - expected_ids)}"
        )
    probabilities: dict[str, float] = {}
    for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS:
        try:
            value = float(raw[scenario_id])
        except (TypeError, ValueError) as exc:
            raise MacroForecastRunnerError(
                f"BVAR scenario_probabilities_soft.{scenario_id} must be numeric in {path}"
            ) from exc
        if not (0.0 <= value <= 1.0):
            raise MacroForecastRunnerError(
                f"BVAR scenario_probabilities_soft.{scenario_id} must be in [0, 1] in {path}; got {value}"
            )
        probabilities[scenario_id] = value
    total = float(sum(probabilities.values()))
    if abs(total - 1.0) > 1e-6:
        raise MacroForecastRunnerError(
            f"BVAR scenario_probabilities_soft must sum to 1 within 1e-6 in {path}; got {total:.12f}"
        )
    return probabilities


def _mark_forecast_input_set_monitoring_only(forecast_input_set):
    note = "Monitoring — no probability impact in two_source_v1."

    def mark(signal: MacroInputSignal) -> MacroInputSignal:
        return signal.model_copy_validate(
            {
                "used_in_probability_update": False,
                "display_only": True,
                "exclusion_reason": note,
            }
        )

    return forecast_input_set.model_copy_validate(
        {
            "layer_summary_signals": [mark(signal) for signal in forecast_input_set.layer_summary_signals],
            "raw_component_signals": [mark(signal) for signal in forecast_input_set.raw_component_signals],
            "composite_signals": [mark(signal) for signal in forecast_input_set.composite_signals],
            "market_tape_signals": [mark(signal) for signal in forecast_input_set.market_tape_signals],
            "regime_driver_signals": [mark(signal) for signal in forecast_input_set.regime_driver_signals],
            "scenario_falsifier_signals": [mark(signal) for signal in forecast_input_set.scenario_falsifier_signals],
            "theme_specific_signals": [mark(signal) for signal in forecast_input_set.theme_specific_signals],
            "all_signals": [mark(signal) for signal in forecast_input_set.all_signals],
            "methodology_notes": list(forecast_input_set.methodology_notes)
            + ["All deterministic signal inputs are Monitoring — no probability impact in two_source_v1."],
        }
    )


def _parse_generated_at(value: Any, *, path: Path) -> datetime:
    if not value:
        raise MacroForecastRunnerError(f"BVAR artifact missing generated_at: {path}")
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MacroForecastRunnerError(
            f"BVAR generated_at is not ISO-parseable in {path}: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _current_calendar_quarter_text() -> str:
    now = datetime.now(timezone.utc)
    quarter = (now.month - 1) // 3 + 1
    return f"{now.year}Q{quarter}"


def _parse_quarter(value: str) -> tuple[int, int]:
    try:
        period = pd.Period(str(value), freq="Q")
    except Exception as exc:
        raise MacroForecastRunnerError(f"invalid quarter string {value!r}") from exc
    return int(period.year), int(period.quarter)


def _quarter_distance(start: str, end: str) -> int:
    start_year, start_quarter = _parse_quarter(start)
    end_year, end_quarter = _parse_quarter(end)
    return (end_year - start_year) * 4 + (end_quarter - start_quarter)


def _quarter_end_date_text(quarter: str) -> str:
    try:
        return pd.Period(str(quarter), freq="Q").end_time.date().isoformat()
    except Exception as exc:
        raise MacroForecastRunnerError(f"invalid BVAR asof_quarter {quarter!r}") from exc


def _bvar_rebuild_command(asof_quarter: str) -> str:
    return (
        "PYTHONPATH=backend python3 -m "
        "src.agent_system.forecasting.bvar_ensemble.cli forecast "
        f"--asof-quarter {asof_quarter}"
    )


def run_macro_forecast(
    regime_state: RegimeState,
    scenario_set: ScenarioSet | None = None,
    horizon: str = "3m",
    probability_config: ScenarioProbabilityConfig | None = None,
    dedupe_config: InputDedupeConfig | None = None,
    raw_inputs: object | None = None,
    market_state: object | None = None,
    historical_calibration_config: HistoricalCalibrationConfig | None = None,
    bvar_cache_dir: str | Path | None = None,
    allow_stale_bvar: bool = False,
    fan_output_dir: str | Path | None = None,
) -> MacroForecastResult:
    """Run the two-source macro forecast probability path."""

    if scenario_set is not None:
        raise MacroForecastRunnerError(
            f"scenario_set priors are {TWO_SOURCE_REWIRE_MESSAGE}"
        )
    if probability_config is not None:
        raise MacroForecastRunnerError(
            f"ScenarioProbabilityConfig usage in the runner is {TWO_SOURCE_REWIRE_MESSAGE}"
        )
    if historical_calibration_config is not None:
        raise MacroForecastRunnerError(
            f"HistoricalCalibrationConfig usage in the runner is {TWO_SOURCE_REWIRE_MESSAGE}"
        )
    dedupe_config = dedupe_config or InputDedupeConfig()
    forecast_input_set = build_forecast_input_set(
        regime_state,
        raw_inputs=raw_inputs,  # type: ignore[arg-type]
        market_state=market_state,
        horizon=horizon,
        dedupe_config=dedupe_config,
    )
    forecast_input_set = _mark_forecast_input_set_monitoring_only(forecast_input_set)
    input_signals = forecast_input_set.all_signals

    bvar_artifact = load_latest_bvar_forecast(
        bvar_cache_dir=bvar_cache_dir,
        allow_stale=allow_stale_bvar,
    )
    evidence_config = load_analogue_evidence_config()
    evidence = compute_analogue_evidence(query_date=bvar_artifact.asof_quarter)
    scenario_probabilities, mixture_report = apply_analogue_mixture(
        bvar_artifact.soft_probabilities,
        evidence,
        alpha=evidence_config.mixture_alpha,
    )
    fan_payload, fan_outputs, fan_warnings = _compute_analogue_fan_outputs(
        bvar_artifact.asof_quarter,
        output_dir=fan_output_dir,
    )
    mixture_report = {
        **mixture_report,
        "analogue_fan": fan_payload,
        "analogue_fan_artifact_path": fan_outputs.get("analogue_fan_json_path"),
    }
    bvar_provenance = dict(bvar_artifact.provenance)
    if fan_warnings:
        bvar_provenance["warnings"] = list(
            dict.fromkeys(
                [str(item) for item in (bvar_provenance.get("warnings") or [])]
                + fan_warnings
            )
        )
    theme_rankings = rank_themes(
        scenario_probabilities,
        input_signals,
        taxonomy="behavioral_v1",
    )
    sector_rankings = rank_sectors(theme_rankings)
    factor_rankings = rank_factors(theme_rankings)
    result = MacroForecastResult(
        asof_date=regime_state.asof_date,
        horizon=horizon,
        input_signals=input_signals,
        forecast_input_set=forecast_input_set,
        scenario_updates=[],
        scenario_probabilities=scenario_probabilities,
        sector_rankings=sector_rankings,
        factor_rankings=factor_rankings,
        theme_rankings=theme_rankings,
        recommended_research_priorities=build_research_priorities_from_theme_forecasts(
            theme_rankings,
            [],
            regime_state,
            scenario_probabilities=scenario_probabilities,
        ),
        probability_mode="two_source_v1",
        mixture_report=mixture_report,
        bvar_provenance=bvar_provenance,
        outputs=fan_outputs,
    )
    return result.model_copy_validate(
        {
            "forecast_interpretation": build_macro_forecast_interpretation(result),
            "probability_shifters": build_probability_shifters(result),
        }
    )


def _apply_yaml_priors_override(
    result: MacroForecastResult,
    scenario_set: ScenarioSet,
    regime_state: RegimeState,
) -> MacroForecastResult:
    """Retired YAML-prior override retained as a fail-loud compatibility stub."""

    raise MacroForecastRunnerError(
        f"_apply_yaml_priors_override is {TWO_SOURCE_REWIRE_MESSAGE}"
    )


def _scenario_name(scenario_id: str) -> str:
    labels = {
        "expansion_disinflation": "Expansion Disinflation",
        "late_cycle_expansion": "Late-Cycle Expansion",
        "inflation_shock": "Inflation Shock",
        "stagflation": "Stagflation",
        "growth_scare_no_credit": "Growth Scare, No Credit",
        "credit_led_recession": "Credit-Led Recession",
        "reopening_soft_landing": "Reopening / Soft Landing",
        "sticky_late_cycle_ai": "Sticky Late Cycle AI",
        "oil_inflation_tail": "Oil Inflation Tail",
        "late_cycle_risk_off": "Late Cycle Risk-Off",
        "ai_capex_rollover": "AI Capex Rollover",
    }
    return labels.get(scenario_id, scenario_id.replace("_", " ").title())


def build_macro_forecast_interpretation(result: MacroForecastResult) -> ForecastInterpretation:
    probabilities = result.scenario_probabilities
    if not probabilities:
        raise MacroForecastRunnerError("two_source_v1 result has no scenario_probabilities")
    dominant_id, dominant_probability = max(probabilities.items(), key=lambda item: item[1])
    second = sorted(
        [(scenario_id, probability) for scenario_id, probability in probabilities.items() if scenario_id != dominant_id],
        key=lambda item: item[1],
        reverse=True,
    )[:1]
    top_themes = [theme for theme in result.theme_rankings if theme.ranking_score > 0][:5]
    bottom_themes = sorted(result.theme_rankings, key=lambda item: item.ranking_score)[:4]
    positive_factors = [factor for factor in result.factor_rankings if factor.score > 0][:3]
    negative_factors = [factor for factor in result.factor_rankings if factor.score < 0][:3]

    headline = f"Forecast favors {_scenario_name(dominant_id)} in the behavioral two-source mix."

    runner_up = f"; runner-up {second[0][0]} at {second[0][1]:.1%}" if second else ""
    mixture = result.mixture_report or {}
    evidence = mixture.get("evidence") if isinstance(mixture, dict) else {}
    evidence_state = str((evidence or {}).get("current_state") or mixture.get("abstention_state") or "unknown")
    trailing = mixture.get("s")
    trailing_text = f"{float(trailing):.1%}" if trailing is not None else "n/a"
    summary = (
        f"The model assigns the highest probability to {_scenario_name(dominant_id)} "
        f"at {dominant_probability:.1%}{runner_up}. Probabilities are a linear mixture of BVAR soft "
        f"posteriors and directional analogue evidence; analogue state is {evidence_state} with "
        f"trailing recession share {trailing_text}. Deterministic signal layers are retained as "
        "monitoring and falsifier evidence only."
    )
    preferred = [theme.label for theme in top_themes] + [factor.label for factor in positive_factors]
    avoid = [theme.label for theme in bottom_themes if theme.ranking_score < 0] + [
        factor.label for factor in negative_factors
    ]

    signals = {signal.input_id: signal for signal in result.input_signals}
    tensions: list[str] = []
    if signals.get("credit_conditions") and signals["credit_conditions"].signal == "bullish":
        breadth = signals.get("market_breadth")
        if breadth and breadth.signal in {"bearish", "mixed"}:
            tensions.append("Credit is healthy but breadth is weak or narrow.")
    monetary = signals.get("monetary_policy_composite")
    if monetary and monetary.signal in {"mixed", "bearish"}:
        tensions.append("Fed path remains restrictive despite some monetary-layer improvement.")
    oil = signals.get("oil_reopening_optionality")
    if oil:
        tensions.append("Oil risk remains two-sided between inflation pressure and reopening relief.")
    if result.mixture_report.get("stress_advisory"):
        tensions.append("Analogue evidence is in unprecedented-state stress advisory mode.")
    if signals.get("ai_earnings_resilience"):
        tensions.append("AI earnings resilience remains a monitoring-only falsifier, not a probability input.")

    if dominant_probability >= 0.65:
        confidence = "high"
    elif dominant_probability >= 0.40:
        confidence = "medium"
    else:
        confidence = "low"
    gap = dominant_probability - (second[0][1] if second else 0.0)
    confidence_rationale = (
        f"Dominant scenario probability is {dominant_probability:.1%} with a "
        f"{gap:.1%} gap to the next scenario. The only floor is the uniform 0.1% numerical guard "
        "applied after the BVAR-plus-analogue mixture."
    )

    return ForecastInterpretation(
        headline=headline,
        summary=summary,
        dominant_scenario_id=dominant_id,
        dominant_scenario_probability=dominant_probability,
        regime_read=(
            f"{_scenario_name(dominant_id)} leads; top macro-supported themes are "
            f"{', '.join(theme.label for theme in top_themes[:3]) or 'none'}."
        ),
        preferred_exposures=preferred[:8],
        exposures_to_avoid=avoid[:8],
        key_tensions=tensions,
        confidence_level=confidence,  # type: ignore[arg-type]
        confidence_rationale=confidence_rationale,
    )


def build_probability_shifters(result: MacroForecastResult) -> list[ProbabilityShifter]:
    if result.probability_mode == "two_source_v1":
        return []
    templates = {
        "sticky_late_cycle_ai": (
            [
                "Breadth remains weak while AI earnings revisions stay positive.",
                "Fed hold/hike odds remain elevated.",
                "Credit stays contained and hyperscaler capex guidance remains resilient.",
            ],
            [
                "Breadth broadens materially with equal-weight and small-cap leadership.",
                "Fed cut probabilities rise.",
                "AI capex guidance weakens or infrastructure leaders lose relative strength.",
            ],
            ["market_breadth", "fed_path", "ai_earnings_resilience", "hyperscaler_capex_falsifier_not_triggered"],
        ),
        "reopening_soft_landing": (
            [
                "RSP begins outperforming SPY and small caps outperform.",
                "Credit remains tight while Fed cut optionality rises.",
                "Oil risk premium fades without growth deterioration.",
            ],
            [
                "Breadth narrows further.",
                "Fed hold/hike odds rise.",
                "Inflation or oil reaccelerates.",
            ],
            ["market_breadth", "credit_conditions", "fed_path", "oil_reopening_optionality"],
        ),
        "oil_inflation_tail": (
            [
                "Oil breaks higher or supply-risk headlines worsen.",
                "Breakevens rise and Fed hike odds increase.",
                "Energy leadership broadens beyond tactical hedges.",
            ],
            [
                "Hormuz reopening is confirmed and oil risk premium compresses.",
                "Breakevens roll over.",
                "Fed hike odds fade.",
            ],
            ["oil_reopening_optionality", "fed_path", "inflation_expectations", "energy_oil_beta"],
        ),
        "late_cycle_risk_off": (
            [
                "HY spreads widen or credit-sensitive equities underperform.",
                "VIX spikes while breadth deteriorates further.",
                "Healthy credit signal breaks down.",
            ],
            [
                "Credit stays tight.",
                "Breadth improves and volatility remains contained.",
                "Risk appetite broadens without inflation reacceleration.",
            ],
            ["credit_conditions", "market_breadth", "volatility", "positioning_hedging"],
        ),
        "ai_capex_rollover": (
            [
                "Hyperscaler capex guidance weakens.",
                "AI earnings revisions turn negative.",
                "Semis, grid, or power leaders lose relative strength.",
            ],
            [
                "Capex guidance remains resilient.",
                "AI infrastructure orders and backlogs strengthen.",
                "Quality AI earnings revisions remain positive.",
            ],
            ["hyperscaler_capex_falsifier_not_triggered", "ai_earnings_resilience", "quality_ai"],
        ),
    }
    updates_by_id = {update.scenario_id: update for update in result.scenario_updates}
    shifters: list[ProbabilityShifter] = []
    for scenario_id, update in updates_by_id.items():
        inc, dec, inputs = templates.get(
            scenario_id,
            (
                ["Scenario-specific confirming data improves."],
                ["Scenario-specific confirming data fades."],
                [],
            ),
        )
        labels: list[str] = []
        if update.floor_applied:
            labels.append(f"floor {update.floor_value:.1%}" if update.floor_value is not None else "floor applied")
        if update.cap_applied:
            labels.append(f"cap {update.cap_value:.1%}" if update.cap_value is not None else "cap applied")
        current_probability = result.scenario_probabilities.get(
            scenario_id,
            update.posterior_probability,
        )
        shifters.append(
            ProbabilityShifter(
                scenario_id=scenario_id,
                would_increase_probability_if=inc,
                would_decrease_probability_if=dec,
                key_inputs_to_watch=inputs,
                current_probability=current_probability,
                floor_or_cap_note=", ".join(labels) if labels else None,
            )
        )
    return sorted(shifters, key=lambda item: item.current_probability, reverse=True)


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def _num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.3f}"


def _plain_num(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _horizon_label(horizon: str) -> str:
    return {
        "1d": "1D",
        "5d": "5D",
        "10d": "10D",
        "21d": "1M / 21D",
        "63d": "3M / 63D",
        "126d": "6M / 126D",
        "252d": "1Y / 252D",
    }.get(horizon, horizon.upper())


def _risk_profile_items_for_report(risk_profile: dict) -> list[tuple[str, object]]:
    available_macro_excursions = set(risk_profile.get("drawdown_upside_available_horizons") or [])
    items: list[tuple[str, object]] = []
    for key, value in risk_profile.items():
        if key == "drawdown_upside_available_horizons":
            continue
        if key.startswith(("median_max_drawdown_", "median_max_upside_")):
            horizon = key.rsplit("_", 1)[-1]
            if horizon in {"21d", "63d", "126d", "252d"} and horizon not in available_macro_excursions:
                continue
        if key.startswith("worst_drawdown_"):
            continue
        items.append((key, value))
    return items


def _signal_reading(value: float | str | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _top_driver(update) -> str:
    contributors = list(update.top_positive_contributors) + list(update.top_negative_contributors)
    if not contributors:
        return "none"
    top = sorted(contributors, key=lambda item: abs(item.contribution), reverse=True)[0]
    return f"{top.name} ({top.contribution:+.3f})"


def _floor_cap_label(update) -> str:
    labels: list[str] = []
    if update.floor_applied:
        labels.append(f"floor {update.floor_value:.1%}" if update.floor_value is not None else "floor")
    if update.cap_applied:
        labels.append(f"cap {update.cap_value:.1%}" if update.cap_value is not None else "cap")
    return ", ".join(labels) if labels else "-"


def _calibration_by_scenario(result: MacroForecastResult):
    calibration = result.historical_calibration
    if calibration is None:
        return {}
    return {
        item.scenario_id: item
        for item in calibration.scenario_calibrations
    }


def _run_timestamp(result: MacroForecastResult) -> str:
    """Format a UTC timestamp for the output filename."""
    created = getattr(result, "created_at", None)
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_docx_output_path(
    result: MacroForecastResult,
    reports_dir: str | Path,
) -> Path:
    return (
        Path(reports_dir)
        / f"macro_forecast_{result.asof_date}_{_run_timestamp(result)}_math_audit_review.docx"
    )


def _default_json_output_path(
    result: MacroForecastResult,
    reports_dir: str | Path,
) -> Path:
    return Path(reports_dir) / f"macro_forecast_{result.asof_date}_{_run_timestamp(result)}.json"


def _default_current_regime_output_dir(
    *,
    reports_dir: str | Path,
    docx_path: Path | None = None,
    json_path: Path | None = None,
) -> Path:
    if docx_path is not None:
        return docx_path.parent
    if json_path is not None:
        return json_path.parent
    return Path(reports_dir)


def _default_fan_output_dir(reports_dir: str | Path = DEFAULT_REPORTS_DIR) -> Path:
    return Path(reports_dir) / "analogue_fans"


def _compute_analogue_fan_outputs(
    query_date: str,
    *,
    output_dir: str | Path | None,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    target_dir = Path(output_dir) if output_dir is not None else _default_fan_output_dir()
    fan = compute_analogue_fan(query_date=query_date)
    fan_json_path = write_fan_result(
        fan,
        target_dir / f"analogue_fan_{fan.query_date}.json",
    )
    outputs: dict[str, str] = {
        "analogue_fan_json_path": str(fan_json_path),
    }
    warnings: list[str] = []
    fan_payload = fan.to_dict()
    fan_payload["artifact_path"] = str(fan_json_path)
    try:
        chart_paths = render_fan_charts(fan, target_dir)
        for key, value in chart_paths.items():
            if key == "combined_grid":
                outputs["analogue_fan_grid_png_path"] = value
            else:
                outputs[f"analogue_fan_{key}_png_path"] = value
    except Exception as exc:
        warnings.append(f"Analogue fan chart rendering failed: {exc}")
    return fan_payload, outputs, warnings


def _write_json_result(result: MacroForecastResult, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


def _volatility_coverage_warning(result: MacroForecastResult) -> str | None:
    input_set = result.forecast_input_set
    if input_set is None:
        return "ForecastInputSet unavailable; raw input coverage could not be audited."
    raw_coverage = input_set.raw_input_coverage or {}
    groups = raw_coverage.get("groups") if isinstance(raw_coverage, dict) else None
    volatility = groups.get("volatility") if isinstance(groups, dict) else None
    if not isinstance(volatility, dict):
        return "Volatility raw input coverage unavailable."
    missing = [str(item) for item in volatility.get("missing") or []]
    if missing:
        return f"Volatility raw input coverage incomplete; missing: {', '.join(missing)}."
    return None


def _run_warnings(result: MacroForecastResult) -> list[str]:
    warnings: list[str] = []
    volatility_warning = _volatility_coverage_warning(result)
    if volatility_warning:
        warnings.append(volatility_warning)
    input_set = result.forecast_input_set
    if input_set is not None:
        raw_coverage = input_set.raw_input_coverage or {}
        if isinstance(raw_coverage, dict):
            warnings.extend(str(item) for item in (raw_coverage.get("warnings") or []))
    for update in result.scenario_updates:
        warnings.extend(str(item) for item in getattr(update, "warnings", []) or [])
    calibration = result.historical_calibration
    if calibration is not None:
        warnings.extend(str(item) for item in calibration.warnings)
    warnings.extend(str(item) for item in (result.bvar_provenance.get("warnings") or []))
    return list(dict.fromkeys(item for item in warnings if item))


def _input_mode_label(config: MacroForecastRunConfig) -> str:
    if config.input_mode == "hybrid" and config.raw_inputs_enabled:
        return "hybrid_raw_inputs"
    return config.input_mode


def _historical_analogue_label(result: MacroForecastResult, config: MacroForecastRunConfig) -> str:
    if result.probability_mode == "two_source_v1":
        return "retired; directional analogue evidence enters via mixture"
    if result.historical_calibration is None:
        return "disabled"
    return result.historical_calibration.analogue_version


def _print_run_summary(
    *,
    result: MacroForecastResult,
    config: MacroForecastRunConfig,
    docx_path: Path | None,
    json_path: Path | None,
    current_regime_yaml_path: Path | None,
    docx_disabled: bool = False,
    json_disabled: bool = False,
    current_regime_yaml_disabled: bool = False,
) -> None:
    print("Forecast complete.")
    print(f"As-of date: {result.asof_date}")
    print(f"Horizon: {result.horizon}")
    print(f"Probability mode: {result.probability_mode}")
    print(f"Input mode: {_input_mode_label(config)}")
    print(f"Volatility inputs: {'included' if config.volatility_enabled else 'disabled'}")
    print(f"Historical analogues: {_historical_analogue_label(result, config)}")
    if result.probability_mode == "two_source_v1":
        mixture = result.mixture_report or {}
        evidence = mixture.get("evidence") if isinstance(mixture, dict) else {}
        print()
        print("Two-source mixture:")
        print(f"  BVAR artifact: {result.bvar_provenance.get('path', 'n/a')}")
        print(f"  BVAR asof: {result.bvar_provenance.get('asof_quarter', 'n/a')}")
        print(f"  BVAR generated_at: {result.bvar_provenance.get('generated_at', 'n/a')}")
        print(f"  BVAR handoff_fingerprint: {result.bvar_provenance.get('handoff_fingerprint', 'n/a')}")
        print(f"  alpha: {_plain_num(mixture.get('alpha'))}")
        print(f"  s/trailing_max: {_pct(mixture.get('s'))}")
        print(f"  evidence state: {(evidence or {}).get('current_state') or mixture.get('abstention_state') or 'n/a'}")
        print(f"  stress advisory: {bool(mixture.get('stress_advisory', False))}")
        print("  Scenario decomposition:")
        per_scenario = mixture.get("per_scenario") if isinstance(mixture, dict) else {}
        for scenario_id, final_probability in sorted(
            result.scenario_probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            row = per_scenario.get(scenario_id, {}) if isinstance(per_scenario, dict) else {}
            print(
                "    "
                f"{scenario_id}: bvar={_pct(row.get('bvar_soft'))} "
                f"analogue={_pct(row.get('analogue_implied'))} "
                f"mixed={_pct(row.get('mixed_pre_floor'))} "
                f"final={_pct(final_probability)} "
                f"delta={_pct(row.get('delta'))}"
            )
        limitations = result.bvar_provenance.get("model_limitations") or {}
        if limitations:
            print("  BVAR model_limitations:")
            for key, value in limitations.items():
                print(f"    {key}: {value}")
    if docx_disabled:
        print("DOCX report disabled by --no-docx")
    elif docx_path is not None:
        print(f"DOCX report saved to: {docx_path}")
    if json_disabled:
        print("JSON forecast disabled by --no-json")
    elif json_path is not None:
        print(f"JSON forecast saved to: {json_path}")
    if current_regime_yaml_disabled:
        print("Current regime YAML disabled by --no-current-regime-yaml")
    elif current_regime_yaml_path is not None:
        print(f"Current regime YAML saved to: {current_regime_yaml_path}")
    fan_outputs = {
        key: value
        for key, value in result.outputs.items()
        if key.startswith("analogue_fan_")
    }
    if fan_outputs:
        print("Analogue fan artifacts:")
        for key, value in sorted(fan_outputs.items()):
            print(f"  {key}: {value}")

    warnings = _run_warnings(result)
    if warnings:
        print()
        print("Warnings:")
        for warning in warnings:
            print(f"* {warning}")


def _contributor_lines(update, positive: bool) -> list[str]:
    if positive:
        items = [
            item
            for item in update.contributions
            if item.adjusted_contribution > 0
        ]
    else:
        items = [
            item
            for item in update.contributions
            if item.adjusted_contribution < 0
        ]
    lines: list[str] = []
    for item in sorted(items, key=lambda value: abs(value.adjusted_contribution), reverse=True)[:5]:
        prefix = "+" if item.adjusted_contribution > 0 else "-"
        source = _contribution_source_label(item)
        lines.append(
            f"    {prefix} {item.input_name} [{source}]: {item.adjusted_contribution:+.3f} "
            f"(strength {item.strength:.2f} x confidence {item.confidence:.2f})"
        )
    return lines or ["    none"]


def _contribution_source_label(item) -> str:
    role = getattr(item, "source_role", None) or "input"
    layer = getattr(item, "parent_layer", None)
    label = f"{role}/{layer}" if layer else role
    if getattr(item, "capped_by_dedupe", False):
        label += ", capped"
    return label


def _top_scenario_effects(signal: MacroInputSignal) -> str:
    if not signal.affected_scenarios:
        return "none"
    return ", ".join(
        f"{impact.scenario_id} {impact.direction} {impact.strength:.2f}"
        for impact in signal.affected_scenarios[:3]
    )


def _raw_components_for_layer(result: MacroForecastResult, parent_layer: str | None) -> str:
    if result.forecast_input_set is None or parent_layer is None:
        return "-"
    values = [
        signal.input_id
        for signal in result.forecast_input_set.raw_component_signals
        if signal.parent_layer == parent_layer
    ]
    return ", ".join(values) if values else "-"


def _append_signal_rows(
    lines: list[str],
    signals: list[MacroInputSignal],
    row_builder,
) -> None:
    if not signals:
        lines.append("none")
        return
    for signal in signals:
        lines.append(row_builder(signal))


def _ranking_driver_summary(contributions) -> str:
    if not contributions:
        return "none"
    return ", ".join(
        f"{item.source_label} {item.contribution:+.2f}"
        for item in contributions[:3]
    )


def _theme_contribution_summary(theme) -> str:
    if not getattr(theme, "scenario_contributions", None):
        return "none"
    return "; ".join(
        f"{item.scenario_label} {item.contribution:+.2f}"
        for item in sorted(
            theme.scenario_contributions,
            key=lambda value: abs(value.contribution),
            reverse=True,
        )
    )


def format_macro_forecast_report(result: MacroForecastResult) -> str:
    """Format an audit-friendly text report for CLI/manual review."""

    lines: list[str] = [
        "Macro Forecast Report",
        f"As of: {result.asof_date} | Horizon: {result.horizon}",
    ]
    if result.forecast_interpretation is not None:
        interpretation = result.forecast_interpretation
        lines.extend(
            [
                "",
                "0. Forecast Interpretation",
                f"Headline: {interpretation.headline}",
                f"Summary: {interpretation.summary}",
                f"Dominant Scenario: {interpretation.dominant_scenario_id} ({_pct(interpretation.dominant_scenario_probability)})",
                f"Regime Read: {interpretation.regime_read}",
                f"Preferred Exposures: {', '.join(interpretation.preferred_exposures) or 'none'}",
                f"Exposures To Avoid: {', '.join(interpretation.exposures_to_avoid) or 'none'}",
                f"Key Tensions: {', '.join(interpretation.key_tensions) or 'none'}",
                f"Confidence: {interpretation.confidence_level} - {interpretation.confidence_rationale}",
            ]
        )

    lines.extend(
        [
            "",
            "1. Scenario Probabilities",
        ]
    )
    calibration_by_scenario = _calibration_by_scenario(result)
    if result.probability_mode == "two_source_v1":
        mixture = result.mixture_report or {}
        per_scenario = mixture.get("per_scenario") if isinstance(mixture, dict) else {}
        lines.append(
            "Scenario | BVAR Soft | Analogue Implied | Mixed Pre-Floor | Final | Delta vs BVAR | Floor Guard"
        )
        for scenario_id, final_probability in sorted(
            result.scenario_probabilities.items(),
            key=lambda item: item[1],
            reverse=True,
        ):
            row = per_scenario.get(scenario_id, {}) if isinstance(per_scenario, dict) else {}
            lines.append(
                " | ".join(
                    [
                        scenario_id,
                        _pct(row.get("bvar_soft", result.bvar_provenance.get("soft_probabilities", {}).get(scenario_id))),
                        _pct(row.get("analogue_implied")),
                        _pct(row.get("mixed_pre_floor")),
                        _pct(final_probability),
                        _pct(row.get("delta")),
                        str(bool(row.get("floor_applied", False))),
                    ]
                )
            )
    elif result.probability_mode == "yaml_priors_override":
        lines.extend(
            [
                "",
                "+-- YAML PRIORS OVERRIDE ACTIVE --+",
                "The 'Prior' column reflects the actually-used probabilities (your YAML values).",
                "The 'Pre-Floor Posterior' and 'Final Posterior' columns are the engine's deterministic math,",
                "preserved for audit only. Downstream theme rankings, research priorities, and portfolio",
                "construction use the Prior column values, not the Final Posterior.",
                "",
            ]
        )
        lines.append(
            "Scenario | Prior (ACTIVE) | Engine Pre-Floor | Engine Final (audit) | Engine Change | Floor/Cap | Top Driver"
        )
    elif result.probability_mode == "historically_calibrated" and calibration_by_scenario:
        lines.append(
            "Scenario | Prior | Deterministic Posterior | Historical Analogue Probability | Blended Posterior | Change vs Prior | Floor/Cap | Top Driver"
        )
    else:
        lines.append("Scenario | Prior | Pre-Floor Posterior | Final Posterior | Change | Floor/Cap | Top Driver")
    if result.probability_mode != "two_source_v1":
        for update in result.scenario_updates:
            calibration = calibration_by_scenario.get(update.scenario_id)
            if result.probability_mode == "historically_calibrated" and calibration is not None:
                lines.append(
                    " | ".join(
                        [
                            update.scenario_id,
                            _pct(update.prior_probability),
                            _pct(calibration.deterministic_probability),
                            _pct(calibration.historical_probability),
                            _pct(calibration.blended_probability),
                            _pct(calibration.blended_probability - update.prior_probability),
                            _floor_cap_label(update),
                            _top_driver(update),
                        ]
                    )
                )
                continue
            lines.append(
                " | ".join(
                    [
                        update.scenario_id,
                        _pct(update.prior_probability),
                        _pct(update.pre_floor_posterior_probability),
                        _pct(update.posterior_probability),
                        _pct(update.probability_change),
                        _floor_cap_label(update),
                        _top_driver(update),
                    ]
                )
            )

    lines.extend(["", "2. Scenario Probability Math"])
    if result.probability_mode == "two_source_v1":
        mixture = result.mixture_report or {}
        evidence = mixture.get("evidence") if isinstance(mixture, dict) else {}
        bvar_provenance = result.bvar_provenance or {}
        lines.append("Probability mode: two_source_v1")
        lines.append(f"Combination: {mixture.get('combination', 'linear_mixture')}")
        lines.append(f"Alpha: {_plain_num(mixture.get('alpha'))} | alpha_effective: {_plain_num(mixture.get('alpha_effective'))}")
        lines.append(f"Analogue trailing share s: {_pct(mixture.get('s'))} | base rate b: {_pct(mixture.get('b'))}")
        lines.append(f"Evidence state: {(evidence or {}).get('current_state') or mixture.get('abstention_state') or 'n/a'}")
        lines.append(f"Stress advisory: {bool(mixture.get('stress_advisory', False))}")
        lines.append(f"Numerical floor: {_pct(mixture.get('numerical_floor'))} ({mixture.get('floor_note', 'n/a')})")
        lines.append(f"BVAR artifact: {bvar_provenance.get('path', 'n/a')}")
        lines.append(f"BVAR asof_quarter: {bvar_provenance.get('asof_quarter', 'n/a')} | generated_at: {bvar_provenance.get('generated_at', 'n/a')}")
        lines.append(f"BVAR handoff_fingerprint: {bvar_provenance.get('handoff_fingerprint', 'n/a')}")
        limitations = bvar_provenance.get("model_limitations") or {}
        if limitations:
            lines.append("BVAR model_limitations:")
            for key, value in limitations.items():
                lines.append(f"  {key}: {value}")
        warnings = bvar_provenance.get("warnings") or []
        if warnings:
            lines.append("BVAR warnings:")
            lines.extend(f"  {warning}" for warning in warnings)
    else:
        for update in result.scenario_updates:
            audit = update.math_audit
            if audit is None:
                lines.append(f"{update.scenario_id}: no math audit available")
                continue
            lines.append(_scenario_name(update.scenario_id))
            lines.append(f"  Prior: {_pct(audit.prior_probability)}")
            lines.append(f"  Prior Score: {audit.prior_logit_or_log_score:+.3f}" if audit.prior_logit_or_log_score is not None else "  Prior Score: n/a")
            lines.append(f"  Net Contribution: {audit.net_contribution:+.3f}")
            lines.append(f"  Raw Score Before Softmax: {audit.raw_score_before_softmax:+.3f}")
            lines.append(f"  Exp Score: {audit.exp_score:.6f}" if audit.exp_score is not None else "  Exp Score: n/a")
            lines.append(f"  Softmax Denominator: {audit.softmax_denominator:.6f}" if audit.softmax_denominator is not None else "  Softmax Denominator: n/a")
            lines.append(f"  Pre-Floor Posterior: {_pct(audit.pre_floor_posterior_probability)}")
            lines.append(f"  Floor Applied: {audit.floor_applied} ({_pct(audit.floor_value)})")
            lines.append(f"  Cap Applied: {audit.cap_applied} ({_pct(audit.cap_value)})")
            lines.append(f"  Final Posterior: {_pct(audit.final_posterior_probability)}")
            lines.append(f"  Change: {_pct(audit.final_probability_change)}")
            lines.append("  Top Positive:")
            lines.extend(_contributor_lines(update, positive=True))
            lines.append("  Top Negative:")
            lines.extend(_contributor_lines(update, positive=False))

    lines.extend(["", "3. Historical Analogue Calibration"])
    calibration = result.historical_calibration
    if result.probability_mode == "two_source_v1":
        lines.append(
            "Legacy rolling historical calibration is retired in the runner. "
            "Directional analogue evidence enters only through the two-source mixture above."
        )
    elif calibration is None:
        lines.append("Historical calibration: disabled")
    else:
        lines.append(f"Enabled: {calibration.enabled}")
        lines.append(f"Method: {calibration.method}")
        lines.append(f"Conditions: {calibration.conditions_summary or 'n/a'}")
        lines.append(f"Analogues: {calibration.n_analogues} | Unique: {calibration.n_unique_analogues or 'n/a'} | Pooled: {calibration.n_pooled or 'n/a'}")
        lines.append(f"Confidence: {calibration.confidence:.2f}")
        lines.append(f"Analogue Version: {calibration.analogue_version}")
        if calibration.warnings:
            lines.append(f"Warnings: {'; '.join(calibration.warnings)}")
        if calibration.analogue_version == "v2_detailed":
            diagnostics = calibration.detailed_analogue_diagnostics or {}
            lines.append(
                "Detailed Analogue Match Quality: "
                f"v1_weight={diagnostics.get('v1_weight')}, "
                f"v2_weight={diagnostics.get('v2_weight')}, "
                f"candidate_pool_n={diagnostics.get('candidate_pool_n')}, "
                f"ESS={diagnostics.get('effective_sample_size')}, "
                f"adjusted_deterministic_weight={diagnostics.get('adjusted_deterministic_weight')}, "
                f"adjusted_historical_weight={diagnostics.get('adjusted_historical_weight')}, "
                f"avg_detailed_similarity={diagnostics.get('average_detailed_similarity')}, "
                f"avg_blended_similarity={diagnostics.get('average_blended_similarity')}"
            )
            group_summary = diagnostics.get("group_similarity_summary") or {}
            for group, values in group_summary.items():
                if isinstance(values, dict):
                    lines.append(
                        f"  {group}: avg_similarity={values.get('avg_similarity')}, "
                        f"features_used={values.get('features_used')}, "
                        f"features_missing={values.get('features_missing')}, "
                        f"coverage={values.get('coverage')}"
                    )
        lines.append("Historical Macro Forward Return Stats:")
        lines.append("Horizon | N | Weight Sum | Median | Mean | % Positive | P10 | P25 | P75 | P90 | Worst | Best")
        macro_stats = calibration.macro_forward_return_stats or {
            horizon: calibration.forward_return_stats[horizon]
            for horizon in ["21d", "63d", "126d", "252d"]
            if horizon in calibration.forward_return_stats
        }
        for horizon in ["21d", "63d", "126d", "252d"]:
            stats = macro_stats.get(horizon)
            if stats is None:
                continue
            lines.append(
                " | ".join(
                    [
                        _horizon_label(horizon),
                        str(stats.n),
                        _plain_num(stats.weight_sum),
                        _num(stats.median),
                        _num(stats.mean),
                        f"{stats.pct_positive:.1f}" if stats.pct_positive is not None else "n/a",
                        _num(stats.p10),
                        _num(stats.p25),
                        _num(stats.p75),
                        _num(stats.p90),
                        _num(stats.worst),
                        _num(stats.best),
                    ]
                )
            )
        lines.append(
            "Note: Longer horizons naturally have lower sample sizes because recent historical rows do not yet have full forward-return windows, especially 1Y / 252D."
        )
        tactical_stats = calibration.tactical_forward_return_stats or {
            horizon: calibration.forward_return_stats[horizon]
            for horizon in ["1d", "5d", "10d"]
            if horizon in calibration.forward_return_stats
        }
        if tactical_stats:
            lines.append("Historical Tactical Forward Return Stats:")
            lines.append("Horizon | N | Weight Sum | Median | Mean | % Positive | P10 | P25 | P75 | P90 | Worst | Best")
            for horizon in ["1d", "5d", "10d"]:
                stats = tactical_stats.get(horizon)
                if stats is None:
                    continue
                lines.append(
                    " | ".join(
                        [
                            _horizon_label(horizon),
                            str(stats.n),
                            _plain_num(stats.weight_sum),
                            _num(stats.median),
                            _num(stats.mean),
                            f"{stats.pct_positive:.1f}" if stats.pct_positive is not None else "n/a",
                            _num(stats.p10),
                            _num(stats.p25),
                            _num(stats.p75),
                            _num(stats.p90),
                            _num(stats.worst),
                            _num(stats.best),
                        ]
                    )
                )
        if calibration.risk_profile:
            risk_items = _risk_profile_items_for_report(calibration.risk_profile)
            lines.append(
                "Risk Profile: "
                + ", ".join(f"{key}={value}" for key, value in risk_items)
            )
        lines.append("Top Analogue Dates:")
        for analogue in calibration.top_analogues[:10]:
            lines.append(
                f"  {analogue.date} | weight={_num(analogue.composite_weight)} | similarity={_num(analogue.similarity_score)} | "
                f"env={analogue.environment or 'n/a'} | score={_num(analogue.score_total)} | "
                f"VIX={_num(analogue.vix_level)} | sectors={analogue.sectors_green if analogue.sectors_green is not None else 'n/a'} | "
                f"v1_sim={_num(analogue.v1_similarity)} | detailed_sim={_num(analogue.detailed_similarity)} | "
                f"blended_sim={_num(analogue.blended_similarity)} | strong_groups={','.join(analogue.strongest_matching_groups) or 'n/a'} | "
                f"weak_groups={','.join(analogue.weakest_matching_groups) or 'n/a'} | "
                f"63d={_num(analogue.forward_returns.get('63d'))} | 21d={_num(analogue.forward_returns.get('21d'))} | mapped={analogue.mapped_scenario_id} | "
                f"rationale={analogue.mapping_rationale or 'n/a'}"
            )
        lines.append("Scenario Calibration:")
        lines.append("Scenario | Deterministic Probability | Historical Probability | Blended Probability | Analog Effect | Supporting Analogues | Confidence | Rationale")
        for item in calibration.scenario_calibrations:
            lines.append(
                " | ".join(
                    [
                        item.scenario_id,
                        _pct(item.deterministic_probability),
                        _pct(item.historical_probability),
                        _pct(item.blended_probability),
                        _pct(item.analog_effect),
                        str(item.n_supporting_analogues),
                        f"{item.confidence:.2f}",
                        item.rationale,
                    ]
                )
            )
        lines.append("Methodology:")
        lines.extend(f"- {note}" for note in calibration.methodology_notes)

    lines.extend(["", "4. Forecast Input Set"])
    lines.append("Monitoring — no probability impact.")
    input_set = result.forecast_input_set
    if input_set is None:
        lines.extend(
            [
                "ForecastInputSet is not available; falling back to legacy flat input signal list.",
                "Signal | Category | Reading | Signal | Trend | Confidence | Quality | Probability Impact? | Display Only? | Composite / Parent | Exclusion Reason",
            ]
        )
        for signal in result.input_signals:
            lines.append(
                " | ".join(
                    [
                        signal.name,
                        signal.category,
                        _signal_reading(signal.current_value),
                        signal.signal,
                        signal.trend,
                        f"{signal.confidence:.2f}",
                        signal.data_quality,
                        "Yes" if signal.used_in_probability_update else "No",
                        str(signal.display_only),
                        signal.parent_signal_id or ("composite" if signal.child_signal_ids else "-"),
                        signal.exclusion_reason or "-",
                    ]
                )
            )
    else:
        input_warning = _volatility_coverage_warning(result)
        if input_warning:
            lines.extend(["Forecast Input Warnings:", f"- {input_warning}", ""])
        lines.extend(
            [
                "4.1 Layer Summary Signals",
                "Layer | Score | Status | Confidence/Data Quality | Probability Impact? | Key Signals | Raw Components Attached",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.layer_summary_signals,
            lambda signal: " | ".join(
                [
                    signal.parent_layer or signal.category,
                    _signal_reading(signal.current_value),
                    f"{signal.signal}/{signal.trend}",
                    f"{signal.confidence:.2f}/{signal.data_quality}",
                    "Yes" if signal.used_in_probability_update else "No",
                    signal.notes or "-",
                    _raw_components_for_layer(result, signal.parent_layer),
                ]
            ),
        )

        lines.extend(
            [
                "",
                "4.2 Raw Component Signals",
                "Input | Parent Layer | Raw Value | Transformed Value | Status | Trend | Confidence | Probability Impact? | Top Scenario Effects",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.raw_component_signals,
            lambda signal: " | ".join(
                [
                    signal.name,
                    signal.parent_layer or "-",
                    _signal_reading(signal.raw_value),
                    _num(signal.transformed_value),
                    signal.level_status or signal.signal,
                    signal.trend_status or signal.trend,
                    f"{signal.confidence:.2f}",
                    "Yes" if signal.used_in_probability_update else "No",
                    _top_scenario_effects(signal),
                ]
            ),
        )

        lines.extend(
            [
                "",
                "4.3 Composite Signals",
                "Composite | Parent Layer | Signal | Confidence | Probability Impact? | Child Signals | Scenario Effects",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.composite_signals,
            lambda signal: " | ".join(
                [
                    signal.name,
                    signal.parent_layer or "-",
                    signal.signal,
                    f"{signal.confidence:.2f}",
                    "Yes" if signal.used_in_probability_update else "No",
                    ", ".join(signal.child_signal_ids) or "-",
                    _top_scenario_effects(signal),
                ]
            ),
        )

        lines.extend(
            [
                "",
                "4.4 Market/Tape Signals",
                "Input | Raw Value | Status | Confidence | Probability Impact? | Horizon/Dedupe Effect | Top Scenario Effects",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.market_tape_signals,
            lambda signal: " | ".join(
                [
                    signal.name,
                    _signal_reading(signal.raw_value),
                    signal.level_status or signal.signal,
                    f"{signal.confidence:.2f}",
                    "Yes" if signal.used_in_probability_update else "No",
                    signal.transformation_method or "-",
                    _top_scenario_effects(signal),
                ]
            ),
        )

        lines.extend(
            [
                "",
                "4.5 Regime-Specific Drivers",
                "Driver | Parent Layer | Signal | Confidence | Active Regime | Scenario Effects",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.regime_driver_signals,
            lambda signal: " | ".join(
                [
                    signal.name,
                    signal.parent_layer or "-",
                    signal.signal,
                    f"{signal.confidence:.2f}",
                    ", ".join(signal.active_only_in_regime_ids) or "-",
                    _top_scenario_effects(signal),
                ]
            ),
        )

        lines.extend(
            [
                "",
                "4.6 Scenario Falsifiers",
                "Falsifier | Related Scenarios | Signal | Confidence | Current Value | Scenario Effects",
            ]
        )
        _append_signal_rows(
            lines,
            input_set.scenario_falsifier_signals,
            lambda signal: " | ".join(
                [
                    signal.name,
                    ", ".join(signal.related_scenario_ids) or "-",
                    signal.signal,
                    f"{signal.confidence:.2f}",
                    _signal_reading(signal.current_value),
                    _top_scenario_effects(signal),
                ]
            ),
        )

        lines.extend(["", "4.7 Dedupe / Weighting Notes"])
        lines.extend(f"- {note}" for note in input_set.methodology_notes)

    lines.extend(["", "5. Monetary Composite Detail"])
    monetary = next((signal for signal in result.input_signals if signal.input_id == "monetary_policy_composite"), None)
    if monetary is None:
        lines.append("No monetary composite signal present.")
    else:
        children = [
            signal for signal in result.input_signals
            if signal.input_id in set(monetary.child_signal_ids)
        ]
        lines.append(f"Composite Signal: {monetary.signal}")
        lines.append(f"Composite Confidence: {monetary.confidence:.2f}")
        lines.append(f"Probability impact: {'Yes' if monetary.used_in_probability_update else 'No'}")
        lines.append(f"Composite Method: {monetary.composite_method or 'n/a'}")
        for child in children:
            lines.append(
                f"Component: {child.name} | signal={child.signal} | confidence={child.confidence:.2f} | "
                f"display_only={child.display_only} | probability_impact={'Yes' if child.used_in_probability_update else 'No'}"
            )
        impacts = ", ".join(
            f"{impact.scenario_id} {impact.direction} {impact.strength:.2f}"
            for impact in monetary.affected_scenarios
        )
        lines.append(f"Assigned Scenario Impacts: {impacts or 'none'}")

    lines.extend(
        [
            "",
            "6. Theme Rankings - Macro Support Score",
            "# | Theme | Macro Support Score | Best Scenarios | Worst Scenarios | Scenario Contribution Breakdown | Interpretation",
            "Note: Theme rankings in the macro forecast are based only on macro/scenario support. The score is the probability-weighted scenario exposure of each theme. Crowding, valuation, narrative maturity, consensus gap, and ticker-level dispersion are intentionally excluded here and evaluated by downstream agents.",
            "Deprecated overlay fields may exist in historical records but are not used in current macro ranking.",
        ]
    )
    for idx, theme in enumerate(result.theme_rankings, 1):
        lines.append(
            " | ".join(
                [
                    str(idx),
                    theme.label,
                    f"{theme.macro_support_score:+.2f}",
                    ", ".join(theme.best_scenarios) or "none",
                    ", ".join(theme.worst_scenarios) or "none",
                    _theme_contribution_summary(theme),
                    "Macro-supported research direction; downstream agents evaluate crowding, valuation, narrative maturity, consensus gap, and ticker quality.",
                ]
            )
        )

    lines.extend(["", "6a. Theme Macro Support Math"])
    for theme in result.theme_rankings[:5]:
        lines.append(f"{theme.label}: {theme.macro_support_score:+.3f}")
        for contribution in sorted(
            theme.scenario_contributions,
            key=lambda item: abs(item.contribution),
            reverse=True,
        ):
            lines.append(
                f"  {contribution.scenario_label}: "
                f"{contribution.scenario_probability:.1%} x "
                f"{contribution.theme_exposure_score:+.1f} = "
                f"{contribution.contribution:+.3f}"
            )
        lines.append(
            f"  Net: {theme.net_macro_support_score:+.3f} "
            f"(positive {theme.positive_contribution_total:+.3f}, "
            f"negative {theme.negative_contribution_total:+.3f})"
        )

    lines.extend(
        [
            "",
            "7. Sector & Instrument Rankings",
            "# | Sector/Instrument | Score | Top Theme Drivers",
        ]
    )
    for idx, ranking in enumerate(result.sector_rankings, 1):
        lines.append(
            f"{idx} | {ranking.label or ranking.ticker or ranking.item_id} | {ranking.score:+.2f} | "
            f"{_ranking_driver_summary(ranking.contributions)}"
        )

    lines.extend(
        [
            "",
            "8. Factor Rankings",
            "# | Factor | Score | Top Theme Drivers",
        ]
    )
    for idx, ranking in enumerate(result.factor_rankings, 1):
        lines.append(
            f"{idx} | {ranking.label or ranking.factor_id or ranking.item_id} | {ranking.score:+.2f} | "
            f"{_ranking_driver_summary(ranking.contributions)}"
        )

    lines.extend(["", "9. Probability Shifters / Watchlist"])
    if result.probability_mode == "two_source_v1":
        lines.append("Deterministic probability shifters are retired; monitoring signals and falsifiers remain display-only.")
    else:
        for shifter in result.probability_shifters:
            lines.append(f"{_scenario_name(shifter.scenario_id)} ({_pct(shifter.current_probability)})")
            lines.append(f"  Would increase if: {'; '.join(shifter.would_increase_probability_if)}")
            lines.append(f"  Would decrease if: {'; '.join(shifter.would_decrease_probability_if)}")
            lines.append(f"  Watch: {', '.join(shifter.key_inputs_to_watch) or 'none'}")
            if shifter.floor_or_cap_note:
                lines.append(f"  Floor/Cap: {shifter.floor_or_cap_note}")

    lines.extend(["", "10. Recommended Research Priorities"])
    for priority in result.recommended_research_priorities:
        lines.append(f"{priority.priority_rank}. {priority.theme}")
        lines.append(f"   Rationale: {priority.rationale}")
        lines.append(f"   Edge: {priority.edge_hypothesis}")

    lines.extend(["", "11. Input Signal Detail"])
    for signal in result.input_signals:
        lines.append(f"{signal.input_id}: {signal.notes}")
        if signal.affected_scenarios:
            impacts = ", ".join(
                f"{impact.scenario_id} {impact.direction} {impact.strength:.2f}"
                for impact in signal.affected_scenarios
            )
            lines.append(f"  Scenario impacts: {impacts}")
        if signal.affected_themes:
            theme_impacts = ", ".join(
                f"{impact.theme_id} {impact.direction} {impact.strength:.2f}"
                for impact in signal.affected_themes
            )
            lines.append(f"  Theme impacts: {theme_impacts}")

    lines.extend(["", "12. Methodology Notes"])
    if result.probability_mode == "two_source_v1":
        lines.extend(
            [
                "Input construction:",
                "Layer summaries, raw components, market/tape signals, regime drivers, and falsifiers are generated for monitoring only.",
                "Probability sources:",
                "BVAR contribution = scenario_probabilities_soft from the behavioral-v1 ensemble artifact.",
                "Analogue contribution = directional analogue trailing maximum of the PIT-observable shrunk recession share.",
                "Mixture:",
                "analogue_implied allocates recession and non-recession group mass using the BVAR within-group proportions.",
                "mixed_probability_s = (1 - alpha) × bvar_soft_s + alpha × analogue_implied_s",
                "final_probability_s = apply uniform 0.1% numerical floor, then renormalize.",
                "Retired probability paths:",
                "Hardcoded priors, deterministic contribution updates, YAML prior overrides, hand-tuned scenario floors/caps, and legacy rolling historical calibration have no probability impact in two_source_v1.",
                "Theme score:",
                "macro_support_score_t = Σ scenario_probability_s × behavioral_v1_theme_exposure_score_t,s",
                "theme_contribution_t,s = scenario_probability_s × theme_exposure_score_t,s",
                "ranking_score_t = macro_support_score_t",
                "Sector/factor score:",
                "sector_score = Σ theme_macro_support_score_t × sector_theme_weight_t",
                "factor_score = Σ theme_macro_support_score_t × factor_theme_weight_t",
                "Macro forecast theme rankings intentionally exclude valuation, crowding, narrative maturity, consensus gap, and ticker-level quality. Those are evaluated by downstream research agents.",
            ]
        )
    else:
        lines.extend(
            [
                "Input construction:",
                "Layer summaries are generated from Helix regime layer scores.",
                "Raw components are generated from the underlying RegimeInputs fields.",
                "Market/tape signals are generated from MarketState.",
                "Regime drivers and scenario falsifiers are generated from active regime context and scenario definitions.",
                "Contribution method:",
                "In hybrid mode, layer summaries provide base scenario impacts and raw components act as modifiers within the same parent layer.",
                "Dedupe caps prevent one layer from dominating through many correlated inputs.",
                "Market/tape signals are downweighted for longer horizons.",
                "raw_component_contribution = direction_sign × base_strength × confidence × signal_multiplier × horizon_weight × dedupe_weight",
                "layer_summary_contribution = direction_sign × base_strength × confidence × layer_summary_base_weight",
                "final_layer_group_contribution = layer_summary_contribution + capped_sum(raw_component_modifiers)",
                "Scenario probability update:",
                "raw_score_s = prior_score_s + Σ input_contribution_i,s",
                "input_contribution_i,s = direction_sign × base_strength_i,s × confidence_i × signal_multiplier_i",
                "pre_floor_probability_s = softmax(raw_score_s)",
                "final_probability_s = apply_floors_and_caps(pre_floor_probability_s)",
                "Theme score:",
                "macro_support_score_t = Σ scenario_probability_s × theme_exposure_score_t,s",
                "theme_contribution_t,s = scenario_probability_s × theme_exposure_score_t,s",
                "ranking_score_t = macro_support_score_t",
                "Sector/factor score:",
                "sector_score = Σ theme_macro_support_score_t × sector_theme_weight_t",
                "factor_score = Σ theme_macro_support_score_t × factor_theme_weight_t",
                "Macro forecast theme rankings intentionally exclude valuation, crowding, narrative maturity, consensus gap, and ticker-level quality. Those are evaluated by downstream research agents.",
                "Monetary composite:",
                "monetary component signals are displayed as inputs but excluded from probability math when monetary_policy_composite is enabled.",
            ]
        )

    return "\n".join(lines)


def _load_regime_for_cli(asof_date: str | None = None) -> RegimeState:
    from src.agent_system.orchestration.run_research_cycle import _select_regime_state

    regime, _, _ = _select_regime_state(asof_date=asof_date)
    return regime


def _non_null_field_count(value: object | None) -> int:
    if value is None:
        return 0
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()  # type: ignore[attr-defined]
        except Exception:
            data = {}
    elif hasattr(value, "__dataclass_fields__"):
        try:
            from dataclasses import asdict

            data = asdict(value)
        except Exception:
            data = {}
    elif isinstance(value, dict):
        data = value
    else:
        data = {
            key: getattr(value, key)
            for key in dir(value)
            if not key.startswith("_") and not callable(getattr(value, key, None))
        }
    return sum(
        1
        for item in data.values()
        if item is not None and item != {} and item != []
    )


def _load_regime_inputs_for_cli(asof_date: str | None = None) -> object | None:
    try:
        from src.state.regime_data import fetch_regime_inputs

        return fetch_regime_inputs(asof_date=asof_date)
    except Exception as exc:
        print(f"RegimeInputs fetch failed: {exc}", file=sys.stderr)
        return None


def _market_state_horizon(run_horizon: str) -> str:
    return {
        "1m": "1M",
        "3m": "3M",
        "6m": "6M",
        "1y": "1Y",
    }.get(str(run_horizon).lower(), "1D")


def _load_market_state_for_cli(asof_date: str | None = None, horizon: str = "3m") -> object | None:
    try:
        from src.state.market_state import build_market_state, load_snapshot

        if asof_date:
            snapshot = load_snapshot("data/snapshots", asof_date)
            if snapshot is not None:
                return snapshot
        return build_market_state(horizon=_market_state_horizon(horizon))
    except Exception as exc:
        print(f"MarketState fetch failed: {exc}", file=sys.stderr)
        return None


def _raw_input_run_diagnostics(
    *,
    regime_inputs: object | None,
    market_state: object | None,
    forecast_input_set,
) -> dict[str, object]:
    raw_signals = list(getattr(forecast_input_set, "raw_component_signals", []) or [])
    return {
        "RegimeInputs fetched": "yes" if regime_inputs is not None else "no",
        "RegimeInputs non-null fields count": _non_null_field_count(regime_inputs),
        "MarketState fetched": "yes" if market_state is not None else "no",
        "MarketState non-null fields count": _non_null_field_count(market_state),
        "ForecastInputSet raw_component_signals count": len(raw_signals),
        "ForecastInputSet raw_component_signals used_in_probability_update count": sum(
            1 for signal in raw_signals if signal.used_in_probability_update and not signal.display_only
        ),
        "ForecastInputSet raw_component_signals used_in_historical_similarity count": sum(
            1 for signal in raw_signals if signal.used_in_historical_similarity
        ),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Helix Macro Forecast production runner.")
    parser.set_defaults(
        historical_calibration=None,
        detailed_analogues=None,
        save_docx=None,
        save_json=None,
        save_current_regime_yaml=None,
        include_volatility_inputs=None,
    )

    parser.add_argument("--asof-date", default=None, help="Optional YYYY-MM-DD regime snapshot date.")
    parser.add_argument("--horizon", choices=["1m", "3m", "6m", "1y"], default=None, help="Forecast horizon.")
    parser.add_argument("--reports-dir", default=None, help="Directory for default DOCX/JSON outputs.")
    parser.add_argument("--docx-output", default=None, help="Optional explicit DOCX output path.")
    parser.add_argument("--json-output", default=None, help="Optional explicit JSON output path.")
    parser.add_argument("--current-regime-output", default=None, help="Optional explicit current-regime YAML output path.")
    parser.add_argument("--bvar-cache-dir", default=None, help="Directory containing BVAR forecast_*.json artifacts.")
    parser.add_argument(
        "--allow-stale-bvar",
        action="store_true",
        help="Allow the newest BVAR forecast artifact to lag the current calendar quarter, with a printed warning.",
    )
    parser.add_argument("--debug", action="store_true", help="Print additional debug output.")
    parser.add_argument(
        "--use-yaml-priors",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    parser.add_argument("--no-historical-calibration", dest="historical_calibration", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--no-detailed-analogues", dest="detailed_analogues", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--no-docx", dest="save_docx", action="store_false")
    parser.add_argument("--no-json", dest="save_json", action="store_false")
    parser.add_argument("--no-current-regime-yaml", dest="save_current_regime_yaml", action="store_false")

    advanced = parser.add_argument_group("advanced/debug overrides")
    advanced.add_argument("--input-mode", choices=["hybrid", "layer_only", "raw_only"], default=None)
    advanced.add_argument("--historical-weight", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--deterministic-weight", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-v1-weight", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-v2-weight", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-candidate-pool-n", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--min-feature-coverage", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--min-effective-sample-size", type=int, default=None, help=argparse.SUPPRESS)

    advanced.add_argument("--layer-summary-base-weight", type=float, default=None)
    advanced.add_argument("--raw-component-modifier-weight", type=float, default=None)
    advanced.add_argument("--max-raw-modifier-ratio", type=float, default=None)
    advanced.add_argument("--analogue-lookback-days", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-half-life", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-pool-top-n", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-top-n-per-lookup", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-exclude-recent-days", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analogue-min-count", type=int, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--analog-macro-horizons", default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--scenario-mapping-horizon", choices=["21d", "63d", "126d", "252d"], default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--current-state-lookup-weight", type=float, default=None, help=argparse.SUPPRESS)
    advanced.add_argument("--overwrite-current-regime", action="store_true")

    parser.add_argument("--default-scenarios", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--format", choices=["summary", "json", "report"], default="summary", help=argparse.SUPPRESS)
    parser.add_argument("--strict-report", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-save", dest="save_json", action="store_false", help=argparse.SUPPRESS)
    parser.add_argument("--docx", dest="save_docx", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--historical-calibration", dest="historical_calibration", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--detailed-analogues", dest="detailed_analogues", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--include-volatility-inputs",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser


def _run_config_from_args(args: argparse.Namespace) -> MacroForecastRunConfig:
    retired = _retired_cli_options(args)
    if retired:
        raise MacroForecastRunnerError(
            f"CLI option(s) {retired} are {TWO_SOURCE_REWIRE_MESSAGE}"
        )
    values: dict[str, object] = {}
    for arg_name, field_name in {
        "asof_date": "asof_date",
        "horizon": "horizon",
        "reports_dir": "reports_dir",
        "docx_output": "docx_output",
        "json_output": "json_output",
        "current_regime_output": "current_regime_output",
        "bvar_cache_dir": "bvar_cache_dir",
        "input_mode": "input_mode",
        "layer_summary_base_weight": "layer_summary_base_weight",
        "raw_component_modifier_weight": "raw_component_modifier_weight",
        "max_raw_modifier_ratio": "max_raw_modifier_ratio",
    }.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            values[field_name] = value

    if args.save_docx is not None:
        values["save_docx"] = bool(args.save_docx)
    if args.save_json is not None:
        values["save_json"] = bool(args.save_json)
    if args.save_current_regime_yaml is not None:
        values["save_current_regime_yaml"] = bool(args.save_current_regime_yaml)
    if args.overwrite_current_regime:
        values["overwrite_current_regime"] = True
    if args.include_volatility_inputs is not None:
        values["volatility_enabled"] = bool(args.include_volatility_inputs)
    if args.allow_stale_bvar:
        values["allow_stale_bvar"] = True
    if args.debug:
        values["debug"] = True
    return MacroForecastRunConfig.model_validate(values)


def _retired_cli_options(args: argparse.Namespace) -> list[str]:
    retired_names = []
    boolean_flags = {
        "use_yaml_priors": "--use-yaml-priors",
        "default_scenarios": "--default-scenarios",
    }
    for attr, flag in boolean_flags.items():
        if getattr(args, attr, False):
            retired_names.append(flag)
    nullable_flags = {
        "historical_calibration": "--historical-calibration/--no-historical-calibration",
        "detailed_analogues": "--detailed-analogues/--no-detailed-analogues",
        "historical_weight": "--historical-weight",
        "deterministic_weight": "--deterministic-weight",
        "analogue_v1_weight": "--analogue-v1-weight",
        "analogue_v2_weight": "--analogue-v2-weight",
        "analogue_candidate_pool_n": "--analogue-candidate-pool-n",
        "analogue_lookback_days": "--analogue-lookback-days",
        "analogue_half_life": "--analogue-half-life",
        "analogue_pool_top_n": "--analogue-pool-top-n",
        "analogue_top_n_per_lookup": "--analogue-top-n-per-lookup",
        "analogue_exclude_recent_days": "--analogue-exclude-recent-days",
        "analogue_min_count": "--analogue-min-count",
        "analog_macro_horizons": "--analog-macro-horizons",
        "scenario_mapping_horizon": "--scenario-mapping-horizon",
        "current_state_lookup_weight": "--current-state-lookup-weight",
        "min_feature_coverage": "--min-feature-coverage",
        "min_effective_sample_size": "--min-effective-sample-size",
    }
    for attr, flag in nullable_flags.items():
        if getattr(args, attr, None) is not None:
            retired_names.append(flag)
    return retired_names


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    run_config = _run_config_from_args(args)

    regime_state = _load_regime_for_cli(run_config.asof_date)
    asof_for_inputs = run_config.asof_date or regime_state.asof_date
    regime_inputs = _load_regime_inputs_for_cli(asof_for_inputs) if run_config.raw_inputs_enabled else None
    market_state = _load_market_state_for_cli(asof_for_inputs, run_config.horizon)
    result = run_macro_forecast(
        regime_state,
        horizon=run_config.horizon,
        dedupe_config=run_config.dedupe_config(),
        raw_inputs=regime_inputs,
        market_state=market_state,
        bvar_cache_dir=run_config.bvar_cache_dir,
        allow_stale_bvar=run_config.allow_stale_bvar,
        fan_output_dir=_default_fan_output_dir(run_config.reports_dir),
    )

    requested_docx_path = (
        Path(run_config.docx_output)
        if run_config.docx_output
        else _default_docx_output_path(result, run_config.reports_dir)
    )
    requested_json_path = (
        Path(run_config.json_output)
        if run_config.json_output
        else _default_json_output_path(result, run_config.reports_dir)
    )

    current_regime_yaml_path: Path | None = None
    if run_config.save_current_regime_yaml:
        macro_source = get_macro_scenario_source(
            cycle_date=_quarter_end_date_text(str(result.bvar_provenance["asof_quarter"])),
            config=MacroScenarioSourceConfig(
                macro_forecast_source="ensemble",
                bvar_cache_dir=run_config.bvar_cache_dir,
                analogue_evidence_enabled=True,
            ),
        )
        handoff = build_current_regime_handoff_from_macro_source(
            macro_source,
            analogue_report_override=result.mixture_report,
            fan_artifact_path=result.outputs.get("analogue_fan_json_path"),
        )
        output_dir = _default_current_regime_output_dir(
            reports_dir=run_config.reports_dir,
            docx_path=requested_docx_path if run_config.save_docx else None,
            json_path=requested_json_path if run_config.save_json else None,
        )
        current_regime_yaml_path = save_current_regime_yaml(
            handoff,
            output_dir=output_dir,
            asof_date=result.asof_date,
            output_path=run_config.current_regime_output,
            overwrite=run_config.overwrite_current_regime,
        )
        result = result.model_copy_validate(
            {
                "outputs": {
                    **result.outputs,
                    "current_regime_yaml_path": str(current_regime_yaml_path),
                }
            }
        )

    docx_path: Path | None = None
    if run_config.save_docx:
        try:
            from src.agent_system.reporting.macro_forecast_docx import (
                generate_macro_forecast_docx,
            )

            docx_path = generate_macro_forecast_docx(result, requested_docx_path)
            result = result.model_copy_validate(
                {
                    "outputs": {
                        **result.outputs,
                        "docx_path": str(docx_path),
                    }
                }
            )
        except Exception as exc:
            if args.strict_report:
                raise
            print(f"DOCX report generation failed: {exc}", file=sys.stderr)

    json_path: Path | None = None
    if run_config.save_json:
        result = result.model_copy_validate(
            {
                "outputs": {
                    **result.outputs,
                    "json_path": str(requested_json_path),
                }
            }
        )
        json_path = _write_json_result(result, requested_json_path)

    _print_run_summary(
        result=result,
        config=run_config,
        docx_path=docx_path,
        json_path=json_path,
        current_regime_yaml_path=current_regime_yaml_path,
        docx_disabled=not run_config.save_docx,
        json_disabled=not run_config.save_json,
        current_regime_yaml_disabled=not run_config.save_current_regime_yaml,
    )

    if run_config.debug:
        print()
        print("Raw input data flow:")
        for key, value in _raw_input_run_diagnostics(
            regime_inputs=regime_inputs,
            market_state=market_state,
            forecast_input_set=result.forecast_input_set,
        ).items():
            print(f"{key}: {value}")
        print()
        print("Run config:")
        print(run_config.model_dump_json(indent=2))
    if args.format == "report":
        print()
        print(format_macro_forecast_report(result))
    elif args.format == "json":
        print()
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
