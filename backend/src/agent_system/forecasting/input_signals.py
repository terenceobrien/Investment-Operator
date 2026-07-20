"""Convert RegimeState into deterministic macro forecast input signals."""
from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Iterable

from src.agent_system.schemas.common import FalsifierStatus
from src.agent_system.schemas.macro_forecast import (
    DeterministicInputConfig,
    ForecastInputSet,
    InputDedupeConfig,
    LevelAssessment,
    MacroInputSignal,
    ScenarioImpact,
    SignalDirection,
    SignalTrend,
    ThemeImpact,
)
from src.agent_system.schemas.regime import RegimeLayerScore, RegimeState
from src.state.regime_data import RegimeInputs


def _scenario(
    scenario_id: str,
    direction: str,
    strength: float,
    rationale: str,
) -> ScenarioImpact:
    return ScenarioImpact(
        scenario_id=scenario_id,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,
        rationale=rationale,
    )


def _theme(
    theme_id: str,
    direction: str,
    strength: float,
    rationale: str,
) -> ThemeImpact:
    return ThemeImpact(
        theme_id=theme_id,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,
        rationale=rationale,
    )


def _layer_confidence(layer: RegimeLayerScore) -> float:
    return max(0.1, min(1.0, float(layer.data_quality)))


def _quality(layer: RegimeLayerScore) -> str:
    if layer.data_quality >= 0.8:
        return "high"
    if layer.data_quality >= 0.5:
        return "medium"
    if layer.data_quality > 0:
        return "low"
    return "absent"


def _joined_signals(layer: RegimeLayerScore) -> str:
    return "; ".join(layer.signals) if layer.signals else ""


def _last_updated(regime_state: RegimeState) -> datetime | None:
    return getattr(regime_state, "created_at", None)


def _clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


RAW_INPUT_FIELD_MAP: dict[str, list[str]] = {
    "net_liquidity": ["net_liquidity"],
    "net_liquidity_z": ["net_liquidity_z"],
    "nfci": ["nfci"],
    "nfci_inverted": ["nfci_inverted"],
    "m2_growth_yoy": ["m2_growth_yoy"],
    "fci_z": ["fci_z"],
    "hy_spread_level": ["hy_spread_level", "hy_spread", "hy_oas"],
    "hy_spread_z": ["hy_spread_z"],
    "hy_spread_chg_4w": ["hy_spread_chg_4w", "hy_spread_change_4w"],
    "ig_spread_level": ["ig_spread_level", "ig_spread", "ig_oas"],
    "ig_spread_z": ["ig_spread_z"],
    "hyg_tlt_ratio_z": ["hyg_tlt_ratio_z", "hyg_minus_tlt"],
    "vix_level": ["vix_level", "vix"],
    "vix_z_20d": ["vix_z_20d"],
    "vix_term_slope": ["vix_term_slope"],
    "vvix_level": ["vvix_level", "vvix"],
    "vvix_z": ["vvix_z"],
    "put_call_ratio": ["put_call_ratio", "put_call_5d_ma"],
    "skew_index": ["skew_index", "skew"],
    "pct_above_200d": ["pct_above_200d", "percent_above_200d"],
    "new_highs_minus_lows_z": ["new_highs_minus_lows_z", "nh_nl_z"],
    "sectors_green": ["sectors_green"],
    "rsp_vs_spy_z": ["rsp_vs_spy_z", "rsp_minus_spy"],
    "adl_slope": ["adl_slope"],
    "dealer_gamma_z": ["dealer_gamma_z"],
    "put_call_5d_ma": ["put_call_5d_ma", "put_call_ratio"],
    "aaii_bull_minus_bear": ["aaii_bull_minus_bear"],
    "cot_net_large_spec_z": ["cot_net_large_spec_z"],
    "equity_etf_flow_z": ["equity_etf_flow_z"],
}

EXPECTED_RAW_INPUTS_BY_GROUP: dict[str, list[str]] = {
    "monetary_liquidity": ["net_liquidity", "net_liquidity_z", "nfci", "nfci_inverted", "m2_growth_yoy", "fci_z"],
    "credit": ["hy_spread_level", "hy_spread_z", "hy_spread_chg_4w", "ig_spread_level", "ig_spread_z", "hyg_tlt_ratio_z"],
    "volatility": ["vix_level", "vix_z_20d", "vix_term_slope", "vvix_level", "vvix_z", "put_call_ratio", "skew_index"],
    "breadth_market_structure": ["pct_above_200d", "new_highs_minus_lows_z", "sectors_green", "rsp_vs_spy_z", "adl_slope"],
    "positioning": ["dealer_gamma_z", "put_call_5d_ma", "aaii_bull_minus_bear", "cot_net_large_spec_z", "equity_etf_flow_z"],
    "market_tape": [
        "spy_clv",
        "spy_range_pct",
        "spy_vol_z_20d",
        "volume_confirmation",
        "spy_above_vwap",
        "spy_above_prev_close",
        "sector_dispersion",
        "sectors_green",
        "leadership_top3",
        "rsp_minus_spy",
        "iwm_minus_spy",
        "hyg_minus_tlt",
        "qqq_minus_spy",
    ],
}

REGIME_STATE_FALLBACK_FIELDS = {
    "vix_level",
    "vix_term_slope",
    "hy_spread_level",
    "net_liquidity_z",
    "pct_above_200d",
    "new_highs_minus_lows_z",
    "sectors_green",
}


def get_input_value(obj: Any, *names: str) -> Any | None:
    if obj is None:
        return None
    for name in names:
        value = None
        if isinstance(obj, dict):
            value = obj.get(name)
        elif hasattr(obj, name):
            value = getattr(obj, name)
        if _safe_float(value) is not None:
            return value
    return None


def _flatten_regime_state_inputs(regime_state: RegimeState | None) -> dict[str, Any]:
    if regime_state is None:
        return {}
    values: dict[str, Any] = {}
    layers = getattr(regime_state, "layers", None)
    if layers is None:
        return values
    for layer_name in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        layer = getattr(layers, layer_name, None)
        if layer is not None:
            values.update(getattr(layer, "inputs", {}) or {})
    return values


def _market_state_feature_values(market_state: Any | None) -> dict[str, Any]:
    if market_state is None:
        return {}
    values: dict[str, Any] = {}
    for field in [
        "spy_clv",
        "spy_range_pct",
        "spy_vol_z_20d",
        "volume_confirmation",
        "spy_above_vwap",
        "spy_above_prev_close",
        "sectors_green",
        "dispersion",
        "sector_dispersion",
        "vix_level",
        "vix_z_20d",
        "vix_change_pct_1d",
        "rsp_minus_spy",
    ]:
        if hasattr(market_state, field):
            values[field] = getattr(market_state, field)
    cross = getattr(market_state, "cross_asset_returns", {}) or {}
    def diff(left: str, right: str) -> float | None:
        left_value = _safe_float(cross.get(left))
        right_value = _safe_float(cross.get(right))
        if left_value is None or right_value is None:
            return None
        return left_value - right_value
    values["rsp_minus_spy"] = values.get("rsp_minus_spy") if _safe_float(values.get("rsp_minus_spy")) is not None else diff("RSP", "SPY")
    values["iwm_minus_spy"] = diff("IWM", "SPY")
    values["hyg_minus_tlt"] = diff("HYG", "TLT")
    values["qqq_minus_spy"] = diff("QQQ", "SPY")
    return values


def _resolve_raw_input_value(
    canonical_field: str,
    regime_inputs: RegimeInputs | None,
    regime_state_values: dict[str, Any],
    market_state_values: dict[str, Any],
    extra_features: dict[str, Any] | None = None,
) -> tuple[float | None, str | None]:
    names = RAW_INPUT_FIELD_MAP.get(canonical_field, [canonical_field])
    value = get_input_value(regime_inputs, *names)
    if value is not None:
        return _safe_float(value), "RegimeInputs"
    if canonical_field in REGIME_STATE_FALLBACK_FIELDS:
        value = get_input_value(regime_state_values, *names)
        if value is not None:
            return _safe_float(value), "RegimeState"
    value = get_input_value(market_state_values, *names)
    if value is not None:
        return _safe_float(value), "MarketState"
    value = get_input_value(extra_features or {}, *names)
    if value is not None:
        return _safe_float(value), "extra_features"
    return None, None


def _historical_group_for_layer(parent_layer: str | None) -> str | None:
    mapping = {
        "monetary": "monetary_liquidity",
        "credit": "credit",
        "volatility": "volatility",
        "breadth": "breadth_market_structure",
        "positioning": "positioning",
        "market_state": "path_momentum",
        "rates_fx": "rates_fx",
        "commodities": "commodities_oil",
        "earnings": "theme_catalysts",
        "geopolitical": "theme_catalysts",
    }
    return mapping.get(parent_layer or "")


def _historical_layer_column(parent_layer: str | None) -> str | None:
    if parent_layer in {"monetary", "credit", "volatility", "breadth", "positioning"}:
        return f"layer_{parent_layer}"
    return None


def _related_scenarios(impacts: list[ScenarioImpact]) -> list[str]:
    return sorted({impact.scenario_id for impact in impacts})


def _related_themes(impacts: list[ThemeImpact]) -> list[str]:
    return sorted({impact.theme_id for impact in impacts})


def _tag_signal(
    signal: MacroInputSignal,
    *,
    input_scope: str,
    parent_layer: str | None,
    role: str,
    is_persistent_input: bool = True,
    dedupe_group: str | None = None,
    dedupe_role: str | None = None,
    dedupe_weight: float | None = None,
    raw_value: float | str | bool | None = None,
    transformed_value: float | None = None,
    transformation_method: str | None = None,
    source_object: str | None = None,
    active_only_in_regime_ids: list[str] | None = None,
) -> MacroInputSignal:
    historical_column = _historical_layer_column(parent_layer) if role == "layer_summary" else None
    used_in_historical_similarity = historical_column is not None
    return signal.model_copy_validate(
        {
            "input_scope": input_scope,
            "parent_layer": parent_layer,
            "role": role,
            "is_persistent_input": is_persistent_input,
            "active_only_in_regime_ids": active_only_in_regime_ids or [],
            "related_scenario_ids": _related_scenarios(signal.affected_scenarios),
            "related_theme_ids": _related_themes(signal.affected_themes),
            "raw_value": signal.current_value if raw_value is None else raw_value,
            "transformed_value": transformed_value,
            "transformation_method": transformation_method,
            "source_object": source_object or "RegimeState",
            "level_status": signal.signal,
            "trend_status": signal.trend,
            "signal_strength": max((impact.strength for impact in signal.affected_scenarios), default=None),
            "dedupe_group": dedupe_group or parent_layer,
            "dedupe_role": dedupe_role,
            "dedupe_weight": dedupe_weight,
            "used_in_historical_similarity": used_in_historical_similarity,
            "historical_feature_id": signal.input_id if used_in_historical_similarity else None,
            "historical_column": historical_column,
            "historical_similarity_group": _historical_group_for_layer(parent_layer),
            "historical_similarity_weight": signal.confidence if used_in_historical_similarity else None,
        }
    )


