"""
Portfolio schemas — the portfolio agent's outputs and the live-position
management layer.

This is the consumer-side schema that holds the system's live state. The
portfolio agent does three things:

1. Maintains the `thesis_inventory` — the living book of theses with
   falsifier status, updated daily by the falsifier-checking job.
2. Answers ConstraintResponse queries from the construction agent (Loop A).
3. Emits PortfolioDecision items for the morning review queue.

Key design choices:

- `ActiveThesis` links back to the originating `TradeIdea` via id, so the
  full reasoning chain that justified opening a position is always
  recoverable. When a thesis is violated, the violated falsifier and the
  original trade idea are both surfaced in the decision queue.

- `PortfolioState` does not duplicate the regime overlay's exposure
  calculations — instead it wraps `RegimeOverlay`-style structured data
  produced by your existing code. The portfolio agent reads from your
  existing helix `regime_overlay.compute_overlay()` and represents the
  output here.

- `ConstraintResponse` distinguishes `hard_block=True` (sector caps, risk
  limits — non-negotiable) from `hard_block=False` (adjustable, e.g. "you
  could reduce size to fit"). The construction agent treats these
  differently.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import Field, model_validator

from src.agent_system.schemas.common import (
    BaseSchema,
    Falsifier,
    UnitInterval,
)


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ThesisStatus(str, Enum):
    """
    Current state of an active thesis.

    INTACT: falsifiers untriggered, thesis holds.
    WEAKENING: at least one falsifier APPROACHING, others not yet triggered.
    VIOLATED: at least one falsifier TRIGGERED — forces a decision.
    PLAYED_OUT: thesis succeeded, exit criteria met. Closed for non-loss reasons.
    """

    INTACT = "intact"
    WEAKENING = "weakening"
    VIOLATED = "violated"
    PLAYED_OUT = "played_out"


class ThesisPerformance(str, Enum):
    """Performance vs original thesis expectations."""

    AHEAD = "ahead"            # thesis playing out faster/better than expected
    ON_TRACK = "on_track"
    BEHIND = "behind"          # underperforming expectations but not yet violated
    UNKNOWN = "unknown"        # too early or insufficient signal


class PortfolioDecisionType(str, Enum):
    """Categorization of items in the daily decision queue."""

    NEW_TRADE = "new_trade"
    ADD = "add"
    TRIM = "trim"
    CLOSE = "close"
    SWAP = "swap"               # close one, open another in the same theme
    HEDGE = "hedge"
    HOLD = "hold"               # affirmative hold despite signal
    REVIEW = "review"           # flag for human review without specific action


# ─────────────────────────────────────────────────────────────────────────────
# Positions and theses
# ─────────────────────────────────────────────────────────────────────────────


class Position(BaseSchema):
    """
    A current portfolio holding.

    `weight` is the position's fraction of total portfolio NAV. `theme_tags`
    use the same vocabulary as regime_overlay.TICKER_METADATA so positions
    can be matched against exposure buckets.

    `thesis_id` links to the ActiveThesis if there is one. Some positions
    (legacy holdings, mechanical exposures like cash) may not have a thesis
    — that's allowed but flagged in review.
    """

    ticker: str = Field(min_length=1, max_length=20)
    weight: UnitInterval = Field(description="Fraction of total NAV, 0.0–1.0.")
    cost_basis: Optional[float] = None
    current_price: Optional[float] = None
    theme_tags: List[str] = Field(default_factory=list, max_length=15)
    opened_at: Optional[datetime] = None

    thesis_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Link to ActiveThesis, or None for holdings without a tracked thesis.",
    )


class FalsifierCheckResult(BaseSchema):
    """
    Result of a single falsifier check during the daily sweep.

    The falsifier-checking job (Phase 4) produces these for each falsifier on
    each active thesis on each check cycle. Storage-layer table is a
    hypertable in TimescaleDB (high write volume, time-bucketed queries).
    """

    falsifier: Falsifier
    checked_at: datetime
    status_after_check: Literal["not_triggered", "approaching", "triggered", "unknown"]
    check_notes: str = Field(default="", max_length=2000)
    evidence_observed: str = Field(
        default="",
        max_length=2000,
        description="What the check observed that produced the status.",
    )


class ActiveThesis(BaseSchema):
    """
    A live thesis being tracked in the portfolio.

    The crucial fields:
    - `trade_id` links to the TradeIdea that opened the position. Full
      reasoning chain is recoverable from there.
    - `current_status` is updated daily by the falsifier-checking job.
    - `falsifier_checks` is the running log of all falsifier evaluations,
      not just the latest. Lets you see how a thesis weakened over time.

    A thesis with `current_status == VIOLATED` forces a PortfolioDecision
    in the daily queue. The system does NOT auto-close — the decision is
    surfaced for human review (or, post-calibration, for an auto-close
    path with explicit guardrails).
    """

    trade_id: str = Field(min_length=1, max_length=100)
    ticker: str = Field(min_length=1, max_length=20)
    opened_at: datetime
    original_thesis_statement: str = Field(min_length=20, max_length=1000)

    current_status: ThesisStatus = ThesisStatus.INTACT
    last_status_change_at: Optional[datetime] = None

    falsifier_checks: List[FalsifierCheckResult] = Field(
        default_factory=list,
        max_length=500,  # bounded to prevent unbounded growth; rotated by job
    )

    performance: ThesisPerformance = ThesisPerformance.UNKNOWN
    pnl_pct: Optional[float] = None
    days_since_last_review: int = Field(default=0, ge=0)

    notes: str = Field(default="", max_length=4000)


# ─────────────────────────────────────────────────────────────────────────────
# Exposure tracking — wrapping the existing Helix regime_overlay output
# ─────────────────────────────────────────────────────────────────────────────


class ExposureBucket(BaseSchema):
    """
    A single exposure bucket — Pydantic mirror of regime_overlay's
    exposure_map entries.
    """

    name: str = Field(min_length=1, max_length=100)
    current_weight: UnitInterval
    target_min: UnitInterval
    target_max: UnitInterval
    gap_to_min: float = Field(
        description="Positive = underweight; how much weight to add to reach min."
    )
    gap_to_max: float = Field(
        description="Positive = overweight; how much weight to trim to reach max."
    )
    status: Literal["underweight", "in_range", "overweight"]


class AlignmentSummary(BaseSchema):
    """Top-level alignment summary — mirrors regime_overlay's alignment block."""

    score: float = Field(ge=0, le=100)
    aligned_weight: UnitInterval
    misaligned_weight: UnitInterval
    unknown_weight: UnitInterval
    cash_like_weight: UnitInterval
    main_mismatch: str = Field(min_length=1, max_length=1000)


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio state — the top-level snapshot
# ─────────────────────────────────────────────────────────────────────────────


