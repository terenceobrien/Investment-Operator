"""Historical analogue calibration for Macro Forecast Engine probabilities."""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any, Mapping

from src.agent_system.schemas.macro_forecast import (
    AnalogueForwardStats,
    ForecastInputSet,
    HistoricalAnalogueMatch,
    HistoricalCalibrationConfig,
    HistoricalCalibrationResult,
    HistoricalScenarioCalibration,
    MACRO_ANALOGUE_HORIZONS,
    MacroForecastResult,
    ScenarioMappingHorizon,
    TACTICAL_ANALOGUE_HORIZONS,
)
from src.agent_system.schemas.regime import RegimeState


SCENARIO_LABELS: dict[str, str] = {
    "reopening_soft_landing": "Reopening / Soft Landing",
    "sticky_late_cycle_ai": "Sticky Late Cycle AI",
    "oil_inflation_tail": "Oil Inflation Tail",
    "late_cycle_risk_off": "Late Cycle Risk-Off",
    "ai_capex_rollover": "AI Capex Rollover",
}

METHODOLOGY_NOTES = [
    "Historical analogue calibration is a second-stage probability adjustment; deterministic input-signal math is retained unchanged.",
    "Analogue-implied scenario probabilities are computed from weighted analogue counts after deterministic rule-based scenario mapping.",
    "blended_probability_s = deterministic_weight × deterministic_probability_s + historical_weight × historical_probability_s",
    "Blended probabilities are renormalized and then used to recompute theme, sector, and factor rankings when calibration is enabled.",
    "The current/as-of market state is assigned full analogue lookup weight. Prior lookback days are included to capture path context and are exponentially downweighted.",
    "Historical scenario mapping is approximate until the historical feature store includes explicit scenario labels and theme/basket forward returns.",
    "AI capex rollover and oil-tail mappings are lower confidence when explicit AI, semis, oil, or commodity forward features are unavailable.",
    "Shock-window filtering removes horizon-specific forward returns whose forward windows overlap configured exogenous shock periods.",
]

SCENARIO_MAPPING_FALLBACKS: dict[str, list[str]] = {
    "21d": ["10d", "5d", "1d"],
    "63d": ["21d", "10d", "5d", "1d"],
    "126d": ["63d", "21d", "10d", "5d", "1d"],
    "252d": ["126d", "63d", "21d", "10d", "5d", "1d"],
}


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


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize(probabilities: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, float(value)) for value in probabilities.values())
    if total <= 0:
        equal = 1.0 / len(probabilities) if probabilities else 0.0
        return {key: equal for key in probabilities}
    return {key: max(0.0, float(value)) / total for key, value in probabilities.items()}


def _renormalize_blend_weights(config: HistoricalCalibrationConfig) -> tuple[float, float]:
    total = config.deterministic_weight + config.historical_weight
    if total <= 0:
        return 1.0, 0.0
    return config.deterministic_weight / total, config.historical_weight / total


def _dict_float_values(value: Any) -> dict[str, float | None]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _safe_float(item) for key, item in value.items()}


def _historical_weight(analogue: Mapping[str, Any]) -> float:
    composite_weight = _safe_float(analogue.get("composite_weight"))
    if composite_weight is not None and composite_weight > 0:
        return composite_weight
    similarity = _safe_float(analogue.get("similarity_score"))
    if similarity is not None and similarity >= 0:
        return 1.0 / (1.0 + similarity)
    return 1.0


def _scenario_available(scenario_id: str, available_scenarios: list[str]) -> bool:
    return scenario_id in set(available_scenarios)


def _append_unique_warning(warnings: list[str] | None, warning: str | None) -> None:
    if warnings is not None and warning and warning not in warnings:
        warnings.append(warning)


def _shock_windows_for_engine(config: HistoricalCalibrationConfig) -> list[dict[str, Any]]:
    if not config.exclude_shock_windows:
        return []
    return [
        window.model_dump(mode="json") if hasattr(window, "model_dump") else dict(window)
        for window in config.shock_windows
    ]


def _mapping_excluded_by_shock_window(
    analogue: Mapping[str, Any],
    config: HistoricalCalibrationConfig,
) -> bool:
    if not config.exclude_shock_windows or config.shock_window_mode != "exclude":
        return False
    try:
        from src.analysis.analogues import forward_window_overlaps_shock
    except Exception:
        return False
    return forward_window_overlaps_shock(
        analogue.get("date"),
        config.scenario_mapping_horizon,
        _shock_windows_for_engine(config),
    )


def _mapping_forward_return(
    analogue: Mapping[str, Any],
    selected_horizon: str,
) -> tuple[float | None, str | None, str, str | None]:
    forward_returns = analogue.get("forward_returns") or {}
    if not isinstance(forward_returns, Mapping):
        return (
            None,
            None,
            f"no usable mapping-horizon return because selected mapping horizon {selected_horizon} return unavailable",
            f"Selected scenario mapping horizon {selected_horizon} unavailable for one or more analogues; no fallback return was available.",
        )

    ordered_horizons = [selected_horizon] + [
        horizon
        for horizon in SCENARIO_MAPPING_FALLBACKS.get(selected_horizon, ["21d", "10d", "5d", "1d"])
        if horizon != selected_horizon
    ]
    for horizon in ordered_horizons:
        value = _safe_float(forward_returns.get(horizon))
        if value is None:
            continue
        if horizon == selected_horizon:
            return value, horizon, f"selected mapping horizon {selected_horizon} return", None
        warning = (
            f"Selected scenario mapping horizon {selected_horizon} unavailable for one or more analogues; "
            f"used fallback {horizon} return."
        )
        return (
            value,
            horizon,
            f"fallback {horizon} return because {selected_horizon} return unavailable",
            warning,
        )

    return (
        None,
        None,
        f"no usable mapping-horizon return because selected mapping horizon {selected_horizon} return unavailable",
        f"Selected scenario mapping horizon {selected_horizon} unavailable for one or more analogues; no fallback return was available.",
    )


