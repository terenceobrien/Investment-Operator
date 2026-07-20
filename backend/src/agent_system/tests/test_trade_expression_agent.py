"""Tests for the trade expression agent."""
from __future__ import annotations

import asyncio
import os
from datetime import date, datetime, timedelta, timezone

import pytest

from src.agent_system.agents.trade_expression_agent import (
    _AlternativeOutput,
    _FalsifierOutput,
    _TradeExpressionLLMOutput,
    PriorityThesisDirection,
    TradeExpressionRejection,
    compute_base_sizing,
    compute_tenor_window,
    express_trade,
    max_loss_for_strategy,
)
from src.agent_system.config.trader_profile import load_trader_profile
from src.agent_system.data import get_fundamental_data, get_market_data
from src.agent_system.data.types import (
    FundamentalDataBundle,
    MarketDataBundle,
    TechnicalContext,
)
from src.agent_system.llm.client import StructuredOutputError
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.common import (
    Conviction,
    ConvictionRating,
    DerivedEvidence,
    FalsifierFrequency,
    FalsifierObservable,
)
from src.agent_system.schemas.forward import ForwardContext, MarketEvent
from src.agent_system.schemas.fundamental_screen import (
    Archetype,
    FundamentalScreen,
    ScreenVerdict,
)
from src.agent_system.schemas.regime import EdgeDecayHorizon, ResearchPriority
from src.agent_system.schemas.thematic import (
    Candidate,
    InstrumentType,
    ResearchDepth,
    VariantStrength,
)
from src.agent_system.schemas.trade import ReviewCadence, TradeIdea


def _candidate(
    *,
    ticker: str = "XXX",
    variant_strength: VariantStrength = VariantStrength.STRONG,
    fit_strength: float = 0.85,
    instrument_type: InstrumentType = InstrumentType.SINGLE_STOCK,
    variant_view: str = "Consensus underestimates upside from the catalyst.",
) -> Candidate:
    return Candidate(
        ticker=ticker,
        instrument_type=instrument_type,
        name=f"{ticker} Corp",
        thematic_fit="Directly expresses the priority thesis with liquid public equity.",
        fit_strength=fit_strength,
        consensus_view="Consensus appears too cautious on the setup.",
        potential_variant_view=variant_view,
        variant_strength=variant_strength,
        priority_rank=1,
        recommended_research_depth=ResearchDepth.DEEP,
        theme_tags=["test_theme"],
    )


def _priority(
    *,
    theme: str = "Dovish pivot beneficiaries - long rate-sensitive names",
    rationale: str | None = None,
    edge_hypothesis: str | None = None,
) -> ResearchPriority:
    return ResearchPriority(
        theme=theme,
        rationale=rationale
        or (
            "The priority is to identify names that should benefit if the Fed "
            "path reprices dovishly and rate-sensitive equities recover."
        ),
        edge_hypothesis=edge_hypothesis
        or (
            "Consensus is underpricing rate-cut convexity in quality "
            "beneficiaries while over-owning crowded leadership."
        ),
        sub_questions=[
            "Which names benefit most from lower mortgage rates or lower discount rates?"
        ],
        priority_rank=2,
        expected_edge_decay=EdgeDecayHorizon.MONTHS,
        supporting_evidence=[
            DerivedEvidence(
                claim="Test priority direction is bullish",
                supports=True,
                computation="test fixture",
                upstream_claims=["dovish pivot beneficiaries"],
            )
        ],
    )


def _screen(
    *,
    crowding_flag: bool = False,
    data_quality_flag: bool = False,
) -> FundamentalScreen:
    return FundamentalScreen(
        created_at=datetime.now(timezone.utc),
        ticker="XXX",
        archetype=Archetype.ESTABLISHED,
        verdict=ScreenVerdict.PASS,
        reason="Established: FCF positive, leverage acceptable - PASS",
        crowding_flag=crowding_flag,
        crowding_detail="crowded" if crowding_flag else None,
        data_quality_flag=data_quality_flag,
        data_quality_detail="growth anomaly" if data_quality_flag else None,
        metrics_used={},
    )