def _normalize_trend(trend: str | None) -> SignalTrend:
    if trend in {"improving", "deteriorating", "stable", "mixed", "unknown"}:
        return trend  # type: ignore[return-value]
    return "unknown"


def assess_layer_signal(score: float, trend: str | None, layer_name: str) -> LevelAssessment:
    """Separate absolute layer level from trend before assigning signal direction."""

    normalized_trend = _normalize_trend(trend)
    if score >= 7.0:
        absolute_status = "bullish"
    elif score >= 4.5:
        absolute_status = "neutral"
    else:
        absolute_status = "bearish"

    layer = layer_name.strip() or "Layer"
    if normalized_trend == "unknown":
        return LevelAssessment(
            absolute_status=absolute_status,  # type: ignore[arg-type]
            trend_status=normalized_trend,
            combined_signal=absolute_status,  # type: ignore[arg-type]
            confidence_adjustment=0.65,
            explanation=(
                f"{layer} has a {absolute_status} absolute score but missing trend data, "
                "so confidence is reduced."
            ),
        )

    if absolute_status == "bullish":
        if normalized_trend == "deteriorating":
            combined = "mixed"
            adjustment = 0.75
            explanation = (
                f"{layer} has a strong absolute score but is deteriorating, "
                "so the signal is mixed rather than outright bullish."
            )
        else:
            combined = "bullish"
            adjustment = 0.95 if normalized_trend == "mixed" else 1.0
            explanation = f"{layer} has a strong absolute score and no adverse trend conflict."
    elif absolute_status == "neutral":
        if normalized_trend == "stable":
            combined = "neutral"
            adjustment = 0.85
            explanation = f"{layer} is neutral on both absolute level and trend."
        else:
            combined = "mixed"
            adjustment = 0.75
            explanation = (
                f"{layer} has a neutral absolute score with a {normalized_trend} trend, "
                "so signal strength is moderated."
            )
    else:
        if normalized_trend == "improving":
            combined = "mixed"
            adjustment = 0.60
            explanation = (
                f"{layer} is improving from a weak absolute level, so signal is mixed "
                "rather than outright bullish."
            )
        elif normalized_trend in {"stable", "deteriorating"}:
            combined = "bearish"
            adjustment = 0.90 if normalized_trend == "deteriorating" else 0.80
            explanation = f"{layer} remains weak on an absolute basis."
        else:
            combined = "mixed"
            adjustment = 0.65
            explanation = f"{layer} is weak on level with a mixed trend."

    return LevelAssessment(
        absolute_status=absolute_status,  # type: ignore[arg-type]
        trend_status=normalized_trend,
        combined_signal=combined,  # type: ignore[arg-type]
        confidence_adjustment=adjustment,
        explanation=explanation,
    )


def _adjust_scenario_impacts(
    impacts: list[ScenarioImpact],
    assessment: LevelAssessment,
) -> list[ScenarioImpact]:
    factor = 0.5 if assessment.combined_signal == "mixed" else 1.0
    if assessment.combined_signal == "neutral":
        factor = 0.35
    adjusted: list[ScenarioImpact] = []
    for impact in impacts:
        strength = impact.strength * factor
        if (
            assessment.absolute_status == "bearish"
            and assessment.trend_status == "improving"
            and impact.direction == "increases"
        ):
            strength = min(strength, 0.25)
        adjusted.append(
            ScenarioImpact(
                scenario_id=impact.scenario_id,
                direction=impact.direction,
                strength=_clamp_unit(strength),
                rationale=impact.rationale,
            )
        )
    return adjusted


def _adjust_theme_impacts(
    impacts: list[ThemeImpact],
    assessment: LevelAssessment,
) -> list[ThemeImpact]:
    factor = 0.5 if assessment.combined_signal == "mixed" else 1.0
    if assessment.combined_signal == "neutral":
        factor = 0.35
    adjusted: list[ThemeImpact] = []
    for impact in impacts:
        strength = impact.strength * factor
        if (
            assessment.absolute_status == "bearish"
            and assessment.trend_status == "improving"
            and impact.direction == "positive"
        ):
            strength = min(strength, 0.25)
        adjusted.append(
            ThemeImpact(
                theme_id=impact.theme_id,
                direction=impact.direction,
                strength=_clamp_unit(strength),
                rationale=impact.rationale,
            )
        )
    return adjusted


def _credit_signal(regime_state: RegimeState) -> MacroInputSignal:
    layer = regime_state.layers.credit
    healthy = layer.score >= 6.0 or layer.status.value == "bullish"
    if healthy:
        scenario_impacts = [
            _scenario("late_cycle_risk_off", "decreases", 0.70, "Healthy credit reduces near-term risk-off odds."),
            _scenario("reopening_soft_landing", "increases", 0.40, "Tight credit supports soft-landing broadening."),
            _scenario("sticky_late_cycle_ai", "increases", 0.25, "Contained spreads allow narrow leadership to persist."),
        ]
        theme_impacts = [
            _theme("quality_ai", "positive", 0.35, "Healthy credit supports profitable growth leadership."),
            _theme("cash_short_duration", "neutral", 0.10, "Credit health modestly reduces urgency for cash."),
            _theme("small_caps", "positive", 0.20, "Tight spreads are a prerequisite for broader risk appetite."),
        ]
        signal = "bullish"
        trend = "stable"
    else:
        scenario_impacts = [
            _scenario("late_cycle_risk_off", "increases", 0.70, "Deteriorating credit increases drawdown risk."),
            _scenario("reopening_soft_landing", "decreases", 0.45, "Credit stress undermines soft landing odds."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.25, "Wider spreads make narrow equity leadership harder to sustain."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.55, "Credit stress favors liquidity."),
            _theme("healthcare_defensives", "positive", 0.35, "Defensives benefit if credit stress rises."),
            _theme("small_caps", "negative", 0.45, "Small caps are vulnerable to tighter credit."),
        ]
        signal = "bearish"
        trend = "deteriorating"

    return MacroInputSignal(
        input_id="credit_conditions",
        name="Credit layer health",
        category="credit",
        current_value=layer.score,
        unit="0-10 layer score",
        percentile=None,
        z_score=layer.inputs.get("hy_spread_z") or layer.inputs.get("ig_spread_z"),
        trend=trend,  # type: ignore[arg-type]
        signal=signal,  # type: ignore[arg-type]
        confidence=_layer_confidence(layer),
        data_quality=_quality(layer),  # type: ignore[arg-type]
        last_updated=_last_updated(regime_state),
        affected_scenarios=scenario_impacts,
        affected_themes=theme_impacts,
        notes=_joined_signals(layer) or "Credit layer converted from RegimeState.",
    )


def _breadth_signal(regime_state: RegimeState) -> MacroInputSignal:
    layer = regime_state.layers.breadth
    weak_text = any(
        "lagging" in item.lower() or "narrow" in item.lower()
        for item in layer.signals
    )
    if weak_text or layer.status.value == "bearish":
        trend: SignalTrend = "deteriorating"
    elif layer.score < 4.5:
        trend = "improving"
    elif layer.score >= 5.5:
        trend = "improving"
    else:
        trend = "stable"

    assessment = assess_layer_signal(layer.score, trend, "Breadth")
    if assessment.combined_signal == "bearish":
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.60, "Weak breadth favors narrow leadership persistence."),
            _scenario("late_cycle_risk_off", "increases", 0.45, "Weak breadth raises fragility risk."),
            _scenario("reopening_soft_landing", "decreases", 0.55, "Soft landing broadening needs participation."),
        ]
        theme_impacts = [
            _theme("quality_ai", "positive", 0.45, "Narrow markets reward established leaders."),
            _theme("high_beta_ai_semis", "negative", 0.25, "Narrow breadth raises unwind risk in crowded beta."),
            _theme("small_caps", "negative", 0.60, "Weak breadth directly penalizes small caps."),
        ]
    else:
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.55, "Improving breadth supports broadening."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.35, "Broader participation reduces narrow-AI dependence."),
            _scenario("late_cycle_risk_off", "decreases", 0.30, "Breadth improvement lowers fragility risk."),
        ]
        theme_impacts = [
            _theme("small_caps", "positive", 0.50, "Breadth improvement supports smaller-cap participation."),
            _theme("long_duration_growth", "positive", 0.25, "Broadening helps duration-sensitive growth."),
        ]

    return MacroInputSignal(
        input_id="market_breadth",
        name="Breadth and participation",
        category="breadth",
        current_value=layer.score,
        unit="0-10 layer score",
        percentile=None,
        z_score=layer.inputs.get("rsp_vs_spy_z"),
        trend=assessment.trend_status,
        signal=assessment.combined_signal,
        confidence=_clamp_unit(_layer_confidence(layer) * assessment.confidence_adjustment),
        data_quality=_quality(layer),  # type: ignore[arg-type]
        last_updated=_last_updated(regime_state),
        affected_scenarios=_adjust_scenario_impacts(scenario_impacts, assessment),
        affected_themes=_adjust_theme_impacts(theme_impacts, assessment),
        notes=(
            f"{_joined_signals(layer) or 'Breadth layer converted from RegimeState.'} "
            f"{assessment.explanation}"
        ),
    )


