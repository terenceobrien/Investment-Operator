"""
Tests for real/stub research-cycle selection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.agent_system.agents.thematic_agent import ThematicAgentValidationError
from src.agent_system.agents.trade_expression_agent import (
    PriorityThesisDirection,
    TradeExpressionComponents,
    TradeExpressionRejection,
)
from src.agent_system.data.types import CompanyFacts, FundamentalDataBundle
from src.agent_system.orchestration.run_research_cycle import (
    run_research_cycle,
    run_stub_research_cycle,
)
from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_regime_state,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_thematic_map,
)
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.schemas.common import ConvictionRating
from src.agent_system.schemas.fundamental_screen import FundamentalScreen
from src.agent_system.schemas.regime import ClarificationRequest
from src.agent_system.schemas.thematic import ThematicMap
from src.agent_system.schemas.trade import TradeIdea, TradeProvenance
from src.agent_system.storage.repository import list_schemas
from src.state.regime_state import RegimeState as DataclassRegimeState


SUMMARY_BASE_FIELDS = {
    "cycle_id",
    "regime_id",
    "thematic_maps",
    "candidates_considered",
    "trade_ideas_saved",
    "accepted",
    "rejected",
    "decision_log_entries",
    "accepted_underlyings",
    "rejected_underlyings",
}
SUMMARY_NEW_FIELDS = {
    "regime_source",
    "regime_asof_date",
    "fallback_reason",
    "thematic_agent_errors",
    "clarifications_received",
    "fundamental_screened",
    "fundamental_eliminated",
    "fundamental_passed",
    "crowding_flags",
    "trade_expressions_attempted",
    "trade_expressions_succeeded",
    "trade_expressions_failed",
    "trade_expressions_fallback_used",
    "trade_options_selected",
    "trade_stocks_selected",
    "trade_rejections_pre_expression",
    "trade_rejections_post_expression",
    "trade_rejections_direction_misalignment",
    "portfolio_trades_executed",
    "portfolio_trades_reduced",
    "portfolio_trades_rejected",
    "portfolio_total_deployment_pct",
    "portfolio_binding_constraints",
}


@pytest.fixture(autouse=True)
def _use_jsonl_storage(monkeypatch):
    monkeypatch.setenv("AGENT_STORAGE_BACKEND", "jsonl")
    from src.agent_system.storage import backend as storage_backend

    storage_backend._backend_singletons.clear()
    yield
    storage_backend._backend_singletons.clear()


def _cycle_facts(
    *,
    stockholders_equity: float = 50.0,
) -> CompanyFacts:
    return CompanyFacts(
        revenue_ttm=100.0,
        gross_profit_ttm=None,
        operating_income_ttm=20.0,
        net_income_ttm=10.0,
        total_assets=100.0,
        total_debt=10.0,
        cash_and_equivalents=20.0,
        stockholders_equity=stockholders_equity,
        operating_cash_flow_ttm=12.0,
        free_cash_flow_ttm=10.0,
        capex_ttm=None,
        depreciation_amortization_ttm=0.0,
        ebitda_ttm=20.0,
        most_recent_fiscal_year_end=None,
        most_recent_quarter_end=None,
        revenue_yoy_growth=0.08,
        revenue_3yr_cagr=None,
        gross_margin=None,
        operating_margin=None,
        net_margin=None,
    )


def _cycle_bundle(
    ticker: str,
    *,
    is_etf: bool = False,
    stockholders_equity: float = 50.0,
    crowded: bool = False,
) -> FundamentalDataBundle:
    return FundamentalDataBundle(
        ticker=ticker,
        as_of=datetime.now(timezone.utc),
        is_etf=is_etf,
        cik=None if is_etf else "0000000001",
        company_name=f"{ticker} Corp",
        most_recent_10k=None,
        most_recent_10q=None,
        recent_8ks=[],
        company_facts=None if is_etf else _cycle_facts(
            stockholders_equity=stockholders_equity
        ),
        current_price=100.0 if crowded else None,
        market_cap=None,
        trailing_pe=None,
        forward_pe=None,
        price_to_sales=None,
        enterprise_value=None,
        ev_to_ebitda=None,
        analyst_count_buy=8 if crowded else None,
        analyst_count_hold=2 if crowded else None,
        analyst_count_sell=0 if crowded else None,
        mean_price_target=102.0 if crowded else None,
        sector=None,
        industry=None,
        earnings_history=[],
        sec_fetch_success=not is_etf,
        yahoo_fetch_success=crowded or is_etf,
        fetch_errors=[],
        fetch_duration_ms=0,
    )


def test_run_research_cycle_force_stub_runs_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert summary["regime_source"] == "stub"
    assert summary["fallback_reason"] is None
    assert summary["accepted"] >= 1
    assert summary["rejected"] >= 1


def test_run_research_cycle_falls_back_when_no_real_snapshot(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        DataclassRegimeState,
        "load_latest_snapshot",
        classmethod(lambda cls: None),
    )

    summary = run_research_cycle(
        use_stub_thematic=True,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert summary["regime_source"] == "stub_fallback"
    assert summary["fallback_reason"] == "no_snapshot_found"
    assert summary["accepted"] >= 1
    assert summary["rejected"] >= 1


def test_run_research_cycle_returns_existing_and_new_summary_fields(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert SUMMARY_BASE_FIELDS.issubset(summary)
    assert SUMMARY_NEW_FIELDS.issubset(summary)


def test_run_stub_research_cycle_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    summary = run_stub_research_cycle()

    assert summary["regime_source"] == "stub"
    assert summary["fallback_reason"] is None
    assert summary["accepted"] >= 1
    assert summary["rejected"] >= 1


def test_cycle_with_real_thematic_agent_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    async def _return_map(*, priority, regime_state):
        return make_stub_thematic_map(regime_state).model_copy_validate(
            {"source_priority": priority}
        )

    mock_agent = AsyncMock(side_effect=_return_map)
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.translate_priority_to_candidates",
        mock_agent,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=False,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert mock_agent.await_count == 1
    assert summary["thematic_maps"] == 1
    assert summary["candidates_considered"] > 0
    assert summary["thematic_agent_errors"] == 0
    assert summary["clarifications_received"] == 0
    stored_maps = list_schemas(ThematicMap)
    assert len(stored_maps) == 1
    assert stored_maps[0].source_priority_id is not None


def test_cycle_counts_thematic_agent_validation_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    mock_agent = AsyncMock(
        side_effect=ThematicAgentValidationError("invalid thematic output")
    )
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.translate_priority_to_candidates",
        mock_agent,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=False,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert mock_agent.await_count == 1
    assert summary["thematic_agent_errors"] == 1
    assert summary["clarifications_received"] == 0
    assert summary["thematic_maps"] == 0
    assert summary["candidates_considered"] == 0
    assert summary["trade_ideas_saved"] == 0


def test_cycle_persists_thematic_clarification_and_skips_downstream(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    clarification = ClarificationRequest(
        question="Which candidate-selection angle should be researched first?",
        suggested_options=[
            "Focus on direct infrastructure beneficiaries.",
            "Focus on rate-sensitive contrarian names.",
        ],
        reasoning=(
            "The priority is too broad to identify a coherent candidate map "
            "without choosing which distinct exposure to investigate."
        ),
        original_input="Broad mixed thematic priority",
    )
    mock_agent = AsyncMock(return_value=clarification)
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.translate_priority_to_candidates",
        mock_agent,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=False,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert mock_agent.await_count == 1
    assert summary["clarifications_received"] == 1
    assert summary["thematic_agent_errors"] == 0
    assert summary["thematic_maps"] == 0
    assert summary["candidates_considered"] == 0
    assert summary["trade_ideas_saved"] == 0
    stored_clarifications = list_schemas(ClarificationRequest)
    assert len(stored_clarifications) == 1
    assert stored_clarifications[0].question == clarification.question


def test_cycle_with_real_fundamental_screen_mocked_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    def _mock_bundle(ticker: str):
        if ticker == "NVDA":
            return _cycle_bundle(ticker, stockholders_equity=-5.0)
        if ticker == "ETN":
            return _cycle_bundle(ticker, crowded=True)
        return _cycle_bundle(ticker, is_etf=ticker in {"SMH", "IFRA", "PAVE"})

    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.get_fundamental_data",
        _mock_bundle,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=False,
        use_stub_trade_expression=True,
    )

    assert summary["candidates_considered"] == 6
    assert summary["fundamental_screened"] == 6
    assert summary["fundamental_eliminated"] == 1
    assert summary["fundamental_passed"] == 5
    assert summary["crowding_flags"] == 1
    assert "NVDA" in summary["rejected_underlyings"]
    stored_screens = list_schemas(FundamentalScreen)
    assert len(stored_screens) == 6


def test_cycle_with_real_trade_expression_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    def _mock_bundle(ticker: str):
        return _cycle_bundle(ticker, is_etf=ticker in {"SMH", "IFRA", "PAVE"})

    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.get_fundamental_data",
        _mock_bundle,
    )
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.get_market_data",
        lambda _ticker: object(),
    )

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
    accepted_trade = construct_trade_idea(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
        conviction=conviction,
    )
    components = TradeExpressionComponents(
        expression=accepted_trade.expression,
        proposed_sizing=accepted_trade.proposed_sizing,
        invalidation_thesis=accepted_trade.invalidation_thesis,
        trade_falsifiers=accepted_trade.trade_falsifiers,
        expected_holding_period=accepted_trade.expected_holding_period,
        thesis_review_cadence=accepted_trade.thesis_review_cadence,
        provenance=TradeProvenance(),
        selected_strategy="long_stock",
        fallback_used=False,
    )
    mock_agent = AsyncMock(return_value=components)
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.express_trade",
        mock_agent,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=False,
        use_stub_trade_expression=False,
    )

    assert mock_agent.await_count >= 1
    assert summary["trade_expressions_attempted"] == mock_agent.await_count
    assert summary["trade_expressions_succeeded"] == mock_agent.await_count
    assert summary["trade_expressions_failed"] == 0
    assert summary["trade_stocks_selected"] == mock_agent.await_count


def test_cycle_rejects_direction_misaligned_trade_expression(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    def _mock_bundle(ticker: str):
        return _cycle_bundle(ticker, is_etf=ticker in {"SMH", "IFRA", "PAVE"})

    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.get_fundamental_data",
        _mock_bundle,
    )
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.get_market_data",
        lambda _ticker: object(),
    )
    rejection = TradeExpressionRejection(
        misalignment_reason=(
            "Priority thesis is bullish but chosen instrument expresses bearish exposure"
        ),
        priority_thesis_direction=PriorityThesisDirection.BULLISH,
        effective_direction="bearish",
        selected_strategy="long_put_spread",
    )
    mock_agent = AsyncMock(return_value=rejection)
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.express_trade",
        mock_agent,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=False,
        use_stub_trade_expression=False,
    )

    assert mock_agent.await_count >= 1
    assert summary["trade_rejections_direction_misalignment"] == mock_agent.await_count
    assert summary["trade_expressions_succeeded"] == 0
    stored_trades = list_schemas(TradeIdea)
    direction_rejections = [
        trade
        for trade in stored_trades
        if trade.rejection_rule_fired == "direction_misaligned"
    ]
    assert len(direction_rejections) == mock_agent.await_count
    assert all(
        trade.combined_conviction.rating == ConvictionRating.PASS
        for trade in direction_rejections
    )
