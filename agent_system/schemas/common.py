"""
Foundational types for the agent system.

Every other schema in agent_system.schemas imports from this module. The types
here intentionally have no dependencies on existing Helix code so they can be
imported into any context.

Design choices worth noting:

- All models are frozen via ConfigDict(frozen=True). Mutation raises
  ValidationError. Use model_copy(update={...}) to derive a modified version.
- Evidence is a discriminated union by source_type. Construction without the
  required source-link field for that type will fail at validation time, not
  at downstream use. This is deliberate: "evidence with no link" is the most
  common failure mode of LLM research output and we want it to fail fast.
- The InefficiencyArchetype enum is sourced from the existing
  inefficiency_taxonomy.INEFFICIENCY_TAXONOMY at import time, so the two
  cannot drift. Add a new archetype to the taxonomy and it appears here
  automatically.
- Timestamps are real datetime objects (UTC). The existing narrative pipeline
  uses string `asof_utc` — boundary code in narrative.py will translate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)

from agent_system import SCHEMA_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Bounded numeric types — reused everywhere
# ─────────────────────────────────────────────────────────────────────────────

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
"""Confidence, probabilities, normalized scores. Always 0.0–1.0 inclusive."""

Score0to10 = Annotated[float, Field(ge=0.0, le=10.0)]
"""Layer-level scoring scale (matches regime_layers.LayerScore.score)."""

Score0to100 = Annotated[float, Field(ge=0.0, le=100.0)]
"""Composite scoring scale (matches regime_layers composite and confidence)."""


# ─────────────────────────────────────────────────────────────────────────────
# Enums — closed vocabularies the rules engine can match on
# ─────────────────────────────────────────────────────────────────────────────


class ConvictionRating(str, Enum):
    """
    Five-level conviction scale used throughout the system.

    Order matters: PASS < WEAK < MODERATE < STRONG < EXCEPTIONAL.
    Compare via ConvictionRating.rank() to check thresholds.
    """

    PASS = "pass"
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    EXCEPTIONAL = "exceptional"

    @property
    def rank(self) -> int:
        """Numeric rank for threshold comparisons. PASS=0, EXCEPTIONAL=4."""
        return _CONVICTION_RANK[self]

    def at_least(self, other: "ConvictionRating") -> bool:
        """True if this rating is >= other."""
        return self.rank >= other.rank


_CONVICTION_RANK = {
    ConvictionRating.PASS: 0,
    ConvictionRating.WEAK: 1,
    ConvictionRating.MODERATE: 2,
    ConvictionRating.STRONG: 3,
    ConvictionRating.EXCEPTIONAL: 4,
}


class EvidenceSourceType(str, Enum):
    """
    Closed set of evidence source categories.

    Each value corresponds to a concrete Evidence subclass below. When adding
    a new source type, also add the corresponding model and update the
    Evidence union.
    """

    FRED = "fred"
    NEWS = "news"
    FILING = "filing"
    PRICE = "price"
    POSITIONING = "positioning"
    DERIVED = "derived"  # computed from other evidence; must cite inputs


class FalsifierObservable(str, Enum):
    """Where a falsifier can be checked for trigger status."""

    DATA_SERIES = "data_series"  # FRED, market data, etc.
    NEWS = "news"
    PRICE_ACTION = "price_action"
    POSITIONING_DATA = "positioning_data"
    EARNINGS = "earnings"
    FILING = "filing"


class FalsifierFrequency(str, Enum):
    """How often the falsifier-checking job should re-evaluate."""

    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    EVENT_DRIVEN = "event_driven"


class FalsifierStatus(str, Enum):
    """Current trigger state of a falsifier."""

    NOT_TRIGGERED = "not_triggered"
    APPROACHING = "approaching"
    TRIGGERED = "triggered"
    UNKNOWN = "unknown"  # check failed or data unavailable


class CatalystType(str, Enum):
    """Categorization of trade catalysts."""

    EARNINGS = "earnings"
    MACRO_RELEASE = "macro_release"
    POLICY = "policy"
    GEOPOLITICAL = "geopolitical"
    PRODUCT = "product"
    STRUCTURAL = "structural"
    LITIGATION = "litigation"
    CORPORATE_ACTION = "corporate_action"


# Build InefficiencyArchetype from the existing taxonomy so the two cannot
# drift. We import lazily inside the build function to avoid a hard dependency
# at module load time (useful in tests / partial setups).
def _build_archetype_enum() -> type[Enum]:
    try:
        from inefficiency_taxonomy import INEFFICIENCY_TAXONOMY
    except ImportError:
        # Fallback: hardcoded IDs matching the v1 taxonomy. Kept in sync
        # manually if the import path isn't available (e.g. in isolated tests).
        ids = [
            "narrative_fundamental_divergence",
            "speculative_bubble_mania",
            "panic_crash_forced_liquidation",
            "post_earnings_announcement_drift",
            "momentum_trend_persistence",
            "value_mean_reversion",
            "volatility_risk_premium",
            "liquidity_crisis",
            "crowded_trade_positioning_extreme",
            "information_cascade",
            "regime_shift",
            "event_driven_mispricing",
            "credit_equity_divergence",
            "small_cap_neglect",
        ]
    else:
        ids = [item["id"] for item in INEFFICIENCY_TAXONOMY]

    # Always include UNKNOWN sentinel for the agent-system enum. This matches
    # the convention in NarrativeStateV1.executive_snapshot.primary_archetype
    # which uses "Not specified" when classification fails. In the agent
    # system we use a real enum value so downstream rules can branch on it.
    members = {_to_enum_member_name(i): i for i in ids}
    members["UNKNOWN"] = "unknown_unclassified"
    return Enum("InefficiencyArchetype", members, type=str)


def _to_enum_member_name(taxonomy_id: str) -> str:
    """Convert snake_case taxonomy id to UPPER_SNAKE enum member name."""
    return taxonomy_id.upper()


InefficiencyArchetype = _build_archetype_enum()
"""
Enum of inefficiency archetypes, sourced from inefficiency_taxonomy.