def _volatility_signal(regime_state: RegimeState) -> MacroInputSignal:
    layer = regime_state.layers.volatility
    assessment = assess_layer_signal(layer.score, "stable", "Volatility")
    stressed = layer.status.value == "bearish" or layer.score < 4.5
    very_calm = bool(layer.inputs.get("vix_level") is not None and layer.inputs["vix_level"] < 15)
    if stressed:
        scenario_impacts = [
            _scenario("late_cycle_risk_off", "increases", 0.55, "Stressed volatility structure raises risk-off odds."),
            _scenario("reopening_soft_landing", "decreases", 0.35, "Volatility stress undermines soft-landing broadening."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.15, "Volatility stress can interrupt narrow leadership."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.45, "Volatility stress favors liquidity."),
            _theme("healthcare_defensives", "positive", 0.25, "Defensives benefit from volatility stress."),
            _theme("high_beta_ai_semis", "negative", 0.35, "High-beta growth is vulnerable to volatility stress."),
            _theme("small_caps", "negative", 0.30, "Small caps are vulnerable to volatility stress."),
        ]
        signal: SignalDirection = "bearish"
        trend: SignalTrend = "deteriorating"
    elif very_calm:
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.15, "Suppressed volatility can support trend continuation."),
            _scenario("late_cycle_risk_off", "increases", 0.10, "Very low VIX can signal complacency fragility."),
            _scenario("reopening_soft_landing", "increases", 0.10, "Calm volatility modestly supports broadening."),
        ]
        theme_impacts = [
            _theme("quality_ai", "positive", 0.10, "Calm volatility supports liquid leadership."),
            _theme("cash_short_duration", "negative", 0.10, "Calm volatility reduces urgency for liquidity."),
        ]
        signal = "mixed"
        trend = "stable"
    else:
        scenario_impacts = [
            _scenario("late_cycle_risk_off", "decreases", 0.30, "Orderly volatility structure reduces risk-off odds."),
            _scenario("reopening_soft_landing", "increases", 0.20, "Orderly volatility supports soft-landing broadening."),
            _scenario("sticky_late_cycle_ai", "increases", 0.10, "Calm volatility allows leadership trends to persist."),
        ]
        theme_impacts = [
            _theme("quality_ai", "positive", 0.15, "Orderly volatility supports quality leadership."),
            _theme("small_caps", "positive", 0.10, "Orderly volatility modestly supports broader risk."),
            _theme("cash_short_duration", "negative", 0.10, "Calm volatility reduces need for cash."),
        ]
        signal = "bullish" if layer.score >= 6.5 else "neutral"
        trend = "stable"

    return MacroInputSignal(
        input_id="volatility_layer_summary",
        name="Volatility layer summary",
        category="volatility",
        current_value=layer.score,
        unit="0-10 layer score",
        percentile=None,
        z_score=layer.inputs.get("vix_z_20d") or layer.inputs.get("vvix_z"),
        trend=trend,
        signal=signal,
        confidence=_clamp_unit(_layer_confidence(layer) * assessment.confidence_adjustment),
        data_quality=_quality(layer),  # type: ignore[arg-type]
        last_updated=_last_updated(regime_state),
        affected_scenarios=scenario_impacts,
        affected_themes=theme_impacts,
        notes=_joined_signals(layer) or "Volatility layer converted from RegimeState.",
    )


def _monetary_layer_signal(regime_state: RegimeState) -> MacroInputSignal:
    layer = regime_state.layers.monetary
    if layer.status.value == "bearish" or layer.score < 4.5:
        trend: SignalTrend = "stable"
    elif layer.score >= 5.0:
        trend = "improving"
    else:
        trend = "stable"

    assessment = assess_layer_signal(layer.score, trend, "Monetary layer")
    restrictive = assessment.absolute_status == "bearish"
    if restrictive:
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.35, "Restrictive policy favors quality and narrow leadership."),
            _scenario("oil_inflation_tail", "increases", 0.30, "Restrictive policy often reflects inflation pressure."),
            _scenario("reopening_soft_landing", "decreases", 0.35, "Restrictive policy limits broadening."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.55, "Higher front-end rates keep cash attractive."),
            _theme("long_duration_growth", "negative", 0.45, "Restrictive rates pressure long-duration assets."),
            _theme("quality_ex_ai_cash_flow", "positive", 0.30, "Cash-flow quality matters when rates stay restrictive."),
        ]
    else:
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.35, "Easier monetary conditions support broadening."),
            _scenario("late_cycle_risk_off", "decreases", 0.25, "Less restrictive policy lowers break risk."),
        ]
        theme_impacts = [
            _theme("small_caps", "positive", 0.25, "Less restrictive policy supports broader risk."),
            _theme("long_duration_growth", "positive", 0.30, "Lower rates support duration."),
        ]

    return MacroInputSignal(
        input_id="monetary_conditions",
        name="Monetary layer",
        category="monetary",
        current_value=layer.score,
        unit="0-10 layer score",
        percentile=None,
        z_score=layer.inputs.get("net_liquidity_z"),
        trend=assessment.trend_status,
        signal=assessment.combined_signal,
        confidence=_clamp_unit(_layer_confidence(layer) * assessment.confidence_adjustment),
        data_quality=_quality(layer),  # type: ignore[arg-type]
        last_updated=_last_updated(regime_state),
        affected_scenarios=_adjust_scenario_impacts(scenario_impacts, assessment),
        affected_themes=_adjust_theme_impacts(theme_impacts, assessment),
        notes=(
            f"{_joined_signals(layer) or 'Monetary layer converted from RegimeState.'} "
            f"{assessment.explanation}"
        ),
    )


def _fed_path_signal(regime_state: RegimeState) -> MacroInputSignal:
    forward = regime_state.forward_context
    if forward is None or not forward.fed_path:
        return MacroInputSignal(
            input_id="fed_path",
            name="Forward Fed path",
            category="monetary",
            current_value=None,
            unit=None,
            percentile=None,
            z_score=None,
            trend="unknown",
            signal="neutral",
            confidence=0.0,
            data_quality="absent",
            last_updated=None,
            affected_scenarios=[],
            affected_themes=[],
            notes="ForwardContext had no Fed path readings.",
        )

    near = forward.fed_path[0]
    hold_hike = near.prob_hold + near.prob_hike_25 + near.prob_hike_50
    cut_prob = near.prob_cut_25 + near.prob_cut_50
    if hold_hike >= 0.75:
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.45, "Hold/hike odds support higher-for-longer."),
            _scenario("oil_inflation_tail", "increases", 0.35, "Hold/hike odds leave less room to absorb inflation shocks."),
            _scenario("reopening_soft_landing", "decreases", 0.45, "Soft landing broadening needs easier policy optionality."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.60, "Hold/hike pricing keeps cash attractive."),
            _theme("long_duration_growth", "negative", 0.50, "Hold/hike pricing pressures duration."),
        ]
        signal = "bearish"
        trend = "stable"
    elif cut_prob >= 0.50:
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.45, "Cut odds support broadening."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.25, "Easing optionality reduces narrow-leadership dependence."),
        ]
        theme_impacts = [
            _theme("small_caps", "positive", 0.35, "Cut odds can broaden risk appetite."),
            _theme("long_duration_growth", "positive", 0.40, "Cut odds support duration."),
        ]
        signal = "bullish" if cut_prob > hold_hike else "mixed"
        trend = "mixed"
    else:
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.15, "Balanced Fed pricing leaves some broadening optionality."),
            _scenario("sticky_late_cycle_ai", "increases", 0.10, "Balanced Fed pricing can still support quality leadership."),
        ]
        theme_impacts = [
            _theme("quality_ex_ai_cash_flow", "positive", 0.15, "Policy uncertainty favors durable cash flow."),
            _theme("cash_short_duration", "positive", 0.10, "Uncertain policy keeps carry relevant."),
        ]
        signal = "mixed"
        trend = "mixed"

    return MacroInputSignal(
        input_id="fed_path",
        name=f"Fed path {near.meeting_date}",
        category="monetary",
        current_value=hold_hike,
        unit="hold+hike probability",
        percentile=None,
        z_score=None,
        trend=trend,  # type: ignore[arg-type]
        signal=signal,  # type: ignore[arg-type]
        confidence=0.75,
        data_quality="medium",
        last_updated=forward.as_of,
        affected_scenarios=scenario_impacts,
        affected_themes=theme_impacts,
        notes=near.source,
    )


def _numeric_current_value(signal: MacroInputSignal | None) -> float | None:
    if signal is None:
        return None
    value = signal.current_value
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _monetary_component_copy(
    signal: MacroInputSignal,
    parent_signal_id: str,
) -> MacroInputSignal:
    return signal.model_copy_validate(
        {
            "used_in_probability_update": False,
            "display_only": True,
            "parent_signal_id": parent_signal_id,
            "exclusion_reason": (
                "Excluded from probability update to avoid double-counting; "
                "included in monetary_policy_composite."
            ),
            "dedupe_role": "display_only",
        }
    )


