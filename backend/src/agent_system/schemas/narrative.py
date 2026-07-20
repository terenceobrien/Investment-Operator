"""
Narrative schemas — the narrative agent's per-ticker output.

The existing Pipeline B (synth.py / schema.py) produces NarrativeStateV1, which
is a *market-wide* view: dominant narratives, inefficiency map, market tone.
This module is the agent-system layer that produces *per-ticker* narrative
analyses by consuming NarrativeStateV1 plus ticker-specific news.

Key design choices:

- This is NOT a replacement for NarrativeStateV1. The narrative agent reads
  NarrativeStateV1 as input and produces NarrativeAnalysis as output. The
  two live side by side — Pipeline B handles the market-wide synthesis;
  the agent system handles the per-ticker application.

- `narrative_could_be_wrong_if` is SEPARATE from trade-level falsifiers.
  The narrative read itself can be wrong (we misread how the market is
  positioned on this name) independent of whether the trade thesis is wrong.
  Collapsing them into one falsifier list would conflate two different
  uncertainties.

- `current_archetype` uses the InefficiencyArchetype enum sourced from the
  taxonomy. Use `archetype_from_taxonomy_id` at the boundary when ingesting
  values from NarrativeStateV1.inefficiency_map[].archetype_id (which is a
  free string).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import Field

from src.agent_system.schemas.common import (
    AnalysisConviction,
    BaseSchema,
    Evidence,
    InefficiencyArchetype,
    Score0to10,
)
from src.agent_system.schemas.regime import EdgeDecayHorizon


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class NarrativeAge(str, Enum):
    """
    Maturity of the current narrative.

    Different ages imply different risk profiles. EMERGING narratives have
    less crowded positioning but more uncertainty; MATURE narratives are
    well-priced; FADING narratives may already be reversing.
    """

    EMERGING = "emerging"          # narrative just forming, not yet consensus
    ESTABLISHED = "established"    # narrative is consensus, well-recognized
    MATURE = "mature"              # narrative fully priced, late stage
    FADING = "fading"              # narrative losing grip, possible reversal


# ─────────────────────────────────────────────────────────────────────────────
# Building blocks
# ─────────────────────────────────────────────────────────────────────────────


class CurrentNarrative(BaseSchema):
    """
    What the market story is right now for this ticker.

    `dominant_archetype` is the agent's classification of which inefficiency
    archetype best describes the current setup. `secondary_archetype` is for
    cases where two archetypes overlap (e.g. narrative_fundamental_divergence
    on the long side with crowded_trade_positioning_extreme on the short).
    """

    summary: str = Field(min_length=20, max_length=2000)
    dominant_archetype: InefficiencyArchetype
    secondary_archetype: Optional[InefficiencyArchetype] = None
    narrative_strength: Score0to10 = Field(
        description="How entrenched the current narrative is, 0=barely a story to 10=fully consensus."
    )
    narrative_age: NarrativeAge


class InefficiencyThesis(BaseSchema):
    """
    The specific dislocation the agent thinks exists for this ticker.

    `why_it_persists` is the most important field — every reasonable
    inefficiency should have eventually closed, so if a mispricing is still
    present, there must be a structural reason. Common answers: information
    is hard to access, time horizon mismatch, mandate constraints prevent
    institutional money from acting, market plumbing creates flow not tied
    to fundamentals. An agent that can't articulate why_it_persists doesn't
    have a real thesis.
    """

    archetype: InefficiencyArchetype
    description: str = Field(
        min_length=30,
        max_length=2000,
        description="Specific to this ticker, not generic taxonomy text.",
    )
    evidence: List[Evidence] = Field(default_factory=list, max_length=15)
    why_it_persists: str = Field(
        min_length=20,
        max_length=2000,
        description=(
            "Structural reason this mispricing hasn't been arbitraged away. "
            "Without this, the thesis is just 'I disagree with the price'."
        ),
    )
    expected_resolution_path: str = Field(min_length=20, max_length=2000)
    resolution_horizon: EdgeDecayHorizon


# ─────────────────────────────────────────────────────────────────────────────
# NarrativeAnalysis — top-level per-ticker output
# ─────────────────────────────────────────────────────────────────────────────


class NarrativeAnalysis(BaseSchema):
    """
    Per-ticker narrative + sentiment + inefficiency analysis.

    Inputs (consumed at the boundary, not stored here):
    - NarrativeStateV1 from Pipeline B (market-wide narrative state)
    - Ticker-specific news, filings, transcripts

    Outputs: a structured per-ticker read on what story the market is
    telling, what's mispriced, how that mispricing resolves, and what
    would invalidate the narrative read itself.
    """

    ticker: str = Field(min_length=1, max_length=20)

    current_narrative: CurrentNarrative
    inefficiency_thesis: InefficiencyThesis

    # Query-layer metadata from src.agent_system.narrative_service. These are
    # additive so older persisted NarrativeAnalysis records still validate.
    coverage_quality: Literal["high", "medium", "low", "absent", "stale"] = "absent"
    snapshot_date: Optional[str] = Field(default=None, max_length=20)
    snapshot_subject: Optional[str] = Field(default=None, max_length=20)
    inefficiency_archetype_id: Optional[str] = Field(default=None, max_length=200)
    price_confirmation: Optional[
        Literal["confirming", "contradicting", "partial", "unavailable"]
    ] = None
    sector_etf: Optional[str] = Field(default=None, max_length=20)
    sector_narrative_alignment: Optional[
        Literal["aligned", "diverging", "idiosyncratic", "no_sector_signal"]
    ] = None
    source_narrative_indices: List[int] = Field(default_factory=list)
    is_stale: bool = False

    # Narrative-level falsifiers — separate from trade falsifiers.
    # These invalidate the NARRATIVE READ, not the trade thesis.
    narrative_could_be_wrong_if: List[str] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Conditions under which the narrative read itself would be wrong. "
            "Separate from trade falsifiers (which kill the trade). A "
            "narrative falsifier triggers re-analysis, not necessarily an exit. "
            "Minimum 1 — every narrative read must articulate at least one "
            "way it could be wrong."
        ),
    )
    contradicting_signals: List[Evidence] = Field(
        default_factory=list,
        max_length=15,
        description=(
            "Evidence that contradicts the narrative read. Empty list means "
            "the agent looked and found no contradicting evidence — itself "
            "a claim worth surfacing in review."
        ),
    )

    # Self-rated conviction
    conviction: AnalysisConviction

    # Provenance — which NarrativeStateV1 snapshot this was derived from
    source_narrative_state_asof: Optional[str] = Field(
        default=None,
        max_length=50,
        description=(
            "asof_utc of the NarrativeStateV1 snapshot consumed. None if the "
            "agent worked from raw news without a market-wide synthesis. "
            "Required for full lineage but optional in the schema for "
            "flexibility during early-phase development."
        ),
    )
