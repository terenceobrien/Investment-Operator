"""Portfolio construction plan schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.schemas.common import BaseSchema


class SizingAdjustment(BaseModel):
    """One adjustment applied to a trade's size during portfolio construction."""

    model_config = ConfigDict(frozen=True)

    step: Literal[
        "robustness_demotion",
        "existing_overlap_cap",
        "priority_concentration_cap",
        "options_allocation_cap",
        "total_deployment_cap",
        "min_size_floor",
    ]
    size_before: float
    size_after: float
    rationale: str = Field(max_length=500)


class PortfolioTradeDecision(BaseModel):
    """The portfolio agent's decision for one TradeIdea."""

    model_config = ConfigDict(frozen=True)

    trade_id: str
    underlying: str
    priority_theme: str | None = None
    proposed_size_pct: float
    robustness_score: float | None
    robustness_quartile: int | None
    existing_position_pct: float = 0.0
    final_size_pct: float
    sizing_adjustments: list[SizingAdjustment] = Field(default_factory=list)
    decision: Literal["execute", "reduced", "rejected_portfolio"]
    rationale_summary: str = Field(max_length=2000)


class PortfolioPlan(BaseSchema):
    """Cycle-level portfolio construction output."""

    cycle_id: str
    nav_unlevered_usd: float
    cash_usd: float
    existing_positions_snapshot_id: str | None = None
    scenario_set_basis: str | None = None
    trade_decisions: list[PortfolioTradeDecision]
    total_new_deployment_pct: float
    total_new_deployment_usd: float
    per_priority_deployment_pct: dict[str, float]
    binding_constraints: list[str] = Field(
        default_factory=list,
        description=(
            "Names of constraints that bound the cycle, e.g. "
            "'priority_concentration:Hormuz' or 'total_deployment_cap'."
        ),
    )
    n_executed: int
    n_reduced: int
    n_rejected_portfolio: int