def reconcile_monetary_signals(
    monetary_layer_signal: MacroInputSignal | None,
    fed_path_signals: list[MacroInputSignal],
) -> MacroInputSignal:
    """Build one monetary signal for probability updates to avoid double counting."""

    fed_signal = next(
        (signal for signal in fed_path_signals if signal.data_quality != "absent"),
        None,
    )
    hold_hike_probability = _numeric_current_value(fed_signal)
    cut_probability = (
        max(0.0, min(1.0, 1.0 - hold_hike_probability))
        if hold_hike_probability is not None
        else None
    )
    layer_score = _numeric_current_value(monetary_layer_signal)
    layer_direction: SignalDirection = monetary_layer_signal.signal if monetary_layer_signal else "neutral"
    fed_direction: SignalDirection = fed_signal.signal if fed_signal else "neutral"
    fed_restrictive = bool(hold_hike_probability is not None and hold_hike_probability >= 0.75)
    fed_easing = fed_direction == "bullish"

    conflict = False
    if fed_restrictive and layer_direction in {"bullish", "mixed", "neutral"}:
        composite_signal: SignalDirection = "mixed" if layer_direction != "bearish" else "bearish"
        conflict = layer_direction in {"bullish", "mixed"}
    elif fed_easing and layer_direction == "bearish":
        composite_signal = "mixed"
        conflict = True
    elif layer_direction == "bearish" and fed_direction in {"bearish", "mixed"}:
        composite_signal = "bearish"
    elif layer_direction == "bullish" and fed_direction in {"bullish", "neutral"}:
        composite_signal = "bullish"
    elif layer_direction == "neutral" and fed_direction == "bullish":
        composite_signal = "mixed"
    elif layer_direction == "neutral" and fed_direction == "bearish":
        composite_signal = "mixed"
    else:
        composite_signal = "mixed" if fed_direction == "mixed" or layer_direction == "mixed" else layer_direction

    if composite_signal == "bearish":
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.45, "Restrictive policy supports higher-for-longer and quality leadership."),
            _scenario("oil_inflation_tail", "increases", 0.35, "Restrictive Fed pricing leaves less room to absorb inflation shocks."),
            _scenario("reopening_soft_landing", "decreases", 0.45, "Soft landing broadening needs easier policy optionality."),
            _scenario("late_cycle_risk_off", "increases", 0.15, "Restrictive policy raises late-cycle break risk."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.60, "Restrictive policy keeps cash attractive."),
            _theme("long_duration_growth", "negative", 0.50, "Restrictive policy pressures duration."),
            _theme("quality_ex_ai_cash_flow", "positive", 0.25, "Cash-flow durability matters when policy is restrictive."),
        ]
    elif composite_signal == "bullish":
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.35, "Monetary conditions support broadening."),
            _scenario("late_cycle_risk_off", "decreases", 0.25, "Easier policy lowers break risk."),
            _scenario("oil_inflation_tail", "decreases", 0.15, "Easing optionality reduces inflation-tail pressure."),
        ]
        theme_impacts = [
            _theme("small_caps", "positive", 0.25, "Easier policy supports broader risk."),
            _theme("long_duration_growth", "positive", 0.30, "Easier policy supports duration."),
        ]
    elif fed_restrictive:
        scenario_impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.25, "Fed hold/hike pricing offsets softer monetary-layer signals."),
            _scenario("oil_inflation_tail", "increases", 0.20, "High hold/hike odds leave less cushion against inflation tails."),
            _scenario("reopening_soft_landing", "decreases", 0.25, "Policy is not easy enough to fully endorse broadening."),
        ]
        theme_impacts = [
            _theme("cash_short_duration", "positive", 0.35, "High hold/hike odds keep carry relevant."),
            _theme("long_duration_growth", "negative", 0.30, "High hold/hike odds restrain duration."),
            _theme("quality_ex_ai_cash_flow", "positive", 0.15, "Mixed policy favors durable cash flow."),
        ]
    else:
        scenario_impacts = [
            _scenario("reopening_soft_landing", "increases", 0.10, "Mixed monetary conditions leave limited broadening support."),
            _scenario("sticky_late_cycle_ai", "increases", 0.10, "Mixed policy can still support quality leadership."),
        ]
        theme_impacts = [
            _theme("quality_ex_ai_cash_flow", "positive", 0.10, "Mixed policy favors durable cash flow."),
            _theme("cash_short_duration", "positive", 0.10, "Policy uncertainty keeps liquidity useful."),
        ]

    confidences = [
        signal.confidence
        for signal in [monetary_layer_signal, fed_signal]
        if signal is not None and signal.data_quality != "absent"
    ]
    confidence = sum(confidences) / len(confidences) if confidences else 0.0
    if conflict:
        confidence *= 0.85

    layer_note = (
        f"layer score {layer_score:.2f}, layer signal {layer_direction}"
        if layer_score is not None
        else f"layer signal {layer_direction}"
    )
    fed_note = (
        f"Fed hold/hike probability {hold_hike_probability:.0%}, "
        f"cut probability {cut_probability:.0%}, Fed signal {fed_direction}"
        if hold_hike_probability is not None
        else f"Fed signal {fed_direction}"
    )
    notes = (
        f"Composite reconciles {layer_note} with {fed_note}. "
        "Component signals are displayed but excluded from probability updates."
    )
    if fed_restrictive and layer_direction in {"bullish", "mixed", "neutral"}:
        notes += " High hold/hike odds keep policy from being treated as outright bullish."

    children: list[str] = []
    if monetary_layer_signal is not None:
        children.append(monetary_layer_signal.input_id)
    for signal in fed_path_signals:
        if signal.input_id not in children:
            children.append(signal.input_id)
    latest = fed_signal.last_updated if fed_signal and fed_signal.last_updated else (
        monetary_layer_signal.last_updated if monetary_layer_signal else None
    )
    data_quality = "medium" if confidences else "absent"
    current_value = (
        f"monetary_score={layer_score:.2f}; hold_hike={hold_hike_probability:.2f}; cut={cut_probability:.2f}"
        if layer_score is not None and hold_hike_probability is not None
        else None
    )

    return MacroInputSignal(
        input_id="monetary_policy_composite",
        name="Monetary policy composite",
        category="monetary",
        current_value=current_value,
        unit=None,
        percentile=None,
        z_score=None,
        trend="mixed" if conflict else (monetary_layer_signal.trend if monetary_layer_signal else "unknown"),
        signal=composite_signal,
        confidence=_clamp_unit(confidence),
        data_quality=data_quality,  # type: ignore[arg-type]
        last_updated=latest,
        affected_scenarios=scenario_impacts,
        affected_themes=theme_impacts,
        notes=notes,
        used_in_probability_update=True,
        display_only=False,
        composite_method=(
            "Reconciles the monetary layer with near-term Fed hold/hike pricing; "
            "component monetary signals are displayed but excluded from scenario math."
        ),
        child_signal_ids=children,
    )


def _positioning_signal(regime_state: RegimeState) -> MacroInputSignal:
    layer = regime_state.layers.positioning
    put_call = layer.inputs.get("put_call_ratio") or layer.inputs.get("equity_pcr_5dma") or layer.inputs.get("put_call")
    fearful = bool(put_call and put_call >= 1.0)
    scenario_impacts = [
        _scenario("reopening_soft_landing", "increases", 0.20, "Fearful positioning can create contrarian support."),
        _scenario("late_cycle_risk_off", "increases", 0.20, "Elevated hedging also signals fragility."),
    ]
    theme_impacts = [
        _theme("quality_ai", "positive", 0.15, "Hedged markets can still support liquid leaders."),
        _theme("cash_short_duration", "positive", 0.20, "Hedging demand favors optionality and liquidity."),
    ]
    return MacroInputSignal(
        input_id="positioning_hedging",
        name="Positioning and hedging",
        category="positioning",
        current_value=put_call if put_call is not None else layer.score,
        unit="generic put/call ratio or 0-10 score",
        percentile=None,
        z_score=layer.inputs.get("cftc_cot_large_spec_z"),
        trend="mixed" if fearful else "stable",
        signal="mixed",
        confidence=_layer_confidence(layer),
        data_quality=_quality(layer),  # type: ignore[arg-type]
        last_updated=_last_updated(regime_state),
        affected_scenarios=scenario_impacts,
        affected_themes=theme_impacts,
        notes=_joined_signals(layer) or "Positioning converted from RegimeState.",
    )


def _driver_texts(regime_state: RegimeState) -> Iterable[tuple[str, str]]:
    for driver in regime_state.key_drivers:
        yield driver.name.lower(), f"{driver.status} {driver.explanation}".lower()


def _driver_signals(regime_state: RegimeState) -> list[MacroInputSignal]:
    results: list[MacroInputSignal] = []
    for name, text in _driver_texts(regime_state):
        combined = f"{name} {text}"
        if "oil" in combined or "hormuz" in combined or "reopening" in combined:
            results.append(
                MacroInputSignal(
                    input_id="oil_reopening_optionality",
                    name="Oil shock and reopening optionality",
                    category="commodities",
                    current_value="two-sided",
                    unit=None,
                    percentile=None,
                    z_score=None,
                    trend="mixed",
                    signal="mixed",
                    confidence=regime_state.regime_call_confidence,
                    data_quality="medium",
                    last_updated=_last_updated(regime_state),
                    affected_scenarios=[
                        _scenario("oil_inflation_tail", "increases", 0.45, "Oil shock language keeps inflation-tail risk alive."),
                        _scenario("reopening_soft_landing", "increases", 0.35, "Reopening optionality supports soft-landing relief."),
                    ],
                    affected_themes=[
                        _theme("energy_oil_beta", "positive", 0.50, "Oil risk supports energy beta."),
                        _theme("commodities_real_assets", "positive", 0.35, "Inflation tails support real assets."),
                    ],
                    notes=text[:1000],
                )
            )
        if "ai" in combined and ("resilien" in combined or "earnings" in combined or "capex" in combined):
            results.append(
                MacroInputSignal(
                    input_id="ai_earnings_resilience",
                    name="AI earnings resilience",
                    category="earnings",
                    current_value="resilient",
                    unit=None,
                    percentile=None,
                    z_score=None,
                    trend="stable",
                    signal="bullish",
                    confidence=regime_state.regime_call_confidence,
                    data_quality="medium",
                    last_updated=_last_updated(regime_state),
                    affected_scenarios=[
                        _scenario("sticky_late_cycle_ai", "increases", 0.65, "AI earnings resilience supports narrow leadership."),
                        _scenario("ai_capex_rollover", "decreases", 0.55, "Resilient AI earnings reduce capex-rollover odds."),
                    ],
                    affected_themes=[
                        _theme("quality_ai", "positive", 0.65, "AI resilience supports quality AI leaders."),
                        _theme("grid_power_infrastructure", "positive", 0.45, "AI capex resilience supports power demand."),
                        _theme("high_beta_ai_semis", "positive", 0.25, "AI resilience helps semis, though crowding remains."),
                    ],
                    notes=text[:1000],
                )
            )
    return results


def _falsifier_signals(regime_state: RegimeState) -> list[MacroInputSignal]:
    results: list[MacroInputSignal] = []
    for falsifier in regime_state.falsifiers:
        text = falsifier.condition.lower()
        if "hyperscaler" not in text and "capex" not in text:
            continue
        if falsifier.current_status == FalsifierStatus.NOT_TRIGGERED:
            results.append(
                MacroInputSignal(
                    input_id="hyperscaler_capex_falsifier_not_triggered",
                    name="Hyperscaler capex rollover falsifier",
                    category="earnings",
                    current_value=falsifier.current_status.value,
                    unit=None,
                    percentile=None,
                    z_score=None,
                    trend="stable",
                    signal="bullish",
                    confidence=0.55,
                    data_quality="medium",
                    last_updated=falsifier.last_checked_at,
                    affected_scenarios=[
                        _scenario("ai_capex_rollover", "decreases", 0.25, "Capex rollover falsifier has not triggered."),
                        _scenario("sticky_late_cycle_ai", "increases", 0.20, "Untriggered capex falsifier supports AI leadership persistence."),
                    ],
                    affected_themes=[
                        _theme("quality_ai", "positive", 0.25, "Untriggered capex risk supports quality AI."),
                        _theme("grid_power_infrastructure", "positive", 0.20, "Untriggered capex risk supports grid demand."),
                    ],
                    notes=falsifier.condition,
                )
            )
    return results


