"""Tests for deterministic portfolio construction."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.agent_system.agents.portfolio_agent import construct_portfolio
from src.agent_system.config.trader_profile import load_trader_profile
from src.agent_system.orchestration.run_research_cycle import run_research_cycle
from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.positions.types import Position, PositionsSnapshot
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.scenarios.types import ScenarioScore, TradeScenarioAnalysis
from src.agent_system.schemas.portfolio_plan import PortfolioPlan
from src.agent_system.schemas.thematic import InstrumentType
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.storage.repository import list_schemas


@pytest.fixture(autouse=True)
def _use_jsonl_storage(monkeypatch):
    monkeypatch.setenv("AGENT_STORAGE_BACKEND", "jsonl")
    from src.agent_system.storage import backend as storage_backend

    storage_backend._backend_singletons.clear()
    yield
    storage_backend._backend_singletons.clear()


def _base_trade(
    *,
    ticker: str = "ETN",
    trade_id: str = "trade_1",
    size: float = 0.05,
    priority_theme: str = "AI power/grid",
    option: bool = False,
) -> TradeIdea:
    regime = make_stub_regime_state()
    candidate = make_stub_thematic_map(regime).candidates[0].model_copy_validate(
        {"ticker": ticker}
    )
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
    priority = trade.research_priority.model_copy_validate({"theme": priority_theme})
    sizing = trade.proposed_sizing.model_copy_validate({"base_size_pct": size})
    expression = trade.expression
    if option:
        instrument = expression.primary_instrument.model_copy_validate(
            {
                "instrument_type": InstrumentType.OPTION_UNDERLYING,
                "description": "long Mar 2027 $400/$435 call spread",
            }
        )
        expression = expression.model_copy_validate({"primary_instrument": instrument})
    return trade.model_copy_validate(
        {
            "id": trade_id,
            "underlying": ticker,
            "research_priority": priority,
            "proposed_sizing": sizing,
            "expression": expression,
        }
    )


def _analysis(trade: TradeIdea, robustness: float) -> TradeScenarioAnalysis:
    scores = [
        ScenarioScore(
            scenario_id="base",
            expected_pnl_pct=0.10,
            confidence="medium",
            reasoning="Base case creates a positive payoff.",
        )
    ]
    return TradeScenarioAnalysis(
        created_at=datetime.now(timezone.utc),
        trade_id=trade.id,
        scenario_set_horizon_months=6,
        scenario_scores=scores,
        expected_return=0.10,
        worst_case_pnl_pct=0.0,
        best_case_pnl_pct=0.10,
        robustness_score=robustness,
        scenarios_positive=1,
    )


def _positions(*weights: tuple[str, float]) -> PositionsSnapshot:
    nav = 100_000.0
    positions = [
        Position(
            symbol=symbol,
            description=f"{symbol} position",
            quantity_shares=1,
            current_value_usd=nav * pct,
            percent_of_account=pct,
            position_type="margin",
        )
        for symbol, pct in weights
    ]
    cash = nav - sum(position.current_value_usd for position in positions)
    positions.append(
        Position(
            symbol="SPAXX**",
            description="Fidelity Government Money Market",
            quantity_shares=None,
            current_value_usd=cash,
            percent_of_account=cash / nav,
            position_type="cash",
            is_cash=True,
        )
    )
    return PositionsSnapshot(
        source_file="positions.csv",
        file_mtime=datetime.now(timezone.utc),
        positions=positions,
        total_nav_usd=nav,
        cash_usd=cash,
        cash_pct=cash / nav,
        long_equity_usd=sum(position.current_value_usd for position in positions if not position.is_cash),
        margin_positions_usd=sum(position.current_value_usd for position in positions if position.position_type == "margin"),
    )


def _plan(
    trades: list[TradeIdea],
    analyses: list[TradeScenarioAnalysis] | None = None,
    positions: PositionsSnapshot | None = None,
    trader_profile=None,
) -> PortfolioPlan:
    return construct_portfolio(
        accepted_trades=trades,
        scenario_analyses=analyses or [],
        positions=positions,
        trader_profile=trader_profile or load_trader_profile(),
        scenario_set=None,
        cycle_id="cycle_test",
    )


def test_robustness_demotion_bottom_quartile():
    trades = [
        _base_trade(ticker=f"T{i}", trade_id=f"t{i}", priority_theme=f"theme{i}")
        for i in range(4)
    ]
    analyses = [_analysis(trade, robustness) for trade, robustness in zip(trades, [0.1, 0.2, 0.3, 0.4])]

    plan = _plan(trades, analyses)

    by_id = {decision.trade_id: decision for decision in plan.trade_decisions}
    assert by_id["t0"].final_size_pct == 0.025
    assert by_id["t0"].robustness_quartile == 1
    assert "robustness_demotion" in by_id["t0"].sizing_adjustments[0].step
    assert by_id["t1"].final_size_pct == 0.05


def test_none_robustness_is_not_demoted():
    trade = _base_trade()

    plan = _plan([trade], analyses=[])

    decision = plan.trade_decisions[0]
    assert decision.robustness_score is None
    assert decision.final_size_pct == 0.05
    assert not any(adj.step == "robustness_demotion" for adj in decision.sizing_adjustments)


def test_overlap_cap_zero_headroom():
    trade = _base_trade(ticker="MSFT")

    plan = _plan([trade], positions=_positions(("MSFT", 0.06)))

    decision = plan.trade_decisions[0]
    assert decision.existing_position_pct == 0.06
    assert decision.final_size_pct == 0
    assert decision.decision == "rejected_portfolio"


def test_overlap_cap_partial_headroom():
    trade = _base_trade(ticker="MSFT")

    plan = _plan([trade], positions=_positions(("MSFT", 0.01)))

    decision = plan.trade_decisions[0]
    assert decision.final_size_pct == 0.04
    assert decision.decision == "reduced"


def test_priority_concentration_cap_scales_group():
    trades = [
        _base_trade(ticker=f"P{i}", trade_id=f"p{i}", priority_theme="AI-power")
        for i in range(5)
    ]

    plan = _plan(trades)

    assert all(decision.final_size_pct == 0.03 for decision in plan.trade_decisions)
    assert plan.per_priority_deployment_pct["AI-power"] == 0.15
    assert "priority_concentration:AI-power" in plan.binding_constraints


def test_options_allocation_cap_scales_options():
    trades = [
        _base_trade(ticker=f"O{i}", trade_id=f"o{i}", option=True, priority_theme=f"theme{i}")
        for i in range(6)
    ]

    plan = _plan(trades)

    assert all(round(decision.final_size_pct, 8) == round(0.05 * (0.20 / 0.30), 8) for decision in plan.trade_decisions)
    assert "options_allocation_cap" in plan.binding_constraints


def test_total_deployment_cap_scales_all_trades():
    trades = [
        _base_trade(ticker=f"D{i}", trade_id=f"d{i}", priority_theme=f"theme{i}")
        for i in range(12)
    ]

    plan = _plan(trades)

    assert round(plan.total_new_deployment_pct, 8) == 0.50
    assert all(round(decision.final_size_pct, 8) == round(0.05 * (0.50 / 0.60), 8) for decision in plan.trade_decisions)
    assert "total_deployment_cap" in plan.binding_constraints


def test_min_size_floor_zeroes_tiny_trade():
    trade = _base_trade(size=0.003)

    plan = _plan([trade])

    decision = plan.trade_decisions[0]
    assert decision.final_size_pct == 0
    assert decision.decision == "rejected_portfolio"
    assert "min_size_floor" in plan.binding_constraints


def test_multiple_constraints_bind_in_order():
    profile = load_trader_profile()
    profile = profile.model_copy(
        update={
            "portfolio_constraints": profile.portfolio_constraints.model_copy(
                update={"max_priority_pct": 0.25}
            )
        }
    )
    trades = [
        _base_trade(ticker=f"M{i}", trade_id=f"m{i}", option=True, priority_theme="crowded")
        for i in range(6)
    ]

    plan = _plan(trades, trader_profile=profile)

    first_steps = [adj.step for adj in plan.trade_decisions[0].sizing_adjustments]
    assert first_steps == ["priority_concentration_cap", "options_allocation_cap"]
    assert "priority_concentration:crowded" in plan.binding_constraints
    assert "options_allocation_cap" in plan.binding_constraints


def test_decision_classification_execute_reduced_rejected():
    execute = _base_trade(ticker="EXE", trade_id="execute", priority_theme="a")
    reduced = _base_trade(ticker="RED", trade_id="reduced", priority_theme="b")
    rejected = _base_trade(ticker="REJ", trade_id="rejected", size=0.003, priority_theme="c")

    plan = _plan([execute, reduced, rejected], positions=_positions(("RED", 0.01)))

    decisions = {decision.trade_id: decision.decision for decision in plan.trade_decisions}
    assert decisions["execute"] == "execute"
    assert decisions["reduced"] == "reduced"
    assert decisions["rejected"] == "rejected_portfolio"


def test_missing_scenarios_positions_and_both_missing_still_plan():
    trades = [_base_trade(ticker="ETN", trade_id="etn")]

    no_scenarios = _plan(trades, analyses=[], positions=_positions())
    no_positions = _plan(trades, analyses=[_analysis(trades[0], 0.5)], positions=None)
    both_missing = _plan(trades, analyses=[], positions=None)

    assert no_scenarios.trade_decisions[0].robustness_score is None
    assert no_positions.trade_decisions[0].existing_position_pct == 0
    assert both_missing.n_executed == 1


def test_cycle_integration_persists_portfolio_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    def _mock_score(trade, *_args, **_kwargs):
        return _analysis(trade, 0.50)

    mock_score = AsyncMock(side_effect=_mock_score)
    monkeypatch.setattr(
        "src.agent_system.orchestration.run_research_cycle.score_trade_against_scenarios",
        mock_score,
    )

    summary = run_research_cycle(
        force_stub=True,
        use_stub_thematic=True,
        use_stub_fundamental=True,
        use_stub_trade_expression=True,
    )

    assert (
        summary["portfolio_trades_executed"]
        + summary["portfolio_trades_reduced"]
    ) >= 1
    assert "portfolio_total_deployment_pct" in summary
    plans = list_schemas(PortfolioPlan)
    assert len(plans) == 1
    assert plans[0].n_executed + plans[0].n_reduced >= 1
