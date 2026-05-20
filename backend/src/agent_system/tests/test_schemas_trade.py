"""
Tests for agent_system.schemas.trade.

The most important tests in this file cover the conviction/expression
coupling enforced by the model validator. The schema literally cannot
represent "a trade idea that didn't pass conviction" — that's the
structural enforcement of the pragmatic-bearish discipline.

Shared fixtures (strong_combined_conviction, pass_combined_conviction,
long_cvx_expression, proposed_sizing_4pct, three_trade_falsifiers) come
from conftest.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent_system.schemas.common import (
    ConvictionRating,
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
)
from src.agent_system.schemas.thematic import InstrumentType
from src.agent_system.schemas.trade import (
    AlternativeRejected,
    Hedge,
    HedgeType,
    Instrument,
    ReviewCadence,
    TradeDirection,
    TradeExpression,
    TradeIdea,
)


# ─────────────────────────────────────────────────────────────────────────────
# Instrument and basic types
# ─────────────────────────────────────────────────────────────────────────────


class TestInstrument:
    def test_well_formed(self):
        i = Instrument(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            direction=TradeDirection.LONG,
        )
        assert i.ticker == "CVX"
        assert i.direction == TradeDirection.LONG

    def test_with_description(self):
        i = Instrument(
            ticker="CVX",
            instrument_type=InstrumentType.OPTION_UNDERLYING,
            direction=TradeDirection.LONG,
            description="Jan 2027 $100 calls, paying 12% of underlying.",
        )
        assert "Jan 2027" in i.description


class TestHedge:
    def test_well_formed_index_short(self):
        h = Hedge(
            hedge_type=HedgeType.INDEX_SHORT,
            instrument=Instrument(
                ticker="SPY",
                instrument_type=InstrumentType.ETF,
                direction=TradeDirection.SHORT,
            ),
            hedge_ratio=0.3,
            rationale="Short SPY to neutralize broad-market beta.",
        )
        assert h.hedge_ratio == 0.3

    def test_none_hedge(self):
        # Hedge with type NONE is valid (e.g. "no hedge needed").
        h = Hedge(
            hedge_type=HedgeType.NONE,
            rationale="Position size small enough that hedging isn't worth the cost.",
        )
        assert h.hedge_type == HedgeType.NONE


# ─────────────────────────────────────────────────────────────────────────────
# TradeExpression
# ─────────────────────────────────────────────────────────────────────────────


class TestTradeExpression:
    def test_well_formed(self, long_cvx_expression):
        # The fixture proves construction works.
        assert long_cvx_expression.primary_instrument.ticker == "CVX"
        assert long_cvx_expression.hedges == []

    def test_with_alternatives_considered(self):
        e = TradeExpression(
            primary_instrument=Instrument(
                ticker="CVX",
                instrument_type=InstrumentType.SINGLE_STOCK,
                direction=TradeDirection.LONG,
            ),
            rationale_for_instrument="Direct single-name exposure to Permian thesis.",
            alternatives_considered=[
                AlternativeRejected(
                    instrument=Instrument(
                        ticker="XLE",
                        instrument_type=InstrumentType.ETF,
                        direction=TradeDirection.LONG,
                    ),
                    why_rejected="Includes too much smaller-cap E&P which dilutes the thesis.",
                ),
            ],
            entry_logic="Scale in over 3 sessions on confirmation.",
            exit_target="20% target or thesis validation.",
            exit_stop="10% trailing stop.",
        )
        assert len(e.alternatives_considered) == 1


# ─────────────────────────────────────────────────────────────────────────────
# TradeIdea — the conviction/expression coupling
# ─────────────────────────────────────────────────────────────────────────────


class TestAcceptedTradeIdea:
    def test_well_formed_accepted_trade(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        proposed_sizing_4pct,
        three_trade_falsifiers,
    ):
        # Happy path: STRONG conviction, expression present, all required fields.
        idea = TradeIdea(
            underlying="CVX",
            combined_conviction=strong_combined_conviction,
            expression=long_cvx_expression,
            proposed_sizing=proposed_sizing_4pct,
            expected_holding_period="3-6 months",
            thesis_review_cadence=ReviewCadence.MONTHLY,
            next_review_trigger="Q4 earnings release",
            trade_falsifiers=three_trade_falsifiers,
            invalidation_thesis=(
                "Permian unit cost improvements reverse and Q4 capex guide "
                "is raised meaningfully above Q3 levels."
            ),
        )
        assert idea.combined_conviction.rating == ConvictionRating.STRONG
        assert idea.expression is not None
        assert idea.rejection_reason is None

    def test_accepted_trade_requires_expression(
        self,
        strong_combined_conviction,
        proposed_sizing_4pct,
        three_trade_falsifiers,
    ):
        # STRONG conviction with expression=None must fail.
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=None,  # invalid — STRONG requires expression
                proposed_sizing=proposed_sizing_4pct,
                thesis_review_cadence=ReviewCadence.MONTHLY,
                trade_falsifiers=three_trade_falsifiers,
                invalidation_thesis="...",
            )

    def test_accepted_trade_requires_sizing(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        three_trade_falsifiers,
    ):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=long_cvx_expression,
                proposed_sizing=None,  # invalid
                thesis_review_cadence=ReviewCadence.MONTHLY,
                trade_falsifiers=three_trade_falsifiers,
                invalidation_thesis="...",
            )

    def test_accepted_trade_requires_min_3_falsifiers(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        proposed_sizing_4pct,
    ):
        # Only 2 falsifiers — invalid.
        too_few = [
            Falsifier(
                condition="WTI falls below $65 for 10 sessions",
                observable_in=FalsifierObservable.PRICE_ACTION,
                check_frequency=FalsifierFrequency.DAILY,
            ),
            Falsifier(
                condition="CVX raises capex guide >15%",
                observable_in=FalsifierObservable.EARNINGS,
                check_frequency=FalsifierFrequency.EVENT_DRIVEN,
            ),
        ]
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=long_cvx_expression,
                proposed_sizing=proposed_sizing_4pct,
                thesis_review_cadence=ReviewCadence.MONTHLY,
                trade_falsifiers=too_few,
                invalidation_thesis="...",
            )

    def test_accepted_trade_requires_invalidation_thesis(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        proposed_sizing_4pct,
        three_trade_falsifiers,
    ):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=long_cvx_expression,
                proposed_sizing=proposed_sizing_4pct,
                thesis_review_cadence=ReviewCadence.MONTHLY,
                trade_falsifiers=three_trade_falsifiers,
                invalidation_thesis=None,  # invalid
            )

    def test_accepted_trade_requires_review_cadence(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        proposed_sizing_4pct,
        three_trade_falsifiers,
    ):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=long_cvx_expression,
                proposed_sizing=proposed_sizing_4pct,
                thesis_review_cadence=None,  # invalid
                trade_falsifiers=three_trade_falsifiers,
                invalidation_thesis="...",
            )

    def test_accepted_trade_rejects_rejection_fields(
        self,
        strong_combined_conviction,
        long_cvx_expression,
        proposed_sizing_4pct,
        three_trade_falsifiers,
    ):
        # Accepted trades can't have rejection_reason or rejection_stage.
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=strong_combined_conviction,
                expression=long_cvx_expression,
                proposed_sizing=proposed_sizing_4pct,
                thesis_review_cadence=ReviewCadence.MONTHLY,
                trade_falsifiers=three_trade_falsifiers,
                invalidation_thesis="...",
                rejection_reason="this shouldn't be here",  # invalid
            )


class TestRejectedTradeIdea:
    def test_well_formed_rejection(self, pass_combined_conviction):
        # PASS conviction with no expression, with rejection fields set.
        idea = TradeIdea(
            underlying="CVX",
            combined_conviction=pass_combined_conviction,
            expression=None,
            proposed_sizing=None,
            rejection_reason=(
                "Fundamental analysis lacked an articulated variant view; "
                "the agent agreed with consensus, which is not a tradeable thesis."
            ),
            rejection_stage="single_name",
            rejection_rule_fired="rule_missing_variant_view",
        )
        assert idea.expression is None
        assert idea.rejection_reason is not None

    def test_rejection_cannot_have_expression(
        self,
        pass_combined_conviction,
        long_cvx_expression,
    ):
        # PASS conviction with expression set must fail — this is the
        # critical structural enforcement.
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=pass_combined_conviction,
                expression=long_cvx_expression,  # invalid
                rejection_reason="agreeing with consensus",
                rejection_stage="single_name",
            )

    def test_rejection_cannot_have_sizing(
        self,
        pass_combined_conviction,
        proposed_sizing_4pct,
    ):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=pass_combined_conviction,
                expression=None,
                proposed_sizing=proposed_sizing_4pct,  # invalid
                rejection_reason="agreeing with consensus",
                rejection_stage="single_name",
            )

    def test_rejection_requires_reason(self, pass_combined_conviction):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=pass_combined_conviction,
                expression=None,
                rejection_reason=None,  # invalid for PASS
                rejection_stage="single_name",
            )

    def test_rejection_requires_stage(self, pass_combined_conviction):
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=pass_combined_conviction,
                expression=None,
                rejection_reason="some reason for rejection that meets the min length",
                rejection_stage=None,  # invalid for PASS
            )

    def test_rejection_cannot_have_falsifiers(
        self,
        pass_combined_conviction,
        three_trade_falsifiers,
    ):
        # Trade falsifiers belong on accepted trades, not rejections.
        with pytest.raises(ValidationError):
            TradeIdea(
                underlying="CVX",
                combined_conviction=pass_combined_conviction,
                expression=None,
                rejection_reason="agreeing with consensus",
                rejection_stage="single_name",
                trade_falsifiers=three_trade_falsifiers,  # invalid
            )

    def test_weak_conviction_is_also_a_rejection(self):
        # WEAK conviction follows the rejection path — it's NOT an accepted trade.
        from src.agent_system.schemas.common import Conviction

        weak_conviction = Conviction(
            rating=ConvictionRating.WEAK,
            rule_applied="rule_bear_case_unanswered",
            weakest_link="fundamental",
            reasoning="what_bear_case_misses defaulted to 'nothing material' — capping at WEAK.",
        )
        idea = TradeIdea(
            underlying="CVX",
            combined_conviction=weak_conviction,
            expression=None,
            rejection_reason="Bear case insufficiently addressed.",
            rejection_stage="single_name",
            rejection_rule_fired="rule_bear_case_unanswered",
        )
        assert idea.expression is None