def _raw_component_signal(
    *,
    input_id: str,
    name: str,
    category: str,
    parent_layer: str,
    raw_value: float | str | bool | None,
    transformed_value: float | None,
    transformation_method: str,
    level_status: SignalDirection,
    trend_status: SignalTrend,
    confidence: float,
    scenario_impacts: list[ScenarioImpact],
    theme_impacts: list[ThemeImpact] | None = None,
    notes: str,
    input_scope: str = "core_macro",
    historical_feature_id: str | None = None,
    historical_column: str | None = None,
    historical_similarity_group: str | None = None,
    historical_similarity_weight: float | None = None,
    source_object: str | None = None,
) -> MacroInputSignal:
    feature_id = historical_feature_id or input_id
    column = historical_column if historical_column is not None else input_id
    group = historical_similarity_group or _historical_group_for_layer(parent_layer)
    use_historical = bool(raw_value is not None and column and input_scope != "market_tape")
    return MacroInputSignal(
        input_id=input_id,
        name=name,
        category=category,  # type: ignore[arg-type]
        current_value=raw_value,
        unit=None,
        percentile=None,
        z_score=transformed_value if "z" in input_id else None,
        trend=trend_status,
        signal=level_status,
        confidence=_clamp_unit(confidence),
        data_quality="high" if raw_value is not None else "absent",
        last_updated=None,
        affected_scenarios=scenario_impacts if raw_value is not None else [],
        affected_themes=theme_impacts or [],
        notes=notes,
        input_scope=input_scope,  # type: ignore[arg-type]
        parent_layer=parent_layer,  # type: ignore[arg-type]
        role="raw_component",
        is_persistent_input=True,
        raw_value=raw_value,
        transformed_value=transformed_value,
        transformation_method=transformation_method,
        source_object=source_object,
        level_status=level_status,
        trend_status=trend_status,
        signal_strength=max((impact.strength for impact in scenario_impacts), default=None),
        related_scenario_ids=_related_scenarios(scenario_impacts),
        related_theme_ids=_related_themes(theme_impacts or []),
        used_in_probability_update=raw_value is not None,
        used_in_historical_similarity=use_historical,
        display_only=raw_value is None,
        exclusion_reason=None if raw_value is not None else "Raw component unavailable.",
        dedupe_group=parent_layer,
        dedupe_role="modifier",
        historical_feature_id=feature_id if use_historical else None,
        historical_column=column if use_historical else None,
        historical_similarity_group=group if use_historical else None,
        historical_similarity_weight=historical_similarity_weight or confidence if use_historical else None,
    )


def _monetary_raw_signal(field: str, value: float | None) -> MacroInputSignal | None:
    if value is None:
        return None
    if field == "net_liquidity":
        return _raw_component_signal(
            input_id=field,
            name="Net liquidity",
            category="monetary",
            parent_layer="monetary",
            raw_value=value,
            transformed_value=None,
            transformation_method="Raw net liquidity level; directional impact handled primarily by net_liquidity_z.",
            level_status="neutral",
            trend_status="stable",
            confidence=0.45,
            scenario_impacts=[],
            theme_impacts=[],
            notes=f"Net liquidity raw value {value:.2f}.",
        )
    if field == "nfci":
        status: SignalDirection = "bullish" if value < -0.2 else "bearish" if value > 0.2 else "neutral"
        impacts = (
            [_scenario("reopening_soft_landing", "increases", 0.08, "Easy NFCI supports soft landing.")]
            if status == "bullish"
            else [_scenario("late_cycle_risk_off", "increases", 0.10, "Tight NFCI raises stress risk.")]
            if status == "bearish"
            else []
        )
        return _raw_component_signal(
            input_id=field,
            name="NFCI level",
            category="monetary",
            parent_layer="monetary",
            raw_value=value,
            transformed_value=None,
            transformation_method="Raw NFCI level; lower is easier, higher is tighter.",
            level_status=status,
            trend_status="stable",
            confidence=0.55,
            scenario_impacts=impacts,
            theme_impacts=[],
            notes=f"NFCI raw value {value:.2f}.",
        )
    specs = {
        "net_liquidity_z": ("Net liquidity z-score", "z-score; positive means expanding liquidity"),
        "nfci_inverted": ("NFCI inverted", "z-score; higher means easier financial conditions"),
        "fci_z": ("Financial conditions z-score", "z-score; higher means easier financial conditions"),
    }
    if field in specs:
        if value > 0.5:
            status: SignalDirection = "bullish"
            impacts = [
                _scenario("reopening_soft_landing", "increases", 0.22, "Easier liquidity supports soft-landing broadening."),
                _scenario("late_cycle_risk_off", "decreases", 0.18, "Easier liquidity reduces break risk."),
                _scenario("sticky_late_cycle_ai", "decreases", 0.08, "Easing conditions can reduce narrow-leadership dependence."),
            ]
            themes = [
                _theme("long_duration_growth", "positive", 0.18, "Easier liquidity supports duration."),
                _theme("small_caps", "positive", 0.15, "Easier liquidity supports broader risk."),
            ]
        elif value < -0.5:
            status = "bearish"
            impacts = [
                _scenario("reopening_soft_landing", "decreases", 0.22, "Tighter liquidity undermines broadening."),
                _scenario("late_cycle_risk_off", "increases", 0.20, "Tighter liquidity raises break risk."),
                _scenario("sticky_late_cycle_ai", "increases", 0.10, "Tighter liquidity can favor liquid narrow leadership."),
            ]
            themes = [
                _theme("cash_short_duration", "positive", 0.20, "Tighter liquidity favors cash."),
                _theme("long_duration_growth", "negative", 0.18, "Tighter liquidity pressures duration."),
            ]
        else:
            status = "neutral"
            impacts = []
            themes = []
        label, method = specs[field]
        return _raw_component_signal(
            input_id=field,
            name=label,
            category="monetary",
            parent_layer="monetary",
            raw_value=value,
            transformed_value=value,
            transformation_method=method,
            level_status=status,
            trend_status="stable",
            confidence=0.70,
            scenario_impacts=impacts,
            theme_impacts=themes,
            notes=f"{label} raw value {value:.2f}.",
        )
    if field == "m2_growth_yoy":
        if value > 5:
            status = "bullish"
            impacts = [_scenario("reopening_soft_landing", "increases", 0.12, "Positive M2 growth supports liquidity.")]
            themes = [_theme("long_duration_growth", "positive", 0.10, "M2 growth supports duration.")]
        elif value < 0:
            status = "bearish"
            impacts = [
                _scenario("reopening_soft_landing", "decreases", 0.14, "Contracting M2 is a monetary headwind."),
                _scenario("late_cycle_risk_off", "increases", 0.12, "Contracting M2 raises liquidity risk."),
            ]
            themes = [_theme("cash_short_duration", "positive", 0.12, "Contracting M2 favors liquidity.")]
        else:
            status = "neutral"
            impacts = []
            themes = []
        return _raw_component_signal(
            input_id=field,
            name="M2 growth YoY",
            category="monetary",
            parent_layer="monetary",
            raw_value=value,
            transformed_value=value,
            transformation_method="YoY percent; >5 bullish, <0 bearish",
            level_status=status,
            trend_status="stable",
            confidence=0.55,
            scenario_impacts=impacts,
            theme_impacts=themes,
            notes=f"M2 growth YoY {value:.1f}%.",
        )
    return None


def _credit_raw_signal(field: str, value: float | None) -> MacroInputSignal | None:
    if value is None:
        return None
    status: SignalDirection = "neutral"
    trend: SignalTrend = "stable"
    impacts: list[ScenarioImpact] = []
    themes: list[ThemeImpact] = []
    if field == "hy_spread_level":
        if value < 350:
            status = "bullish"
            impacts = [
                _scenario("late_cycle_risk_off", "decreases", 0.25, "Tight HY spreads reduce risk-off odds."),
                _scenario("reopening_soft_landing", "increases", 0.18, "Tight HY spreads support soft landing."),
                _scenario("sticky_late_cycle_ai", "increases", 0.10, "Contained spreads allow leadership to persist."),
            ]
            themes = [_theme("small_caps", "positive", 0.12, "Tight HY spreads support broader risk.")]
        elif value > 500:
            status = "bearish"
            impacts = [
                _scenario("late_cycle_risk_off", "increases", 0.32 if value > 600 else 0.25, "Wide HY spreads raise credit stress."),
                _scenario("reopening_soft_landing", "decreases", 0.22, "Wide HY spreads undermine soft landing."),
            ]
            themes = [_theme("cash_short_duration", "positive", 0.20, "Wide HY spreads favor liquidity.")]
        method = "HY OAS bps; <350 bullish, >500 bearish, >600 stress"
    elif field == "hy_spread_z":
        if value < -0.5:
            status = "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.18, "HY spreads are tight versus recent history.")]
        elif value > 1.0:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.28 if value > 1.5 else 0.20, "HY spreads are elevated versus recent history.")]
        method = "HY OAS z-score; <-0.5 bullish, >1 bearish"
    elif field == "hy_spread_chg_4w":
        if value < -30:
            status = "bullish"
            trend = "improving"
            impacts = [
                _scenario("late_cycle_risk_off", "decreases", 0.18, "HY spreads are tightening over 4 weeks."),
                _scenario("reopening_soft_landing", "increases", 0.12, "Tightening spreads support soft landing."),
            ]
        elif value > 30:
            status = "bearish"
            trend = "deteriorating"
            impacts = [
                _scenario("late_cycle_risk_off", "increases", 0.25 if value > 50 else 0.18, "HY spreads are widening over 4 weeks."),
                _scenario("reopening_soft_landing", "decreases", 0.14, "Widening spreads pressure broadening."),
            ]
        method = "4-week bps change; <-30 improving, >30 deteriorating"
    elif field == "ig_spread_level":
        if value < 100:
            status = "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.12, "Tight IG spreads reduce systemic stress.")]
        elif value > 150:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.25 if value > 180 else 0.18, "Wide IG spreads raise systemic stress.")]
        method = "IG OAS bps; <100 bullish, >150 bearish, >180 systemic stress"
    elif field == "ig_spread_z":
        if value < -0.5:
            status = "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.10, "IG spreads are tight versus history.")]
        elif value > 1.0:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.16, "IG spreads are elevated versus history.")]
        method = "IG spread z-score; <-0.5 bullish, >1 bearish"
    elif field == "hyg_tlt_ratio_z":
        if value > 0.5:
            status = "bullish"
            impacts = [
                _scenario("reopening_soft_landing", "increases", 0.14, "HYG/TLT confirms credit risk appetite."),
                _scenario("late_cycle_risk_off", "decreases", 0.12, "HYG/TLT reduces risk-off pressure."),
            ]
        elif value < -0.5:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.22 if value < -1.0 else 0.16, "HYG/TLT signals weaker risk appetite.")]
        method = "HYG/TLT ratio z-score; >0.5 risk-on, <-0.5 risk-off"
    else:
        return None
    return _raw_component_signal(
        input_id=field,
        name=field.replace("_", " ").title(),
        category="credit",
        parent_layer="credit",
        raw_value=value,
        transformed_value=value if field.endswith("_z") else None,
        transformation_method=method,
        level_status=status,
        trend_status=trend,
        confidence=0.75,
        scenario_impacts=impacts,
        theme_impacts=themes,
        notes=f"{field} raw value {value:.2f}.",
    )