def _energy_signal(analogue: Mapping[str, Any]) -> bool:
    sector_returns = analogue.get("sector_returns") or {}
    if isinstance(sector_returns, Mapping):
        for key, value in sector_returns.items():
            key_text = str(key).lower()
            val = _safe_float(value)
            if val is None:
                continue
            if ("energy" in key_text or "oil" in key_text or key_text == "xle") and val >= 1.0:
                return True
    forward = analogue.get("forward_returns") or {}
    if isinstance(forward, Mapping):
        uso = _safe_float(forward.get("USO") or forward.get("uso"))
        if uso is not None and uso > 0:
            return True
    return False


def _technology_weakness(analogue: Mapping[str, Any]) -> bool:
    sector_returns = analogue.get("sector_returns") or {}
    if not isinstance(sector_returns, Mapping):
        return False
    for key, value in sector_returns.items():
        key_text = str(key).lower()
        val = _safe_float(value)
        if val is None:
            continue
        if ("technology" in key_text or "semiconductor" in key_text or key_text in {"xlk", "smh"}) and val <= -1.0:
            return True
    return False


def map_analogue_to_scenario(
    analogue: dict,
    available_scenarios: list[str],
    scenario_mapping_horizon: ScenarioMappingHorizon = "63d",
    warnings: list[str] | None = None,
) -> tuple[str, float, str]:
    """Map one historical analogue row into the closest macro scenario bucket."""

    env = str(analogue.get("environment") or "").lower()
    risk_profile = analogue.get("risk_profile") or {}
    mapping_return, mapping_horizon, mapping_return_text, mapping_warning = _mapping_forward_return(
        analogue,
        scenario_mapping_horizon,
    )
    _append_unique_warning(warnings, mapping_warning)
    selected_drawdown = _safe_float(
        risk_profile.get(f"max_drawdown_{mapping_horizon}") if isinstance(risk_profile, Mapping) and mapping_horizon else None
    )
    drawdown_5d = _safe_float(risk_profile.get("max_drawdown_5d") if isinstance(risk_profile, Mapping) else None)
    sectors_green = _safe_int(analogue.get("sectors_green"))
    vix_level = _safe_float(analogue.get("vix_level"))
    score_delta = _safe_float(analogue.get("score_delta"))

    risk_conditions = [
        mapping_return is not None and mapping_return <= -5.0,
        selected_drawdown is not None and selected_drawdown <= -4.0,
        drawdown_5d is not None and drawdown_5d <= -4.0,
        "risk-off" in env or "risk off" in env,
    ]
    if _scenario_available("late_cycle_risk_off", available_scenarios) and any(risk_conditions):
        hits = sum(1 for item in risk_conditions if item)
        return (
            "late_cycle_risk_off",
            min(0.95, 0.55 + 0.15 * hits),
            f"Mapped to risk-off because {mapping_return_text}, observed drawdown, or environment indicates stress.",
        )

    energy_signal = _energy_signal(analogue)
    if _scenario_available("oil_inflation_tail", available_scenarios) and energy_signal:
        mixed_or_negative_market = mapping_return is None or mapping_return <= 2.0
        confidence = 0.55 if mixed_or_negative_market else 0.40
        return (
            "oil_inflation_tail",
            confidence,
            "Mapped to oil/inflation tail because energy or oil leadership appears in the analogue row.",
        )

    broad_positive = bool(
        mapping_return is not None
        and mapping_return > 0
        and sectors_green is not None
        and sectors_green >= 6
        and (vix_level is None or vix_level < 25)
    )
    env_broad = any(token in env for token in ["risk-on", "risk on", "rotation", "broad", "mixed"])
    if _scenario_available("reopening_soft_landing", available_scenarios) and broad_positive and env_broad:
        confidence = 0.70
        if score_delta is not None and score_delta > 0:
            confidence += 0.10
        return (
            "reopening_soft_landing",
            min(0.90, confidence),
            f"Mapped to soft landing because {mapping_return_text} is positive with broad participation and contained VIX.",
        )

    narrow_positive = bool(
        mapping_return is not None
        and mapping_return > 0
        and (sectors_green is None or sectors_green < 6)
        and (vix_level is None or vix_level <= 25)
    )
    env_narrow = any(token in env for token in ["mixed", "neutral", "risk-on", "risk on", "rotation", "chop"])
    if _scenario_available("sticky_late_cycle_ai", available_scenarios) and narrow_positive and env_narrow:
        return (
            "sticky_late_cycle_ai",
            0.55,
            f"Mapped to sticky late-cycle AI proxy because {mapping_return_text} is positive but breadth is narrow.",
        )

    ai_rollover_proxy = bool(mapping_return is not None and mapping_return < 0 and _technology_weakness(analogue))
    if _scenario_available("ai_capex_rollover", available_scenarios) and ai_rollover_proxy:
        return (
            "ai_capex_rollover",
            0.45,
            f"Mapped to AI capex rollover proxy because {mapping_return_text} is negative and technology/semis leadership is weak.",
        )

    if mapping_return is not None and mapping_return < 0 and _scenario_available("late_cycle_risk_off", available_scenarios):
        return (
            "late_cycle_risk_off",
            0.45,
            f"Fallback mapped to risk-off because {mapping_return_text} was negative.",
        )
    if (
        mapping_return is not None
        and mapping_return > 0
        and sectors_green is not None
        and sectors_green >= 6
        and _scenario_available("reopening_soft_landing", available_scenarios)
    ):
        return (
            "reopening_soft_landing",
            0.45,
            f"Fallback mapped to soft landing because {mapping_return_text} was positive with broad participation.",
        )
    if _scenario_available("sticky_late_cycle_ai", available_scenarios):
        return (
            "sticky_late_cycle_ai",
            0.35,
            "Fallback mapped to sticky late-cycle AI proxy because scenario-specific evidence was incomplete.",
        )
    return (
        available_scenarios[0],
        0.25,
        "Fallback mapped to first available scenario because no deterministic rule matched.",
    )


