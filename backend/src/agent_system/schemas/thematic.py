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
from typing import Annotated, Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.agent_system.schemas.common import (
    BaseSchema,
    Catalyst,
    Evidence,
    UnitInterval,
)
from src.agent_system.schemas.regime import ResearchPriority


def compute_fit_strength_from_components(
    components: "FitStrengthComponents",
) -> float:
    """Compute deterministic fit_strength from the documented sub-scores."""

    return round(
        (0.40 * components.thesis_mechanism_match)
        + (0.30 * components.consensus_anchoring_strength)
        + (0.20 * components.catalyst_proximity)
        + (0.10 * components.tradeability),
        4,
    )


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


class ConsensusType(str, Enum):
    """Type of consensus claim made in a candidate's consensus_view."""

    ESTIMATE = "estimate"
    POSITIONING = "positioning"
    NARRATIVE = "narrative"
    MIXED = "mixed"


class VerificationRequiredEvidence(BaseSchema):
    """
    Thematic-only evidence marker for claims that need unavailable source data.

    The thematic agent currently has no sell-side estimates, positioning feeds,
    short-interest datasets, or fund-flow data. When it makes an estimate- or
    positioning-consensus claim, it must flag the missing validation source here
    instead of presenting the claim as sourced evidence.
    """

    source_type: Literal["verification_required"] = "verification_required"
    claim: str = Field(min_length=1, max_length=2000)
    supports: bool = True
    computation: str = Field(
        default="No direct source available to the thematic agent.",
        min_length=1,
        max_length=500,
    )
    upstream_claims: List[str] = Field(
        default_factory=lambda: ["missing external source"],
        min_length=1,
        max_length=20,
    )
    notes: str = Field(
        min_length=1,
        max_length=2000,
        description="What external data would be required to validate this claim.",
    )


ThematicFitEvidence = Annotated[
    Union[Evidence, VerificationRequiredEvidence],
    Field(discriminator="source_type"),
]


class FitStrengthComponents(BaseModel):
    """
    Audit trail for fit_strength.

    fit_strength is computed as:
      40% thesis_mechanism_match
      30% consensus_anchoring_strength
      20% catalyst_proximity
      10% tradeability
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    thesis_mechanism_match: UnitInterval
    consensus_anchoring_strength: UnitInterval
    catalyst_proximity: UnitInterval
    tradeability: UnitInterval


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

    @field_validator("ticker", mode="before")
    @classmethod
    def _validate_ticker_format(cls, v: str) -> str:
        if isinstance(v, str) and ("/" in v or any(ch.isspace() for ch in v)):
            raise ValueError(
                "ticker must be a single symbol (no '/' or whitespace). "
                "For pair trades, use one leg's ticker (the long leg, "
                "conventionally) and describe the pair in thematic_fit; "
                "set instrument_type=PAIR. Got: " + repr(v)
            )
        return v

    # Fit to the source priority
    @model_validator(mode="before")
    @classmethod
    def _compute_fit_strength_from_components(cls, data):
        if not isinstance(data, dict):
            return data
        raw_components = data.get("fit_strength_components")
        if raw_components is None:
            return data
        components = FitStrengthComponents.model_validate(raw_components)
        data = dict(data)
        data["fit_strength"] = compute_fit_strength_from_components(components)
        return data

    thematic_fit: str = Field(
        min_length=1,
        max_length=1000,
        description="Specific tie-back to the priority — not generic 'this is energy'.",
    )
    fit_strength: UnitInterval
    fit_strength_components: Optional[FitStrengthComponents] = Field(
        default=None,
        description=(
            "Named sub-scores used to compute fit_strength. Required for new "
            "thematic-agent output; optional only for backward-compatible records."
        ),
    )
    fit_evidence: List[ThematicFitEvidence] = Field(default_factory=list, max_length=15)

    # The variant view requirement
    consensus_view: str = Field(
        min_length=1,
        max_length=2000,
        description="What the market thinks. If this is blank or trivial, the candidate is unresearchable.",
    )
    consensus_type: ConsensusType = ConsensusType.NARRATIVE
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
    priority_rank: int = Field(ge=1, le=15)
    recommended_research_depth: ResearchDepth

    # Pre-attached metadata from regime_overlay.TICKER_METADATA (optional)
    theme_tags: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Tags from existing TICKER_METADATA, e.g. 'oil_beta', 'quality_ai'.",
    )
    existing_position_verdicts: List[dict[str, Any]] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Conviction-stage diagnostics comparing this candidate with already "
            "held/watched/recently closed positions. Empty unless the existing "
            "position filter runs."
        ),
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


class RejectedQuickItem(BaseModel):
    """A quickly dismissed ticker from the broader universe audit trail."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )

    ticker: str = Field(min_length=1, max_length=20)
    one_line_reason: str = Field(
        min_length=5,
        max_length=100,
        description="Tight reason for quick dismissal; not a full exclusion record.",
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
    rejected_quick: List[RejectedQuickItem] = Field(
        default_factory=list,
        max_length=30,
        description="Fast first-pass dismissals that did not warrant full exclusion records.",
    )

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