def _fundamentals(ticker: str = "XXX") -> FundamentalDataBundle:
    return FundamentalDataBundle(
        ticker=ticker,
        as_of=datetime.now(timezone.utc),
        is_etf=False,
        cik="0000000001",
        company_name=f"{ticker} Corp",
        most_recent_10k=None,
        most_recent_10q=None,
        recent_8ks=[],
        company_facts=None,
        current_price=100.0,
        market_cap=None,
        trailing_pe=None,
        forward_pe=None,
        price_to_sales=None,
        enterprise_value=None,
        ev_to_ebitda=None,
        analyst_count_buy=None,
        analyst_count_hold=None,
        analyst_count_sell=None,
        mean_price_target=None,
        earnings_history=[],
        sec_fetch_success=False,
        yahoo_fetch_success=True,
        fetch_errors=[],
        fetch_duration_ms=0,
    )


def _market(ticker: str = "XXX") -> MarketDataBundle:
    return MarketDataBundle(
        ticker=ticker,
        as_of=datetime.now(timezone.utc),
        current_price=100.0,
        history_start=date(2025, 1, 1),
        history_end=date(2026, 1, 1),
        bars_count=252,
        technicals=TechnicalContext(
            sma_50=95.0,
            sma_200=80.0,
            price_vs_sma_50=0.0526,
            price_vs_sma_200=0.25,
            high_20d=103.0,
            low_20d=92.0,
            high_52w=115.0,
            low_52w=70.0,
            atr_14=3.0,
            atr_pct=0.03,
            trend_regime="uptrend",
        ),
        fetch_success=True,
        fetch_errors=[],
    )


def _llm_output(
    *,
    strategy: str = "long_call_spread",
    priority_direction: PriorityThesisDirection | None = None,
    falsifier_count: int = 3,
    alternatives: bool = True,
    primary_description: str | None = None,
    entry_logic: str | None = None,
    target_derivation: dict | None = None,
) -> _TradeExpressionLLMOutput:
    falsifiers = [
        _FalsifierOutput(
            condition=f"Falsifier {idx} invalidates a distinct part of the thesis.",
            observable_in=FalsifierObservable.PRICE_ACTION
            if idx == 0
            else FalsifierObservable.EARNINGS,
            check_frequency=FalsifierFrequency.DAILY
            if idx == 0
            else FalsifierFrequency.EVENT_DRIVEN,
        )
        for idx in range(falsifier_count)
    ]
    descriptions = {
        "long_call_spread": "long Sep 2026 $95/$100 call spread",
        "long_put_spread": "long Sep 2026 $95/$80 put spread",
        "long_call": "long Sep 2026 $95 calls",
        "long_put": "long Sep 2026 $95 puts",
        "long_stock": "long stock",
        "covered_call": "covered call against long stock",
        "cash_secured_put": "cash-secured put",
        "pair_trade": "long XXX / short YYY pair trade",
    }
    payload = {
        "chosen_instrument_type": strategy,
        "primary_instrument_description": primary_description or descriptions.get(
            strategy,
            f"{strategy} expression for XXX",
        ),
        "rationale_for_instrument": (
            "This structure best matches the thesis while respecting the "
            "trader profile and computed technical anchors."
        ),
        "alternatives_considered": [
            _AlternativeOutput(
                instrument_type="long_stock",
                instrument_description="long stock",
                why_rejected="Long stock was less capital efficient for this setup.",
            )
        ]
        if alternatives
        else [],
        "entry_logic": entry_logic
        or "Enter on a pullback toward the 50-day moving average near $95.",
        "target_derivation": target_derivation
        or {
            "method": "technical",
            "inputs_used": [
                "52-week high at $115 from supplied technical anchors",
                "Current uptrend with SMA50 support near $95",
            ],
            "implied_price": 115.0,
        },
        "exit_target": "Target a move toward the 52-week high near $115.",
        "exit_stop": "Cut risk on a close below the 200-day moving average near $80.",
        "exit_time_stop": "Exit after 90 days if the thesis has not started to play out.",
        "invalidation_thesis": (
            "The thesis is invalidated if the operating signal fails to appear "
            "and consensus no longer differs from our variant view."
        ),
        "trade_falsifiers": falsifiers,
        "expected_holding_period": "2-3 months",
        "thesis_review_cadence": ReviewCadence.WEEKLY,
        "sizing_logic": (
            "Sizing follows the configured conviction factor and remains below "
            "the trader profile maximum position size."
        ),
    }
    if priority_direction is not None:
        payload["priority_thesis_direction"] = priority_direction
    return _TradeExpressionLLMOutput(**payload)