def _mapping_display_fields(
    scenario_id: str,
    rationale: str,
) -> tuple[str, str]:
    text = rationale.lower()
    if "energy" in text or "oil" in text:
        return "energy_leadership", "Energy leadership"
    if "technology" in text or "semis" in text or "ai capex rollover" in text:
        return "ai_proxy_weak", "AI proxy weak"
    if "observed drawdown" in text or "drawdown" in text:
        return "stress_drawdown", "Stress drawdown"
    if "broad participation" in text and "positive" in text:
        return "positive_broad", "Positive + broad"
    if "breadth is narrow" in text:
        return "positive_narrow", "Positive + narrow"
    if "fallback" in text and "positive" in text:
        return "fallback_positive", "Fallback positive"
    if "fallback" in text and "negative" in text:
        return "fallback_negative", "Fallback negative"
    if scenario_id == "late_cycle_risk_off":
        return "negative_forward", "Risk-off return"
    if "fallback" in text:
        return "low_confidence", "Low confidence"
    return "low_confidence", "Low confidence"


def _match_from_analogue(
    analogue: Mapping[str, Any],
    available_scenarios: list[str],
    config: HistoricalCalibrationConfig,
    warnings: list[str] | None = None,
) -> HistoricalAnalogueMatch:
    overlap_horizons: list[str] = []
    if config.exclude_shock_windows:
        try:
            from src.analysis.analogues import shock_overlap_horizons

            overlap_horizons = shock_overlap_horizons(
                analogue.get("date"),
                horizons=TACTICAL_ANALOGUE_HORIZONS + list(config.macro_horizons),
                shock_windows=_shock_windows_for_engine(config),
            )
        except Exception:
            overlap_horizons = []
    scenario_id, confidence, rationale = map_analogue_to_scenario(
        dict(analogue),
        available_scenarios,
        scenario_mapping_horizon=config.scenario_mapping_horizon,
        warnings=warnings,
    )
    mapping_tag, mapping_short = _mapping_display_fields(scenario_id, rationale)
    return HistoricalAnalogueMatch(
        date=str(analogue.get("date") or "unknown"),
        composite_weight=_safe_float(analogue.get("composite_weight")),
        similarity_score=_safe_float(analogue.get("similarity_score")),
        score_total=_safe_float(analogue.get("score_total")),
        environment=str(analogue.get("environment")) if analogue.get("environment") is not None else None,
        vix_level=_safe_float(analogue.get("vix_level")),
        sectors_green=_safe_int(analogue.get("sectors_green")),
        score_delta=_safe_float(analogue.get("score_delta")),
        forward_returns=_dict_float_values(analogue.get("forward_returns")),
        risk_profile=_dict_float_values(analogue.get("risk_profile")),
        score_components=_dict_float_values(analogue.get("score_components")),
        sector_returns=_dict_float_values(analogue.get("sector_returns")),
        mapped_scenario_id=scenario_id,
        mapped_scenario_confidence=confidence,
        mapping_rationale=rationale,
        mapping_tag=mapping_tag,
        mapping_rationale_short=mapping_short,
        mapping_rationale_full=rationale,
        v1_similarity=_safe_float(analogue.get("v1_similarity")),
        detailed_similarity=_safe_float(analogue.get("detailed_similarity")),
        blended_similarity=_safe_float(analogue.get("blended_similarity")),
        strongest_matching_groups=[
            str(item)
            for item in (analogue.get("strongest_matching_groups") or [])
        ],
        weakest_matching_groups=[
            str(item)
            for item in (analogue.get("weakest_matching_groups") or [])
        ],
        feature_coverage=dict(analogue.get("feature_coverage") or {}),
        shock_window_overlap_horizons=overlap_horizons,
        excluded_from_scenario_mapping=_mapping_excluded_by_shock_window(analogue, config),
    )


