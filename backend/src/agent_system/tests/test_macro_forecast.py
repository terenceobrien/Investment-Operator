from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_system.forecasting.input_signals import (
    assess_layer_signal,
    build_forecast_input_set,
    build_macro_input_signals,
    build_market_tape_signals_from_market_state,
    build_raw_component_signals_from_regime_inputs,
)
from src.agent_system.forecasting.macro_forecast_runner import (
    DEFAULT_SCENARIO_PRIORS,
    MacroForecastRunConfig,
    format_macro_forecast_report,
    run_macro_forecast,
)
from src.agent_system.forecasting.research_agenda_builder import (
    build_research_priorities_from_theme_forecasts,
)
from src.agent_system.forecasting.scenario_probability_engine import (
    update_scenario_probabilities,
)
from src.agent_system.forecasting.theme_exposure_matrix import (
    rank_factors,
    rank_sectors,
    rank_themes,
)
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.macro_forecast import (
    InputDedupeConfig,
    MacroForecastResult,
    MacroInputSignal,
    ScenarioImpact,
    ScenarioProbabilityConfig,
    ThemeForecast,
)
from src.agent_system.schemas.regime import RegimeLayerStatus
from src.agent_system.storage.repository import save_schema
from src.state.market_state import MarketState
from src.state.regime_data import RegimeInputs


def _impact(scenario_id: str, direction: str, strength: float) -> ScenarioImpact:
    return ScenarioImpact(
        scenario_id=scenario_id,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,
        rationale=f"{direction} {scenario_id} for test",
    )


def _signal(
    *impacts: ScenarioImpact,
    input_id: str = "test_signal",
    confidence: float = 1.0,
    used_in_probability_update: bool = True,
) -> MacroInputSignal:
    return MacroInputSignal(
        input_id=input_id,
        name="Test signal",
        category="credit",
        current_value=1.0,
        unit=None,
        percentile=None,
        z_score=None,
        trend="stable",
        signal="bullish",
        confidence=confidence,
        data_quality="high",
        last_updated=None,
        affected_scenarios=list(impacts),
        affected_themes=[],
        notes="test signal",
        used_in_probability_update=used_in_probability_update,
    )


def _posterior(updates, scenario_id: str) -> float:
    return next(
        update.posterior_probability
        for update in updates
        if update.scenario_id == scenario_id
    )


def _theme_forecast(
    theme_id: str,
    label: str,
    macro_support_score: float,
    *,
    final_score: float | None = None,
    crowding_score: float | None = None,
) -> ThemeForecast:
    return ThemeForecast(
        theme_id=theme_id,
        label=label,
        probability_weighted_score=macro_support_score,
        macro_score=macro_support_score,
        macro_support_score=macro_support_score,
        ranking_score=macro_support_score,
        crowding_score=crowding_score,
        final_score=macro_support_score if final_score is None else final_score,
        best_scenarios=["sticky_late_cycle_ai"],
        worst_scenarios=["late_cycle_risk_off"],
        positive_scenario_count=1,
        negative_scenario_count=1,
        positioning_assessment="unknown",
        narrative_assessment="unknown",
        rationale="test",
    )


def _raw_inputs_fixture() -> RegimeInputs:
    return RegimeInputs(
        asof_date="2026-06-05",
        net_liquidity_z=0.8,
        nfci_inverted=0.7,
        m2_growth_yoy=2.5,
        hy_spread_level=320,
        hy_spread_z=-0.7,
        hy_spread_chg_4w=45,
        ig_spread_level=95,
        ig_spread_z=-0.6,
        hyg_tlt_ratio_z=-0.8,
        vix_level=13.5,
        vix_z_20d=-0.6,
        vix_term_slope=4.5,
        vvix_level=112,
        vvix_z=1.2,
        put_call_ratio=1.15,
        skew_index=148,
        pct_above_200d=45,
        new_highs_minus_lows_z=-1.2,
        sectors_green=2,
        rsp_vs_spy_z=-1.1,
        adl_slope=-0.2,
        dealer_gamma_z=-1.2,
        put_call_5d_ma=1.05,
        aaii_bull_minus_bear=-25,
        cot_net_large_spec_z=2.2,
        equity_etf_flow_z=-2.3,
    )