def _run_with_mock(monkeypatch, output, *, candidate=None, priority=None):
    def fake_parse_structured(**_kwargs):
        return output

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    return asyncio.run(
        express_trade(
            candidate=candidate or _candidate(),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
            priority=priority,
        )
    )


def test_bearish_thesis_without_short_stock_routes_to_puts(monkeypatch):
    captured = {}

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _llm_output(strategy="long_put")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    candidate = _candidate(
        variant_view="Consensus underestimates downside and margin compression."
    )
    result = asyncio.run(
        express_trade(
            candidate=candidate,
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert "long_put" in captured["user"]
    assert "long_put_spread" in captured["user"]
    assert "long_call" not in captured["user"]
    assert result.selected_strategy == "long_put"
    assert result.expression.primary_instrument.instrument_type == InstrumentType.OPTION_UNDERLYING


def test_weak_variant_routes_to_stock_only(monkeypatch):
    captured = {}

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _llm_output(strategy="long_stock")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(variant_strength=VariantStrength.WEAK),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert "Eligible instruments: ['long_stock']" in captured["user"]
    assert result.selected_strategy == "long_stock"


def test_tenor_selection_weeks_with_near_catalyst_and_quarters():
    profile = load_trader_profile()
    today = date.today()
    regime = make_stub_regime_state().model_copy_validate(
        {
            "forward_context": ForwardContext(
                as_of=datetime.now(timezone.utc),
                upcoming_catalysts=[
                    MarketEvent(
                        name="Q2 earnings cluster",
                        date=(today + timedelta(days=20)).isoformat(),
                        category="earnings_season",
                        significance="high",
                    )
                ],
            )
        }
    )

    weeks = compute_tenor_window(
        edge_decay=EdgeDecayHorizon.WEEKS,
        regime=regime,
        trader_profile=profile,
        today=today,
    )
    quarters = compute_tenor_window(
        edge_decay=EdgeDecayHorizon.QUARTERS,
        regime=regime,
        trader_profile=profile,
        today=today,
    )

    assert weeks.min_dte == 30
    assert weeks.max_dte == 75
    assert 30 <= weeks.target_dte <= 75
    assert quarters.min_dte == 180
    assert quarters.target_dte == 270
    assert quarters.max_dte == 365


def test_tenor_clamp_respects_profile_min_and_max():
    profile = load_trader_profile()
    profile = profile.model_copy(
        update={
            "constraints": profile.constraints.model_copy(
                update={"min_option_dte": 60, "max_option_dte": 120}
            )
        }
    )

    tenor = compute_tenor_window(
        edge_decay=EdgeDecayHorizon.WEEKS,
        regime=make_stub_regime_state(),
        trader_profile=profile,
    )

    assert tenor.min_dte == 60
    assert tenor.target_dte == 60
    assert tenor.max_dte == 60


def test_base_size_pct_math():
    profile = load_trader_profile()

    strong, strong_key = compute_base_sizing(
        candidate=_candidate(variant_strength=VariantStrength.STRONG, fit_strength=0.85),
        screen=_screen(),
        trader_profile=profile,
    )
    moderate, moderate_key = compute_base_sizing(
        candidate=_candidate(variant_strength=VariantStrength.MODERATE, fit_strength=0.70),
        screen=_screen(),
        trader_profile=profile,
    )
    flagged, flagged_key = compute_base_sizing(
        candidate=_candidate(variant_strength=VariantStrength.STRONG, fit_strength=0.85),
        screen=_screen(data_quality_flag=True),
        trader_profile=profile,
    )

    assert strong_key == "strong_clean"
    assert strong == pytest.approx(0.05)
    assert moderate_key == "moderate_default"
    assert moderate == pytest.approx(0.02)
    assert flagged_key == "weak_or_flagged"
    assert flagged == pytest.approx(0.01)


def test_max_loss_estimate_for_stock_option_and_spread():
    assert max_loss_for_strategy(0.05, "long_stock") == pytest.approx(0.015)
    assert max_loss_for_strategy(0.05, "long_call") == pytest.approx(0.05)
    assert max_loss_for_strategy(0.05, "long_call_spread") == pytest.approx(0.025)


def test_options_fully_forbidden_routes_to_stock(monkeypatch):
    captured = {}
    profile = load_trader_profile()
    allowed = profile.instruments_allowed.model_copy(
        update={
            "long_call": False,
            "long_put": False,
            "covered_call": False,
            "cash_secured_put": False,
            "long_call_spread": False,
            "long_put_spread": False,
            "pair_trade": False,
        }
    )
    profile = profile.model_copy(update={"instruments_allowed": allowed})

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _llm_output(strategy="long_stock")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=profile,
        )
    )

    assert "Eligible instruments: ['long_stock']" in captured["user"]
    assert result.selected_strategy == "long_stock"