def _forward_stats_from_mapping(values_by_horizon: Mapping[str, Any]) -> dict[str, AnalogueForwardStats]:
    stats: dict[str, AnalogueForwardStats] = {}
    for horizon, values in values_by_horizon.items():
        if not isinstance(values, Mapping):
            continue
        stats[str(horizon)] = AnalogueForwardStats(
            horizon=str(horizon),
            n=int(values.get("n") or 0),
            weight_sum=_safe_float(values.get("weight_sum")),
            median=_safe_float(values.get("median")),
            mean=_safe_float(values.get("mean")),
            pct_positive=_safe_float(values.get("pct_positive")),
            p10=_safe_float(values.get("p10")),
            p25=_safe_float(values.get("p25")),
            p75=_safe_float(values.get("p75")),
            p90=_safe_float(values.get("p90")),
            worst=_safe_float(values.get("worst")),
            best=_safe_float(values.get("best")),
        )
    return stats


def _forward_stats_from_aggregate(aggregate_stats: Mapping[str, Any]) -> dict[str, AnalogueForwardStats]:
    forward = aggregate_stats.get("forward_returns") if isinstance(aggregate_stats, Mapping) else {}
    if not isinstance(forward, Mapping):
        return {}
    return _forward_stats_from_mapping(forward)


def _ordered_subset_stats(
    stats: Mapping[str, AnalogueForwardStats],
    horizons: list[str],
) -> dict[str, AnalogueForwardStats]:
    return {
        horizon: stats[horizon]
        for horizon in horizons
        if horizon in stats
    }


def _sample_sizes(stats: Mapping[str, AnalogueForwardStats]) -> dict[str, int]:
    return {
        horizon: int(item.n)
        for horizon, item in stats.items()
    }


def _conditions_from_state(
    regime_state: RegimeState,
    market_state: Any | None,
) -> dict[str, Any]:
    def market_attr(name: str) -> Any:
        return getattr(market_state, name, None) if market_state is not None else None

    vix = _safe_float(market_attr("vix_level"))
    if vix is None:
        vix = _safe_float(regime_state.layers.volatility.inputs.get("vix_level"))
    sectors_green = _safe_int(market_attr("sectors_green"))
    if sectors_green is None:
        sectors_green = _safe_int(regime_state.layers.breadth.inputs.get("sectors_green"))
    score_delta = _safe_float(market_attr("score_delta"))

    return {
        "environment": str(market_attr("environment") or regime_state.environment or regime_state.regime_label),
        "score_total": _safe_float(market_attr("score_total")) or float(regime_state.composite),
        "vix_level": vix,
        "sectors_green": sectors_green,
        "score_delta": score_delta,
        "confidence": _safe_float(market_attr("confidence")) or float(regime_state.composite_confidence),
    }


def _call_historical_engine(
    config: HistoricalCalibrationConfig,
    regime_state: RegimeState,
    market_state: Any | None,
    forecast_input_set: ForecastInputSet | None = None,
) -> dict[str, Any]:
    if config.method in {"rolling_composite", "hybrid"}:
        from src.analysis.rolling_composite import get_rolling_composite

        current_features = None
        feature_specs = None
        current_feature_diagnostics: dict[str, Any] = {}
        detailed_warnings: list[str] = []
        use_detailed_similarity = False
        if config.use_detailed_analogues and forecast_input_set is not None:
            from src.analysis.detailed_analogue_similarity import (
                build_current_feature_vector_for_analogues,
                diagnose_forecast_input_set_for_analogue_features,
                feature_specs_from_forecast_input_set,
            )

            current_feature_diagnostics = diagnose_forecast_input_set_for_analogue_features(forecast_input_set)
            current_features = build_current_feature_vector_for_analogues(
                forecast_input_set,
                regime_state=regime_state,
                market_state=market_state,
            )
            feature_specs = feature_specs_from_forecast_input_set(forecast_input_set)
            raw_features_used = len(current_feature_diagnostics.get("raw_signals_used_for_similarity") or [])
            if raw_features_used == 0:
                current_features = None
                feature_specs = None
                detailed_warnings.append(
                    "Detailed analogue mode enabled but no raw current features with historical mappings were available; "
                    "falling back to V1 broad-state analogues."
                )
            else:
                use_detailed_similarity = True
                if raw_features_used < 3:
                    detailed_warnings.append(
                        "Detailed analogue mode enabled but too few raw current features were available; "
                        "V2 similarity may be unreliable."
                    )
        result = get_rolling_composite(
            asof_date=regime_state.asof_date,
            lookback_days=config.lookback_days,
            half_life=config.half_life,
            top_n_per_lookup=config.top_n_per_lookup,
            pool_top_n=config.pool_top_n,
            current_state_lookup_weight=config.current_state_lookup_weight,
            exclude_recent_days=config.exclude_recent_days,
            macro_horizons=config.macro_horizons,
            use_detailed_similarity=bool(use_detailed_similarity and current_features),
            current_features=current_features,
            feature_specs=feature_specs,
            v1_weight=config.v1_similarity_weight,
            v2_weight=config.v2_similarity_weight,
            candidate_pool_n=config.candidate_pool_n,
            exclude_shock_windows=config.exclude_shock_windows,
            shock_window_mode=config.shock_window_mode,
            shock_windows=_shock_windows_for_engine(config),
        )
        if current_feature_diagnostics:
            result["current_feature_diagnostics"] = current_feature_diagnostics
        if detailed_warnings:
            result["warnings"] = list(dict.fromkeys([*(result.get("warnings") or []), *detailed_warnings]))
        return result

    conditions = _conditions_from_state(regime_state, market_state)
    if config.method == "single_date":
        from src.analysis.analogues import get_historical_analogues

        asof_dt = datetime.strptime(regime_state.asof_date, "%Y-%m-%d")
        exclude_before = (asof_dt - timedelta(days=config.exclude_recent_days)).strftime("%Y-%m-%d")
        return get_historical_analogues(
            environment=conditions["environment"],
            score_total=conditions["score_total"],
            vix_level=conditions["vix_level"],
            sectors_green=conditions["sectors_green"],
            score_delta=conditions["score_delta"],
            confidence=conditions["confidence"],
            top_n=config.pool_top_n,
            exclude_before=exclude_before,
            shock_windows=_shock_windows_for_engine(config),
            shock_window_mode=config.shock_window_mode,
        )

    from src.analysis.conditional_probability import get_conditional_stats

    conditional = get_conditional_stats(
        environment=conditions["environment"],
        score_total=conditions["score_total"],
        vix_level=conditions["vix_level"],
        sectors_green=conditions["sectors_green"],
        score_delta=conditions["score_delta"],
        confidence=conditions["confidence"],
    )
    multi_factor = conditional.get("multi_factor", {})
    return {
        "asof_date": regime_state.asof_date,
        "analogues": [],
        "aggregate_stats": {
            "n_analogues": int(multi_factor.get("n") or 0) if isinstance(multi_factor, Mapping) else 0,
            "forward_returns": {
                key: value
                for key, value in (multi_factor.items() if isinstance(multi_factor, Mapping) else [])
                if isinstance(value, Mapping)
            },
            "available_horizons": conditional.get("available_horizons") or [],
            "missing_horizons": conditional.get("missing_horizons") or [],
            "warnings": conditional.get("warnings") or [],
            "risk_profile": conditional.get("risk_profile") or {},
            "environment_distribution": {},
        },
        "available_horizons": conditional.get("available_horizons") or [],
        "missing_horizons": conditional.get("missing_horizons") or [],
        "warnings": conditional.get("warnings") or [],
        "conditions_summary": conditional.get("plain_english_summary") or conditional.get("condition_description"),
    }