def _market_state_fixture() -> MarketState:
    return MarketState(
        asof_utc="2026-06-05T00:00:00+00:00",
        horizon="1D",
        cross_asset_returns={
            "SPY": 0.4,
            "QQQ": 0.8,
            "IWM": -0.2,
            "TLT": 0.1,
            "HYG": 0.3,
            "GLD": 0.2,
            "USO": 1.0,
            "BTC-USD": 2.0,
            "RSP": 0.0,
        },
        sector_returns={"XLK": 1.0, "XLE": 0.5, "XLU": -0.1},
        leadership_top3=[("Technology", 1.0), ("Energy", 0.5), ("Industrials", 0.3)],
        sectors_green=3,
        dispersion=0.5,
        spy_clv=0.6,
        spy_range_pct=0.8,
        spy_vol_z_20d=1.1,
        volume_confirmation=0.7,
        vix_level=14.0,
        vix_z_20d=-0.5,
        vix_change_pct_1d=-3.0,
    )


def test_posterior_probabilities_sum_to_one():
    result = run_macro_forecast(make_stub_regime_state())

    assert round(sum(result.scenario_probabilities.values()), 10) == 1.0
    assert len(result.scenario_updates) == 5
    assert all(update.top_positive_contributors or update.top_negative_contributors for update in result.scenario_updates)


def test_positive_credit_signal_decreases_risk_off_probability():
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [
            _signal(
                _impact("late_cycle_risk_off", "decreases", 0.9),
                _impact("reopening_soft_landing", "increases", 0.3),
            )
        ],
    )

    assert _posterior(updates, "late_cycle_risk_off") < DEFAULT_SCENARIO_PRIORS["late_cycle_risk_off"]


def test_probability_floor_lifts_tail_scenarios_and_sums_to_one():
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [
            _signal(
                _impact("reopening_soft_landing", "increases", 1.0),
                _impact("late_cycle_risk_off", "decreases", 1.0),
                _impact("ai_capex_rollover", "decreases", 1.0),
            )
        ],
    )

    risk_off = next(update for update in updates if update.scenario_id == "late_cycle_risk_off")
    rollover = next(update for update in updates if update.scenario_id == "ai_capex_rollover")
    assert risk_off.posterior_probability >= 0.05
    assert rollover.posterior_probability >= 0.05
    assert risk_off.floor_applied or rollover.floor_applied
    assert round(sum(update.posterior_probability for update in updates), 10) == 1.0


def test_probability_constraints_leave_pre_floor_unchanged_when_not_breached():
    config = ScenarioProbabilityConfig(
        scenario_probability_floors={scenario_id: 0.001 for scenario_id in DEFAULT_SCENARIO_PRIORS},
        max_single_scenario_probability=None,
    )
    updates = update_scenario_probabilities(DEFAULT_SCENARIO_PRIORS, [], config=config)

    assert all(not update.floor_applied and not update.cap_applied for update in updates)
    assert all(
        update.posterior_probability == pytest.approx(update.pre_floor_posterior_probability)
        for update in updates
    )


def test_probability_cap_redistributes_excess():
    config = ScenarioProbabilityConfig(
        use_probability_floors=False,
        max_single_scenario_probability=0.40,
    )
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [
            _signal(_impact("reopening_soft_landing", "increases", 1.0), input_id="cap_1"),
            _signal(_impact("reopening_soft_landing", "increases", 1.0), input_id="cap_2"),
        ],
        config=config,
    )

    assert max(update.posterior_probability for update in updates) <= 0.400001
    assert any(update.cap_applied for update in updates)
    assert round(sum(update.posterior_probability for update in updates), 10) == 1.0


def test_level_assessment_separates_absolute_level_from_trend():
    weak_improving = assess_layer_signal(4.22, "improving", "Breadth")
    strong_stable = assess_layer_signal(8.2, "stable", "Credit")
    weak_deteriorating = assess_layer_signal(3.8, "deteriorating", "Breadth")
    neutral_improving = assess_layer_signal(5.6, "improving", "Monetary")

    assert weak_improving.absolute_status == "bearish"
    assert weak_improving.combined_signal == "mixed"
    assert "weak absolute level" in weak_improving.explanation
    assert strong_stable.combined_signal == "bullish"
    assert weak_deteriorating.combined_signal == "bearish"
    assert neutral_improving.combined_signal == "mixed"


