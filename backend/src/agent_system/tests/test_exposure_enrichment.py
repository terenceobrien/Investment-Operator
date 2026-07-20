from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.scenarios.types import (
    ScenarioScore,
    TradeScenarioAnalysis,
    compute_robustness,
)
from src.agent_system.services.exposure_enrichment import ExposureEnrichmentService


def _trade():
    regime = make_stub_regime_state()
    candidate = make_stub_thematic_map(regime).candidates[0]
    fundamental = make_stub_fundamental_analysis(candidate)
    narrative = make_stub_narrative_analysis(candidate)
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )
    trade = construct_trade_idea(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
        conviction=conviction,
    )
    priority = trade.research_priority.model_copy_validate(
        {
            "theme": "Second-order grid and power infrastructure beneficiaries with cross-scenario support",
        }
    )
    return trade.model_copy_validate(
        {
            "id": "trade_eme",
            "underlying": "EME",
            "research_priority": priority,
        }
    )


def _analysis() -> TradeScenarioAnalysis:
    scores = [
        ScenarioScore(
            scenario_id="sticky_late_cycle_ai",
            expected_pnl_pct=0.20,
            confidence="high",
            reasoning="AI infrastructure scenario supports the trade.",
        ),
        ScenarioScore(
            scenario_id="late_cycle_risk_off",
            expected_pnl_pct=-0.10,
            confidence="medium",
            reasoning="Risk-off scenario pressures the trade.",
        ),
    ]
    weights = {"sticky_late_cycle_ai": 0.75, "late_cycle_risk_off": 0.25}
    expected = sum(score.expected_pnl_pct * weights[score.scenario_id] for score in scores)
    worst = min(score.expected_pnl_pct for score in scores)
    best = max(score.expected_pnl_pct for score in scores)
    return TradeScenarioAnalysis(
        created_at=datetime.now(timezone.utc),
        trade_id="trade_eme",
        scenario_set_horizon_months=3,
        scenario_scores=scores,
        expected_return=expected,
        worst_case_pnl_pct=worst,
        best_case_pnl_pct=best,
        robustness_score=compute_robustness(expected, worst),
        scenarios_positive=sum(1 for score in scores if score.expected_pnl_pct > 0),
        scenario_weight_source="macro_forecast",
        scenario_weights_used=weights,
    )


def test_exposure_enrichment_uses_reference_data_and_scenario_pnls():
    service = ExposureEnrichmentService()

    exposure = service.enrich(_trade(), _analysis(), final_size_pct=0.05)

    assert exposure.trade_idea_id == "trade_eme"
    assert exposure.underlying == "EME"
    assert exposure.instrument_type == "single_stock"
    assert exposure.position_size_pct == pytest.approx(0.05)
    assert exposure.delta == pytest.approx(1.0)
    assert exposure.sector == "Engineering/Construction"
    assert exposure.market_beta == pytest.approx(1.21)
    assert exposure.market_beta_source == "damodaran_sector"
    assert exposure.sector_beta == pytest.approx(1.21)
    assert exposure.theme_exposure == pytest.approx(0.9)
    assert exposure.theme_exposure_source == "theme_matrix"
    assert exposure.scenario_exposure_source == "derived_from_scenario_pnl"
    assert exposure.scenario_exposures["sticky_late_cycle_ai"] == pytest.approx(0.075)
    assert exposure.scenario_exposures["late_cycle_risk_off"] == pytest.approx(-0.225)
    assert exposure.idiosyncratic_volatility == pytest.approx(0.1299038)
    assert exposure.idiosyncratic_vol_source == "scenario_pnl_range"
    assert exposure.overall_confidence == "high"


def test_exposure_enrichment_fallbacks_lower_confidence():
    trade = _trade()
    priority = trade.research_priority.model_copy_validate({"theme": "Unmapped theme"})
    unknown = trade.model_copy_validate(
        {
            "id": "trade_unknown",
            "underlying": "ZZZ",
            "research_priority": priority,
        }
    )

    exposure = ExposureEnrichmentService().enrich(
        unknown,
        _analysis(),
        final_size_pct=0.03,
    )

    assert exposure.sector == "Unknown"
    assert exposure.market_beta == pytest.approx(1.0)
    assert exposure.market_beta_source == "sector_proxy"
    assert exposure.theme_exposure == pytest.approx(0.5)
    assert exposure.theme_exposure_source == "manual_estimate"
    assert exposure.overall_confidence == "low"