def _forecast_input_similarity_diagnostics(
    forecast_input_set: ForecastInputSet | None,
    raw_result: Mapping[str, Any],
) -> dict[str, Any]:
    current_feature_diagnostics = raw_result.get("current_feature_diagnostics") if isinstance(raw_result, Mapping) else {}
    if not isinstance(current_feature_diagnostics, Mapping):
        current_feature_diagnostics = {}

    group_summary = raw_result.get("group_similarity_summary") if isinstance(raw_result, Mapping) else {}
    if not isinstance(group_summary, Mapping):
        group_summary = {}

    features_used_by_group: dict[str, list[str]] = {}
    missing_features_by_group: dict[str, list[str]] = {}
    for group, values in group_summary.items():
        if not isinstance(values, Mapping):
            continue
        features_used_by_group[str(group)] = [str(item) for item in values.get("top_features_used") or []]
        missing_features_by_group[str(group)] = [str(item) for item in values.get("top_features_missing") or []]

    raw_signal_ids_used: list[str] = [
        str(item)
        for item in (current_feature_diagnostics.get("raw_signals_used_for_similarity") or [])
    ]
    raw_signal_ids_missing: list[str] = [
        str(item)
        for item in (current_feature_diagnostics.get("raw_signals_missing_historical_column") or [])
    ]
    if forecast_input_set is not None and not current_feature_diagnostics:
        all_missing = {
            feature_id
            for feature_ids in missing_features_by_group.values()
            for feature_id in feature_ids
        }
        for signal in forecast_input_set.raw_component_signals:
            if not signal.used_in_historical_similarity:
                continue
            feature_id = signal.historical_feature_id or signal.input_id
            if feature_id in raw_signal_ids_used or feature_id in raw_signal_ids_missing:
                continue
            if feature_id in all_missing:
                raw_signal_ids_missing.append(feature_id)
            else:
                raw_signal_ids_used.append(feature_id)

    return {
        "current_features_count": int(current_feature_diagnostics.get("current_features_count") or 0),
        "current_features_by_group": current_feature_diagnostics.get("current_features_by_group") or {},
        "features_used_by_group": features_used_by_group,
        "missing_features_by_group": missing_features_by_group,
        "raw_signal_ids_used_in_similarity": sorted(dict.fromkeys(raw_signal_ids_used)),
        "raw_signal_ids_missing_from_history": sorted(dict.fromkeys(raw_signal_ids_missing)),
        "raw_signals_used_for_similarity": current_feature_diagnostics.get("raw_signals_used_for_similarity") or [],
        "raw_signals_missing_values": current_feature_diagnostics.get("raw_signals_missing_values") or [],
        "raw_signals_missing_historical_column": current_feature_diagnostics.get("raw_signals_missing_historical_column") or [],
    }