def test_low_absolute_improving_breadth_reduces_positive_impact_strength():
    regime = make_stub_regime_state()
    breadth = regime.layers.breadth.model_copy_validate(
        {
            "score": 4.22,
            "signals": [],
            "status": RegimeLayerStatus.NEUTRAL,
        }
    )
    layers = regime.layers.model_copy_validate({"breadth": breadth})
    regime = regime.model_copy_validate({"layers": layers})

    signals = build_macro_input_signals(regime)
    breadth_signal = next(signal for signal in signals if signal.input_id == "market_breadth")
    reopening_impact = next(
        impact
        for impact in breadth_signal.affected_scenarios
        if impact.scenario_id == "reopening_soft_landing"
    )

    assert breadth_signal.signal == "mixed"
    assert breadth_signal.trend == "improving"
    assert reopening_impact.strength <= 0.25


def test_raw_component_extraction_from_regime_inputs():
    signals = build_raw_component_signals_from_regime_inputs(_raw_inputs_fixture())
    by_id = {signal.input_id: signal for signal in signals}

    for input_id in [
        "net_liquidity_z",
        "hy_spread_level",
        "hy_spread_chg_4w",
        "vix_level",
        "rsp_vs_spy_z",
        "dealer_gamma_z",
    ]:
        assert input_id in by_id
        assert by_id[input_id].role == "raw_component"
        assert by_id[input_id].raw_value is not None
        assert by_id[input_id].parent_layer is not None
        assert by_id[input_id].source_object == "RegimeInputs"
        assert by_id[input_id].level_status in {"bullish", "bearish", "neutral", "mixed"}

    assert by_id["hy_spread_chg_4w"].trend_status == "deteriorating"
    assert by_id["vix_level"].parent_layer == "volatility"
    assert by_id["rsp_vs_spy_z"].parent_layer == "breadth"


def test_market_tape_extraction_from_market_state():
    signals = build_market_tape_signals_from_market_state(_market_state_fixture())
    by_id = {signal.input_id: signal for signal in signals}

    assert "market_tape_spy_return" in by_id
    assert "market_tape_qqq_return" in by_id
    assert "market_tape_hyg_return" in by_id
    assert "rsp_minus_spy" in by_id
    assert "iwm_minus_spy" in by_id
    assert "hyg_minus_tlt" in by_id
    assert "qqq_minus_spy" in by_id
    assert "vix_level" in by_id
    assert all(signal.input_scope == "market_tape" for signal in signals)
    assert all(signal.parent_layer == "market_state" for signal in signals)
    assert all(signal.source_object == "MarketState" for signal in signals)


def test_forecast_input_set_includes_volatility_layer_and_raw_components():
    input_set = build_forecast_input_set(
        make_stub_regime_state(),
        raw_inputs=_raw_inputs_fixture(),
        market_state=_market_state_fixture(),
    )
    ids = {signal.input_id for signal in input_set.all_signals}

    assert input_set.all_signals
    assert "volatility_layer_summary" in ids
    assert "vix_level" in ids
    assert "rsp_minus_spy" in ids
    assert "hyg_minus_tlt" in ids
    assert input_set.methodology_notes
    assert any(signal.parent_layer == "volatility" for signal in input_set.raw_component_signals)
    volatility_layer = next(signal for signal in input_set.layer_summary_signals if signal.parent_layer == "volatility")
    assert "vix_level" in volatility_layer.child_signal_ids


def test_raw_component_falls_back_to_regime_state_source_object():
    base = make_stub_regime_state()
    volatility = base.layers.volatility.model_copy_validate(
        {
            "inputs": {
                **base.layers.volatility.inputs,
                "vix_level": 19.0,
                "vix_term_slope": 2.5,
            }
        }
    )
    layers = base.layers.model_copy_validate({"volatility": volatility})
    regime_state = base.model_copy_validate({"layers": layers})

    signals = build_raw_component_signals_from_regime_inputs(
        RegimeInputs(asof_date=base.asof_date),
        regime_state=regime_state,
    )
    by_id = {signal.input_id: signal for signal in signals}

    assert by_id["vix_level"].raw_value == pytest.approx(19.0)
    assert by_id["vix_level"].source_object == "RegimeState"