def test_pair_thesis_selects_pair_trade_when_allowed(monkeypatch):
    captured = {}

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _llm_output(strategy="pair_trade")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(
                instrument_type=InstrumentType.PAIR,
                variant_view="Relative value pair trade: long XXX / short YYY.",
            ),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert "Eligible instruments: ['pair_trade']" in captured["user"]
    assert result.selected_strategy == "pair_trade"
    assert result.expression.primary_instrument.instrument_type == InstrumentType.PAIR


def test_bullish_priority_with_call_spread_is_aligned(monkeypatch):
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="long_call_spread",
            priority_direction=PriorityThesisDirection.BULLISH,
        ),
        priority=_priority(),
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "long_call_spread"


def test_bullish_priority_with_put_spread_is_direction_misaligned(monkeypatch):
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="long_put_spread",
            priority_direction=PriorityThesisDirection.BULLISH,
        ),
        priority=_priority(),
    )

    assert isinstance(result, TradeExpressionRejection)
    assert result.rejection_rule_fired == "direction_misaligned"
    assert "bullish" in result.misalignment_reason
    assert result.effective_direction == "bearish"


def test_bearish_priority_with_long_put_is_aligned(monkeypatch):
    bearish_priority = _priority(
        theme="Supply-shock losers with margin downside",
        rationale=(
            "The priority is bearish on companies that lose if the supply shock "
            "raises input costs and damages margins."
        ),
        edge_hypothesis=(
            "Consensus is underpricing downside for exposed losers whose "
            "earnings break under the supply-shock scenario."
        ),
    )
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="long_put",
            priority_direction=PriorityThesisDirection.BEARISH,
        ),
        priority=bearish_priority,
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "long_put"


def test_bearish_priority_with_long_call_is_direction_misaligned(monkeypatch):
    bearish_priority = _priority(
        theme="Supply-shock losers with margin downside",
        rationale=(
            "The priority is bearish on companies that lose if the supply shock "
            "raises input costs and damages margins."
        ),
        edge_hypothesis=(
            "Consensus is underpricing downside for exposed losers whose "
            "earnings break under the supply-shock scenario."
        ),
    )
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="long_call",
            priority_direction=PriorityThesisDirection.BEARISH,
        ),
        priority=bearish_priority,
    )

    assert isinstance(result, TradeExpressionRejection)
    assert result.rejection_rule_fired == "direction_misaligned"
    assert "bearish" in result.misalignment_reason
    assert result.effective_direction == "bullish"