def _historical_probabilities_from_matches(
    matches: list[HistoricalAnalogueMatch],
    raw_analogues: list[Mapping[str, Any]],
    scenario_ids: list[str],
    config: HistoricalCalibrationConfig,
) -> tuple[dict[str, float], dict[str, float], dict[str, int], dict[str, float]]:
    support = {scenario_id: 0.0 for scenario_id in scenario_ids}
    counts = {scenario_id: 0 for scenario_id in scenario_ids}
    confidence_sums = {scenario_id: 0.0 for scenario_id in scenario_ids}
    for match, analogue in zip(matches, raw_analogues):
        scenario_id = match.mapped_scenario_id
        if scenario_id not in support:
            continue
        weight = _historical_weight(analogue)
        support[scenario_id] += weight
        counts[scenario_id] += 1
        confidence_sums[scenario_id] += float(match.mapped_scenario_confidence or 0.0) * weight

    probabilities = _normalize(support)
    if config.historical_probability_floor > 0 and probabilities:
        floored = {
            scenario_id: max(probabilities.get(scenario_id, 0.0), config.historical_probability_floor)
            for scenario_id in scenario_ids
        }
        probabilities = _normalize(floored)
    avg_confidence = {
        scenario_id: (
            confidence_sums[scenario_id] / support[scenario_id]
            if support[scenario_id] > 0
            else 0.25 if scenario_id == "ai_capex_rollover" else 0.35
        )
        for scenario_id in scenario_ids
    }
    return probabilities, support, counts, avg_confidence