def test_hybrid_dedupe_caps_raw_component_modifiers():
    layer = _signal(
        _impact("sticky_late_cycle_ai", "increases", 0.6),
        input_id="credit_layer_summary",
    ).model_copy_validate(
        {
            "role": "layer_summary",
            "input_scope": "layer_summary",
            "parent_layer": "credit",
            "dedupe_group": "credit",
            "dedupe_role": "primary",
        }
    )
    raw = _signal(
        _impact("sticky_late_cycle_ai", "increases", 1.0),
        input_id="hy_spread_chg_4w",
    ).model_copy_validate(
        {
            "role": "raw_component",
            "input_scope": "raw_component",
            "parent_layer": "credit",
            "dedupe_group": "credit",
            "dedupe_role": "modifier",
        }
    )

    hybrid = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [layer, raw],
        dedupe_config=InputDedupeConfig(mode="hybrid", raw_component_cap_ratio=0.5),
    )
    sticky = next(update for update in hybrid if update.scenario_id == "sticky_late_cycle_ai")
    raw_contribution = next(item for item in sticky.contributions if item.input_id == "hy_spread_chg_4w")

    assert raw_contribution.capped_by_dedupe is True
    assert raw_contribution.adjusted_contribution == pytest.approx(0.18)

    layer_only = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [layer, raw],
        dedupe_config=InputDedupeConfig(mode="layer_only"),
    )
    raw_only = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [layer, raw],
        dedupe_config=InputDedupeConfig(mode="raw_only"),
    )
    assert {
        item.input_id
        for update in layer_only
        for item in update.contributions
    } == {"credit_layer_summary"}
    assert {
        item.input_id
        for update in raw_only
        for item in update.contributions
    } == {"hy_spread_chg_4w"}


def test_weak_breadth_increases_sticky_ai_or_risk_off_probability():
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [
            _signal(
                _impact("sticky_late_cycle_ai", "increases", 0.7),
                _impact("late_cycle_risk_off", "increases", 0.6),
                _impact("reopening_soft_landing", "decreases", 0.5),
            )
        ],
    )

    assert (
        _posterior(updates, "sticky_late_cycle_ai") > DEFAULT_SCENARIO_PRIORS["sticky_late_cycle_ai"]
        or _posterior(updates, "late_cycle_risk_off") > DEFAULT_SCENARIO_PRIORS["late_cycle_risk_off"]
    )


def test_ai_resilience_decreases_ai_capex_rollover_probability():
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [
            _signal(
                _impact("sticky_late_cycle_ai", "increases", 0.6),
                _impact("ai_capex_rollover", "decreases", 0.8),
            )
        ],
    )

    assert _posterior(updates, "ai_capex_rollover") < DEFAULT_SCENARIO_PRIORS["ai_capex_rollover"]


def test_monetary_composite_reconciles_bullish_layer_with_bearish_fed_path():
    signals = build_macro_input_signals(make_stub_regime_state())
    composite = next(signal for signal in signals if signal.input_id == "monetary_policy_composite")
    monetary_layer = next(signal for signal in signals if signal.input_id == "monetary_conditions")
    fed_path = next(signal for signal in signals if signal.input_id == "fed_path")

    assert composite.signal in {"mixed", "bearish"}
    assert composite.used_in_probability_update is True
    assert monetary_layer.used_in_probability_update is False
    assert fed_path.used_in_probability_update is False
    assert monetary_layer.parent_signal_id == composite.input_id
    assert fed_path.parent_signal_id == composite.input_id


def test_probability_engine_uses_composite_not_monetary_components():
    result = run_macro_forecast(make_stub_regime_state())
    contribution_ids = {
        contribution.input_id
        for update in result.scenario_updates
        for contribution in update.contributions
    }

    assert "monetary_policy_composite" in contribution_ids
    assert "monetary_conditions" not in contribution_ids
    assert "fed_path" not in contribution_ids


def test_theme_rankings_are_deterministic():
    probabilities = {
        "reopening_soft_landing": 0.20,
        "sticky_late_cycle_ai": 0.35,
        "oil_inflation_tail": 0.20,
        "late_cycle_risk_off": 0.15,
        "ai_capex_rollover": 0.10,
    }

    first = rank_themes(probabilities, [])
    second = rank_themes(probabilities, [])

    assert [item.theme_id for item in first] == [item.theme_id for item in second]
    assert [item.probability_weighted_score for item in first] == [
        item.probability_weighted_score for item in second
    ]


def test_theme_rankings_use_macro_support_only():
    result = run_macro_forecast(make_stub_regime_state())
    high_beta = next(item for item in result.theme_rankings if item.theme_id == "high_beta_ai_semis")

    assert high_beta.crowding_score is None
    assert high_beta.overlay_used_in_ranking is False
    assert high_beta.score_method == "macro_support_only"
    assert high_beta.final_score == pytest.approx(high_beta.macro_support_score)
    assert result.theme_rankings == sorted(
        result.theme_rankings,
        key=lambda item: (item.ranking_score, item.theme_id),
        reverse=True,
    )