def test_ambiguous_priority_skips_direction_check(monkeypatch):
    ambiguous_priority = _priority(
        theme="Dry powder dynamics across strategic capital deployment",
        rationale=(
            "The priority is about where capital deployment goes, not one "
            "clean directional trade on every candidate."
        ),
        edge_hypothesis=(
            "Consensus is misreading positioning and strategic capital flows "
            "rather than a simple upside or downside path."
        ),
    )
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="long_put",
            priority_direction=PriorityThesisDirection.AMBIGUOUS,
        ),
        candidate=_candidate(
            variant_view="Consensus underestimates downside in this leg."
        ),
        priority=ambiguous_priority,
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "long_put"


def test_pair_priority_skips_direction_check_for_pair_trade(monkeypatch):
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="pair_trade",
            priority_direction=PriorityThesisDirection.PAIR,
        ),
        candidate=_candidate(
            instrument_type=InstrumentType.PAIR,
            variant_view="Relative value pair trade: long XXX / short YYY.",
        ),
        priority=_priority(
            theme="Quality winners pair trade against crowded beta",
            rationale="The priority is a relative value long/short expression.",
            edge_hypothesis=(
                "Consensus is mispricing relative value between quality winners "
                "and crowded beta losers."
            ),
        ),
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "pair_trade"


def test_covered_call_in_bullish_priority_is_treated_as_neutral(monkeypatch):
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="covered_call",
            priority_direction=PriorityThesisDirection.BULLISH,
        ),
        priority=_priority(),
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "covered_call"


def test_cash_secured_put_in_bearish_priority_is_treated_as_neutral(monkeypatch):
    bearish_priority = _priority(
        theme="Supply-shock losers with margin downside",
        rationale=(
            "The priority is bearish on companies that lose if the supply shock "
            "raises input costs and damages margins."
        ),
        edge_hypothesis=(
            "Consensus is underpricing downside for exposed losers whose "
            "earnings break under the supply-shock scenario."
        ),
    )
    result = _run_with_mock(
        monkeypatch,
        _llm_output(
            strategy="cash_secured_put",
            priority_direction=PriorityThesisDirection.BEARISH,
        ),
        priority=bearish_priority,
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "cash_secured_put"


def test_missing_priority_direction_field_warns_and_skips_check(monkeypatch, caplog):
    caplog.set_level("WARNING")
    result = _run_with_mock(
        monkeypatch,
        _llm_output(strategy="long_put_spread"),
        priority=_priority(),
    )

    assert isinstance(result, TradeExpressionRejection) is False
    assert result.selected_strategy == "long_put_spread"
    assert "missing priority_thesis_direction" in caplog.text


def test_successful_path_sets_target_derivation_and_entry_metadata(monkeypatch):
    result = _run_with_mock(monkeypatch, _llm_output())

    assert result.expression.target_derivation.method == "technical"
    assert result.expression.target_derivation.implied_price == pytest.approx(115.0)
    assert result.expression.entry_mode == "confirmation_required"
    assert result.expression.entry_trigger_price == pytest.approx(95.0)
    assert "strike_rule_validated" in (result.notes or "")


def test_spread_strike_violation_retries_once(monkeypatch):
    invalid = _llm_output(
        strategy="long_put_spread",
        priority_direction=PriorityThesisDirection.BEARISH,
        primary_description="long Mar 2027 $17.50/$7.50 put spread",
        entry_logic="Enter on confirmed close below $14.53.",
        target_derivation={
            "method": "technical",
            "inputs_used": [
                "Breakdown below $14.53 support from supplied technical anchors",
                "Measured downside zone near $7.50 from spread payoff boundary",
            ],
            "implied_price": 7.5,
        },
    )
    valid = _llm_output(
        strategy="long_put_spread",
        priority_direction=PriorityThesisDirection.BEARISH,
        primary_description="long Mar 2027 $15/$7.50 put spread",
        entry_logic="Enter on confirmed close below $14.53.",
        target_derivation={
            "method": "technical",
            "inputs_used": [
                "Breakdown below $14.53 support from supplied technical anchors",
                "Measured downside zone near $7.50 from spread payoff boundary",
            ],
            "implied_price": 7.5,
        },
    )
    calls = []

    def fake_parse_structured(**kwargs):
        calls.append(kwargs["user"])
        return invalid if len(calls) == 1 else valid

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(
                variant_view="Consensus underestimates downside and margin compression."
            ),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert len(calls) == 2
    assert "Previous output violated the spread upper-strike rule" in calls[1]
    assert result.expression.primary_instrument.description == (
        "long Mar 2027 $15/$7.50 put spread"
    )
    assert result.expression.entry_mode == "confirmation_required"
    assert result.expression.entry_trigger_price == pytest.approx(14.53)
    assert "strike_rule_validated" in (result.notes or "")


def test_second_spread_strike_violation_returns_warning_note(monkeypatch):
    invalid = _llm_output(
        strategy="long_put_spread",
        priority_direction=PriorityThesisDirection.BEARISH,
        primary_description="long Mar 2027 $17.50/$7.50 put spread",
        entry_logic="Enter on confirmed close below $14.53.",
        target_derivation={
            "method": "technical",
            "inputs_used": [
                "Breakdown below $14.53 support from supplied technical anchors",
                "Measured downside zone near $7.50 from spread payoff boundary",
            ],
            "implied_price": 7.5,
        },
    )
    calls = 0

    def fake_parse_structured(**_kwargs):
        nonlocal calls
        calls += 1
        return invalid

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(
                variant_view="Consensus underestimates downside and margin compression."
            ),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert calls == 2
    assert result.fallback_used is False
    assert "strike_rule_warning" in (result.notes or "")


def test_llm_failure_returns_fallback_components(monkeypatch):
    def fake_parse_structured(**_kwargs):
        raise StructuredOutputError("schema failed")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )
    result = asyncio.run(
        express_trade(
            candidate=_candidate(),
            screen=_screen(),
            fundamentals=_fundamentals(),
            market=_market(),
            regime=make_stub_regime_state(),
            trader_profile=load_trader_profile(),
        )
    )

    assert result.fallback_used is True
    assert result.selected_strategy == "long_stock"
    assert result.expression.primary_instrument.description.startswith("Small long")