def calibrate_macro_forecast_with_analogs(
    forecast_result: MacroForecastResult,
    regime_state: RegimeState,
    market_state: Any | None = None,
    forecast_input_set: ForecastInputSet | None = None,
    config: HistoricalCalibrationConfig | None = None,
) -> HistoricalCalibrationResult:
    """Calibrate deterministic macro scenario probabilities with historical analogues."""

    config = config or HistoricalCalibrationConfig()
    deterministic = dict(forecast_result.scenario_probabilities)
    scenario_ids = list(deterministic)

    if not config.enabled:
        return HistoricalCalibrationResult(
            enabled=False,
            method=config.method,
            asof_date=forecast_result.asof_date,
            n_analogues=0,
            n_unique_analogues=None,
            n_pooled=None,
            forward_return_stats={},
            tactical_forward_return_stats={},
            macro_forward_return_stats={},
            available_horizons=[],
            missing_horizons=[],
            horizon_sample_sizes={},
            analogue_version="disabled",
            detailed_analogue_diagnostics={},
            risk_profile={},
            environment_distribution={},
            top_analogues=[],
            scenario_calibrations=[],
            blended_scenario_probabilities=deterministic,
            confidence=0.0,
            warnings=["Historical calibration disabled."],
            methodology_notes=METHODOLOGY_NOTES,
        )

    warnings: list[str] = []
    if config.use_detailed_analogues and forecast_input_set is None:
        warnings.append("Detailed analogue similarity requested but ForecastInputSet was unavailable; using V1 broad-state analogues.")
    try:
        raw_result = _call_historical_engine(config, regime_state, market_state, forecast_input_set)
    except Exception as exc:
        if not config.fallback_to_display_only:
            raise
        warnings.append(f"Historical calibration failed and was kept display-only: {exc}")
        raw_result = {
            "asof_date": forecast_result.asof_date,
            "analogues": [],
            "aggregate_stats": {},
            "conditions_summary": None,
        }

    raw_analogues = [
        analogue
        for analogue in (raw_result.get("analogues") or [])
        if isinstance(analogue, Mapping)
    ]
    warnings.extend(str(item) for item in (raw_result.get("warnings") or []))
    aggregate = raw_result.get("aggregate_stats") if isinstance(raw_result.get("aggregate_stats"), Mapping) else {}
    if isinstance(aggregate, Mapping):
        warnings.extend(str(item) for item in (aggregate.get("warnings") or []))
    all_matches = [
        _match_from_analogue(analogue, scenario_ids, config, warnings=warnings)
        for analogue in raw_analogues
    ]

    scenario_mapping_excluded_dates: list[str] = []
    mapped_pairs: list[tuple[HistoricalAnalogueMatch, Mapping[str, Any]]] = []
    for match, analogue in zip(all_matches, raw_analogues):
        if _mapping_excluded_by_shock_window(analogue, config):
            scenario_mapping_excluded_dates.append(str(analogue.get("date") or match.date))
            continue
        mapped_pairs.append((match, analogue))
    if scenario_mapping_excluded_dates:
        warnings.append(
            f"Shock-window filter excluded {len(scenario_mapping_excluded_dates)} analogue(s) from "
            f"{config.scenario_mapping_horizon} scenario mapping."
        )

    matches = [match for match, _ in mapped_pairs]
    mapping_raw_analogues = [analogue for _, analogue in mapped_pairs]
    n_analogues_raw = int(aggregate.get("n_analogues") or len(all_matches))
    n_analogues = len(matches) if scenario_mapping_excluded_dates else n_analogues_raw
    n_pooled = _safe_int(raw_result.get("n_pooled")) or len(matches)
    n_unique = _safe_int(raw_result.get("n_unique_analogues"))
    analogue_version = str(raw_result.get("analogue_version") or "v1_broad_state")
    shock_window_diagnostics = {
        "enabled": bool(config.exclude_shock_windows),
        "mode": config.shock_window_mode,
        "windows": _shock_windows_for_engine(config),
    }
    if isinstance(aggregate, Mapping):
        shock_window_diagnostics.update(dict(aggregate.get("shock_window_diagnostics") or {}))
    shock_window_diagnostics.update(dict(raw_result.get("shock_window_diagnostics") or {}))
    shock_window_diagnostics.update(
        {
            "scenario_mapping_horizon": config.scenario_mapping_horizon,
            "scenario_mapping_excluded_dates": scenario_mapping_excluded_dates,
            "scenario_mapping_excluded_count": len(scenario_mapping_excluded_dates),
        }
    )
    detailed_diagnostics = {
        "analogue_version": analogue_version,
        "v1_weight": raw_result.get("v1_weight", config.v1_similarity_weight if config.use_detailed_analogues else None),
        "v2_weight": raw_result.get("v2_weight", config.v2_similarity_weight if config.use_detailed_analogues else None),
        "candidate_pool_n": raw_result.get("candidate_pool_n", config.candidate_pool_n if config.use_detailed_analogues else None),
        "average_detailed_similarity": raw_result.get("average_detailed_similarity"),
        "average_blended_similarity": raw_result.get("average_blended_similarity"),
        "group_similarity_summary": raw_result.get("group_similarity_summary") or {},
        "feature_coverage_summary": raw_result.get("feature_coverage_summary") or {},
        "strongest_match_groups": raw_result.get("strongest_match_groups") or [],
        "weakest_match_groups": raw_result.get("weakest_match_groups") or [],
        "missing_important_features": raw_result.get("missing_important_features") or [],
        "effective_sample_size": raw_result.get("effective_sample_size"),
    }
    detailed_diagnostics.update(_forecast_input_similarity_diagnostics(forecast_input_set, raw_result))
    if config.use_detailed_analogues and analogue_version == "v2_detailed":
        group_summary = detailed_diagnostics.get("group_similarity_summary") or {}
        for group, warning in {
            "volatility": "Volatility detailed analogue features are missing or sparse.",
            "commodities_oil": "commodities_oil group is missing or sparse while oil-tail calibration may be active.",
            "rates_fx": "rates_fx group is missing or sparse while Fed path/rates drivers may be active.",
            "theme_catalysts": "theme_catalysts group is missing or sparse while AI capex scenario calibration may be active.",
        }.items():
            values = group_summary.get(group) if isinstance(group_summary, Mapping) else None
            coverage = _safe_float(values.get("coverage")) if isinstance(values, Mapping) else None
            if coverage is None or coverage < 0.25:
                warnings.append(warning)

    unfiltered_historical = None
    if scenario_mapping_excluded_dates:
        unfiltered_historical, _, _, _ = _historical_probabilities_from_matches(
            all_matches,
            raw_analogues,
            scenario_ids,
            config,
        )
    historical, support, counts, scenario_confidence = _historical_probabilities_from_matches(
        matches,
        mapping_raw_analogues,
        scenario_ids,
        config,
    )
    shock_probabilities_changed = False
    if unfiltered_historical is not None:
        shock_probabilities_changed = any(
            abs(unfiltered_historical.get(scenario_id, 0.0) - historical.get(scenario_id, 0.0)) > 1e-9
            for scenario_id in scenario_ids
        )
        shock_window_diagnostics["historical_probabilities_before_shock_filter"] = unfiltered_historical
        shock_window_diagnostics["historical_probabilities_after_shock_filter"] = historical
    shock_window_diagnostics["historical_probabilities_changed"] = shock_probabilities_changed
    detailed_diagnostics["shock_window_diagnostics"] = shock_window_diagnostics
    det_weight, hist_weight = _renormalize_blend_weights(config)
    ess = _safe_float(raw_result.get("effective_sample_size"))
    avg_coverage = None
    feature_coverage_summary = raw_result.get("feature_coverage_summary")
    if isinstance(feature_coverage_summary, Mapping):
        avg_coverage = _safe_float(feature_coverage_summary.get("average_coverage"))
    if config.use_detailed_analogues:
        if avg_coverage is not None and avg_coverage < config.min_feature_coverage:
            warnings.append(
                f"Detailed analogue feature coverage {avg_coverage:.1%} is below minimum {config.min_feature_coverage:.1%}."
            )
        if ess is not None and ess < config.min_effective_sample_size:
            warnings.append(
                f"Detailed analogue effective sample size {ess:.1f} is below minimum {config.min_effective_sample_size}."
            )
            if config.reduce_weight_on_low_ess:
                scale = max(0.0, ess / max(1, config.min_effective_sample_size))
                hist_weight *= scale
                if config.historical_weight > 0 and hist_weight > 0:
                    hist_weight = max(hist_weight, config.min_historical_weight_after_penalty)
                total_weight = det_weight + hist_weight
                if total_weight > 0:
                    det_weight /= total_weight
                    hist_weight /= total_weight
                detailed_diagnostics["historical_weight_scale"] = round(scale, 3)
                detailed_diagnostics["adjusted_deterministic_weight"] = round(det_weight, 3)
                detailed_diagnostics["adjusted_historical_weight"] = round(hist_weight, 3)
    insufficient = n_analogues < config.min_analogue_count
    if insufficient:
        warning = (
            f"Only {n_analogues} analogue(s) available; minimum is {config.min_analogue_count}."
        )
        warnings.append(warning)
        blended = dict(deterministic) if config.fallback_to_display_only else _normalize(
            {
                scenario_id: det_weight * deterministic.get(scenario_id, 0.0)
                + hist_weight * historical.get(scenario_id, 0.0)
                for scenario_id in scenario_ids
            }
        )
    else:
        blended = _normalize(
            {
                scenario_id: det_weight * deterministic.get(scenario_id, 0.0)
                + hist_weight * historical.get(scenario_id, 0.0)
                for scenario_id in scenario_ids
            }
        )

    calibrations: list[HistoricalScenarioCalibration] = []
    for scenario_id in scenario_ids:
        hist_prob = historical.get(scenario_id, 0.0)
        blended_prob = blended.get(scenario_id, deterministic.get(scenario_id, 0.0))
        support_weight = support.get(scenario_id, 0.0)
        confidence = scenario_confidence.get(scenario_id, 0.0)
        if insufficient and config.fallback_to_display_only:
            confidence *= 0.50
        rationale = (
            f"{SCENARIO_LABELS.get(scenario_id, scenario_id)} received "
            f"{counts.get(scenario_id, 0)} mapped analogue(s), weighted support {support_weight:.3f}. "
            f"Historical probability {hist_prob:.1%}; deterministic probability "
            f"{deterministic.get(scenario_id, 0.0):.1%}; blended probability {blended_prob:.1%}."
        )
        if scenario_id == "ai_capex_rollover":
            rationale += " Mapping confidence is structurally lower without explicit historical AI capex/theme labels."
        calibrations.append(
            HistoricalScenarioCalibration(
                scenario_id=scenario_id,
                deterministic_probability=deterministic.get(scenario_id, 0.0),
                historical_probability=hist_prob,
                blended_probability=blended_prob,
                analog_effect=blended_prob - deterministic.get(scenario_id, 0.0),
                n_supporting_analogues=counts.get(scenario_id, 0),
                weighted_support=support_weight,
                confidence=max(0.0, min(1.0, confidence)),
                rationale=rationale,
            )
        )

    mapping_confidences = [
        float(match.mapped_scenario_confidence or 0.0)
        for match in matches
        if match.mapped_scenario_confidence is not None
    ]
    count_confidence = min(1.0, n_analogues / max(1, config.min_analogue_count))
    mapping_confidence = sum(mapping_confidences) / len(mapping_confidences) if mapping_confidences else 0.0
    confidence = max(0.0, min(1.0, count_confidence * (0.5 + 0.5 * mapping_confidence)))
    if insufficient and config.fallback_to_display_only:
        confidence *= 0.50

    environment_distribution = aggregate.get("environment_distribution") if isinstance(aggregate, Mapping) else {}
    if not isinstance(environment_distribution, Mapping):
        environment_distribution = {}

    forward_stats = _forward_stats_from_aggregate(aggregate)
    tactical_stats = _ordered_subset_stats(forward_stats, TACTICAL_ANALOGUE_HORIZONS)
    macro_stats = _ordered_subset_stats(forward_stats, list(config.macro_horizons))

    aggregate_available = aggregate.get("available_horizons") if isinstance(aggregate, Mapping) else None
    raw_available = raw_result.get("available_horizons") if isinstance(raw_result, Mapping) else None
    available_horizons = [
        str(item)
        for item in (aggregate_available or raw_available or list(forward_stats))
    ]
    aggregate_missing = aggregate.get("missing_horizons") if isinstance(aggregate, Mapping) else None
    raw_missing = raw_result.get("missing_horizons") if isinstance(raw_result, Mapping) else None
    missing_horizons = [
        str(item)
        for item in (aggregate_missing or raw_missing or [])
    ]
    for horizon in list(TACTICAL_ANALOGUE_HORIZONS) + list(config.macro_horizons):
        if horizon not in forward_stats and horizon not in missing_horizons:
            missing_horizons.append(horizon)
            warnings.append(f"Requested analogue horizon {horizon} unavailable in historical aggregate output.")

    horizon_sample_sizes = dict(aggregate.get("horizon_sample_sizes") or {}) if isinstance(aggregate, Mapping) else {}
    if not horizon_sample_sizes:
        horizon_sample_sizes = _sample_sizes(forward_stats)

    deduped_warnings: list[str] = []
    for warning in warnings:
        if warning and warning not in deduped_warnings:
            deduped_warnings.append(warning)

    return HistoricalCalibrationResult(
        enabled=True,
        method=config.method,
        asof_date=str(raw_result.get("asof_date") or forecast_result.asof_date),
        conditions_summary=raw_result.get("conditions_summary") or raw_result.get("conditions_matched"),
        n_analogues=n_analogues,
        n_unique_analogues=n_unique,
        n_pooled=n_pooled,
        forward_return_stats=forward_stats,
        tactical_forward_return_stats=tactical_stats,
        macro_forward_return_stats=macro_stats,
        available_horizons=available_horizons,
        missing_horizons=missing_horizons,
        horizon_sample_sizes={str(key): int(value or 0) for key, value in horizon_sample_sizes.items()},
        analogue_version=analogue_version,
        detailed_analogue_diagnostics=detailed_diagnostics,
        shock_window_diagnostics=shock_window_diagnostics,
        risk_profile=dict(aggregate.get("risk_profile") or {}) if isinstance(aggregate, Mapping) else {},
        environment_distribution={str(key): float(value) for key, value in environment_distribution.items()},
        top_analogues=matches[:10],
        scenario_calibrations=calibrations,
        blended_scenario_probabilities=blended,
        confidence=confidence,
        warnings=deduped_warnings,
        methodology_notes=METHODOLOGY_NOTES,
    )