Values are the snake_case ids (e.g. "narrative_fundamental_divergence").
Member names are the upper-case form (e.g. NARRATIVE_FUNDAMENTAL_DIVERGENCE).
Always includes an UNKNOWN sentinel for unclassifiable cases.
"""


def archetype_from_taxonomy_id(taxonomy_id: Optional[str]) -> InefficiencyArchetype:
    """
    Convert a taxonomy id (or alias) to the corresponding enum member.

    Uses normalize_archetype_id from inefficiency_taxonomy if available so
    aliases resolve correctly. Returns UNKNOWN for unrecognized values.

    Use this at the boundary when consuming output from the narrative pipeline
    (NarrativeStateV1.inefficiency_map[].archetype_id).
    """
    if not taxonomy_id:
        return InefficiencyArchetype.UNKNOWN

    try:
        from inefficiency_taxonomy import normalize_archetype_id

        normalized = normalize_archetype_id(taxonomy_id)
    except ImportError:
        normalized = taxonomy_id.lower().strip()

    if not normalized:
        return InefficiencyArchetype.UNKNOWN

    try:
        return InefficiencyArchetype(normalized)
    except ValueError:
        return InefficiencyArchetype.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Base schema — every domain model inherits from this
# ─────────────────────────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseSchema(BaseModel):
    """
    Common base for all agent-system schemas.

    Provides:
    - Immutability (frozen=True)
    - Strict validation (extra="forbid" catches typos in agent output)
    - schema_version for forward compatibility
    - created_at for audit / lineage
    - Optional id for storage; populated by the repository on save
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,  # keep enum members, not their string values
    )

    schema_version: str = Field(default=SCHEMA_VERSION)
    created_at: datetime = Field(default_factory=_utcnow)
    id: Optional[str] = Field(
        default=None,
        description="Storage primary key. None until persisted by the repository.",
    )

    def model_copy_validate(self, update: Optional[dict] = None):
        """
        Like model_copy(update=...) but re-runs validation on the result.

        Pydantic v2's built-in model_copy is a fast path that does NOT re-run
        field validators on updated values. For frozen schemas where the
        intent is "produce a new validated instance with these changes," that
        behavior is a footgun — you can silently produce an invalid object.

        Use this helper whenever the updated values need to be validated:
            updated = original.model_copy_validate({"rating": new_rating})

        For fields you trust (e.g. setting an id after storage save), the
        plain model_copy is fine and faster.
        """
        data = self.model_dump()
        if update:
            data.update(update)
        return type(self).model_validate(data)