def test_too_few_falsifiers_triggers_fallback(monkeypatch):
    result = _run_with_mock(monkeypatch, _llm_output(falsifier_count=2))

    assert result.fallback_used is True
    assert len(result.trade_falsifiers) >= 3


def test_successful_path_has_three_falsifiers_and_alternative(monkeypatch):
    result = _run_with_mock(monkeypatch, _llm_output())

    assert result.fallback_used is False
    assert len(result.trade_falsifiers) >= 3
    assert result.expression.alternatives_considered
    assert result.proposed_sizing.base_size_pct <= load_trader_profile().constraints.max_position_pct


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_components_assemble_into_trade_idea(monkeypatch):
    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        lambda **_kwargs: _llm_output(strategy="long_call_spread"),
    )
    candidate = _candidate(ticker="ETN")
    regime = make_stub_regime_state()
    components = asyncio.run(
        express_trade(
            candidate=candidate,
            screen=_screen(),
            fundamentals=get_fundamental_data("ETN"),
            market=get_market_data("ETN"),
            regime=regime,
            trader_profile=load_trader_profile(),
        )
    )
    trade = TradeIdea(
        underlying="ETN",
        research_priority=regime.research_priorities[0],
        regime=regime,
        combined_conviction=Conviction(
            rating=ConvictionRating.STRONG,
            rule_applied="test_rule",
            weakest_link="none",
            reasoning="Synthetic integration conviction.",
        ),
        expression=components.expression,
        proposed_sizing=components.proposed_sizing,
        expected_holding_period=components.expected_holding_period,
        thesis_review_cadence=components.thesis_review_cadence,
        trade_falsifiers=components.trade_falsifiers,
        invalidation_thesis=components.invalidation_thesis,
    )

    assert trade.expression is not None
    assert len(trade.trade_falsifiers) >= 3