def test_deprecated_overlay_fields_do_not_change_downstream_ranking_inputs():
    themes = [
        _theme_forecast(
            "grid_power_infrastructure",
            "Grid and power infrastructure",
            2.0,
            final_score=-5.0,
            crowding_score=-1.0,
        ),
        _theme_forecast(
            "quality_ai",
            "Quality AI leaders",
            1.0,
            final_score=10.0,
            crowding_score=1.0,
        ),
    ]

    sector = next(item for item in rank_sectors(themes) if item.item_id == "XLU")
    contribution = next(item for item in sector.contributions if item.source_id == "grid_power_infrastructure")

    assert contribution.source_score == pytest.approx(2.0)
    assert contribution.contribution == pytest.approx(2.0 * 0.65)


def test_recommended_priorities_generated_for_top_positive_themes():
    result = run_macro_forecast(make_stub_regime_state())

    assert len(result.recommended_research_priorities) == 3
    assert result.recommended_research_priorities[0].priority_rank == 1
    assert result.recommended_research_priorities[0].supporting_evidence


def test_research_agenda_builder_uses_theme_specific_language():
    updates = update_scenario_probabilities(DEFAULT_SCENARIO_PRIORS, [])
    themes = [
        ThemeForecast(
            theme_id="grid_power_infrastructure",
            label="Grid and power infrastructure",
            probability_weighted_score=2.0,
            macro_score=2.0,
            macro_support_score=2.0,
            ranking_score=2.0,
            crowding_score=-0.2,
            valuation_score=0.0,
            narrative_score=0.1,
            final_score=2.0,
            best_scenarios=["reopening_soft_landing", "sticky_late_cycle_ai"],
            worst_scenarios=["ai_capex_rollover"],
            positive_scenario_count=2,
            negative_scenario_count=1,
            positioning_assessment="unknown",
            narrative_assessment="improving",
            rationale="test",
        ),
        ThemeForecast(
            theme_id="quality_ex_ai_cash_flow",
            label="Quality ex-AI cash flow",
            probability_weighted_score=1.6,
            macro_score=1.6,
            macro_support_score=1.6,
            ranking_score=1.6,
            crowding_score=0.2,
            valuation_score=0.0,
            narrative_score=0.05,
            final_score=1.6,
            best_scenarios=["reopening_soft_landing"],
            worst_scenarios=["late_cycle_risk_off"],
            positive_scenario_count=1,
            negative_scenario_count=1,
            positioning_assessment="unknown",
            narrative_assessment="unknown",
            rationale="test",
        ),
        ThemeForecast(
            theme_id="quality_ai",
            label="Quality AI leaders",
            probability_weighted_score=1.3,
            macro_score=1.3,
            macro_support_score=1.3,
            ranking_score=1.3,
            crowding_score=-0.25,
            valuation_score=0.0,
            narrative_score=-0.1,
            final_score=1.3,
            best_scenarios=["sticky_late_cycle_ai"],
            worst_scenarios=["ai_capex_rollover"],
            positive_scenario_count=1,
            negative_scenario_count=1,
            positioning_assessment="neutral",
            narrative_assessment="improving",
            rationale="test",
        ),
    ]

    priorities = build_research_priorities_from_theme_forecasts(
        themes,
        updates,
        make_stub_regime_state(),
    )

    assert [priority.priority_rank for priority in priorities] == [1, 2, 3]
    assert len({priority.edge_hypothesis for priority in priorities}) == 3
    assert "Second-order grid" in priorities[0].theme
    assert "downstream" in priorities[0].rationale.lower()
    assert "under-owned" in priorities[1].rationale
    assert "capex-rollover" in priorities[2].theme
    joined = " ".join(priority.rationale for priority in priorities).lower()
    assert "overlay penalizes" not in joined
    assert "overlay gives" not in joined


def test_handles_missing_forward_context_gracefully():
    regime = make_stub_regime_state().model_copy_validate({"forward_context": None})
    result = run_macro_forecast(regime)

    fed_signal = next(signal for signal in result.input_signals if signal.input_id == "fed_path")
    assert fed_signal.data_quality == "absent"
    assert round(sum(result.scenario_probabilities.values()), 10) == 1.0