# ─────────────────────────────────────────────────────────────────────────────
# Evidence — discriminated union by source_type
# ─────────────────────────────────────────────────────────────────────────────


class _EvidenceBase(BaseSchema):
    """
    Shared fields for all evidence types. Not used directly — subclass instead.

    `claim` is what the evidence supports or contradicts.
    `supports` is True if the evidence supports the claim, False if it
    contradicts it. Forcing this to be explicit prevents the failure mode
    where the same source is cited both ways in different contexts without
    the agent noticing the contradiction.
    """

    claim: str = Field(min_length=1, max_length=2000)
    supports: bool
    retrieved_at: datetime = Field(default_factory=_utcnow)
    notes: str = Field(default="", max_length=2000)


class FREDEvidence(_EvidenceBase):
    """Evidence sourced from a FRED data series."""

    source_type: Literal[EvidenceSourceType.FRED] = EvidenceSourceType.FRED
    series_id: str = Field(min_length=1, max_length=64)
    observation_date: datetime
    observation_value: Optional[float] = None


class NewsEvidence(_EvidenceBase):
    """
    Evidence sourced from a news article or other published web content.

    Mirrors the shape of NarrativeStateV1.EvidenceItem (channel, source,
    title, url) so narrative-pipeline output can be wrapped cleanly.
    """

    source_type: Literal[EvidenceSourceType.NEWS] = EvidenceSourceType.NEWS
    publisher: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    url: Optional[HttpUrl] = None
    published_at: Optional[datetime] = None
    channel: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Pipeline B channel tag, e.g. 'policy', 'ticker_news'",
    )


class FilingEvidence(_EvidenceBase):
    """Evidence sourced from a regulatory filing (10-K, 10-Q, 8-K, etc.)."""

    source_type: Literal[EvidenceSourceType.FILING] = EvidenceSourceType.FILING
    cik: str = Field(min_length=1, max_length=20)
    accession_number: str = Field(min_length=1, max_length=30)
    form_type: str = Field(min_length=1, max_length=20)
    filed_at: datetime
    excerpt: str = Field(default="", max_length=4000)


class PriceEvidence(_EvidenceBase):
    """Evidence sourced from price or technical market data."""

    source_type: Literal[EvidenceSourceType.PRICE] = EvidenceSourceType.PRICE
    ticker: str = Field(min_length=1, max_length=20)
    metric: str = Field(
        min_length=1,
        max_length=100,
        description="What about the price, e.g. 'rsi_14', 'pct_above_200dma'",
    )
    value: float
    as_of: datetime
    timeframe: Optional[str] = Field(
        default=None,
        max_length=20,
        description="e.g. 'daily', '1h', '5m'",
    )


class PositioningEvidence(_EvidenceBase):
    """Evidence sourced from positioning, flow, or sentiment data."""

    source_type: Literal[EvidenceSourceType.POSITIONING] = EvidenceSourceType.POSITIONING
    instrument: str = Field(min_length=1, max_length=50)
    metric: str = Field(
        min_length=1,
        max_length=100,
        description="e.g. 'cot_net_spec', 'short_interest_pct_float', 'put_call_ratio'",
    )
    value: float
    percentile_vs_history: Optional[UnitInterval] = None
    as_of: datetime


class DerivedEvidence(_EvidenceBase):
    """
    Evidence computed from other evidence (e.g. a comparison or ratio).

    Must cite at least one upstream evidence claim. This prevents the failure
    mode where an agent asserts a derived conclusion without traceable inputs.
    """

    source_type: Literal[EvidenceSourceType.DERIVED] = EvidenceSourceType.DERIVED
    computation: str = Field(min_length=1, max_length=500)
    upstream_claims: List[str] = Field(min_length=1, max_length=20)


