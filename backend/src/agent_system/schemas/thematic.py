"""
Thematic schemas — the thematic/opportunity-mapping agent's output.

Inputs: a ResearchPriority from the macro agent.
Outputs: a ThematicMap with a ranked list of Candidate instruments, each with
an articulated consensus view and potential variant view.

Design principles:
- A Candidate without an articulated variant view is rated `VariantStrength.UNCLEAR`
  and shouldn't be promoted to deep research. This is where we enforce "we're
  not researching things just because they fit the theme."
- The thematic map's `excluded` list is intentionally first-class. Explicit
  rejection — with reasons — is as important as inclusion. It documents what
  was considered and rejected, which makes the research process auditable.
- Theme tags reuse the strings from regime_overlay.EXPOSURE_BUCKETS and
  TICKER_METADATA where possible, so candidates can be filtered against the
  same buckets the portfolio overlay uses.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field

from src.agent_system.schemas.common import (
    BaseSchema,
    Catalyst,
    Evidence,
    UnitInterval,
)
from src.agent_system.schemas.regime import ResearchPriority


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class InstrumentType(str, Enum):
    """
    Categorization of tradeable instruments.

    Matches asset_type values in regime_overlay.TICKER_METADATA where they
    overlap. ADR and PAIR are new — needed by the construction agent to know
    what expressions are available.
    """

    SINGLE_STOCK = "single_stock"
    ETF = "etf"
    ADR = "adr"
    MONEY_MARKET = "money_market"
    COMMODITY = "commodity"
    OPTION_UNDERLYING = "option_underlying"
    PAIR = "pair"  # for paired/spread expressions


class VariantStrength(str, Enum):
    """
    Strength of the articulated variant view.

    A candidate with UNCLEAR variant strength is research that hasn't yet
    found an edge. The conviction rules at the construction layer will reject
    trades where the underlying candidate had UNCLEAR variant strength —
    which forces honest "we don't have edge here yet" rather than fitting an
    idea to a theme.
    """

    UNCLEAR = "unclear"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class ResearchDepth(str, Enum):
    """How much downstream investigation a candidate warrants."""

    SHALLOW = "shallow"      # quick fundamental check, no narrative agent
    STANDARD = "standard"    # full fundamental + narrative analysis
    DEEP = "deep"            # full pipeline + extra steps (channel checks, etc.)


# ─────────────────────────────────────────────────────────────────────────────
# Candidate — one potential instrument under a research priority
# ─────────────────────────────────────────────────────────────────────────────


class Candidate(BaseSchema):
    """
    A specific instrument the thematic agent thinks is worth investigating.

    The crucial fields are `consensus_view` and `potential_variant_view`. If
    the variant view is articulable and meaningful, the candidate has real
    potential edge. If not (variant_strength == UNCLEAR), it's a thematic
    fit without an edge thesis — and downstream agents should not generate
    trade ideas from it.

    `thematic_fit` is the qualitative tie-back to the priority; `fit_strength`
    is the agent's numeric estimate (0–1) of how well the instrument fits.
    Fit strength alone doesn't justify a trade — variant strength does.
    """

    ticker: str = Field(min_length=1, max_length=20)
    instrument_type: InstrumentType
    name: str = Field(default="", max_length=200, description="Display name.")

    # Fit to the source priority
    thematic_fit: str = Field(
        min_length=1,
        max_length=1000,
        description="Specific tie-back to the priority — not generic 'this is energy'.",
    )
    fit_strength: UnitInterval
    fit_evidence: List[Evidence] = Field(default_factory=list, max_length=15)

    # The variant view requirement
    consensus_view: str = Field(
        min_length=1,
        max_length=2000,
        description="What the market thinks. If this is blank or trivial, the candidate is unresearchable.",
    )
    potential_variant_view: str = Field(
        default="",
        max_length=2000,
        description=(
            "Where consensus might be wrong. Empty means no articulated variant — "
            "such a candidate should be rated VariantStrength.UNCLEAR."
        ),
    )
    variant_strength: VariantStrength
    variant_evidence: List[Evidence] = Field(default_factory=list, max_length=15)

    # Catalysts and depth recommendation
    catalysts: List[Catalyst] = Field(default_factory=list, max_length=10)
    priority_rank: int = Field(ge=1, le=10)
    recommended_research_depth: ResearchDepth

    # Pre-attached metadata from regime_overlay.TICKER_METADATA (optional)
    theme_tags: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Tags from existing TICKER_METADATA, e.g. 'oil_beta', 'quality_ai'.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Exclusion record — explicit "considered but rejected"
# ─────────────────────────────────────────────────────────────────────────────


class ExclusionRecord(BaseSchema):
    """
    A ticker that was considered but explicitly rejected.

    Recording these is as important as recording candidates. It makes the
    research process auditable (you can see what was looked at and rejected)
    and prevents the same candidate from being re-evaluated repeatedly with
    no new information.
    """

    ticker: str = Field(min_length=1, max_length=20)
    reason: str = Field(
        min_length=10,
        max_length=1000,
        description="Specific reason for exclusion. Minimum 10 chars enforced.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# ThematicMap — the top-level output of the thematic agent
# ─────────────────────────────────────────────────────────────────────────────


class ThematicMap(BaseSchema):
    """
    Output of the thematic agent for a single research priority.

    One ResearchPriority in, one ThematicMap out. Multiple priorities produce
    multiple ThematicMaps. The thematic agent does NOT combine across
    priorities — that's the construction agent's job when ranking trades
    across themes.

    `mapping_logic` is required prose explaining how the candidate set was
    derived from the priority. This makes the agent's reasoning auditable
    even when LLM internals are opaque — if mapping_logic doesn't make sense
    given the candidates produced, that's a clear failure signal.
    """

    source_priority_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Storage id of the upstream ResearchPriority. Populated by the repository.",
    )
    source_priority: ResearchPriority

    candidates: List[Candidate] = Field(default_factory=list, max_length=30)
    excluded: List[ExclusionRecord] = Field(default_factory=list, max_length=50)

    mapping_logic: str = Field(
        min_length=20,
        max_length=3000,
        description="How candidates were filtered from the universe. Required prose.",
    )

    # Counters for the rejection store / review UI to query without recomputing
    universe_considered: int = Field(
        default=0,
        ge=0,
        description="How many instruments were screened before filtering. 0 if not tracked.",
    )