def _volatility_raw_signal(field: str, value: float | None) -> MacroInputSignal | None:
    if value is None:
        return None
    status: SignalDirection = "neutral"
    trend: SignalTrend = "stable"
    impacts: list[ScenarioImpact] = []
    themes: list[ThemeImpact] = []
    method = ""
    if field == "vix_level":
        if value < 15:
            status = "mixed"
            impacts = [
                _scenario("sticky_late_cycle_ai", "increases", 0.10, "Low VIX supports trend continuation."),
                _scenario("late_cycle_risk_off", "increases", 0.08, "Very low VIX can indicate complacency risk."),
            ]
            method = "VIX level; <15 calm/complacency, >22 stressed, >30 risk-off"
        elif value > 22:
            status = "bearish"
            trend = "deteriorating"
            impacts = [
                _scenario("late_cycle_risk_off", "increases", 0.30 if value > 30 else 0.20, "Elevated VIX raises risk-off odds."),
                _scenario("reopening_soft_landing", "decreases", 0.20, "Elevated VIX undermines soft landing."),
            ]
            themes = [_theme("cash_short_duration", "positive", 0.20, "Elevated VIX favors liquidity.")]
            method = "VIX level; <15 calm/complacency, >22 stressed, >30 risk-off"
        else:
            method = "VIX level; 15-22 normal"
    elif field == "vix_z_20d":
        if value < -0.5:
            status = "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.12, "VIX is calm versus 20-day history.")]
        elif value > 1.0:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.24 if value > 2.0 else 0.16, "VIX is elevated versus 20-day history.")]
        method = "20-day VIX z-score; <-0.5 calm, >1 bearish"
    elif field == "vix_term_slope":
        if value > 2:
            status = "mixed" if value > 4 else "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.12, "VIX term structure is in contango.")]
            if value > 4:
                impacts.append(_scenario("late_cycle_risk_off", "increases", 0.06, "Steep contango can reflect complacency."))
        elif value < 0:
            status = "bearish"
            impacts = [
                _scenario("late_cycle_risk_off", "increases", 0.30 if value < -2 else 0.20, "VIX term structure inversion signals stress."),
                _scenario("reopening_soft_landing", "decreases", 0.18, "Backwardation undermines broadening."),
            ]
        method = "VIX3M - VIX; >2 calm, <0 stress, <-2 risk-off"
    elif field in {"vvix_level", "vvix_z"}:
        threshold = 110 if field == "vvix_level" else 1.0
        strong = 120 if field == "vvix_level" else 2.0
        if value > threshold:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.24 if value > strong else 0.16, "Vol-of-vol is elevated.")]
        method = "VVIX level/z; elevated vol-of-vol increases fragility"
    elif field in {"put_call_ratio", "put_call_5d_ma"}:
        if value > 1.1:
            status = "mixed"
            impacts = [
                _scenario("reopening_soft_landing", "increases", 0.10, "Generic put/call is high; if verified, hedging can create contrarian support."),
                _scenario("late_cycle_risk_off", "increases", 0.10, "Generic put/call is high; unresolved hedging demand may signal fragility."),
            ]
        elif value < 0.65:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.14, "Generic put/call is low; if verified, this may signal complacency.")]
        method = "Generic put/call ratio; source unresolved; >1.1 hedging/fear, <0.65 complacency"
    elif field == "skew_index":
        if value > 145:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.16, "Elevated SKEW signals tail hedging.")]
        method = "SKEW index; >145 tail hedging"
    else:
        return None
    return _raw_component_signal(
        input_id=field,
        name=field.replace("_", " ").title(),
        category="volatility",
        parent_layer="volatility",
        raw_value=value,
        transformed_value=value if field.endswith("_z") else None,
        transformation_method=method,
        level_status=status,
        trend_status=trend,
        confidence=0.70,
        scenario_impacts=impacts,
        theme_impacts=themes,
        notes=f"{field} raw value {value:.2f}.",
        input_scope="market_structure",
    )


def _breadth_raw_signal(field: str, value: float | None) -> MacroInputSignal | None:
    if value is None:
        return None
    status: SignalDirection = "neutral"
    trend: SignalTrend = "stable"
    impacts: list[ScenarioImpact] = []
    themes: list[ThemeImpact] = []
    method = ""
    bullish = bearish = False
    if field == "pct_above_200d":
        bullish = value > 65
        bearish = value < 50
        method = "% above 200d; >65 bullish, <50 bearish"
    elif field == "new_highs_minus_lows_z":
        bullish = value > 1.0
        bearish = value < -1.0
        method = "New highs minus lows z-score; >1 bullish, <-1 bearish"
    elif field == "sectors_green":
        bullish = value >= 8
        bearish = value <= 3
        method = "Sectors green out of 11; >=8 bullish, <=3 bearish"
    elif field == "rsp_vs_spy_z":
        bullish = value > 0.5
        bearish = value < -0.5
        method = "RSP/SPY z-score; >0.5 broadening, <-0.5 narrowing"
    elif field == "adl_slope":
        bullish = value > 0
        bearish = value < 0
        method = "Advance/decline line slope; positive broadening, negative narrowing"
    else:
        return None
    if bullish:
        status = "bullish"
        trend = "improving"
        impacts = [
            _scenario("reopening_soft_landing", "increases", 0.25, f"{field} supports broad participation."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.14, f"{field} reduces narrow-leadership dependence."),
            _scenario("late_cycle_risk_off", "decreases", 0.14, f"{field} lowers market fragility."),
        ]
        themes = [
            _theme("small_caps", "positive", 0.20, f"{field} supports broader risk."),
            _theme("long_duration_growth", "positive", 0.10, f"{field} supports broader growth participation."),
        ]
    elif bearish:
        status = "bearish"
        trend = "deteriorating"
        impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.24, f"{field} favors narrow leadership."),
            _scenario("late_cycle_risk_off", "increases", 0.18, f"{field} raises fragility."),
            _scenario("reopening_soft_landing", "decreases", 0.22, f"{field} undermines broadening."),
        ]
        themes = [
            _theme("quality_ai", "positive", 0.14, f"{field} favors liquid leaders."),
            _theme("small_caps", "negative", 0.22, f"{field} penalizes small-cap beta."),
        ]
    return _raw_component_signal(
        input_id=field,
        name=field.replace("_", " ").title(),
        category="breadth",
        parent_layer="breadth",
        raw_value=value,
        transformed_value=value if field.endswith("_z") else None,
        transformation_method=method,
        level_status=status,
        trend_status=trend,
        confidence=0.72,
        scenario_impacts=impacts,
        theme_impacts=themes,
        notes=f"{field} raw value {value:.2f}.",
        input_scope="market_structure",
    )


def _positioning_raw_signal(field: str, value: float | None) -> MacroInputSignal | None:
    if value is None:
        return None
    status: SignalDirection = "neutral"
    impacts: list[ScenarioImpact] = []
    themes: list[ThemeImpact] = []
    method = ""
    if field == "dealer_gamma_z":
        if value > 1:
            status = "bullish"
            impacts = [_scenario("late_cycle_risk_off", "decreases", 0.14, "Positive dealer gamma dampens volatility.")]
        elif value < -1:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.24 if value < -1.5 else 0.16, "Negative dealer gamma amplifies volatility.")]
        method = "Dealer gamma z-score; >1 dampening, <-1 amplification"
    elif field == "put_call_5d_ma":
        if value > 0.95:
            status = "mixed"
            impacts = [
                _scenario("reopening_soft_landing", "increases", 0.12, "Generic 5D put/call is high; if verified, hedging can create contrarian support."),
                _scenario("late_cycle_risk_off", "increases", 0.10, "Generic 5D put/call is high; unresolved hedging demand may signal fragility."),
            ]
        elif value < 0.60:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.14, "Generic 5D put/call is low; if verified, this may signal complacency.")]
        method = "Generic 5-day put/call; source unresolved; >0.95 hedging/fear, <0.60 complacency"
    elif field == "aaii_bull_minus_bear":
        if value < -20:
            status = "bullish"
            impacts = [_scenario("reopening_soft_landing", "increases", 0.12, "AAII pessimism can be contrarian support.")]
        elif value > 30:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.12, "AAII optimism can indicate crowding.")]
        method = "AAII bull-bear; <-20 contrarian bullish, >30 euphoric"
    elif field == "cot_net_large_spec_z":
        if value < -2:
            status = "bullish"
            impacts = [_scenario("reopening_soft_landing", "increases", 0.12, "COT washed-out positioning can support rebound.")]
        elif value > 2:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.12, "COT crowded long positioning raises unwind risk.")]
        method = "COT large spec z-score; >2 crowded long, <-2 washed out"
    elif field == "equity_etf_flow_z":
        if value < -2:
            status = "bullish"
            impacts = [_scenario("reopening_soft_landing", "increases", 0.10, "ETF outflows can mark capitulation support.")]
        elif value > 2:
            status = "bearish"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.10, "ETF inflows can signal crowded risk appetite.")]
        method = "Equity ETF flow z-score; >2 crowded inflow, <-2 outflow support"
    else:
        return None
    return _raw_component_signal(
        input_id=field,
        name=field.replace("_", " ").title(),
        category="positioning",
        parent_layer="positioning",
        raw_value=value,
        transformed_value=value if field.endswith("_z") else None,
        transformation_method=method,
        level_status=status,
        trend_status="stable",
        confidence=0.65,
        scenario_impacts=impacts,
        theme_impacts=themes,
        notes=f"{field} raw value {value:.2f}.",
        input_scope="market_structure",
    )


def build_raw_component_signals_from_regime_inputs(
    regime_inputs: RegimeInputs | None,
    deterministic_config: DeterministicInputConfig | InputDedupeConfig | None = None,
    layer_scores: Any | None = None,
    regime_state: RegimeState | None = None,
    market_state: Any | None = None,
    extra_features: dict[str, Any] | None = None,
) -> list[MacroInputSignal]:
    """Build deterministic raw-component forecast inputs from RegimeInputs."""

    builders = {
        "monetary": (_monetary_raw_signal, ["net_liquidity", "net_liquidity_z", "nfci", "nfci_inverted", "m2_growth_yoy", "fci_z"]),
        "credit": (_credit_raw_signal, ["hy_spread_level", "hy_spread_z", "hy_spread_chg_4w", "ig_spread_level", "ig_spread_z", "hyg_tlt_ratio_z"]),
        "volatility": (_volatility_raw_signal, ["vix_level", "vix_z_20d", "vix_term_slope", "vvix_level", "vvix_z", "put_call_ratio", "skew_index"]),
        "breadth": (_breadth_raw_signal, ["pct_above_200d", "new_highs_minus_lows_z", "sectors_green", "rsp_vs_spy_z", "adl_slope"]),
        "positioning": (_positioning_raw_signal, ["dealer_gamma_z", "put_call_5d_ma", "aaii_bull_minus_bear", "cot_net_large_spec_z", "equity_etf_flow_z"]),
    }
    regime_state_values = _flatten_regime_state_inputs(regime_state)
    market_state_values = _market_state_feature_values(market_state)
    signals: list[MacroInputSignal] = []
    for _, (builder, fields) in builders.items():
        for field in fields:
            value, source_object = _resolve_raw_input_value(
                field,
                regime_inputs,
                regime_state_values,
                market_state_values,
                extra_features=extra_features,
            )
            signal = builder(field, value)
            if signal is not None:
                signals.append(
                    signal.model_copy_validate(
                        {
                            "source_object": source_object or "unknown",
                            "used_in_probability_update": bool(value is not None),
                            "display_only": value is None,
                            "exclusion_reason": None if value is not None else "Raw component unavailable.",
                        }
                    )
                )
    return signals


