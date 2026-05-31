"""
Forward-looking macro context schemas.

RegimeState describes where the macro environment is now. These schemas add
the adjacent question: where does consensus think it is going? The objects are
kept separate from the current-state regime layers so forward data can degrade
gracefully without invalidating the algorithmic regime snapshot.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import Field, field_validator, model_validator

from src.agent_system.schemas.common import BaseSchema, UnitInterval


def _validate_iso_date(value: str, field_name: str) -> str:
    """Validate strict YYYY-MM-DD date strings without accepting shortcuts."""
    if not (len(value) == 10 and value[4] == "-" and value[7] == "-"):
        raise ValueError(f"{field_name} must be 'YYYY-MM-DD' format")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid calendar date") from exc
    return value


class FedPathReading(BaseSchema):
    """
    Market-implied policy probabilities for one FOMC meeting.

    The five probability buckets are intentionally simple and mutually
    exhaustive for v1: large cut, small cut, hold, small hike, large hike.
    A tolerance is allowed because public FedWatch snapshots may be rounded.
    """

    meeting_date: str = Field(
        description="FOMC meeting date in YYYY-MM-DD format."
    )
    prob_cut_50: UnitInterval = Field(description="50bp cut probability.")
    prob_cut_25: UnitInterval = Field(description="25bp cut probability.")
    prob_hold: UnitInterval = Field(description="Hold/no-change probability.")
    prob_hike_25: UnitInterval = Field(description="25bp hike probability.")
    prob_hike_50: UnitInterval = Field(description="50bp hike probability.")
    source: str = Field(
        min_length=5,
        max_length=200,
        description="Human-readable source note, e.g. CME FedWatch timestamp.",
    )

    @field_validator("meeting_date")
    @classmethod
    def _validate_meeting_date(cls, value: str) -> str:
        return _validate_iso_date(value, "meeting_date")

    @model_validator(mode="after")
    def _probabilities_sum_to_one(self) -> "FedPathReading":
        total = (
            self.prob_cut_50
            + self.prob_cut_25
            + self.prob_hold
            + self.prob_hike_25
            + self.prob_hike_50
        )
        if abs(total - 1.0) > 0.05:
            raise ValueError(
                f"Fed path probabilities must sum to ~1.0 (got {total:.4f})"
            )
        return self


class InflationExpectations(BaseSchema):
    """
    Market-implied inflation expectations from TIPS breakevens.

    Fields are optional because FRED availability varies by series and date.
    A fully empty object is valid when the fetcher ran but no values were
    available; callers should inspect notes/data_quality_notes.
    """

    breakeven_2y: Optional[float] = Field(
        default=None, description="FRED T2YIE latest value, if available."
    )
    breakeven_5y: Optional[float] = Field(
        default=None, description="FRED T5YIE latest value, if available."
    )
    breakeven_10y: Optional[float] = Field(
        default=None, description="FRED T10YIE latest value, if available."
    )
    forward_5y5y: Optional[float] = Field(
        default=None, description="FRED T5YIFR latest value, if available."
    )
    as_of: datetime = Field(description="Timestamp for this inflation snapshot.")
    trend_30d: Optional[Literal["rising", "stable", "falling"]] = Field(
        default=None,
        description="Simple 30-day trend, left unset in v1 without history.",
    )
    notes: str = Field(
        default="",
        max_length=1000,
        description="Color or caveats about the breakeven snapshot.",
    )


class MarketEvent(BaseSchema):
    """
    Upcoming macro-significance event.

    Named MarketEvent rather than Catalyst to avoid collision with the
    trade-level Catalyst schema in common.py. These are calendar context for
    macro priority generation, not trade-specific asymmetric catalysts.
    """

    name: str = Field(min_length=3, max_length=300)
    date: str = Field(description="Event date in YYYY-MM-DD format.")
    category: Literal[
        "fed",
        "data_release",
        "geopolitical",
        "earnings_season",
        "policy",
        "election",
        "other",
    ]
    significance: Literal["high", "medium", "low"]
    notes: str = Field(default="", max_length=1000)

    @field_validator("date")
    @classmethod
    def _validate_event_date(cls, value: str) -> str:
        return _validate_iso_date(value, "date")


class PredictionMarketReading(BaseSchema):
    """
    Single prediction-market contract reading.

    This is optional forward context. It is intentionally generic so Kalshi,
    Polymarket, or manual readings can share the same contract shape later.
    """

    contract_id: str = Field(min_length=3, max_length=200)
    question: str = Field(min_length=10, max_length=500)
    current_probability: UnitInterval
    volume_usd: Optional[float] = Field(default=None, ge=0)
    source: Literal["polymarket", "kalshi", "other"]
    as_of: datetime
    notes: str = Field(default="", max_length=1000)


class ForwardContext(BaseSchema):
    """
    Top-level forward-looking macro context container.

    Empty lists are valid: the regime algorithm can still operate on current
    state alone. data_quality_notes records source failures and caveats so
    downstream agents can decide whether missing forward data matters.
    """

    fed_path: List[FedPathReading] = Field(default_factory=list, max_length=8)
    inflation_expectations: Optional[InflationExpectations] = None
    upcoming_catalysts: List[MarketEvent] = Field(
        default_factory=list, max_length=30
    )
    prediction_market_signals: List[PredictionMarketReading] = Field(
        default_factory=list, max_length=20
    )
    as_of: datetime
    data_quality_notes: str = Field(default="", max_length=2000)
