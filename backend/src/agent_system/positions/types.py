"""Typed brokerage positions parsed from Fidelity CSV exports."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.schemas.common import BaseSchema


class Position(BaseModel):
    """A single held position from the brokerage."""

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(min_length=1, max_length=20)
    description: str = Field(default="", max_length=500)
    quantity_shares: float | None = Field(
        default=None,
        description="Share count. None for cash/money-market positions.",
    )
    current_value_usd: float = Field(
        description=(
            "Current market value in USD, computed from Last Price x Quantity "
            "by Fidelity."
        ),
    )
    last_price_usd: float | None = None
    cost_basis_total_usd: float | None = None
    average_cost_basis_usd: float | None = None
    total_gain_loss_usd: float | None = None
    total_gain_loss_pct: float | None = None
    percent_of_account: float | None = Field(
        default=None,
        description="Fraction of account NAV this position represents (0.0-1.0).",
    )
    position_type: Literal["cash", "margin"] = Field(
        description="From Fidelity Type column: 'Cash' or 'Margin'.",
    )
    is_cash: bool = Field(
        default=False,
        description="True for money-market sweep positions (SPAXX, FCASH, etc.).",
    )
    is_option: bool = Field(
        default=False,
        description="True if the position is an open option contract.",
    )


class PositionsSnapshot(BaseSchema):
    """A complete portfolio snapshot from one CSV file."""

    source_file: str
    downloaded_at: datetime | None = Field(
        default=None,
        description="Date/time from Fidelity's footer, if parseable.",
    )
    file_mtime: datetime = Field(
        description="Filesystem modification time of the CSV.",
    )
    account_number: str | None = None
    account_name: str | None = None
    positions: list[Position]
    total_nav_usd: float = Field(description="Sum of all current_value_usd.")
    cash_usd: float = Field(description="Sum of current_value_usd for cash positions.")
    cash_pct: float = Field(description="cash_usd / total_nav_usd.")
    long_equity_usd: float = Field(
        description="Total non-cash, non-option position value."
    )
    margin_positions_usd: float = Field(
        description="Total value of positions held on margin."
    )

    def model_post_init(self, __context) -> None:
        expected_total = sum(p.current_value_usd for p in self.positions)
        if abs(self.total_nav_usd - expected_total) > 0.01:
            raise ValueError(
                f"total_nav_usd ({self.total_nav_usd}) does not match sum of "
                f"position values ({expected_total})."
            )