def _raw_input_coverage(
    regime_inputs: RegimeInputs | None,
    signals: list[MacroInputSignal],
    *,
    regime_state: RegimeState | None = None,
    market_state: Any | None = None,
) -> dict[str, Any]:
    signal_ids = {signal.input_id for signal in signals}
    groups: dict[str, Any] = {}
    total_expected = total_present = total_prob = total_hist = total_display_only = 0
    for group, fields in EXPECTED_RAW_INPUTS_BY_GROUP.items():
        present = [
            field
            for field in fields
            if field in signal_ids
        ]
        missing = [
            field
            for field in fields
            if field not in signal_ids
        ]
        total_expected += len(fields)
        total_present += len(present)
        prob_used = [
            field
            for field in fields
            for signal in signals
            if signal.input_id == field and signal.used_in_probability_update and not signal.display_only
        ]
        hist_used = [
            field
            for field in fields
            for signal in signals
            if signal.input_id == field and signal.used_in_historical_similarity
        ]
        display_only = [
            field
            for field in fields
            for signal in signals
            if signal.input_id == field and signal.display_only
        ]
        total_prob += len(prob_used)
        total_hist += len(hist_used)
        total_display_only += len(display_only)
        groups[group] = {
            "expected": fields,
            "present": present,
            "missing": missing,
            "missing_inputs": missing,
            "used_in_probability_update": prob_used,
            "used_in_historical_similarity": hist_used,
            "display_only": display_only,
            "coverage": round(len(present) / len(fields), 3) if fields else 0.0,
        }
    warnings: list[str] = []
    if regime_inputs is None:
        warnings.append("RegimeInputs unavailable; raw component signals cannot be fully built.")
    return {
        "groups": groups,
        "present_count": total_present,
        "expected_count": total_expected,
        "missing_count": total_expected - total_present,
        "coverage": round(total_present / total_expected, 3) if total_expected else 0.0,
        "totals": {
            "total_raw_signals_expected": total_expected,
            "total_raw_signals_available": total_present,
            "total_raw_signals_used_in_probability_update": total_prob,
            "total_raw_signals_used_in_historical_similarity": total_hist,
            "total_raw_signals_display_only": total_display_only,
            "total_raw_signals_missing": total_expected - total_present,
        },
        "regime_inputs_available": regime_inputs is not None,
        "market_state_available": market_state is not None,
        "warnings": warnings,
    }


def _regime_inputs_from_regime_state(regime_state: RegimeState) -> RegimeInputs:
    values: dict[str, Any] = {"asof_date": regime_state.asof_date}
    for layer in [
        regime_state.layers.monetary,
        regime_state.layers.credit,
        regime_state.layers.volatility,
        regime_state.layers.breadth,
        regime_state.layers.positioning,
    ]:
        values.update(layer.inputs)
    return RegimeInputs(**{key: value for key, value in values.items() if key in RegimeInputs.__dataclass_fields__})


def build_market_tape_signals_from_market_state(
    market_state: Any,
    *,
    horizon: str = "3m",
) -> list[MacroInputSignal]:
    """Build lower-weight market/tape forecast inputs from MarketState."""

    signals: list[MacroInputSignal] = []
    cross = getattr(market_state, "cross_asset_returns", {}) or {}
    spy = _safe_float(cross.get("SPY"))
    rsp = _safe_float(cross.get("RSP"))
    iwm = _safe_float(cross.get("IWM"))
    hyg = _safe_float(cross.get("HYG"))
    tlt = _safe_float(cross.get("TLT"))

    def add_tape_signal(
        input_id: str,
        name: str,
        value: float | bool | str | None,
        status: SignalDirection,
        impacts: list[ScenarioImpact],
        notes: str,
        transformed: float | None = None,
        category: str = "breadth",
    ) -> None:
        signals.append(
            _raw_component_signal(
                input_id=input_id,
                name=name,
                category=category,
                parent_layer="market_state",
                raw_value=value,
                transformed_value=transformed,
                transformation_method=f"Market tape signal, horizon {getattr(market_state, 'horizon', horizon)}.",
                level_status=status,
                trend_status="stable",
                confidence=0.55,
                scenario_impacts=impacts,
                theme_impacts=[],
                notes=notes,
                input_scope="market_tape",
                source_object="MarketState",
            )
        )

    cross_specs = {
        "SPY": ("spy", "SPY return", "breadth"),
        "QQQ": ("qqq", "QQQ return", "breadth"),
        "IWM": ("iwm", "IWM return", "breadth"),
        "TLT": ("tlt", "TLT return", "monetary"),
        "HYG": ("hyg", "HYG return", "credit"),
        "GLD": ("gld", "GLD return", "commodities"),
        "USO": ("uso", "USO return", "commodities"),
        "BTC-USD": ("btc", "BTC return", "breadth"),
        "RSP": ("rsp", "RSP return", "breadth"),
    }
    for ticker, (slug, label, category) in cross_specs.items():
        value = _safe_float(cross.get(ticker))
        if value is None:
            continue
        status = "bullish" if value > 0 else "bearish" if value < 0 else "neutral"
        impacts: list[ScenarioImpact] = []
        if ticker in {"SPY", "QQQ", "BTC-USD"}:
            impacts = (
                [_scenario("sticky_late_cycle_ai", "increases", 0.05, f"{label} is positive.")]
                if value > 0
                else [_scenario("late_cycle_risk_off", "increases", 0.06, f"{label} is negative.")]
            )
        elif ticker in {"RSP", "IWM"}:
            impacts = (
                [_scenario("reopening_soft_landing", "increases", 0.08, f"{label} supports broadening.")]
                if value > 0
                else [_scenario("reopening_soft_landing", "decreases", 0.08, f"{label} weakens broadening.")]
            )
        elif ticker == "HYG":
            impacts = (
                [_scenario("late_cycle_risk_off", "decreases", 0.07, "HYG tape is constructive.")]
                if value > 0
                else [_scenario("late_cycle_risk_off", "increases", 0.08, "HYG tape is weak.")]
            )
        elif ticker == "TLT":
            impacts = (
                [_scenario("late_cycle_risk_off", "increases", 0.05, "Treasury strength can reflect defensive demand.")]
                if value > 0
                else [_scenario("reopening_soft_landing", "increases", 0.04, "Treasury weakness can reflect risk appetite.")]
            )
        elif ticker in {"GLD", "USO"}:
            impacts = (
                [_scenario("oil_inflation_tail", "increases", 0.07, f"{label} supports inflation-tail watchlist.")]
                if value > 0
                else [_scenario("oil_inflation_tail", "decreases", 0.05, f"{label} pressure reduces inflation-tail tape.")]
            )
        add_tape_signal(
            f"market_tape_{slug}_return",
            label,
            value,
            status,
            impacts,
            f"{label} from MarketState cross_asset_returns.",
            value,
            category=category,
        )

    if hyg is not None and tlt is not None:
        risk_on = hyg - tlt
        status = "bullish" if risk_on > 0 else "bearish" if risk_on < 0 else "neutral"
        impacts = [
            _scenario("reopening_soft_landing", "increases", 0.10, "HYG minus TLT tape is risk-on."),
            _scenario("late_cycle_risk_off", "decreases", 0.08, "HYG minus TLT tape is risk-on."),
        ] if risk_on > 0 else [
            _scenario("late_cycle_risk_off", "increases", 0.10, "HYG minus TLT tape is risk-off."),
            _scenario("reopening_soft_landing", "decreases", 0.08, "HYG minus TLT tape is risk-off."),
        ]
        add_tape_signal("hyg_minus_tlt", "HYG minus TLT risk-on proxy", risk_on, status, impacts, "Cross-asset risk-on proxy from MarketState.", risk_on, category="credit")
    if rsp is not None and spy is not None:
        participation = rsp - spy
        status = "bullish" if participation > 0 else "bearish" if participation < 0 else "neutral"
        impacts = [
            _scenario("reopening_soft_landing", "increases", 0.12, "RSP outperformance confirms participation."),
            _scenario("sticky_late_cycle_ai", "decreases", 0.08, "RSP outperformance reduces narrow leadership dependence."),
        ] if participation > 0 else [
            _scenario("sticky_late_cycle_ai", "increases", 0.12, "RSP underperformance confirms narrow leadership."),
            _scenario("reopening_soft_landing", "decreases", 0.10, "RSP underperformance undermines broadening."),
        ]
        add_tape_signal("rsp_minus_spy", "RSP minus SPY participation proxy", participation, status, impacts, "Equal-weight versus cap-weight tape.", participation)
    if iwm is not None and spy is not None:
        small = iwm - spy
        status = "bullish" if small > 0 else "bearish" if small < 0 else "neutral"
        impacts = [
            _scenario("reopening_soft_landing", "increases", 0.10, "Small-cap leadership supports broadening."),
        ] if small > 0 else [
            _scenario("reopening_soft_landing", "decreases", 0.08, "Small-cap underperformance weakens broadening."),
            _scenario("sticky_late_cycle_ai", "increases", 0.08, "Small-cap underperformance supports narrow leadership."),
        ]
        add_tape_signal("iwm_minus_spy", "IWM minus SPY small-cap leadership", small, status, impacts, "Small-cap leadership tape.", small)
    qqq = _safe_float(cross.get("QQQ"))
    if qqq is not None and spy is not None:
        mega_cap = qqq - spy
        status = "bullish" if mega_cap > 0 else "bearish" if mega_cap < 0 else "neutral"
        impacts = [
            _scenario("sticky_late_cycle_ai", "increases", 0.08, "QQQ outperformance supports growth/AI leadership."),
        ] if mega_cap > 0 else [
            _scenario("ai_capex_rollover", "increases", 0.06, "QQQ underperformance can warn on growth leadership fatigue."),
        ] if mega_cap < 0 else []
        add_tape_signal("qqq_minus_spy", "QQQ minus SPY growth leadership", mega_cap, status, impacts, "Nasdaq versus S&P tape.", mega_cap)

    sectors_green = _safe_float(getattr(market_state, "sectors_green", None))
    if sectors_green is not None:
        status = "bullish" if sectors_green >= 8 else "bearish" if sectors_green <= 3 else "neutral"
        impacts = [
            _scenario("reopening_soft_landing", "increases", 0.10, "Many sectors green confirms participation."),
            _scenario("late_cycle_risk_off", "decreases", 0.08, "Sector breadth reduces risk-off tape."),
        ] if status == "bullish" else [
            _scenario("late_cycle_risk_off", "increases", 0.10, "Few sectors green signals fragile tape."),
            _scenario("reopening_soft_landing", "decreases", 0.08, "Few sectors green undermines broadening."),
        ] if status == "bearish" else []
        add_tape_signal("sectors_green", "Market tape sectors green", sectors_green, status, impacts, "Sectors positive in MarketState.", sectors_green)

    leadership = getattr(market_state, "leadership_top3", None) or []
    if leadership:
        leaders = ", ".join(f"{name} {value:+.1f}%" for name, value in leadership[:3])
        lower_leaders = leaders.lower()
        impacts = (
            [_scenario("sticky_late_cycle_ai", "increases", 0.07, "Technology-led leadership supports narrow AI/tape persistence.")]
            if "tech" in lower_leaders
            else []
        )
        add_tape_signal(
            "market_tape_leadership_top3",
            "Market tape leadership top 3",
            leaders,
            "mixed" if impacts else "neutral",
            impacts,
            "Top sector leadership from MarketState.",
            None,
        )

    dispersion = _safe_float(getattr(market_state, "dispersion", None))
    if dispersion is not None:
        status = "bearish" if dispersion > 1.5 else "neutral"
        impacts = (
            [_scenario("late_cycle_risk_off", "increases", 0.06, "High sector dispersion can signal fragile leadership.")]
            if status == "bearish"
            else []
        )
        add_tape_signal(
            "sector_dispersion",
            "Market tape sector dispersion",
            dispersion,
            status,
            impacts,
            "Sector return dispersion from MarketState.",
            dispersion,
        )

    for field in ["spy_above_vwap", "spy_above_prev_close"]:
        value = getattr(market_state, field, None)
        if not isinstance(value, bool):
            continue
        status = "bullish" if value else "bearish"
        impacts = (
            [_scenario("reopening_soft_landing", "increases", 0.04, f"{field} is constructive.")]
            if value
            else [_scenario("late_cycle_risk_off", "increases", 0.04, f"{field} is weak.")]
        )
        add_tape_signal(
            field,
            field.replace("_", " ").title(),
            value,
            status,
            impacts,
            f"{field} from MarketState.",
            1.0 if value else 0.0,
        )

    for field in ["spy_clv", "spy_range_pct", "spy_vol_z_20d", "volume_confirmation", "vix_level", "vix_z_20d", "vix_change_pct_1d"]:
        value = _safe_float(getattr(market_state, field, None))
        if value is None:
            continue
        if field.startswith("vix"):
            status = "bearish" if value > (1.0 if field.endswith("z_20d") else 20.0) else "neutral"
            impacts = [_scenario("late_cycle_risk_off", "increases", 0.08, f"{field} warns on volatility tape.")] if status == "bearish" else []
            category = "volatility"
        else:
            status = "bullish" if value > 0 else "bearish" if value < 0 else "neutral"
            impacts = [_scenario("reopening_soft_landing", "increases", 0.06, f"{field} is constructive.")] if status == "bullish" else [_scenario("late_cycle_risk_off", "increases", 0.06, f"{field} is weak.")] if status == "bearish" else []
            category = "breadth"
        signal = _raw_component_signal(
            input_id=field,
            name=field.replace("_", " ").title(),
            category=category,
            parent_layer="market_state",
            raw_value=value,
            transformed_value=value,
            transformation_method=f"Market tape field from MarketState, horizon {getattr(market_state, 'horizon', horizon)}.",
            level_status=status,
            trend_status="stable",
            confidence=0.50,
            scenario_impacts=impacts,
            theme_impacts=[],
            notes=f"{field} raw value {value:.2f}.",
            input_scope="market_tape",
            source_object="MarketState",
        )
        signals.append(signal)
    return signals