def test_contribution_attribution_is_complete_and_sorted():
    result = run_macro_forecast(make_stub_regime_state())

    for update in result.scenario_updates:
        assert update.contributions
        assert update.math_audit is not None
        assert update.net_contribution == pytest.approx(
            sum(item.adjusted_contribution for item in update.contributions)
        )
        assert update.total_positive_contribution >= 0
        assert update.total_negative_contribution <= 0
        positives = [item.contribution for item in update.top_positive_contributors]
        negatives = [abs(item.contribution) for item in update.top_negative_contributors]
        assert positives == sorted(positives, reverse=True)
        assert negatives == sorted(negatives, reverse=True)


def test_scenario_math_contributions_include_source_type_metadata():
    result = run_macro_forecast(
        make_stub_regime_state(),
        raw_inputs=_raw_inputs_fixture(),
        market_state=_market_state_fixture(),
    )

    contributions = [
        contribution
        for update in result.scenario_updates
        for contribution in update.contributions
    ]
    assert contributions
    assert all(contribution.source_role for contribution in contributions)
    assert any(contribution.source_role == "layer_summary" for contribution in contributions)
    assert any(contribution.source_role == "raw_component" for contribution in contributions)
    assert any(contribution.parent_layer == "volatility" for contribution in contributions)


def test_scenario_math_audit_formulas_are_explicit():
    result = run_macro_forecast(make_stub_regime_state())
    pre_floor_sum = sum(
        update.math_audit.pre_floor_posterior_probability
        for update in result.scenario_updates
        if update.math_audit is not None
    )

    assert pre_floor_sum == pytest.approx(1.0)
    assert sum(result.scenario_probabilities.values()) == pytest.approx(1.0)
    for update in result.scenario_updates:
        audit = update.math_audit
        assert audit is not None
        used = [item for item in audit.contributions if item.used_in_probability_update]
        assert audit.net_contribution == pytest.approx(
            sum(item.adjusted_contribution for item in used)
        )
        assert audit.raw_score_before_softmax == pytest.approx(
            audit.base_score + audit.net_contribution
        )
        assert audit.pre_floor_posterior_probability == pytest.approx(update.pre_floor_posterior_probability)
        assert audit.final_posterior_probability == pytest.approx(update.posterior_probability)
        assert audit.formula_notes
        assert all(item.input_id and item.base_strength >= 0 and item.input_confidence >= 0 for item in audit.contributions)


def test_monetary_display_only_contributions_are_visible_but_excluded():
    result = run_macro_forecast(make_stub_regime_state())
    composite = next(signal for signal in result.input_signals if signal.input_id == "monetary_policy_composite")
    monetary_layer = next(signal for signal in result.input_signals if signal.input_id == "monetary_conditions")
    fed_path = next(signal for signal in result.input_signals if signal.input_id == "fed_path")
    audit_ids = {
        contribution.input_id: contribution.used_in_probability_update
        for update in result.scenario_updates
        for contribution in (update.math_audit.contributions if update.math_audit else [])
    }
    used_ids = {
        contribution.input_id
        for update in result.scenario_updates
        for contribution in update.contributions
    }

    assert composite.used_in_probability_update is True
    assert monetary_layer.display_only is True
    assert fed_path.display_only is True
    assert monetary_layer.exclusion_reason
    assert fed_path.exclusion_reason
    assert audit_ids["monetary_conditions"] is False
    if fed_path.affected_scenarios:
        assert audit_ids["fed_path"] is False
    assert "monetary_policy_composite" in used_ids
    assert "monetary_conditions" not in used_ids
    assert "fed_path" not in used_ids


def test_monetary_composite_can_be_disabled_for_legacy_component_math():
    signals = build_macro_input_signals(make_stub_regime_state(), use_monetary_composite=False)
    updates = update_scenario_probabilities(DEFAULT_SCENARIO_PRIORS, signals)
    used_ids = {
        contribution.input_id
        for update in updates
        for contribution in update.contributions
    }

    assert "monetary_policy_composite" not in {signal.input_id for signal in signals}
    assert "monetary_conditions" in used_ids
    fed_path = next(signal for signal in signals if signal.input_id == "fed_path")
    if fed_path.affected_scenarios:
        assert "fed_path" in used_ids


