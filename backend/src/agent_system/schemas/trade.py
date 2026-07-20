"""
Trade schemas — the construction agent's output.

A TradeIdea is the synthesis point where all upstream analyses meet the
conviction rules. The most important structural discipline here is the
coupling between conviction and expression: if conviction is WEAK or PASS,
the `expression` field MUST be None and `rejection_reason` MUST be set.
This is enforced by a model validator, so the schema itself cannot represent
"a recommended trade that didn't pass conviction" — that's a contradiction.

Key disciplines:
- `trade_falsifiers` requires min 3 — forces enumeration of multiple
  invalidation paths, not just "if it goes against me."
- `invalidation_thesis` is required prose distinct from a price stop. The
  point is "what condition would prove the thesis itself wrong" — which is
  different from "what price triggers a stop-loss for risk management."
- All upstream analyses are referenced by id (foreign keys at the storage
  layer). The full TradeIdea has the actual schemas inlined for runtime
  use; storage layer will store just the ids and rehydrate as needed.
- Rejections are TradeIdeas with expression=None plus a rejection_reason.
  This unifies the accepted-trade and rejected-idea storage path.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import Field

from src.agent_system.schemas.common import (
    BaseSchema,
    Conviction,
    ConvictionRating,
    Evidence,
    Falsifier,
    UnitInterval,
)
from src.agent_system.schemas.fundamental import FundamentalAnalysis
from src.agent_system.schemas.narrative import NarrativeAnalysis
from src.agent_system.schemas.regime import RegimeState, ResearchPriority
from src.agent_system.schemas.thematic import InstrumentType


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class TradeDirection(str, Enum):
    """Direction of the trade expression."""

    LONG = "long"
    SHORT = "short"
    PAIR_LONG_SHORT = "pair_long_short"      # long X / short Y
    SPREAD = "spread"                         # calendar, vertical, etc.
    NEUTRAL = "neutral"                       # delta-neutral options, etc.


class ReviewCadence(str, Enum):
    """How often the trade's thesis should be re-evaluated."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    EVENT_DRIVEN = "event_driven"


class HedgeType(str, Enum):
    """Category of hedging instrument."""

    INDEX_SHORT = "index_short"               # short SPY/QQQ against long
    SECTOR_SHORT = "sector_short"             # short XLE against long CVX
    PUT_OPTION = "put_option"
    VOLATILITY = "volatility"                 # long VIX, long IV
    CORRELATION = "correlation"               # correlated short
    NONE = "none"


# ─────────────────────────────────────────────────────────────────────────────
# Building blocks
# ─────────────────────────────────────────────────────────────────────────────


class Instrument(BaseSchema):
    """A specific tradeable instrument."""

    ticker: str = Field(min_length=1, max_length=20)
    instrument_type: InstrumentType
    direction: TradeDirection
    description: str = Field(
        default="",
        max_length=500,
        description="Optional human-readable description, e.g. 'long Jan 2027 $100 calls'.",
    )


class AlternativeRejected(BaseSchema):
    """An alternative expression that was considered but rejected."""

    instrument: Instrument
    why_rejected: str = Field(min_length=15, max_length=1000)


class Hedge(BaseSchema):
    """
    A hedge attached to the primary expression.

    `hedge_ratio` is the size relationship between the hedge and the primary
    position, expressed as a fraction. 0.5 means hedge sized at half the
    primary. Hedges with type NONE should never have a non-zero ratio.
    """

    hedge_type: HedgeType
    instrument: Optional[Instrument] = None
    hedge_ratio: UnitInterval = Field(
        default=0.0,
        description="Fraction of primary position size, 0.0–1.0.",
    )
    rationale: str = Field(min_length=10, max_length=1000)


class TargetDerivation(BaseSchema):
    """How the trade expression derived its stated exit target."""

    method: Literal[
        "technical",
        "valuation",
        "analyst_target",
        "measured_move",
        "volatility",
        "thesis_based_no_price",
    ]
    inputs_used: List[str] = Field(
        min_length=1,
        max_length=10,
        description="Specific inputs used to derive the target.",
    )
    implied_price: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Price implied by the method, or None for thesis-based targets.",
    )

    def model_post_init(self, __context) -> None:
        if self.method == "thesis_based_no_price" and self.implied_price is not None:
            raise ValueError(
                "implied_price must be None for thesis_based_no_price target derivation."
            )
        if self.method != "thesis_based_no_price" and self.implied_price is None:
            raise ValueError(
                "implied_price is required when target_derivation.method cites a price method."
            )


