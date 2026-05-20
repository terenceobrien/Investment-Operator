"""
Tests for agent_system.schemas.narrative.

Covers:
- CurrentNarrative with archetype enum
- InefficiencyThesis why_it_persists discipline
- NarrativeAnalysis narrative_could_be_wrong_if minimum length
- Separation of narrative falsifiers from trade falsifiers (semantic distinction)

Shared fixtures (narrative_analysis, strong_analysis_conviction) come from
conftest.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_system.schemas.common import (
    InefficiencyArchetype,
)
from agent_system.schemas.narrative import (
    CurrentNarrative,
    InefficiencyThesis,
    NarrativeAge,
    NarrativeAnalysis,
)
from agent_system.schemas.regime import EdgeDecayHorizon


# ─────────────────────────────────────────────────────────────────────────────
# CurrentNarrative
# ─────────────────────────────────────────────────────────────────────────────


class TestCurrentNarrative:
    def test_well_formed(self):
        cn = CurrentNarrative(
            summary="Market sees CVX as a generic E&P proxy.",
            dominant_archetype=InefficiencyArchetype(
                "narrative_fundamental_divergence"
            ),
            narrative_strength=6.5,
            narrative_age=NarrativeAge.ESTABLISHED,
        )
        assert cn.secondary_archetype is None

    def test_with_secondary_archetype(self):
        cn = CurrentNarrative(
            summary=(
                "Established narrative around AI capex sustainability has reached "
                "consensus, with crowded positioning on the largest beneficiaries."
            ),
            dominant_archetype=InefficiencyArchetype(
                "narrative_fundamental_divergence"
            ),
            secondary_archetype=InefficiencyArchetype(
                "crowded_trade_positioning_extreme"
            ),
            narrative_strength=8.5,
            narrative_age=NarrativeAge.MATURE,
        )
        assert cn.secondary_archetype is not None

    def test_unknown_archetype_acceptable(self):
        # The UNKNOWN sentinel exists for cases where the agent can't classify.
        # Downstream rules can branch on this — for example, refuse to
        # generate ideas if narrative archetype is UNKNOWN.
        cn = CurrentNarrative(
            summary="Hard to characterize — market reaction has been mixed.",
            dominant_archetype=InefficiencyArchetype.UNKNOWN,
            narrative_strength=3.0,
            narrative_age=NarrativeAge.EMERGING,
        )
        assert cn.dominant_archetype == InefficiencyArchetype.UNKNOWN

    def test_narrative_strength_bounded(self):
        with pytest.raises(ValidationError):
            CurrentNarrative(
                summary="Market sees CVX as a generic E&P proxy.",
                dominant_archetype=InefficiencyArchetype(
                    "narrative_fundamental_divergence"
                ),
                narrative_strength=11.0,  # > 10, invalid
                narrative_age=NarrativeAge.ESTABLISHED,
            )

    def test_summary_minimum_length(self):
        with pytest.raises(ValidationError):
            CurrentNarrative(
                summary="short",  # < 20 chars
                dominant_archetype=InefficiencyArchetype(
                    "narrative_fundamental_divergence"
                ),
                narrative_strength=5.0,
                narrative_age=NarrativeAge.ESTABLISHED,
            )


# ─────────────────────────────────────────────────────────────────────────────
# InefficiencyThesis — why_it_persists discipline
# ─────────────────────────────────────────────────────────────────────────────


class TestInefficiencyThesis:
    def test_well_formed(self):
        it = InefficiencyThesis(
            archetype=InefficiencyArchetype(
                "narrative_fundamental_divergence"
            ),
            description=(
                "Market views CVX as a generic E&P proxy and misses the Permian "
                "unit cost durability."
            ),
            why_it_persists=(
                "Generalist allocators avoid energy; sector specialists are "
                "mandate-constrained."
            ),
            expected_resolution_path="Q4 results force estimate revisions.",
            resolution_horizon=EdgeDecayHorizon.MONTHS,
        )
        assert it.archetype.value == "narrative_fundamental_divergence"

    def test_why_it_persists_minimum_length(self):
        # 20-char minimum prevents placeholder values like "hard to say"
        # or "structural" without elaboration.
        with pytest.raises(ValidationError):
            InefficiencyThesis(
                archetype=InefficiencyArchetype(
                    "narrative_fundamental_divergence"
                ),
                description=(
                    "Market views CVX as a generic E&P proxy and misses the Permian "
                    "advantage."
                ),
                why_it_persists="hard to say",  # < 20 chars
                expected_resolution_path="Q4 results.",
                resolution_horizon=EdgeDecayHorizon.MONTHS,
            )

    def test_description_minimum_length(self):
        with pytest.raises(ValidationError):
            InefficiencyThesis(
                archetype=InefficiencyArchetype(
                    "narrative_fundamental_divergence"
                ),
                description="CVX mispriced",  # < 30 chars
                why_it_persists=(
                    "Generalists avoid energy entirely; sector specialists "
                    "mandate-constrained from upsizing."
                ),
                expected_resolution_path="Q4 results.",
                resolution_horizon=EdgeDecayHorizon.MONTHS,
            )


# ─────────────────────────────────────────────────────────────────────────────
# NarrativeAnalysis — the main per-ticker output
# ─────────────────────────────────────────────────────────────────────────────


class TestNarrativeAnalysis:
    def test_well_formed_via_fixture(self, narrative_analysis):
        # The fixture proves construction works with all required fields.
        assert narrative_analysis.ticker == "CVX"
        assert len(narrative_analysis.narrative_could_be_wrong_if) >= 1

    def test_narrative_falsifiers_required(self, strong_analysis_conviction):
        # narrative_could_be_wrong_if has min_length=1 — empty is invalid.
        # Every narrative analysis must articulate at least one way it could
        # be wrong.
        with pytest.raises(ValidationError):
            NarrativeAnalysis(
                ticker="CVX",
                current_narrative=CurrentNarrative(
                    summary="Market sees CVX as a generic E&P proxy.",
                    dominant_archetype=InefficiencyArchetype(
                        "narrative_fundamental_divergence"
                    ),
                    narrative_strength=6.5,
                    narrative_age=NarrativeAge.ESTABLISHED,
                ),
                inefficiency_thesis=InefficiencyThesis(
                    archetype=InefficiencyArchetype(
                        "narrative_fundamental_divergence"
                    ),
                    description=(
                        "Market views CVX as a generic E&P proxy and misses Permian "
                        "advantage."
                    ),
                    why_it_persists=(
                        "Generalists avoid energy entirely; sector specialists "
                        "mandate-constrained from upsizing."
                    ),
                    expected_resolution_path="Q4 results force revisions.",
                    resolution_horizon=EdgeDecayHorizon.MONTHS,
                ),
                narrative_could_be_wrong_if=[],  # empty — invalid
                conviction=strong_analysis_conviction,
            )

    def test_contradicting_signals_empty_allowed(self, narrative_analysis):
        # Empty contradicting_signals means the agent looked and found
        # nothing — itself a claim, not an oversight.
        assert narrative_analysis.contradicting_signals == []

    def test_source_provenance_optional(self, narrative_analysis):
        # source_narrative_state_asof is Optional for early-phase development.
        # It'll be required later in Phase 2 when the boundary code is built.
        assert narrative_analysis.source_narrative_state_asof is None

    def test_analysis_is_frozen(self, narrative_analysis):
        with pytest.raises(ValidationError):
            narrative_analysis.ticker = "MU"

    def test_with_provenance(self, narrative_analysis):
        # Can attach the source narrative state asof at boundary ingestion.
        with_source = narrative_analysis.model_copy(
            update={"source_narrative_state_asof": "2026-05-19T20:00:00Z"}
        )
        assert with_source.source_narrative_state_asof == "2026-05-19T20:00:00Z"