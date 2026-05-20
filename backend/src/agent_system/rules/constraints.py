"""
Deterministic portfolio constraint checks for v0 construction.
"""
from __future__ import annotations

from src.agent_system.schemas.portfolio import (
    AlternativePath,
    ConstraintResponse,
    PortfolioState,
)
from src.agent_system.schemas.trade import TradeIdea


def _position_weight(portfolio_state: PortfolioState, ticker: str) -> float:
    ticker = ticker.upper()
    return sum(p.weight for p in portfolio_state.positions if p.ticker.upper() == ticker)


def _overlapping_overweight_bucket(
    proposed_trade: TradeIdea,
    portfolio_state: PortfolioState,
) -> str | None:
    tags = set()
    if proposed_trade.fundamental:
        tags.add(proposed_trade.fundamental.ticker.upper())
    if proposed_trade.research_priority:
        tags.update(t.lower() for t in proposed_trade.research_priority.theme.split())
    if proposed_trade.expression:
        tags.add(proposed_trade.expression.primary_instrument.ticker.upper())

    for bucket in portfolio_state.exposure_map:
        if bucket.status != "overweight":
            continue
        bucket_terms = set(bucket.name.lower().replace("/", " ").split())
        if bucket_terms & tags:
            return bucket.name
    return None


def check_portfolio_constraints(
    *,
    proposed_trade: TradeIdea,
    portfolio_state: PortfolioState | None,
) -> ConstraintResponse:
    """
    Apply a simple v0 portfolio constraint pass.

    The response distinguishes true hard blocks from adjustable soft blocks so
    construction can either reject or propose a smaller/cleaner expression.
    """

    if portfolio_state is None:
        if proposed_trade.expression is None:
            return ConstraintResponse(
                allowed=False,
                hard_block=True,
                binding_constraints=["Rejected ideas cannot be portfolio-approved"],
                reasoning="No live portfolio state was supplied, and the proposed idea has no trade expression.",
            )
        return ConstraintResponse(
            allowed=True,
            reasoning="No live portfolio constraints were applied; trade allowed for stub-cycle validation only.",
        )

    if proposed_trade.expression is None:
        return ConstraintResponse(
            allowed=False,
            hard_block=True,
            binding_constraints=["Rejected ideas cannot be portfolio-approved"],
            reasoning="A rejected or unexpressed TradeIdea cannot pass the portfolio approval layer.",
        )

    if proposed_trade.proposed_sizing is None:
        return ConstraintResponse(
            allowed=False,
            hard_block=True,
            binding_constraints=["Missing proposed sizing"],
            reasoning="Accepted trades must include proposed sizing before portfolio constraints can be evaluated.",
        )

    size = proposed_trade.proposed_sizing.base_size_pct
    if size > 0.10:
        return ConstraintResponse(
            allowed=False,
            hard_block=False,
            binding_constraints=["Proposed size exceeds 10% NAV soft cap"],
            alternative_paths=[
                AlternativePath(
                    description="Reduce proposed sizing to 10% NAV or lower before approval.",
                    requires_action="resubmit reduced sizing",
                )
            ],
            reasoning="Single-name or theme sizing above 10% NAV requires explicit reduction in the v0 policy.",
        )

    ticker = proposed_trade.expression.primary_instrument.ticker
    existing_weight = _position_weight(portfolio_state, ticker)
    if existing_weight > 0.10:
        return ConstraintResponse(
            allowed=False,
            hard_block=False,
            binding_constraints=[f"Existing {ticker} exposure is already above 10% NAV"],
            alternative_paths=[
                AlternativePath(
                    description="Add only after trimming the existing position below the 10% NAV concentration threshold.",
                    requires_action=f"reduce existing {ticker} exposure",
                )
            ],
            reasoning="The portfolio already has concentrated exposure to the proposed underlying.",
        )

    overweight_bucket = _overlapping_overweight_bucket(proposed_trade, portfolio_state)
    if overweight_bucket:
        return ConstraintResponse(
            allowed=False,
            hard_block=False,
            binding_constraints=[f"{overweight_bucket} is already overweight"],
            alternative_paths=[
                AlternativePath(
                    description="Use a smaller starter size or fund it by trimming another position in the same exposure bucket.",
                    requires_action=f"reduce {overweight_bucket} exposure first",
                )
            ],
            reasoning="The proposed trade appears to overlap an exposure bucket that is already overweight.",
        )

    return ConstraintResponse(
        allowed=True,
        reasoning="Proposed trade fits the v0 sizing and concentration constraints.",
    )