def test_theme_score_decomposition_formula():
    result = run_macro_forecast(make_stub_regime_state())

    for theme in result.theme_rankings:
        contribution_sum = sum(item.contribution for item in theme.scenario_contributions)
        positive_sum = sum(item.contribution for item in theme.scenario_contributions if item.contribution > 0)
        negative_sum = sum(item.contribution for item in theme.scenario_contributions if item.contribution < 0)
        assert contribution_sum == pytest.approx(theme.macro_support_score)
        assert theme.net_macro_support_score == pytest.approx(theme.macro_support_score)
        assert theme.positive_contribution_total == pytest.approx(positive_sum)
        assert theme.negative_contribution_total == pytest.approx(negative_sum)
        assert theme.final_score == pytest.approx(theme.macro_support_score)
        assert theme.ranking_score == pytest.approx(theme.macro_support_score)
        assert theme.overlay_adjustment is None
        assert theme.overlay_used_in_ranking is False
        assert theme.adjustment_summary


def test_sector_and_factor_decompositions_sum_to_scores():
    result = run_macro_forecast(make_stub_regime_state())

    for ranking in [*result.sector_rankings, *result.factor_rankings]:
        assert ranking.contributions
        assert ranking.score == pytest.approx(sum(item.contribution for item in ranking.contributions))
        abs_contribs = [abs(item.contribution) for item in ranking.contributions]
        assert abs_contribs == sorted(abs_contribs, reverse=True)
        assert ranking.formula_notes
        assert all("macro support" in (item.rationale or "") for item in ranking.contributions)


def test_sector_and_factor_use_macro_support_not_deprecated_final_score():
    themes = [
        _theme_forecast("grid_power_infrastructure", "Grid and power infrastructure", 2.0, final_score=-10.0),
        _theme_forecast("cash_short_duration", "Cash and short duration", 1.0, final_score=10.0),
        _theme_forecast("quality_ex_ai_cash_flow", "Quality ex-AI cash flow", 0.5, final_score=10.0),
    ]
    sector = next(item for item in rank_sectors(themes) if item.item_id == "XLU")
    factor = next(item for item in rank_factors(themes) if item.factor_id == "cash")

    assert sector.score == pytest.approx(2.0 * 0.65 + 0.5 * 0.20 + 1.0 * 0.15)
    assert factor.score == pytest.approx(1.0)


def test_forecast_interpretation_is_derived_from_result():
    result = run_macro_forecast(make_stub_regime_state())
    interpretation = result.forecast_interpretation
    dominant = max(result.scenario_updates, key=lambda item: item.posterior_probability)

    assert interpretation is not None
    assert interpretation.dominant_scenario_id == dominant.scenario_id
    assert interpretation.dominant_scenario_probability == pytest.approx(dominant.posterior_probability)
    assert interpretation.preferred_exposures
    assert interpretation.key_tensions
    if dominant.scenario_id == "sticky_late_cycle_ai":
        assert "sticky" in interpretation.headline.lower()


def test_probability_shifters_cover_each_scenario_with_specific_drivers():
    result = run_macro_forecast(make_stub_regime_state())
    shifters = {item.scenario_id: item for item in result.probability_shifters}

    assert set(shifters) == set(result.scenario_probabilities)
    for shifter in shifters.values():
        assert len(shifter.would_increase_probability_if) >= 2
        assert len(shifter.would_decrease_probability_if) >= 2
        assert shifter.key_inputs_to_watch
    assert "breadth" in " ".join(shifters["sticky_late_cycle_ai"].would_increase_probability_if).lower()
    assert "fed" in " ".join(shifters["reopening_soft_landing"].would_increase_probability_if).lower()
    assert "oil" in " ".join(shifters["oil_inflation_tail"].would_increase_probability_if).lower()
    assert "credit" in " ".join(shifters["late_cycle_risk_off"].would_increase_probability_if).lower()
    assert "capex" in " ".join(shifters["ai_capex_rollover"].would_increase_probability_if).lower()


