"""
Tests for agent_system.schemas.regime.

Covers:
- LayerWeights sum-to-one validation
- RegimeLayerScore boundary adapter from regime_layers.LayerScore
- ResearchPriority edge_hypothesis minimum length (the anti-helpfulness lever)
- Full RegimeState construction with all required fields

Shared fixtures (neutral_layer_score, regime_layers, default_weights,
research_priority, mock_layer_score_cls) come from conftest.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_system.schemas.common import (
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
    FREDEvidence,
)
from agent_system.schemas.regime import (
    EdgeDecayHorizon,
    LayerWeights,
    RegimeDriver,
    RegimeHorizon,
    RegimeLayerScore,
    RegimeLayerStatus,
    RegimeState,
    ResearchPriority,
)


# ─────────────────────────────────────────────────────────────────────────────
# LayerWeights — sum-to-one validation
# ─────────────────────────────────────────────────────────────────────────────


class TestLayerWeights:
    def test_default_weights_valid(self, default_weights):
        # Mirrors regime_layers.WEIGHTS["default"]
        assert default_weights.monetary == 0.20

    def test_swing_weights_valid(self):
        # Mirrors regime_layers.WEIGHTS["swing"]
        w = LayerWeights(
            monetary=0.15,
            credit=0.25,
            volatility=0.25,
            breadth=0.20,
            positioning=0.15,
        )
        assert w.credit == 0.25

    def test_weights_dont_sum_to_one_rejected(self):
        with pytest.raises(ValidationError):
            LayerWeights(
                monetary=0.50,
                credit=0.50,
                volatility=0.50,
                breadth=0.50,
                positioning=0.50,
            )

    def test_weights_tolerance_for_floating_point(self):
        # 0.2 + 0.2 + 0.2 + 0.2 + 0.2 doesn't always equal 1.0 in float —
        # but the tolerance is 0.01 so this should pass.
        w = LayerWeights(
            monetary=0.2,
            credit=0.2,
            volatility=0.2,
            breadth=0.2,
            positioning=0.2,
        )
        assert w.monetary == 0.2


# ─────────────────────────────────────────────────────────────────────────────
# RegimeLayerScore — boundary adapter from regime_layers.LayerScore
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeLayerScoreAdapter:
    def test_adapter_converts_basic_layer(self, mock_layer_score_cls):
        mock = mock_layer_score_cls(
            score=7.2,
            inputs={"DGS10": 4.5, "DFII10": 2.1},
            signals=["yields rising", "real yields elevated"],
            status="bearish",
            data_quality=0.85,
        )
        layer = RegimeLayerScore.from_layer_score(mock)
        assert layer.score == 7.2
        assert layer.status == RegimeLayerStatus.BEARISH
        assert layer.signals == ["yields rising", "real yields elevated"]
        assert layer.inputs["DGS10"] == 4.5
        assert layer.data_quality == 0.85

    def test_adapter_handles_bullish_neutral_bearish(self, mock_layer_score_cls):
        for status_str, expected in [
            ("bullish", RegimeLayerStatus.BULLISH),
            ("neutral", RegimeLayerStatus.NEUTRAL),
            ("bearish", RegimeLayerStatus.BEARISH),
        ]:
            mock = mock_layer_score_cls(
                score=5.0,
                inputs={},
                signals=[],
                status=status_str,
                data_quality=1.0,
            )
            assert RegimeLayerScore.from_layer_score(mock).status == expected

    def test_adapter_defaults_unknown_status_to_neutral(self, mock_layer_score_cls):
        # Tolerant — legacy or malformed status doesn't break ingest.
        mock = mock_layer_score_cls(
            score=5.0,
            inputs={},
            signals=[],
            status="garbage_status_value",
            data_quality=1.0,
        )
        assert RegimeLayerScore.from_layer_score(mock).status == RegimeLayerStatus.NEUTRAL

    def test_adapter_handles_empty_inputs_and_signals(self, mock_layer_score_cls):
        mock = mock_layer_score_cls(
            score=5.0,
            inputs={},
            signals=[],
            status="neutral",
            data_quality=0.0,
        )
        layer = RegimeLayerScore.from_layer_score(mock)
        assert layer.inputs == {}
        assert layer.signals == []

    def test_layer_score_bounds_enforced(self):
        # score is Score0to10 — must be in [0, 10]
        with pytest.raises(ValidationError):
            RegimeLayerScore(
                score=11.0,
                inputs={},
                signals=[],
                status=RegimeLayerStatus.NEUTRAL,
                data_quality=1.0,
            )


# ─────────────────────────────────────────────────────────────────────────────
# RegimeDriver — basic construction
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeDriver:
    def test_driver_construction(self):
        d = RegimeDriver(
            name="Oil supply shock",
            status="bearish for broad beta / bullish for energy",
            explanation=(
                "A prolonged Strait of Hormuz disruption keeps oil elevated, "
                "raising input costs and inflation expectations."
            ),
        )
        assert d.name == "Oil supply shock"


# ─────────────────────────────────────────────────────────────────────────────
# ResearchPriority — the edge_hypothesis anti-helpfulness lever
# ─────────────────────────────────────────────────────────────────────────────


class TestResearchPriority:
    def test_well_formed_priority(self, research_priority):
        # Fixture itself proves a well-formed priority constructs cleanly.
        assert research_priority.priority_rank == 1
        assert research_priority.expected_edge_decay == EdgeDecayHorizon.QUARTERS

    def test_short_edge_hypothesis_rejected(self):
        # Anti-helpfulness lever: a one-liner placeholder can't pass.
        with pytest.raises(ValidationError):
            ResearchPriority(
                theme="energy",
                rationale="oil is going up",
                edge_hypothesis="oil up",  # < 30 chars — invalid
                priority_rank=1,
                expected_edge_decay=EdgeDecayHorizon.WEEKS,
            )

    def test_priority_rank_bounds(self):
        # rank is 1-5
        with pytest.raises(ValidationError):
            ResearchPriority(
                theme="test",
                rationale="test rationale",
                edge_hypothesis="x" * 100,
                priority_rank=6,
                expected_edge_decay=EdgeDecayHorizon.DAYS,
            )

    def test_supporting_evidence_allowed(self):
        ev = FREDEvidence(
            claim="10y yields broke above 4.5%",
            supports=True,
            series_id="DGS10",
            observation_date=datetime.now(timezone.utc),
            observation_value=4.55,
        )
        p = ResearchPriority(
            theme="long-duration vulnerability",
            rationale="yields rising hurts long-duration assets",
            edge_hypothesis=(
                "Market continues to price 3 cuts by year-end despite reaccelerating "
                "inflation; positioning in TLT is still long."
            ),
            priority_rank=2,
            expected_edge_decay=EdgeDecayHorizon.MONTHS,
            supporting_evidence=[ev],
        )
        assert len(p.supporting_evidence) == 1


# ─────────────────────────────────────────────────────────────────────────────
# RegimeState — full construction
# ─────────────────────────────────────────────────────────────────────────────


class TestRegimeState:
    def test_minimal_regime_state(self, regime_layers, default_weights):
        state = RegimeState(
            asof_date="2026-05-19",
            horizon=RegimeHorizon.DEFAULT,
            layers=regime_layers,
            weights=default_weights,
            composite=50.0,
            layer_agreement=0.6,
            composite_confidence=70.0,
            environment="Mixed / Neutral",
            regime_id="mixed_neutral",
            regime_label="Mixed / Neutral",
            regime_call_confidence=0.5,
        )
        assert state.regime_id == "mixed_neutral"
        assert state.research_priorities == []
        assert state.falsifiers == []

    def test_full_regime_state(self, regime_layers, default_weights, research_priority):
        driver = RegimeDriver(
            name="Oil supply shock",
            status="bearish for broad beta / bullish for energy",
            explanation="Hormuz disruption keeps oil elevated.",
        )
        falsifier = Falsifier(
            condition="Oil falls below $70 for 5 sessions",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        )
        state = RegimeState(
            asof_date="2026-05-19",
            horizon=RegimeHorizon.DEFAULT,
            layers=regime_layers,
            weights=default_weights,
            composite=42.0,
            layer_agreement=0.55,
            composite_confidence=68.0,
            environment="Chop / Layer Divergence",
            environment_drivers=["Bullish: monetary, volatility", "Bearish: credit, breadth"],
            regime_id="supply_shock_inflation",
            regime_label="Supply-shock inflation / late-cycle tightening",
            headline="Oil-driven inflation pressure is tightening financial conditions.",
            summary="The regime is being pulled in two directions.",
            risk_summary="Fractured late-cycle setup.",
            key_drivers=[driver],
            portfolio_implications=["Favor energy and short duration."],
            best_positioned=["Energy", "Short duration / cash"],
            most_vulnerable=["Small caps", "Long-duration bonds"],
            regime_call_confidence=0.78,
            falsifiers=[falsifier],
            research_priorities=[research_priority],
        )
        assert state.regime_id == "supply_shock_inflation"
        assert len(state.research_priorities) == 1
        assert state.research_priorities[0].priority_rank == 1

    def test_invalid_asof_date_format(self, regime_layers, default_weights):
        with pytest.raises(ValidationError):
            RegimeState(
                asof_date="May 19 2026",  # wrong format
                horizon=RegimeHorizon.DEFAULT,
                layers=regime_layers,
                weights=default_weights,
                composite=50.0,
                layer_agreement=0.5,
                composite_confidence=50.0,
                environment="Mixed / Neutral",
                regime_id="mixed_neutral",
                regime_label="Mixed / Neutral",
                regime_call_confidence=0.5,
            )

    def test_composite_out_of_bounds(self, regime_layers, default_weights):
        with pytest.raises(ValidationError):
            RegimeState(
                asof_date="2026-05-19",
                horizon=RegimeHorizon.DEFAULT,
                layers=regime_layers,
                weights=default_weights,
                composite=110.0,  # > 100, invalid
                layer_agreement=0.5,
                composite_confidence=50.0,
                environment="Mixed / Neutral",
                regime_id="mixed_neutral",
                regime_label="Mixed / Neutral",
                regime_call_confidence=0.5,
            )

    def test_regime_state_is_frozen(self, regime_layers, default_weights):
        state = RegimeState(
            asof_date="2026-05-19",
            horizon=RegimeHorizon.DEFAULT,
            layers=regime_layers,
            weights=default_weights,
            composite=50.0,
            layer_agreement=0.6,
            composite_confidence=70.0,
            environment="Mixed",
            regime_id="mixed_neutral",
            regime_label="Mixed",
            regime_call_confidence=0.5,
        )
        with pytest.raises(ValidationError):
            state.composite = 99.0  # frozen — must fail