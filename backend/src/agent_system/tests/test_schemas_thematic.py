"""
Tests for agent_system.schemas.thematic.

Covers:
- Candidate construction with consensus/variant view fields
- VariantStrength enforcement of the "no edge => no research" discipline
- ExclusionRecord requirements
- ThematicMap mapping_logic requirement

Shared fixtures (research_priority) come from conftest.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent_system.schemas.common import (
    Catalyst,
    CatalystType,
)
from src.agent_system.schemas.thematic import (
    Candidate,
    ConsensusType,
    ExclusionRecord,
    FitStrengthComponents,
    InstrumentType,
    RejectedQuickItem,
    ResearchDepth,
    ThematicMap,
    VariantStrength,
    VerificationRequiredEvidence,
    compute_fit_strength_from_components,
)


# ─────────────────────────────────────────────────────────────────────────────
# Candidate
# ─────────────────────────────────────────────────────────────────────────────


class TestCandidate:
    def test_well_formed_candidate(self):
        c = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            name="Chevron Corporation",
            thematic_fit=(
                "Integrated major with Permian leverage and refining margin "
                "tailwind in a structurally short global oil environment."
            ),
            fit_strength=0.85,
            consensus_view=(
                "Consensus expects WTI to mean-revert to $75 by year-end on "
                "Hormuz de-escalation; CVX is rated 'sector perform' by most."
            ),
            potential_variant_view=(
                "Forward curve in backwardation suggests physical tightness "
                "is more durable than equity desk consensus reflects."
            ),
            variant_strength=VariantStrength.STRONG,
            priority_rank=1,
            recommended_research_depth=ResearchDepth.DEEP,
            theme_tags=["energy", "oil_beta", "real_assets"],
        )
        assert c.ticker == "CVX"
        assert c.variant_strength == VariantStrength.STRONG

    def test_candidate_with_unclear_variant_strength(self):
        # A candidate without an articulated variant view should be
        # constructable but flagged as UNCLEAR — downstream rules will
        # reject these from generating trade ideas.
        c = Candidate(
            ticker="XLE",
            instrument_type=InstrumentType.ETF,
            thematic_fit="Broad energy sector exposure.",
            fit_strength=0.7,
            consensus_view="Bullish energy is becoming consensus.",
            potential_variant_view="",  # empty — no edge articulated
            variant_strength=VariantStrength.UNCLEAR,
            priority_rank=3,
            recommended_research_depth=ResearchDepth.SHALLOW,
        )
        assert c.variant_strength == VariantStrength.UNCLEAR
        assert c.potential_variant_view == ""

    def test_thematic_fit_required(self):
        with pytest.raises(ValidationError):
            Candidate(
                ticker="CVX",
                instrument_type=InstrumentType.SINGLE_STOCK,
                thematic_fit="",  # empty — invalid
                fit_strength=0.5,
                consensus_view="something",
                variant_strength=VariantStrength.UNCLEAR,
                priority_rank=1,
                recommended_research_depth=ResearchDepth.STANDARD,
            )

    def test_fit_strength_bounds(self):
        with pytest.raises(ValidationError):
            Candidate(
                ticker="CVX",
                instrument_type=InstrumentType.SINGLE_STOCK,
                thematic_fit="x" * 50,
                fit_strength=1.5,  # > 1.0, invalid
                consensus_view="something",
                variant_strength=VariantStrength.UNCLEAR,
                priority_rank=1,
                recommended_research_depth=ResearchDepth.STANDARD,
            )

    def test_priority_rank_bounds(self):
        with pytest.raises(ValidationError):
            Candidate(
                ticker="CVX",
                instrument_type=InstrumentType.SINGLE_STOCK,
                thematic_fit="x" * 50,
                fit_strength=0.5,
                consensus_view="something",
                variant_strength=VariantStrength.UNCLEAR,
                priority_rank=16,  # > 15, invalid
                recommended_research_depth=ResearchDepth.STANDARD,
            )

    def test_priority_rank_allows_full_candidate_map_range(self):
        c = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            thematic_fit="x" * 50,
            fit_strength=0.5,
            consensus_view="something",
            variant_strength=VariantStrength.UNCLEAR,
            priority_rank=12,
            recommended_research_depth=ResearchDepth.STANDARD,
        )
        assert c.priority_rank == 12

    def test_pair_ticker_string_is_rejected(self):
        with pytest.raises(ValidationError, match="ticker must be a single symbol"):
            Candidate(
                ticker="RSP/SPY",
                instrument_type=InstrumentType.PAIR,
                thematic_fit="Long RSP versus short SPY as a breadth normalization pair.",
                fit_strength=0.7,
                consensus_view="Cap-weight leadership remains consensus.",
                potential_variant_view="Equal-weight may outperform as leadership broadens.",
                variant_strength=VariantStrength.MODERATE,
                priority_rank=1,
                recommended_research_depth=ResearchDepth.STANDARD,
            )

    def test_candidate_with_catalyst(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        c = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            thematic_fit="Permian leverage in tight global oil.",
            fit_strength=0.8,
            consensus_view="Expecting in-line Q3.",
            potential_variant_view="Q3 capex guide may surprise on cost discipline.",
            variant_strength=VariantStrength.MODERATE,
            priority_rank=2,
            recommended_research_depth=ResearchDepth.STANDARD,
            catalysts=[
                Catalyst(
                    event="Q3 earnings",
                    catalyst_type=CatalystType.EARNINGS,
                    earliest_date=now,
                    latest_date=now + timedelta(days=2),
                    asymmetry="+5% if beat, -2% if in-line",
                )
            ],
        )
        assert len(c.catalysts) == 1
        assert c.catalysts[0].catalyst_type == CatalystType.EARNINGS

    def test_fit_strength_computed_from_components(self):
        components = FitStrengthComponents(
            thesis_mechanism_match=1.0,
            consensus_anchoring_strength=0.75,
            catalyst_proximity=0.5,
            tradeability=1.0,
        )
        c = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            thematic_fit="Directly exposed to the thesis mechanism.",
            fit_strength=0.1,  # overwritten by components
            fit_strength_components=components,
            consensus_view="Narrative-based: consensus appears cautious.",
            consensus_type=ConsensusType.NARRATIVE,
            potential_variant_view="Consensus may be too cautious.",
            variant_strength=VariantStrength.MODERATE,
            priority_rank=1,
            recommended_research_depth=ResearchDepth.STANDARD,
        )
        assert c.fit_strength == compute_fit_strength_from_components(components)

    def test_verification_required_fit_evidence_allowed(self):
        c = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            thematic_fit="Directly exposed to refinancing EPS drag.",
            fit_strength=0.7,
            consensus_view=(
                "Estimate-based: consensus appears to under-model higher "
                "refinancing coupons."
            ),
            consensus_type=ConsensusType.ESTIMATE,
            fit_evidence=[
                VerificationRequiredEvidence(
                    claim="Consensus interest expense claim requires validation.",
                    supports=True,
                    notes="Need current sell-side interest expense estimates.",
                )
            ],
            potential_variant_view="Higher coupons could pressure EPS.",
            variant_strength=VariantStrength.MODERATE,
            priority_rank=1,
            recommended_research_depth=ResearchDepth.STANDARD,
        )
        assert c.fit_evidence[0].source_type == "verification_required"


# ─────────────────────────────────────────────────────────────────────────────
# ExclusionRecord
# ─────────────────────────────────────────────────────────────────────────────


class TestExclusionRecord:
    def test_well_formed_exclusion(self):
        e = ExclusionRecord(
            ticker="XOP",
            reason=(
                "Equal-weight E&P index — excessive small-cap weight given "
                "the regime's small-cap caution. CVX or XOM are cleaner."
            ),
        )
        assert e.ticker == "XOP"

    def test_short_reason_rejected(self):
        # 10-char minimum prevents one-word excuses like "no" or "skip".
        with pytest.raises(ValidationError):
            ExclusionRecord(ticker="XOP", reason="no")


# ─────────────────────────────────────────────────────────────────────────────
# ThematicMap
# ─────────────────────────────────────────────────────────────────────────────


class TestThematicMap:
    def test_well_formed_thematic_map(self, research_priority):
        candidate = Candidate(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            thematic_fit="Permian + refining + buybacks.",
            fit_strength=0.85,
            consensus_view="Sector perform consensus.",
            potential_variant_view="Forward curve signals tighter physical market than equity desks reflect.",
            variant_strength=VariantStrength.STRONG,
            priority_rank=1,
            recommended_research_depth=ResearchDepth.DEEP,
        )
        exclusion = ExclusionRecord(
            ticker="XOP",
            reason="Equal-weight E&P index gives unwanted small-cap risk.",
        )
        tm = ThematicMap(
            source_priority=research_priority,
            candidates=[candidate],
            excluded=[exclusion],
            rejected_quick=[
                RejectedQuickItem(
                    ticker="XLE",
                    one_line_reason="ETF too broad for this single-name thesis.",
                )
            ],
            mapping_logic=(
                "Filtered the energy universe by oil_beta > 0.7 and quality_score > 0.6, "
                "then ranked by capital return + balance sheet."
            ),
            universe_considered=42,
        )
        assert len(tm.candidates) == 1
        assert len(tm.excluded) == 1
        assert len(tm.rejected_quick) == 1
        assert tm.universe_considered == 42

    def test_mapping_logic_minimum_length(self, research_priority):
        # 20-char minimum prevents placeholder mapping_logic.
        with pytest.raises(ValidationError):
            ThematicMap(
                source_priority=research_priority,
                candidates=[],
                mapping_logic="filtered",  # too short
            )

    def test_thematic_map_with_empty_candidates_allowed(self, research_priority):
        # It's valid for a thematic map to produce zero candidates — that's
        # an honest answer of "this priority doesn't surface anything worth
        # investigating right now."
        tm = ThematicMap(
            source_priority=research_priority,
            candidates=[],
            mapping_logic=(
                "Filtered the energy universe by oil_beta and quality but no "
                "name meets the variant-strength bar at current valuations."
            ),
        )
        assert tm.candidates == []
        assert tm.excluded == []

    def test_thematic_map_is_frozen(self, research_priority):
        tm = ThematicMap(
            source_priority=research_priority,
            mapping_logic="Filtered the universe and surfaced these candidates.",
        )
        with pytest.raises(ValidationError):
            tm.universe_considered = 99  # frozen — must fail