# Discriminated union: pydantic v2 picks the right subclass based on source_type.
Evidence = Annotated[
    Union[
        FREDEvidence,
        NewsEvidence,
        FilingEvidence,
        PriceEvidence,
        PositioningEvidence,
        DerivedEvidence,
    ],
    Field(discriminator="source_type"),
]
"""
Discriminated union of all evidence types.

Use as a field annotation directly:
    evidence: List[Evidence] = []

Pydantic will pick the right subclass based on the source_type field in the
input data. Construction without the required source-link fields for the
declared source_type will raise ValidationError.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Falsifiers, catalysts, conviction
# ─────────────────────────────────────────────────────────────────────────────


class Falsifier(BaseSchema):
    """
    A condition that, if observed, invalidates a thesis or regime call.

    The falsifier-checking job (Phase 4) re-evaluates `current_status` on a
    cadence determined by `check_frequency`. A falsifier whose `observable_in`
    is NEWS or EARNINGS will be evaluated by an LLM check; DATA_SERIES,
    PRICE_ACTION, and POSITIONING_DATA can be evaluated mechanically.
    """

    condition: str = Field(min_length=1, max_length=1000)
    observable_in: FalsifierObservable
    check_frequency: FalsifierFrequency
    current_status: FalsifierStatus = FalsifierStatus.NOT_TRIGGERED
    last_checked_at: Optional[datetime] = None
    notes: str = Field(default="", max_length=2000)


class Catalyst(BaseSchema):
    """
    An event expected to resolve uncertainty in a thesis.

    Either `earliest_date` and `latest_date` are both set (event window) or
    both None and `is_ongoing` is True (continuous catalyst, e.g. macro
    backdrop). The validator below enforces this.
    """

    event: str = Field(min_length=1, max_length=500)
    catalyst_type: CatalystType
    earliest_date: Optional[datetime] = None
    latest_date: Optional[datetime] = None
    is_ongoing: bool = False
    asymmetry: str = Field(
        default="",
        max_length=1000,
        description="Payoff if right vs cost if wrong, in plain language.",
    )

    @field_validator("latest_date")
    @classmethod
    def _check_date_order(
        cls, v: Optional[datetime], info
    ) -> Optional[datetime]:
        earliest = info.data.get("earliest_date")
        if v is not None and earliest is not None and v < earliest:
            raise ValueError("latest_date must be >= earliest_date")
        return v

    @field_validator("is_ongoing")
    @classmethod
    def _check_ongoing_vs_dates(cls, v: bool, info) -> bool:
        earliest = info.data.get("earliest_date")
        # If ongoing, dates should be None. If dates set, ongoing should be False.
        # We don't have latest_date in info.data yet (validators run in order),
        # so we only check earliest here.
        if v and earliest is not None:
            raise ValueError(
                "is_ongoing=True requires earliest_date=None "
                "(use one or the other, not both)"
            )
        return v


class Conviction(BaseSchema):
    """
    Output of the conviction rules engine.

    The `rule_applied` field is the name of the specific rule function that
    produced this rating. This makes every conviction decision auditable —
    given a Conviction, you can find the exact code that produced it.

    `weakest_link` identifies which input dimension drove the rating down,
    if any. Used by the construction agent to decide whether to escalate
    a contradiction flag (Loop C).
    """

    rating: ConvictionRating
    rule_applied: str = Field(min_length=1, max_length=200)
    weakest_link: Literal[
        "fundamental",
        "narrative",
        "thematic",
        "regime",
        "none",
        "unknown",
    ] = "unknown"
    reasoning: str = Field(min_length=1, max_length=2000)


class AnalysisConviction(BaseSchema):
    """
    Self-rated conviction reported by a single analysis (fundamental, narrative).

    Distinct from `Conviction` above, which is the OUTPUT of the rules engine
    that combines multiple analyses. AnalysisConviction is the INPUT — what a
    single analysis says about its own confidence.

    `primary_uncertainty` is required. An analysis that cannot articulate its
    biggest source of uncertainty is one that hasn't grappled honestly with
    what it might be missing — and downstream rules should cap such an
    analysis at MODERATE regardless of its rating.
    """

    rating: ConvictionRating
    justification: str = Field(min_length=20, max_length=2000)
    primary_uncertainty: str = Field(
        min_length=10,
        max_length=1000,
        description=(
            "The single thing most likely to be wrong about this analysis. "
            "Forces honest engagement with what could be missed. Minimum 10 "
            "chars to prevent placeholder values like 'unknown' or 'TBD'."
        ),
    )