def _default_target_derivation() -> TargetDerivation:
    return TargetDerivation(
        method="thesis_based_no_price",
        inputs_used=["Legacy expression did not cite a target derivation method."],
        implied_price=None,
    )


class TradeExpression(BaseSchema):
    """
    How a trade idea is structured for execution.

    `alternatives_considered` is required to be non-empty for any rating
    above MODERATE — the construction agent must show it considered other
    expressions and rejected them. For MODERATE-rated trades the field can
    be empty since there's less expected analytical depth.
    """

    primary_instrument: Instrument
    rationale_for_instrument: str = Field(min_length=20, max_length=2000)
    alternatives_considered: List[AlternativeRejected] = Field(
        default_factory=list, max_length=10
    )

    entry_logic: str = Field(
        min_length=10,
        max_length=2000,
        description="How to enter — not just 'buy', but conditions and scaling.",
    )
    entry_mode: Literal["confirmation_required", "immediate"] = "immediate"
    entry_trigger_price: Optional[float] = Field(default=None, ge=0.0)
    target_derivation: TargetDerivation = Field(
        default_factory=_default_target_derivation
    )
    exit_target: str = Field(min_length=10, max_length=1000)
    exit_stop: str = Field(min_length=10, max_length=1000)
    exit_time_stop: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Time-based exit if neither target nor stop hit. None = no time stop.",
    )

    hedges: List[Hedge] = Field(default_factory=list, max_length=5)