class PortfolioState(BaseSchema):
    """
    Top-level snapshot of the live portfolio.

    Composed of:
    - Current positions and their weights
    - The thesis inventory (active theses)
    - Exposure / alignment data (from regime_overlay output)
    - Cash, NAV, and other rollup metrics
    - The active regime state (referenced by id; full state stored separately)

    Updated post-close by the portfolio agent. Read by the construction agent
    for constraint queries.
    """

    asof_date: str = Field(
        description="ISO date string for the snapshot (e.g. '2026-05-19')."
    )
    total_nav: Optional[float] = None
    cash_weight: UnitInterval = Field(
        default=0.0,
        description="Fraction of NAV in cash-like instruments.",
    )

    positions: List[Position] = Field(default_factory=list, max_length=200)
    thesis_inventory: List[ActiveThesis] = Field(default_factory=list, max_length=200)

    # Exposure / alignment data — wraps regime_overlay output
    exposure_map: List[ExposureBucket] = Field(default_factory=list, max_length=30)
    alignment: Optional[AlignmentSummary] = None

    # Reference to the regime context — full state stored separately
    regime_state_id: Optional[str] = Field(default=None, max_length=100)

    # Concentration metrics (computed at construction time, stored for query)
    top1_concentration: UnitInterval = Field(default=0.0)
    top3_concentration: UnitInterval = Field(default=0.0)
    top5_concentration: UnitInterval = Field(default=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Constraint response — Loop A output
# ─────────────────────────────────────────────────────────────────────────────


class AlternativePath(BaseSchema):
    """
    An alternative way to express a constrained trade.

    Returned by the portfolio agent when a proposed trade hits a soft
    constraint. Construction agent decides whether to accept any alternative
    or escalate to a pass.
    """

    description: str = Field(min_length=20, max_length=1000)
    requires_action: Optional[str] = Field(
        default=None,
        max_length=500,
        description="What would need to happen first, e.g. 'close existing MU position'.",
    )


class ConstraintResponse(BaseSchema):
    """
    The portfolio agent's response to a constraint query from construction.

    This is the structured output of Loop A. Three possible outcomes:
    - `allowed=True, binding_constraints=[]`: trade can proceed as proposed.
    - `allowed=False, hard_block=False`: trade can proceed if adjusted —
      `alternative_paths` lists options.
    - `allowed=False, hard_block=True`: trade cannot proceed at all. This is
      reserved for cases like absolute sector caps or risk limits.
    """

    allowed: bool
    binding_constraints: List[str] = Field(default_factory=list, max_length=15)
    alternative_paths: List[AlternativePath] = Field(default_factory=list, max_length=10)
    hard_block: bool = Field(
        default=False,
        description="True = trade cannot proceed even with adjustment. False = adjustable.",
    )
    reasoning: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def _check_consistency(self) -> "ConstraintResponse":
        # If allowed=True there should be no binding constraints
        if self.allowed and self.binding_constraints:
            raise ValueError(
                "allowed=True is inconsistent with non-empty binding_constraints"
            )
        # If hard_block=True then allowed must be False
        if self.hard_block and self.allowed:
            raise ValueError("hard_block=True is inconsistent with allowed=True")
        # If allowed=False with hard_block=False, alternative_paths SHOULD be set
        # (we warn rather than enforce — sometimes there genuinely are no alts)
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio decisions — the daily queue
# ─────────────────────────────────────────────────────────────────────────────


class PortfolioDecision(BaseSchema):
    """
    A single item in the daily decision queue.

    Produced by the portfolio agent at the end of the post-close sweep.
    Each morning's review surfaces these for human resolution.

    `forced_action` is True when the system is recommending an action that
    cannot be ignored without explicit override — e.g. closing a position
    whose thesis has been violated. Forced actions still require human
    confirmation in Phase 5; in later phases an auto-execute path may be
    enabled for specific decision types with explicit guardrails.
    """

    decision_type: PortfolioDecisionType
    ticker: Optional[str] = Field(default=None, max_length=20)
    trade_idea_ref: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Link to the TradeIdea this decision relates to.",
    )
    active_thesis_ref: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Link to the ActiveThesis this decision relates to.",
    )

    rationale: str = Field(min_length=20, max_length=2000)
    forced_action: bool = Field(default=False)

    constraints_triggered: List[str] = Field(default_factory=list, max_length=10)
    feedback_to_construction: Optional[str] = Field(
        default=None,
        max_length=2000,
        description=(
            "Message sent upstream to the construction agent, e.g. 'thesis "
            "violated, slot open for replacement'. None if no feedback needed."
        ),
    )

    priority: Literal["urgent", "normal", "low"] = "normal"