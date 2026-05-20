"""
Tests for agent_system.schemas.portfolio.

Covers:
- Position and ActiveThesis construction
- ConstraintResponse consistency rules (hard_block vs allowed, etc.)
- PortfolioState composition
- PortfolioDecision queue items
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.agent_system.schemas.common import (
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
)
from src.agent_system.schemas.portfolio import (
    ActiveThesis,
    AlignmentSummary,
    AlternativePath,
    ConstraintResponse,
    ExposureBucket,
    FalsifierCheckResult,
    PortfolioDecision,
    PortfolioDecisionType,
    PortfolioState,
    Position,
    ThesisPerformance,
    ThesisStatus,
)


# ─────────────────────────────────────────────────────────────────────────────
# Position
# ─────────────────────────────────────────────────────────────────────────────


class TestPosition:
    def test_well_formed(self):
        p = Position(
            ticker="CVX",
            weight=0.04,
            cost_basis=152.30,
            current_price=158.50,
            theme_tags=["energy", "oil_beta", "real_assets"],
            opened_at=datetime.now(timezone.utc),
            thesis_id="thesis_cvx_001",
        )
        assert p.ticker == "CVX"
        assert p.weight == 0.04

    def test_position_without_thesis_allowed(self):
        # Legacy holdings or mechanical exposures (like cash) may not have
        # a tracked thesis — that's allowed but worth flagging in review.
        p = Position(
            ticker="SPAXX",
            weight=0.22,
            theme_tags=["short_duration", "cash_like"],
            thesis_id=None,
        )
        assert p.thesis_id is None

    def test_weight_bounded(self):
        with pytest.raises(ValidationError):
            Position(ticker="CVX", weight=1.5)  # > 1.0


# ─────────────────────────────────────────────────────────────────────────────
# ActiveThesis
# ─────────────────────────────────────────────────────────────────────────────


class TestActiveThesis:
    def test_well_formed(self):
        t = ActiveThesis(
            trade_id="trade_cvx_001",
            ticker="CVX",
            opened_at=datetime.now(timezone.utc),
            original_thesis_statement=(
                "CVX will compound FCF/share at 15%+ on Permian unit cost improvements."
            ),
            current_status=ThesisStatus.INTACT,
            performance=ThesisPerformance.ON_TRACK,
        )
        assert t.current_status == ThesisStatus.INTACT
        assert t.falsifier_checks == []

    def test_thesis_with_falsifier_checks(self):
        check = FalsifierCheckResult(
            falsifier=Falsifier(
                condition="WTI falls below $65 for 10 sessions",
                observable_in=FalsifierObservable.PRICE_ACTION,
                check_frequency=FalsifierFrequency.DAILY,
            ),
            checked_at=datetime.now(timezone.utc),
            status_after_check="approaching",
            check_notes="WTI closed at $66.80 today; 3 sessions below $70.",
            evidence_observed="WTI close: $66.80",
        )
        t = ActiveThesis(
            trade_id="trade_cvx_001",
            ticker="CVX",
            opened_at=datetime.now(timezone.utc),
            original_thesis_statement=(
                "CVX will compound FCF/share at 15%+ on Permian unit cost improvements."
            ),
            current_status=ThesisStatus.WEAKENING,
            falsifier_checks=[check],
        )
        assert t.current_status == ThesisStatus.WEAKENING
        assert len(t.falsifier_checks) == 1

    def test_short_thesis_statement_rejected(self):
        with pytest.raises(ValidationError):
            ActiveThesis(
                trade_id="trade_cvx_001",
                ticker="CVX",
                opened_at=datetime.now(timezone.utc),
                original_thesis_statement="long CVX",  # < 20 chars
            )

    def test_status_transitions_via_model_copy_validate(self):
        # Theses transition status over time. The portfolio-update job
        # creates a new instance with the updated status via model_copy_validate.
        original = ActiveThesis(
            trade_id="trade_cvx_001",
            ticker="CVX",
            opened_at=datetime.now(timezone.utc),
            original_thesis_statement=(
                "CVX will compound FCF/share at 15%+ on Permian unit cost improvements."
            ),
            current_status=ThesisStatus.INTACT,
        )
        violated = original.model_copy_validate(
            {
                "current_status": ThesisStatus.VIOLATED,
                "last_status_change_at": datetime.now(timezone.utc),
            }
        )
        assert original.current_status == ThesisStatus.INTACT
        assert violated.current_status == ThesisStatus.VIOLATED


# ─────────────────────────────────────────────────────────────────────────────
# ConstraintResponse — Loop A coupling rules
# ─────────────────────────────────────────────────────────────────────────────


class TestConstraintResponse:
    def test_allowed_no_constraints(self):
        r = ConstraintResponse(
            allowed=True,
            reasoning="Proposed trade fits within all sector and theme caps.",
        )
        assert r.allowed is True
        assert r.hard_block is False

    def test_allowed_with_constraints_rejected(self):
        # allowed=True with binding_constraints is inconsistent.
        with pytest.raises(ValidationError):
            ConstraintResponse(
                allowed=True,
                binding_constraints=["AI cap at 30%"],
                reasoning="...",
            )

    def test_soft_block_with_alternatives(self):
        # allowed=False, hard_block=False: trade can proceed with adjustment.
        r = ConstraintResponse(
            allowed=False,
            binding_constraints=[
                "AI quality growth already at 29%, ceiling 30%",
            ],
            alternative_paths=[
                AlternativePath(
                    description="Swap candidate: existing MU position has weakening thesis.",
                    requires_action="close existing MU position",
                ),
                AlternativePath(
                    description="Reduce base size to 1% to fit under cap.",
                ),
            ],
            hard_block=False,
            reasoning="Trade would breach AI cap but alternative paths exist.",
        )
        assert r.allowed is False
        assert r.hard_block is False
        assert len(r.alternative_paths) == 2

    def test_hard_block(self):
        # hard_block=True: trade cannot proceed at all.
        r = ConstraintResponse(
            allowed=False,
            binding_constraints=["Position size exceeds 10% absolute cap"],
            hard_block=True,
            reasoning="Single-position concentration cap is non-negotiable.",
        )
        assert r.hard_block is True

    def test_hard_block_with_allowed_true_rejected(self):
        with pytest.raises(ValidationError):
            ConstraintResponse(
                allowed=True,
                hard_block=True,  # inconsistent
                reasoning="...",
            )


# ─────────────────────────────────────────────────────────────────────────────
# ExposureBucket and AlignmentSummary
# ─────────────────────────────────────────────────────────────────────────────


class TestExposureBucket:
    def test_underweight_bucket(self):
        # Mirrors a row from regime_overlay's exposure_map.
        b = ExposureBucket(
            name="Energy / oil beta",
            current_weight=0.04,
            target_min=0.10,
            target_max=0.20,
            gap_to_min=0.06,
            gap_to_max=0.0,
            status="underweight",
        )
        assert b.status == "underweight"
        assert b.gap_to_min == 0.06

    def test_in_range_bucket(self):
        b = ExposureBucket(
            name="Short duration / cash",
            current_weight=0.22,
            target_min=0.10,
            target_max=0.25,
            gap_to_min=0.0,
            gap_to_max=0.0,
            status="in_range",
        )
        assert b.status == "in_range"


class TestAlignmentSummary:
    def test_basic(self):
        a = AlignmentSummary(
            score=54.5,
            aligned_weight=0.48,
            misaligned_weight=0.35,
            unknown_weight=0.0,
            cash_like_weight=0.22,
            main_mismatch="Portfolio is underweight energy/oil beta relative to this supply-shock regime.",
        )
        assert a.score == 54.5


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioState
# ─────────────────────────────────────────────────────────────────────────────


class TestPortfolioState:
    def test_minimal_portfolio_state(self):
        ps = PortfolioState(
            asof_date="2026-05-19",
            cash_weight=0.22,
        )
        assert ps.positions == []
        assert ps.thesis_inventory == []

    def test_portfolio_state_with_data(self):
        ps = PortfolioState(
            asof_date="2026-05-19",
            total_nav=1_000_000.0,
            cash_weight=0.22,
            positions=[
                Position(ticker="SPAXX", weight=0.22, theme_tags=["cash_like"]),
                Position(ticker="MU", weight=0.14, theme_tags=["quality_ai"]),
                Position(ticker="CVX", weight=0.04, theme_tags=["energy", "oil_beta"]),
            ],
            top1_concentration=0.22,
            top3_concentration=0.40,
            top5_concentration=0.51,
        )
        assert len(ps.positions) == 3
        assert ps.top3_concentration == 0.40


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioDecision
# ─────────────────────────────────────────────────────────────────────────────


class TestPortfolioDecision:
    def test_new_trade_decision(self):
        d = PortfolioDecision(
            decision_type=PortfolioDecisionType.NEW_TRADE,
            ticker="CVX",
            trade_idea_ref="trade_cvx_001",
            rationale=(
                "Strong-conviction CVX long passes all rules and fits "
                "under sector cap. Recommend opening at 4% NAV."
            ),
        )
        assert d.decision_type == PortfolioDecisionType.NEW_TRADE
        assert d.forced_action is False
        assert d.priority == "normal"

    def test_forced_close_on_thesis_violation(self):
        d = PortfolioDecision(
            decision_type=PortfolioDecisionType.CLOSE,
            ticker="IBIT",
            active_thesis_ref="thesis_ibit_001",
            rationale=(
                "Falsifier 'liquidity-sensitive risk asset behavior' has triggered: "
                "IBIT has correlated more closely with QQQ than with gold over "
                "the last 20 sessions. Thesis violated."
            ),
            forced_action=True,
            priority="urgent",
            feedback_to_construction=(
                "Liquidity-sensitive risk exposure slot is now open if needed."
            ),
        )
        assert d.forced_action is True
        assert d.priority == "urgent"

    def test_short_rationale_rejected(self):
        with pytest.raises(ValidationError):
            PortfolioDecision(
                decision_type=PortfolioDecisionType.HOLD,
                ticker="CVX",
                rationale="hold",  # < 20 chars
            )