def test_report_includes_v2_audit_sections_in_order():
    result = run_macro_forecast(make_stub_regime_state())
    report = format_macro_forecast_report(result)

    sections = [
        "0. Forecast Interpretation",
        "1. Scenario Probabilities",
        "2. Scenario Probability Math",
        "3. Historical Analogue Calibration",
        "4. Forecast Input Set",
        "4.1 Layer Summary Signals",
        "4.2 Raw Component Signals",
        "4.3 Composite Signals",
        "4.4 Market/Tape Signals",
        "4.5 Regime-Specific Drivers",
        "4.6 Scenario Falsifiers",
        "4.7 Dedupe / Weighting Notes",
        "5. Monetary Composite Detail",
        "6. Theme Rankings",
        "7. Sector & Instrument Rankings",
        "8. Factor Rankings",
        "9. Probability Shifters / Watchlist",
        "10. Recommended Research Priorities",
        "11. Input Signal Detail",
        "12. Methodology Notes",
    ]
    positions = [report.index(section) for section in sections]
    assert positions == sorted(positions)
    assert "Pre-Floor Posterior" in report
    assert "Used in Math?" in report
    assert "volatility_layer_summary" in report
    assert "raw_component_contribution" in report
    assert "[layer_summary/" in report
    assert "Theme Rankings - Macro Support Score" in report
    assert "Scenario Contribution Breakdown" in report
    assert "Theme Macro Support Math" in report
    assert "Crowding Adj" not in report
    assert "Valuation Adj" not in report
    assert "Narrative Adj" not in report
    assert "Overlay Adj" not in report
    assert "Overlay Confidence" not in report
    assert "raw_score_s = prior_score_s + Σ input_contribution_i,s" in report
    assert "ranking_score_t = macro_support_score_t" in report
    assert "Macro forecast theme rankings intentionally exclude valuation, crowding, narrative maturity" in report


def test_macro_forecast_json_round_trips_with_audit_objects():
    result = run_macro_forecast(make_stub_regime_state())
    payload = result.model_dump(mode="json")
    parsed = MacroForecastResult.model_validate(payload)

    assert parsed.scenario_updates[0].math_audit is not None
    assert parsed.probability_shifters
    assert parsed.forecast_interpretation is not None
    assert parsed.forecast_input_set is not None


def test_old_macro_forecast_payload_without_forecast_input_set_loads():
    payload = run_macro_forecast(make_stub_regime_state()).model_dump(mode="json")
    payload.pop("forecast_input_set", None)

    parsed = MacroForecastResult.model_validate(payload)

    assert parsed.forecast_input_set is None
    assert parsed.input_signals


def test_old_theme_overlay_payload_loads_for_backward_compatibility():
    payload = run_macro_forecast(make_stub_regime_state()).model_dump(mode="json")
    for theme in payload["theme_rankings"]:
        for field in [
            "macro_support_score",
            "ranking_score",
            "score_method",
            "scenario_contributions",
            "positive_contribution_total",
            "negative_contribution_total",
            "net_macro_support_score",
            "overlay_used_in_ranking",
            "overlay_note",
        ]:
            theme.pop(field, None)
        theme["crowding_score"] = -0.25
        theme["valuation_score"] = 0.0
        theme["narrative_score"] = -0.10
        theme["overlay_adjustment"] = -0.1075

    parsed = MacroForecastResult.model_validate(payload)

    assert parsed.theme_rankings
    assert parsed.theme_rankings[0].ranking_score == pytest.approx(parsed.theme_rankings[0].macro_score)


def test_macro_forecast_result_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    result = run_macro_forecast(make_stub_regime_state())

    record_id = save_schema(result)

    assert record_id
    assert (tmp_path / "schema_records.jsonl").exists()


def test_macro_forecast_sample_fixture_exists():
    fixture = Path("backend/src/agent_system/fixtures/macro_forecast_sample.json")
    assert fixture.exists()


def test_macro_forecast_run_config_defaults_are_opinionated():
    config = MacroForecastRunConfig()

    assert config.raw_inputs_enabled is True
    assert config.volatility_enabled is True
    assert config.input_mode == "hybrid"
    assert config.historical_calibration_enabled is True
    assert config.detailed_analogues_enabled is True
    assert config.save_docx is True
    assert config.save_json is True
    assert config.save_current_regime_yaml is True
    assert config.current_state_lookup_weight == pytest.approx(1.0)


def test_raw_components_contribute_to_deterministic_math_when_available():
    result = run_macro_forecast(
        make_stub_regime_state(),
        raw_inputs=_raw_inputs_fixture(),
    )
    raw_contributions = [
        contribution
        for update in result.scenario_updates
        for contribution in update.contributions
        if contribution.source_role == "raw_component" and abs(contribution.adjusted_contribution) > 0
    ]

    assert result.forecast_input_set is not None
    assert len(result.forecast_input_set.raw_component_signals) > 1
    assert raw_contributions


def test_raw_component_warning_when_available_but_no_contribution():
    updates = update_scenario_probabilities(
        DEFAULT_SCENARIO_PRIORS,
        [_signal(input_id="raw_without_impacts")],
    )

    warnings = [
        warning
        for update in updates
        for warning in update.warnings
    ]
    assert any("produced no deterministic scenario contributions" in warning for warning in warnings)