def _methodology_notes(dedupe_config: InputDedupeConfig, horizon: str) -> list[str]:
    return [
        "Layer summaries are generated from Helix regime layer scores.",
        "Raw components are generated from underlying RegimeInputs fields when available.",
        "Market/tape signals are generated from MarketState when provided.",
        "Regime drivers and scenario falsifiers are generated from active regime context.",
        f"Input dedupe mode: {dedupe_config.mode}.",
        "In hybrid mode, layer summaries provide base scenario impacts and raw components act as modifiers within the same parent layer.",
        "Dedupe caps prevent one layer from dominating through many correlated inputs.",
        f"Market/tape inputs are horizon-weighted for horizon {horizon}.",
    ]


def build_forecast_input_set(
    regime_state: RegimeState,
    *,
    raw_inputs: RegimeInputs | None = None,
    market_state: Any | None = None,
    horizon: str = "3m",
    use_monetary_composite: bool = True,
    dedupe_config: InputDedupeConfig | None = None,
) -> ForecastInputSet:
    """Build the hierarchical forecast input set used by the macro forecast engine."""

    dedupe_config = dedupe_config or InputDedupeConfig()

    monetary_component = _tag_signal(
        _monetary_layer_signal(regime_state),
        input_scope="layer_summary",
        parent_layer="monetary",
        role="layer_summary",
        dedupe_role="primary",
    )
    fed_component = _tag_signal(
        _fed_path_signal(regime_state),
        input_scope="raw_component",
        parent_layer="monetary",
        role="raw_component",
        dedupe_role="display_only" if use_monetary_composite else "modifier",
    )

    composite_signals: list[MacroInputSignal] = []
    if use_monetary_composite:
        monetary_composite = _tag_signal(
            reconcile_monetary_signals(monetary_component, [fed_component]),
            input_scope="composite",
            parent_layer="monetary",
            role="composite",
            dedupe_role="primary",
        )
        monetary_parent = monetary_composite.input_id
        monetary_component = _monetary_component_copy(monetary_component, monetary_parent)
        fed_component = _monetary_component_copy(fed_component, monetary_parent)
        composite_signals.append(monetary_composite)
    else:
        monetary_component = monetary_component.model_copy_validate({"used_in_probability_update": True, "display_only": False})
        fed_component = fed_component.model_copy_validate({"used_in_probability_update": True, "display_only": False})

    layer_summary_signals = [
        monetary_component,
        _tag_signal(_credit_signal(regime_state), input_scope="layer_summary", parent_layer="credit", role="layer_summary", dedupe_role="primary"),
        _tag_signal(_breadth_signal(regime_state), input_scope="layer_summary", parent_layer="breadth", role="layer_summary", dedupe_role="primary"),
        _tag_signal(_positioning_signal(regime_state), input_scope="layer_summary", parent_layer="positioning", role="layer_summary", dedupe_role="primary"),
    ]
    if dedupe_config.include_volatility_layer:
        layer_summary_signals.insert(
            2,
            _tag_signal(_volatility_signal(regime_state), input_scope="layer_summary", parent_layer="volatility", role="layer_summary", dedupe_role="primary"),
        )

    raw_component_signals = [fed_component]
    raw_components_from_inputs = build_raw_component_signals_from_regime_inputs(
        raw_inputs,
        deterministic_config=dedupe_config,
        regime_state=regime_state,
        market_state=market_state,
    )
    if not dedupe_config.include_volatility_raw_components:
        raw_components_from_inputs = [
            signal
            for signal in raw_components_from_inputs
            if signal.parent_layer != "volatility"
        ]
    raw_component_signals.extend(raw_components_from_inputs)
    raw_ids_by_layer: dict[str, list[str]] = {}
    for signal in raw_component_signals:
        if signal.input_scope == "market_tape" or signal.parent_layer is None:
            continue
        raw_ids_by_layer.setdefault(signal.parent_layer, []).append(signal.input_id)
    layer_summary_signals = [
        signal.model_copy_validate(
            {
                "child_signal_ids": raw_ids_by_layer.get(signal.parent_layer or "", []),
            }
        )
        for signal in layer_summary_signals
    ]
    market_tape_signals = (
        build_market_tape_signals_from_market_state(market_state, horizon=horizon)
        if market_state is not None
        else []
    )
    regime_driver_signals = [
        _tag_signal(
            signal,
            input_scope="regime_driver",
            parent_layer="commodities" if signal.category == "commodities" else "earnings",
            role="regime_driver",
            is_persistent_input=False,
            dedupe_group=signal.input_id,
            dedupe_role="primary",
            active_only_in_regime_ids=[regime_state.regime_id],
        )
        for signal in _driver_signals(regime_state)
    ]
    scenario_falsifier_signals = [
        _tag_signal(
            signal,
            input_scope="scenario_falsifier",
            parent_layer="earnings",
            role="scenario_falsifier",
            is_persistent_input=False,
            dedupe_group=signal.input_id,
            dedupe_role="primary",
            active_only_in_regime_ids=[regime_state.regime_id],
        )
        for signal in _falsifier_signals(regime_state)
    ]
    theme_specific_signals: list[MacroInputSignal] = []

    all_signals = [
        *layer_summary_signals,
        *raw_component_signals,
        *composite_signals,
        *market_tape_signals,
        *regime_driver_signals,
        *scenario_falsifier_signals,
        *theme_specific_signals,
    ]
    deduped: dict[str, MacroInputSignal] = {}
    for signal in all_signals:
        deduped.setdefault(signal.input_id, signal)

    all_signals = list(deduped.values())
    return ForecastInputSet(
        asof_date=regime_state.asof_date,
        layer_summary_signals=[signal for signal in all_signals if signal.role == "layer_summary"],
        raw_component_signals=[
            signal
            for signal in all_signals
            if signal.role == "raw_component" and signal.input_scope != "market_tape"
        ],
        composite_signals=[signal for signal in all_signals if signal.role == "composite"],
        market_tape_signals=[signal for signal in all_signals if signal.input_scope == "market_tape"],
        regime_driver_signals=[signal for signal in all_signals if signal.role == "regime_driver"],
        scenario_falsifier_signals=[signal for signal in all_signals if signal.role == "scenario_falsifier"],
        theme_specific_signals=theme_specific_signals,
        all_signals=all_signals,
        methodology_notes=_methodology_notes(dedupe_config, horizon),
        raw_input_coverage=_raw_input_coverage(
            raw_inputs,
            [*raw_components_from_inputs, *market_tape_signals],
            regime_state=regime_state,
            market_state=market_state,
        ),
    )


def build_macro_input_signals(
    regime_state: RegimeState,
    *,
    use_monetary_composite: bool = True,
) -> list[MacroInputSignal]:
    """Build deterministic input-level macro signals from a RegimeState."""
    return build_forecast_input_set(
        regime_state,
        use_monetary_composite=use_monetary_composite,
    ).all_signals