class ProposedSizing(BaseSchema):
    """
    Construction-agent's pre-portfolio sizing recommendation.

    `base_size_pct` is BEFORE portfolio constraints are applied. The portfolio
    agent's ConstraintResponse may force this lower (or block the trade).

    `max_loss_estimate_pct` is the agent's honest estimate of how much the
    portfolio could lose if the bear case fully plays out. Forced to be set
    so sizing can't be casual.
    """

    base_size_pct: UnitInterval = Field(
        description="Position size as fraction of portfolio NAV, pre-constraints."
    )
    sizing_logic: str = Field(min_length=20, max_length=2000)
    kelly_implied: Optional[UnitInterval] = Field(
        default=None,
        description="Kelly-criterion-implied size if computable. None if not estimable.",
    )
    max_loss_estimate_pct: UnitInterval = Field(
        description="Estimated portfolio drawdown if bear case fully plays out."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Provenance — references to upstream analysis IDs for lineage
# ─────────────────────────────────────────────────────────────────────────────


class TradeProvenance(BaseSchema):
    """
    References to upstream analyses for full lineage.

    Storage layer stores these as foreign keys; at runtime, the inlined
    schemas on TradeIdea provide the full data. This separation lets the
    rejection store reference upstream work without duplicating it.
    """

    research_priority_id: Optional[str] = Field(default=None, max_length=100)
    thematic_map_id: Optional[str] = Field(default=None, max_length=100)
    fundamental_analysis_id: Optional[str] = Field(default=None, max_length=100)
    narrative_analysis_id: Optional[str] = Field(default=None, max_length=100)
    regime_state_id: Optional[str] = Field(default=None, max_length=100)


# ─────────────────────────────────────────────────────────────────────────────
# TradeIdea — the top-level construction output (or rejection)
# ─────────────────────────────────────────────────────────────────────────────


class TradeIdea(BaseSchema):
    """
    The construction agent's output for a candidate trade.

    A TradeIdea represents EITHER:
    (a) An accepted trade, in which case `expression` and `proposed_sizing`
        are set, `rejection_reason` is None, and conviction.rating is
        STRONG or EXCEPTIONAL (or MODERATE for some trade types).
    (b) A rejected idea, in which case `expression` and `proposed_sizing`
        are None, `rejection_reason` and `rejection_stage` are set, and
        conviction.rating is WEAK or PASS.

    The model validator enforces this coupling. The schema literally cannot
    represent "a trade that didn't pass conviction" — that's the structural
    enforcement of the pragmatic-bearish discipline.

    Rejections are first-class. The rejection store is the same table as
    accepted trades; queries can filter by rating or by rejection_stage.
    """

    # Identity
    underlying: str = Field(
        min_length=1,
        max_length=50,
        description=(
            "Primary ticker or theme this idea is about. For pair trades, "
            "use the long leg as the underlying."
        ),
    )

    # Full upstream context (inlined for runtime; ids in provenance for storage)
    fundamental: Optional[FundamentalAnalysis] = None
    narrative: Optional[NarrativeAnalysis] = None
    research_priority: Optional[ResearchPriority] = None
    regime: Optional[RegimeState] = None
    provenance: TradeProvenance = Field(default_factory=TradeProvenance)

    # The conviction decision (output of the rules engine)
    combined_conviction: Conviction

    # The expression — REQUIRED None if conviction is WEAK or PASS,
    # REQUIRED non-None otherwise. Enforced by the model validator.
    expression: Optional[TradeExpression] = None
    proposed_sizing: Optional[ProposedSizing] = None

    # Time horizon (set when expression is present)
    expected_holding_period: Optional[str] = Field(default=None, max_length=200)
    thesis_review_cadence: Optional[ReviewCadence] = None
    next_review_trigger: Optional[str] = Field(default=None, max_length=500)

    # Falsifiers — REQUIRED if expression is present
    trade_falsifiers: List[Falsifier] = Field(default_factory=list, max_length=15)
    invalidation_price: Optional[float] = None
    invalidation_thesis: Optional[str] = Field(
        default=None,
        max_length=2000,
        description=(
            "Condition that kills the THESIS (not just a price stop). "
            "Required when expression is set."
        ),
    )

    # Rejection metadata — REQUIRED if conviction is WEAK or PASS
    rejection_reason: Optional[str] = Field(default=None, max_length=2000)
    rejection_stage: Optional[
        Literal["thematic", "single_name", "narrative", "construction", "portfolio"]
    ] = None
    rejection_rule_fired: Optional[str] = Field(
        default=None,
        max_length=200,
        description=(
            "Name of the conviction rule that produced the WEAK/PASS rating. "
            "Mirrors combined_conviction.rule_applied for ease of querying "
            "the rejection store."
        ),
    )

    def model_post_init(self, __context) -> None:
        """
        Enforce the conviction/expression coupling.

        Accepted trade: conviction rating is MODERATE/STRONG/EXCEPTIONAL,
        expression and required trade-only fields are set, rejection fields
        are None.

        Rejected idea: conviction rating is WEAK or PASS, expression is None,
        rejection_reason and rejection_stage are set.

        Conviction rating MODERATE is a soft middle: trades CAN exist at
        moderate conviction (smaller size, tighter review), but the rules
        engine often kills them. The schema allows MODERATE with an
        expression; the rules engine decides whether to actually emit one.
        """
        rating = self.combined_conviction.rating
        is_rejection = rating in (ConvictionRating.WEAK, ConvictionRating.PASS)

        if is_rejection:
            # Rejection: expression must be None, rejection fields required
            if self.expression is not None:
                raise ValueError(
                    f"Conviction rating {rating.value} requires expression=None "
                    "(this is the structural enforcement of 'no trade idea "
                    "without conviction')."
                )
            if self.proposed_sizing is not None:
                raise ValueError(
                    f"Conviction rating {rating.value} requires proposed_sizing=None."
                )
            if not self.rejection_reason:
                raise ValueError(
                    f"Conviction rating {rating.value} requires rejection_reason to be set."
                )
            if not self.rejection_stage:
                raise ValueError(
                    f"Conviction rating {rating.value} requires rejection_stage to be set."
                )
            if self.trade_falsifiers:
                raise ValueError(
                    "Rejections should not have trade_falsifiers — they belong on accepted trades."
                )
        else:
            # Accepted trade: expression and trade-only fields required
            if self.expression is None:
                raise ValueError(
                    f"Conviction rating {rating.value} requires expression to be set."
                )
            if self.proposed_sizing is None:
                raise ValueError(
                    f"Conviction rating {rating.value} requires proposed_sizing to be set."
                )
            if not self.invalidation_thesis:
                raise ValueError(
                    f"Conviction rating {rating.value} requires invalidation_thesis to be set."
                )
            if len(self.trade_falsifiers) < 3:
                raise ValueError(
                    f"Conviction rating {rating.value} requires at least 3 trade_falsifiers "
                    f"(got {len(self.trade_falsifiers)}). Multiple invalidation paths "
                    "must be enumerated, not just 'if it goes against me'."
                )
            if self.thesis_review_cadence is None:
                raise ValueError(
                    f"Conviction rating {rating.value} requires thesis_review_cadence to be set."
                )
            if self.rejection_reason or self.rejection_stage:
                raise ValueError(
                    "Accepted trades must not have rejection_reason or rejection_stage set."
                )
