"""Trade outcome and price tracking schemas for post-cycle performance measurement."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import Field, model_validator

from src.agent_system.schemas.common import BaseSchema


TradeStatus = Literal[
    "proposed",
    "watching",
    "skipped",
    "shadow_rejected",
    "open",
    "closed_target",
    "closed_stop",
    "closed_time",
    "closed_falsifier",
    "closed_thesis",
    "closed_discretionary",
]

UserDecision = Literal["TAKE", "SKIP", "WATCH"]
ThesisPlayout = Literal["YES", "PARTIAL", "NO"]
WinSource = Literal["thesis", "direction", "timing", "luck", "sizing"]
SystemContribution = Literal["STRONG", "NEUTRAL", "WEAK"]
PriceSource = Literal["yfinance", "manual", "broker_api", "computed", "shadow_track"]


class PricePoint(BaseSchema):
    """One daily price snapshot for a tracked trade. Append-only log."""

    trade_id: str = Field(min_length=1)
    asof_date: str = Field(min_length=10, max_length=10, description="YYYY-MM-DD")
    underlying_price: float
    instrument_price: Optional[float] = Field(
        default=None,
        description=(
            "Option/spread mid-price if instrument is not the underlying. "
            "None if instrument is stock or option pricing unavailable."
        ),
    )
    unrealized_pnl_pct: Optional[float] = Field(
        default=None,
        description=(
            "P&L as percent of capital deployed; computed when entry data exists."
        ),
    )
    days_held: int = Field(ge=0)
    source: PriceSource = "manual"
    notes: Optional[str] = Field(default=None, max_length=500)


class TradeOutcome(BaseSchema):
    """Durable outcome record for one trade produced by an agent cycle.

    Created at portfolio plan finalization for every accepted trade
    (decision != rejected_portfolio and final_size_pct > 0). Mutated as the
    trade moves through its lifecycle.
    """

    # Identity and lineage
    trade_id: str = Field(min_length=1, description="Matches TradeIdea.id")
    cycle_id: str = Field(min_length=1)
    cycle_date: str = Field(min_length=10, max_length=10, description="YYYY-MM-DD")
    underlying: str = Field(min_length=1, max_length=20)
    priority_theme: Optional[str] = Field(default=None, max_length=500)
    originating_cycle_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Cycle id that originally produced this tracked trade.",
    )
    originating_priority_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description=(
            "Stable priority/hypothesis id when available. Usually the macro "
            "source_theme_id; falls back to the saved ResearchPriority record id."
        ),
    )
    originating_priority_label: Optional[str] = Field(default=None, max_length=500)
    originating_priority_scenarios: list[str] = Field(default_factory=list, max_length=10)

    # Structure snapshot at cycle time
    direction: Literal["long", "short", "spread", "pair", "neutral"]
    instrument_type: str = Field(min_length=1)
    instrument_description: str = Field(
        min_length=1,
        max_length=500,
        description=(
            "Human-readable instrument string e.g. 'Mar 2027 $700 calls'."
        ),
    )

    # Sizing snapshot from PortfolioPlan
    proposed_size_pct: float
    final_size_pct: float
    decision: Literal["execute", "reduced", "rejected_portfolio", "shadow_rejected"]

    # Conviction snapshot
    variant_strength: Optional[Literal["strong", "moderate", "weak"]] = None
    conviction: Optional[str] = None
    robustness_score: Optional[float] = None
    robustness_quartile: Optional[int] = Field(default=None, ge=1, le=4)

    # Risk levels snapshot from TradeIdea
    entry_target_price: Optional[float] = None
    target_price: Optional[float] = None
    stop_price: Optional[float] = None
    invalidation_thesis: Optional[str] = Field(default=None, max_length=2000)
    expected_holding_period: Optional[str] = Field(default=None, max_length=200)

    # Lifecycle state
    status: TradeStatus = "proposed"

    # User decision, manual
    user_decision: Optional[UserDecision] = None
    user_decision_reason: Optional[str] = Field(default=None, max_length=2000)
    user_decision_at: Optional[datetime] = None

    # Entry
    entry_triggered: Optional[bool] = None
    entry_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    entry_underlying_price: Optional[float] = None
    entry_instrument_price: Optional[float] = Field(
        default=None,
        description="Premium paid for options; underlying price for stocks.",
    )
    entry_size_usd: Optional[float] = None

    # Exit
    exit_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    exit_underlying_price: Optional[float] = None
    exit_instrument_price: Optional[float] = None
    exit_reason: Optional[str] = Field(default=None, max_length=500)

    # Performance, computed and cached from price points
    current_underlying_price: Optional[float] = None
    current_instrument_price: Optional[float] = None
    current_unrealized_pnl_pct: Optional[float] = None
    realized_pnl_pct: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    days_held: Optional[int] = Field(default=None, ge=0)
    days_since_proposed: int = Field(default=0, ge=0)
    max_drawdown_pct: Optional[float] = None
    max_runup_pct: Optional[float] = None

    # Retrospective analysis, manual after close
    thesis_played_out: Optional[ThesisPlayout] = None
    win_source: Optional[WinSource] = None
    system_contribution: Optional[SystemContribution] = None
    audit_notes: Optional[str] = Field(default=None, max_length=5000)

    # Tracking metadata
    last_price_update: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> "TradeOutcome":
        """Enforce that lifecycle fields are populated consistently with status."""
        if self.status == "open":
            if self.entry_date is None or self.entry_underlying_price is None:
                raise ValueError(
                    "Status 'open' requires entry_date and entry_underlying_price."
                )
        if self.status.startswith("closed_"):
            if self.exit_date is None or self.exit_underlying_price is None:
                raise ValueError(
                    f"Status '{self.status}' requires exit_date and exit_underlying_price."
                )
            if self.entry_date is None:
                raise ValueError(
                    f"Status '{self.status}' requires entry_date to have been recorded."
                )
        if self.status == "skipped":
            if self.user_decision != "SKIP":
                raise ValueError("Status 'skipped' requires user_decision='SKIP'.")
        return self
