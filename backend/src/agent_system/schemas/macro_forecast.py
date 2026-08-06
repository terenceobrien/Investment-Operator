"""Schemas for deterministic upstream macro forecasting."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agent_system.schemas.common import BaseSchema, Evidence, UnitInterval
from src.agent_system.schemas.regime import EdgeDecayHorizon


SignalCategory = Literal[
    "monetary",
    "inflation",
    "growth",
    "credit",
    "liquidity",
    "volatility",
    "breadth",
    "positioning",
    "earnings",
    "commodities",
    "fx",
    "geopolitical",
    "narrative",
]
SignalTrend = Literal["improving", "deteriorating", "stable", "mixed", "unknown"]
SignalDirection = Literal["bullish", "bearish", "neutral", "mixed"]
SignalStatus = Literal["bullish", "bearish", "neutral", "mixed", "unknown"]
DataQuality = Literal["high", "medium", "low", "absent"]
ScenarioDirection = Literal["increases", "decreases"]
ThemeDirection = Literal["positive", "negative", "neutral"]
AbsoluteStatus = Literal["bearish", "neutral", "bullish"]
OverlayConfidence = Literal["high", "medium", "low", "absent"]
InputScope = Literal[
    "core_macro",
    "market_structure",
    "market_tape",
    "layer_summary",
    "raw_component",
    "composite",
    "regime_driver",
    "scenario_falsifier",
    "theme_specific",
]
ParentLayer = Literal[
    "monetary",
    "credit",
    "volatility",
    "breadth",
    "positioning",
    "market_state",
    "rates_fx",
    "earnings",
    "commodities",
    "geopolitical",
    "other",
]
SignalRole = Literal[
    "layer_summary",
    "raw_component",
    "composite",
    "regime_driver",
    "scenario_falsifier",
    "theme_specific",
    "display_only",
]
DedupeRole = Literal["primary", "modifier", "display_only"]


class ScenarioProbabilityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    use_probability_floors: bool = True
    scenario_probability_floors: Dict[str, float] = Field(
        default_factory=lambda: {
            "reopening_soft_landing": 0.05,
            "sticky_late_cycle_ai": 0.05,
            "oil_inflation_tail": 0.05,
            "late_cycle_risk_off": 0.05,
            "ai_capex_rollover": 0.075,
        }
    )
    max_single_scenario_probability: Optional[float] = Field(default=0.65, ge=0.0, le=1.0)
    softmax_temperature: float = Field(default=1.0, gt=0.0)


class InputDedupeConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: Literal["layer_only", "raw_only", "hybrid"] = "hybrid"
    layer_summary_base_weight: float = Field(default=0.60, ge=0.0, le=1.0)
    raw_component_modifier_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    raw_component_cap_ratio: float = Field(default=0.50, ge=0.0, le=2.0)
    max_raw_modifier_ratio: float = Field(default=0.50, ge=0.0, le=2.0)
    include_volatility_layer: bool = True
    include_volatility_raw_components: bool = True
    market_tape_weight_by_horizon: Dict[str, float] = Field(
        default_factory=lambda: {
            "1d": 1.00,
            "1w": 0.75,
            "1m": 0.50,
            "3m": 0.25,
            "6m": 0.15,
            "1y": 0.10,
        }
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_max_raw_modifier_alias(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if values.get("raw_component_cap_ratio") is None and values.get("max_raw_modifier_ratio") is not None:
            values["raw_component_cap_ratio"] = values["max_raw_modifier_ratio"]
        return values

class DeterministicInputConfig(InputDedupeConfig):
    """Deterministic input configuration alias for Macro Forecast V2."""

    pass


class LevelAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    absolute_status: AbsoluteStatus
    trend_status: SignalTrend
    combined_signal: SignalDirection
    confidence_adjustment: float = Field(ge=0.0, le=1.0)
    explanation: str = Field(min_length=1, max_length=1000)


class ScenarioImpact(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    direction: ScenarioDirection
    strength: UnitInterval
    rationale: str = Field(min_length=1, max_length=1000)


class ThemeImpact(BaseSchema):
    theme_id: str = Field(min_length=1, max_length=100)
    direction: ThemeDirection
    strength: UnitInterval
    rationale: str = Field(min_length=1, max_length=1000)


class InputProvenance(BaseModel):
    input_id: str
    display_label: str
    provider: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    source_object: Optional[str] = None
    source_field: Optional[str] = None
    source_alias_used: Optional[str] = None

    asof_date: Optional[str] = None
    observed_date: Optional[str] = None
    last_updated_at: Optional[str] = None
    cache_timestamp: Optional[str] = None
    is_cached: bool = False

    frequency: Literal["intraday", "daily", "weekly", "monthly", "quarterly", "unknown"] = "unknown"
    expected_lag_days: Optional[int] = None
    staleness_days: Optional[float] = None
    freshness_status: Literal["fresh", "acceptable_lag", "stale", "unknown"] = "unknown"

    lookback_window: Optional[str] = None
    calculation_method: Optional[str] = None
    raw_inputs_used: Dict[str, Any] = Field(default_factory=dict)

    value: float | str | bool | None = None
    transformed_value: Optional[float] = None
    units: Optional[str] = None

    interpretation_label: Optional[str] = None
    interpretation_rule_id: Optional[str] = None
    interpretation_detail: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class MacroInputSignal(BaseSchema):
    input_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    label: Optional[str] = Field(default=None, max_length=200)
    category: SignalCategory
    current_value: float | str | None = None
    unit: Optional[str] = Field(default=None, max_length=50)
    percentile: Optional[UnitInterval] = None
    z_score: Optional[float] = None
    trend: SignalTrend
    signal: SignalDirection
    confidence: UnitInterval
    data_quality: DataQuality
    last_updated: Optional[datetime] = None
    affected_scenarios: List[ScenarioImpact] = Field(default_factory=list)
    affected_themes: List[ThemeImpact] = Field(default_factory=list)
    scenario_impacts: List[ScenarioImpact] = Field(default_factory=list)
    theme_impacts: List[ThemeImpact] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    input_scope: InputScope = "core_macro"
    parent_layer: Optional[ParentLayer] = None
    role: SignalRole = "raw_component"
    is_persistent_input: bool = True
    active_only_in_regime_ids: List[str] = Field(default_factory=list)
    related_scenario_ids: List[str] = Field(default_factory=list)
    related_theme_ids: List[str] = Field(default_factory=list)
    raw_value: float | str | bool | None = None
    transformed_value: Optional[float] = None
    transformation_method: Optional[str] = Field(default=None, max_length=500)
    source_object: Optional[str] = Field(default=None, max_length=100)
    provenance: Optional[InputProvenance] = None
    level_status: Optional[SignalStatus] = None
    trend_status: Optional[SignalTrend] = None
    signal_strength: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    used_in_probability_update: bool = True
    used_in_historical_similarity: bool = False
    display_only: bool = False
    parent_signal_id: Optional[str] = Field(default=None, max_length=100)
    child_signal_ids: List[str] = Field(default_factory=list)
    composite_method: Optional[str] = Field(default=None, max_length=1000)
    exclusion_reason: Optional[str] = Field(default=None, max_length=1000)
    dedupe_group: Optional[str] = Field(default=None, max_length=100)
    dedupe_role: Optional[DedupeRole] = None
    dedupe_weight: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    historical_feature_id: Optional[str] = Field(default=None, max_length=100)
    historical_column: Optional[str] = Field(default=None, max_length=100)
    historical_similarity_group: Optional[str] = Field(default=None, max_length=100)
    historical_similarity_weight: Optional[float] = Field(default=None, ge=0.0, le=10.0)

    @model_validator(mode="before")
    @classmethod
    def _fill_signal_taxonomy_defaults(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if values.get("name") is None and values.get("label") is not None:
            values["name"] = values.get("label")
        if values.get("label") is None and values.get("name") is not None:
            values["label"] = values.get("name")
        if values.get("affected_scenarios") is None and values.get("scenario_impacts") is not None:
            values["affected_scenarios"] = values.get("scenario_impacts")
        if values.get("affected_themes") is None and values.get("theme_impacts") is not None:
            values["affected_themes"] = values.get("theme_impacts")
        if not values.get("scenario_impacts") and values.get("affected_scenarios"):
            values["scenario_impacts"] = values.get("affected_scenarios")
        if not values.get("theme_impacts") and values.get("affected_themes"):
            values["theme_impacts"] = values.get("affected_themes")
        role = values.get("role")
        if role is None:
            if values.get("display_only"):
                role = "display_only"
            elif values.get("child_signal_ids"):
                role = "composite"
            else:
                role = "raw_component"
            values["role"] = role
        if values.get("input_scope") is None:
            values["input_scope"] = role if role in {
                "layer_summary",
                "raw_component",
                "composite",
                "regime_driver",
                "scenario_falsifier",
                "theme_specific",
            } else "core_macro"
        if values.get("raw_value") is None:
            values["raw_value"] = values.get("current_value")
        if values.get("level_status") is None:
            values["level_status"] = values.get("signal")
        if values.get("trend_status") is None:
            values["trend_status"] = values.get("trend")
        if values.get("signal_strength") is None:
            impacts = values.get("affected_scenarios") or []
            strengths: list[float] = []
            for impact in impacts:
                if isinstance(impact, dict):
                    strength = impact.get("strength")
                else:
                    strength = getattr(impact, "strength", None)
                if strength is not None:
                    strengths.append(float(strength))
            values["signal_strength"] = max(strengths) if strengths else None
        if values.get("historical_feature_id") is None and values.get("historical_column") is not None:
            values["historical_feature_id"] = values.get("input_id")
        if values.get("historical_column") is None and values.get("historical_feature_id") is not None:
            values["historical_column"] = values.get("historical_feature_id")
        if values.get("historical_similarity_weight") is None and values.get("used_in_historical_similarity"):
            values["historical_similarity_weight"] = values.get("confidence", 1.0)
        return values


class ProbabilityContribution(BaseSchema):
    input_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    contribution: float
    rationale: str = Field(min_length=1, max_length=1000)


class ScenarioContribution(BaseSchema):
    input_id: str = Field(min_length=1, max_length=100)
    input_name: str = Field(min_length=1, max_length=200)
    scenario_id: str = Field(min_length=1, max_length=100)
    direction: Literal["positive", "negative"]
    scenario_impact_direction: Optional[ScenarioDirection] = None
    base_strength: float = Field(default=0.0, ge=0.0)
    input_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_multiplier: float = 1.0
    adjusted_strength: float = Field(default=0.0, ge=0.0)
    raw_contribution: float
    adjusted_contribution: float
    strength: UnitInterval
    confidence: UnitInterval
    rationale: str = Field(min_length=1, max_length=1000)
    used_in_probability_update: bool
    source_role: Optional[SignalRole] = None
    parent_layer: Optional[ParentLayer] = None
    dedupe_group: Optional[str] = Field(default=None, max_length=100)
    dedupe_role: Optional[DedupeRole] = None
    capped_by_dedupe: bool = False
    pre_dedupe_contribution: Optional[float] = None
    final_contribution: Optional[float] = None


class ScenarioMathAudit(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    prior_probability: UnitInterval
    prior_logit_or_log_score: Optional[float] = None
    base_score: float
    total_positive_contribution: float
    total_negative_contribution: float
    net_contribution: float
    raw_score_before_softmax: float
    exp_score: Optional[float] = None
    softmax_denominator: Optional[float] = None
    pre_floor_posterior_probability: UnitInterval
    floor_value: Optional[UnitInterval] = None
    floor_applied: bool = False
    cap_value: Optional[UnitInterval] = None
    cap_applied: bool = False
    final_posterior_probability: UnitInterval
    final_probability_change: float
    formula_notes: List[str] = Field(default_factory=list)
    contributions: List[ScenarioContribution] = Field(default_factory=list)


class ScenarioProbabilityUpdate(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    prior_probability: UnitInterval
    pre_floor_posterior_probability: Optional[UnitInterval] = None
    posterior_probability: UnitInterval
    probability_change: float
    raw_score: float
    floor_applied: bool = False
    floor_value: Optional[UnitInterval] = None
    cap_applied: bool = False
    cap_value: Optional[UnitInterval] = None
    top_positive_contributors: List[ProbabilityContribution] = Field(default_factory=list)
    top_negative_contributors: List[ProbabilityContribution] = Field(default_factory=list)
    contributions: List[ScenarioContribution] = Field(default_factory=list)
    total_positive_contribution: float = 0.0
    total_negative_contribution: float = 0.0
    net_contribution: float = 0.0
    math_audit: Optional[ScenarioMathAudit] = None
    warnings: List[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=2000)


class MacroRanking(BaseSchema):
    item_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    score: float
    rationale: str = Field(min_length=1, max_length=1000)


class RankingContribution(BaseSchema):
    source_id: str = Field(min_length=1, max_length=100)
    source_label: str = Field(min_length=1, max_length=200)
    weight: float
    source_score: float
    contribution: float
    rationale: Optional[str] = Field(default=None, max_length=1000)


class SectorForecast(BaseSchema):
    ticker: Optional[str] = Field(default=None, max_length=20)
    item_id: Optional[str] = Field(default=None, max_length=100)
    label: str = Field(default="", max_length=200)
    score: float = 0.0
    rationale: str = Field(default="", max_length=1000)
    contributions: List[RankingContribution] = Field(default_factory=list)
    formula_notes: List[str] = Field(default_factory=list)


class FactorForecast(BaseSchema):
    factor_id: Optional[str] = Field(default=None, max_length=100)
    item_id: Optional[str] = Field(default=None, max_length=100)
    label: str = Field(default="", max_length=200)
    score: float = 0.0
    rationale: str = Field(default="", max_length=1000)
    contributions: List[RankingContribution] = Field(default_factory=list)
    formula_notes: List[str] = Field(default_factory=list)


class ThemeScenarioContribution(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    scenario_label: str = Field(min_length=1, max_length=200)
    scenario_probability: UnitInterval
    theme_exposure_score: float
    contribution: float
    rationale: Optional[str] = Field(default=None, max_length=1000)


class ForecastInputSet(BaseSchema):
    asof_date: str = Field(min_length=10, max_length=10)
    layer_summary_signals: List[MacroInputSignal] = Field(default_factory=list)
    raw_component_signals: List[MacroInputSignal] = Field(default_factory=list)
    composite_signals: List[MacroInputSignal] = Field(default_factory=list)
    market_tape_signals: List[MacroInputSignal] = Field(default_factory=list)
    regime_driver_signals: List[MacroInputSignal] = Field(default_factory=list)
    scenario_falsifier_signals: List[MacroInputSignal] = Field(default_factory=list)
    theme_specific_signals: List[MacroInputSignal] = Field(default_factory=list)
    all_signals: List[MacroInputSignal] = Field(default_factory=list)
    methodology_notes: List[str] = Field(default_factory=list)
    raw_input_coverage: Dict[str, Any] = Field(default_factory=dict)


class ThemeForecast(BaseSchema):
    theme_id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    probability_weighted_score: float
    macro_score: float = 0.0
    macro_support_score: float = 0.0
    ranking_score: float = 0.0
    score_method: Literal["macro_support_only"] = "macro_support_only"
    crowding_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    valuation_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    narrative_score: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    overlay_adjustment: Optional[float] = None
    final_score: float = 0.0
    overlay_used_in_ranking: bool = False
    overlay_note: str = Field(
        default=(
            "Crowding, valuation, and narrative overlays are intentionally excluded from "
            "macro forecast theme rankings and are evaluated downstream at the theme/ticker "
            "research stage."
        ),
        max_length=1000,
    )
    adjustment_summary: Optional[str] = Field(default=None, max_length=1000)
    overlay_confidence: OverlayConfidence = "absent"
    scenario_contributions: List[ThemeScenarioContribution] = Field(default_factory=list)
    positive_contribution_total: float = 0.0
    negative_contribution_total: float = 0.0
    net_macro_support_score: float = 0.0
    best_scenarios: List[str] = Field(default_factory=list)
    worst_scenarios: List[str] = Field(default_factory=list)
    positive_scenario_count: int = Field(ge=0)
    negative_scenario_count: int = Field(ge=0)
    positioning_assessment: Literal["crowded", "neutral", "underowned", "unknown"]
    narrative_assessment: Literal[
        "crowded",
        "improving",
        "ignored",
        "deteriorating",
        "unknown",
    ]
    rationale: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def _fill_macro_support_aliases(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        support = values.get("macro_support_score")
        if support is None:
            support = values.get("macro_score", values.get("probability_weighted_score", 0.0))
            values["macro_support_score"] = support
        if values.get("ranking_score") is None:
            values["ranking_score"] = support
        if values.get("final_score") is None:
            values["final_score"] = support
        if values.get("net_macro_support_score") in (None, 0.0) and not values.get("scenario_contributions"):
            values["net_macro_support_score"] = support
        values.setdefault("score_method", "macro_support_only")
        values.setdefault("overlay_used_in_ranking", False)
        return values


class ResearchPriorityRecommendation(BaseSchema):
    theme: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=2000)
    edge_hypothesis: str = Field(min_length=30, max_length=2000)
    sub_questions: List[str] = Field(default_factory=list, max_length=10)
    priority_rank: int = Field(ge=1)
    expected_edge_decay: EdgeDecayHorizon
    supporting_evidence: List[Evidence] = Field(default_factory=list)
    source_theme_id: Optional[str] = Field(default=None, max_length=100)
    source_scenario_ids: List[str] = Field(default_factory=list, max_length=10)
    source_macro_forecast_id: Optional[str] = Field(default=None, max_length=100)


class ForecastInterpretation(BaseSchema):
    headline: str = Field(min_length=1, max_length=500)
    summary: str = Field(min_length=1, max_length=2000)
    dominant_scenario_id: str = Field(min_length=1, max_length=100)
    dominant_scenario_probability: UnitInterval
    regime_read: str = Field(min_length=1, max_length=1000)
    preferred_exposures: List[str] = Field(default_factory=list)
    exposures_to_avoid: List[str] = Field(default_factory=list)
    key_tensions: List[str] = Field(default_factory=list)
    confidence_level: Literal["low", "medium", "high"]
    confidence_rationale: str = Field(min_length=1, max_length=1000)


class ProbabilityShifter(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    would_increase_probability_if: List[str] = Field(default_factory=list)
    would_decrease_probability_if: List[str] = Field(default_factory=list)
    key_inputs_to_watch: List[str] = Field(default_factory=list)
    current_probability: UnitInterval
    floor_or_cap_note: Optional[str] = Field(default=None, max_length=500)


class AnalogueForwardStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    horizon: str
    n: int = 0
    weight_sum: Optional[float] = None
    median: Optional[float] = None
    mean: Optional[float] = None
    pct_positive: Optional[float] = None
    p10: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None
    worst: Optional[float] = None
    best: Optional[float] = None


TACTICAL_ANALOGUE_HORIZONS = ["1d", "5d", "10d"]
MACRO_ANALOGUE_HORIZONS = ["21d", "63d", "126d", "252d"]
ANALOGUE_HORIZONS = TACTICAL_ANALOGUE_HORIZONS + MACRO_ANALOGUE_HORIZONS
ScenarioMappingHorizon = Literal["21d", "63d", "126d", "252d"]
ShockWindowMode = Literal["exclude", "downweight", "tag_only"]


class HistoricalShockWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=100)
    start_date: str = Field(min_length=10, max_length=10)
    end_date: str = Field(min_length=10, max_length=10)
    default_action: Literal["exclude_forward_window_overlap", "tag_or_downweight"] = "exclude_forward_window_overlap"


class HistoricalAnalogueMatch(BaseSchema):
    date: str = Field(min_length=1, max_length=20)
    composite_weight: Optional[float] = None
    similarity_score: Optional[float] = None
    score_total: Optional[float] = None
    environment: Optional[str] = Field(default=None, max_length=200)
    vix_level: Optional[float] = None
    sectors_green: Optional[int] = None
    score_delta: Optional[float] = None
    forward_returns: Dict[str, Optional[float]] = Field(default_factory=dict)
    risk_profile: Dict[str, Optional[float]] = Field(default_factory=dict)
    score_components: Dict[str, Optional[float]] = Field(default_factory=dict)
    sector_returns: Dict[str, Optional[float]] = Field(default_factory=dict)
    mapped_scenario_id: Optional[str] = Field(default=None, max_length=100)
    mapped_scenario_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mapping_rationale: Optional[str] = Field(default=None, max_length=1000)
    mapping_tag: Optional[str] = Field(default=None, max_length=100)
    mapping_rationale_short: Optional[str] = Field(default=None, max_length=200)
    mapping_rationale_full: Optional[str] = Field(default=None, max_length=1000)
    v1_similarity: Optional[float] = None
    detailed_similarity: Optional[float] = None
    blended_similarity: Optional[float] = None
    strongest_matching_groups: List[str] = Field(default_factory=list)
    weakest_matching_groups: List[str] = Field(default_factory=list)
    feature_coverage: Dict[str, Any] = Field(default_factory=dict)
    shock_window_overlap_horizons: List[str] = Field(default_factory=list)
    excluded_from_scenario_mapping: bool = False

    @model_validator(mode="before")
    @classmethod
    def _fill_mapping_rationale_compatibility(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        rationale = values.get("mapping_rationale")
        full = values.get("mapping_rationale_full")
        if full is None and rationale is not None:
            values["mapping_rationale_full"] = rationale
        if rationale is None and full is not None:
            values["mapping_rationale"] = full
        if values.get("mapping_rationale_short") is None:
            tag = values.get("mapping_tag")
            scenario = values.get("mapped_scenario_id")
            text = str(full or rationale or "").lower()
            if tag == "positive_broad" or "broad participation" in text:
                values["mapping_rationale_short"] = "Positive + broad"
            elif tag == "positive_narrow" or "breadth is narrow" in text:
                values["mapping_rationale_short"] = "Positive + narrow"
            elif tag == "stress_drawdown" or "drawdown" in text:
                values["mapping_rationale_short"] = "Stress drawdown"
            elif tag == "energy_leadership" or "energy" in text or "oil" in text:
                values["mapping_rationale_short"] = "Energy leadership"
            elif tag == "ai_proxy_weak" or "technology" in text or "semis" in text:
                values["mapping_rationale_short"] = "AI proxy weak"
            elif tag == "fallback_positive" or ("fallback" in text and "positive" in text):
                values["mapping_rationale_short"] = "Fallback positive"
            elif tag == "fallback_negative" or ("fallback" in text and "negative" in text):
                values["mapping_rationale_short"] = "Fallback negative"
            elif tag == "negative_forward" or scenario == "late_cycle_risk_off":
                values["mapping_rationale_short"] = "Risk-off return"
            else:
                values["mapping_rationale_short"] = "Low confidence"
        return values


class HistoricalScenarioCalibration(BaseSchema):
    scenario_id: str = Field(min_length=1, max_length=100)
    deterministic_probability: UnitInterval
    historical_probability: UnitInterval
    blended_probability: UnitInterval
    analog_effect: float
    n_supporting_analogues: int = Field(ge=0)
    weighted_support: Optional[float] = None
    confidence: UnitInterval
    rationale: str = Field(min_length=1, max_length=1500)


class HistoricalCalibrationConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    method: Literal["rolling_composite", "single_date", "conditional_stats", "hybrid"] = "rolling_composite"
    deterministic_weight: float = Field(default=0.70, ge=0.0, le=1.0)
    historical_weight: float = Field(default=0.30, ge=0.0, le=1.0)
    lookback_days: int = Field(default=30, ge=1)
    half_life: int = Field(default=30, ge=1)
    top_n_per_lookup: int = Field(default=15, ge=1)
    pool_top_n: int = Field(default=50, ge=1)
    current_state_lookup_weight: float = Field(default=1.0, ge=1.0)
    exclude_recent_days: int = Field(default=60, ge=0)
    min_analogue_count: int = Field(default=20, ge=1)
    fallback_to_display_only: bool = True
    historical_probability_floor: float = Field(default=0.02, ge=0.0, le=0.20)
    macro_horizons: List[str] = Field(default_factory=lambda: list(MACRO_ANALOGUE_HORIZONS))
    scenario_mapping_horizon: ScenarioMappingHorizon = "63d"
    use_detailed_analogues: bool = False
    detailed_similarity_mode: Literal["rerank", "blend", "replace"] = "blend"
    v1_similarity_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    v2_similarity_weight: float = Field(default=0.60, ge=0.0, le=1.0)
    candidate_pool_n: int = Field(default=300, ge=1)
    min_feature_coverage: float = Field(default=0.40, ge=0.0, le=1.0)
    min_effective_sample_size: int = Field(default=20, ge=1)
    reduce_weight_on_low_ess: bool = True
    min_historical_weight_after_penalty: float = Field(default=0.10, ge=0.0, le=1.0)
    exclude_shock_windows: bool = True
    shock_window_mode: ShockWindowMode = "exclude"
    shock_windows: List[HistoricalShockWindow] = Field(
        default_factory=lambda: [
            HistoricalShockWindow(
                name="covid_crash",
                start_date="2020-02-19",
                end_date="2020-04-30",
                default_action="exclude_forward_window_overlap",
            )
        ]
    )

    @model_validator(mode="after")
    def _validate_macro_horizons(self):
        invalid = [horizon for horizon in self.macro_horizons if horizon not in MACRO_ANALOGUE_HORIZONS]
        if invalid:
            raise ValueError(
                f"macro_horizons contains unsupported horizon(s): {invalid}; "
                f"expected subset of {MACRO_ANALOGUE_HORIZONS}"
            )
        return self


class HistoricalCalibrationResult(BaseSchema):
    enabled: bool
    method: str = Field(min_length=1, max_length=100)
    asof_date: str = Field(min_length=10, max_length=10)
    conditions_summary: Optional[str] = Field(default=None, max_length=2000)
    n_analogues: int = Field(ge=0)
    n_unique_analogues: Optional[int] = Field(default=None, ge=0)
    n_pooled: Optional[int] = Field(default=None, ge=0)
    forward_return_stats: Dict[str, AnalogueForwardStats] = Field(default_factory=dict)
    tactical_forward_return_stats: Dict[str, AnalogueForwardStats] = Field(default_factory=dict)
    macro_forward_return_stats: Dict[str, AnalogueForwardStats] = Field(default_factory=dict)
    available_horizons: List[str] = Field(default_factory=list)
    missing_horizons: List[str] = Field(default_factory=list)
    horizon_sample_sizes: Dict[str, int] = Field(default_factory=dict)
    analogue_version: str = "v1_broad_state"
    detailed_analogue_diagnostics: Dict[str, Any] = Field(default_factory=dict)
    shock_window_diagnostics: Dict[str, Any] = Field(default_factory=dict)
    risk_profile: Dict[str, Any] = Field(default_factory=dict)
    environment_distribution: Dict[str, float] = Field(default_factory=dict)
    top_analogues: List[HistoricalAnalogueMatch] = Field(default_factory=list)
    scenario_calibrations: List[HistoricalScenarioCalibration] = Field(default_factory=list)
    blended_scenario_probabilities: Dict[str, UnitInterval] = Field(default_factory=dict)
    confidence: UnitInterval
    warnings: List[str] = Field(default_factory=list)
    methodology_notes: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _fill_forward_stat_compatibility(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        forward = dict(values.get("forward_return_stats") or {})
        tactical = dict(values.get("tactical_forward_return_stats") or {})
        macro = dict(values.get("macro_forward_return_stats") or {})

        def with_horizon_labels(mapping: Dict[str, Any]) -> Dict[str, Any]:
            labelled: Dict[str, Any] = {}
            for horizon, stats in mapping.items():
                if isinstance(stats, dict) and stats.get("horizon") is None:
                    item = dict(stats)
                    item["horizon"] = str(horizon)
                    labelled[str(horizon)] = item
                else:
                    labelled[str(horizon)] = stats
            return labelled

        forward = with_horizon_labels(forward)
        tactical = with_horizon_labels(tactical)
        macro = with_horizon_labels(macro)
        if forward:
            values["forward_return_stats"] = forward
        if tactical:
            values["tactical_forward_return_stats"] = tactical
        if macro:
            values["macro_forward_return_stats"] = macro

        if not tactical and forward:
            tactical = {
                horizon: forward[horizon]
                for horizon in TACTICAL_ANALOGUE_HORIZONS
                if horizon in forward
            }
            values["tactical_forward_return_stats"] = tactical
        if not macro and forward:
            macro = {
                horizon: forward[horizon]
                for horizon in MACRO_ANALOGUE_HORIZONS
                if horizon in forward
            }
            values["macro_forward_return_stats"] = macro
        if not forward and (tactical or macro):
            forward = {**tactical, **macro}
            values["forward_return_stats"] = forward

        if not values.get("horizon_sample_sizes"):
            sample_sizes: Dict[str, int] = {}
            for horizon, stats in forward.items():
                if isinstance(stats, dict):
                    sample_sizes[str(horizon)] = int(stats.get("n") or 0)
                else:
                    sample_sizes[str(horizon)] = int(getattr(stats, "n", 0) or 0)
            values["horizon_sample_sizes"] = sample_sizes

        if not values.get("available_horizons") and forward:
            values["available_horizons"] = list(forward)
        values.setdefault("missing_horizons", [])
        return values


class MacroForecastResult(BaseSchema):
    asof_date: str = Field(min_length=10, max_length=10)
    horizon: str = Field(min_length=1, max_length=20)
    input_signals: List[MacroInputSignal] = Field(default_factory=list)
    forecast_input_set: Optional[ForecastInputSet] = None
    scenario_updates: List[ScenarioProbabilityUpdate] = Field(default_factory=list)
    scenario_probabilities: Dict[str, UnitInterval] = Field(default_factory=dict)
    sector_rankings: List[SectorForecast] = Field(default_factory=list)
    factor_rankings: List[FactorForecast] = Field(default_factory=list)
    theme_rankings: List[ThemeForecast] = Field(default_factory=list)
    recommended_research_priorities: List[ResearchPriorityRecommendation] = Field(default_factory=list)
    forecast_interpretation: Optional[ForecastInterpretation] = None
    probability_shifters: List[ProbabilityShifter] = Field(default_factory=list)
    historical_calibration: Optional[HistoricalCalibrationResult] = None
    scenario_probabilities_deterministic: Optional[Dict[str, UnitInterval]] = None
    scenario_probabilities_blended: Optional[Dict[str, UnitInterval]] = None
    probability_mode: Literal[
        "deterministic",
        "historically_calibrated",
        "yaml_priors_override",
        "two_source_v1",
    ] = "deterministic"
    mixture_report: Dict[str, Any] = Field(default_factory=dict)
    bvar_provenance: Dict[str, Any] = Field(default_factory=dict)
    outputs: Dict[str, str] = Field(default_factory=dict)
