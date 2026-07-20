"""Deterministic portfolio construction agent."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.agent_system.config.trader_profile import TraderProfile
from src.agent_system.positions.types import PositionsSnapshot
from src.agent_system.scenarios.types import (
    ScenarioSet,
    ScenarioWeightSource,
    TradeScenarioAnalysis,
)
from src.agent_system.schemas.portfolio_plan import (
    PortfolioPlan,
    PortfolioTradeDecision,
    SizingAdjustment,
)
from src.agent_system.schemas.thematic import InstrumentType
from src.agent_system.schemas.trade import TradeIdea

logger = logging.getLogger("agent_system.agents.portfolio")


@dataclass
class _WorkingDecision:
    trade: TradeIdea
    trade_id: str
    underlying: str
    priority_theme: str
    proposed_size_pct: float
    final_size_pct: float
    robustness_score: float | None = None
    robustness_quartile: int | None = None
    scenario_weighted_expected_return: float | None = None
    scenario_weight_source: ScenarioWeightSource | None = None
    scenario_weights_used: dict[str, float] = field(default_factory=dict)
    scenario_weight_warning: str | None = None
    existing_position_pct: float = 0.0
    sizing_adjustments: list[SizingAdjustment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _trade_id(trade: TradeIdea) -> str:
    return trade.id or trade.underlying


def _priority_theme(trade: TradeIdea) -> str:
    if trade.research_priority is not None:
        return trade.research_priority.theme
    return "unknown_priority"


def _scenario_analysis_by_trade_id(
    analyses: list[TradeScenarioAnalysis],
) -> dict[str, TradeScenarioAnalysis]:
    return {analysis.trade_id: analysis for analysis in analyses}


def _is_option_trade(trade: TradeIdea) -> bool:
    if trade.expression is None:
        return False
    instrument = trade.expression.primary_instrument
    if instrument.instrument_type == InstrumentType.OPTION_UNDERLYING:
        return True
    description = instrument.description.lower()
    return any(
        term in description
        for term in [" call", " calls", " put", " puts", "call spread", "put spread"]
    )


def _existing_position_pct(
    underlying: str,
    positions: PositionsSnapshot | None,
) -> float:
    if positions is None or positions.total_nav_usd <= 0:
        return 0.0
    for position in positions.positions:
        if position.symbol.rstrip("*").upper() != underlying.upper():
            continue
        if position.percent_of_account is not None:
            return max(0.0, position.percent_of_account)
        return max(0.0, position.current_value_usd / positions.total_nav_usd)
    return 0.0


def _add_adjustment(
    decision: _WorkingDecision,
    *,
    step: str,
    size_before: float,
    size_after: float,
    rationale: str,
) -> None:
    decision.sizing_adjustments.append(
        SizingAdjustment(
            step=step,  # type: ignore[arg-type]
            size_before=size_before,
            size_after=size_after,
            rationale=rationale,
        )
    )


def _bind(binding_constraints: list[str], name: str) -> None:
    if name not in binding_constraints:
        binding_constraints.append(name)


def _scale_decision(
    decision: _WorkingDecision,
    *,
    step: str,
    scale_factor: float,
    rationale: str,
) -> None:
    before = decision.final_size_pct
    after = before * scale_factor
    if after < -1e-12:
        raise ValueError(f"{step} produced negative size for {decision.underlying}: {after}")
    decision.final_size_pct = max(0.0, after)
    _add_adjustment(
        decision,
        step=step,
        size_before=before,
        size_after=decision.final_size_pct,
        rationale=rationale,
    )


def _assign_robustness_quartiles(decisions: list[_WorkingDecision]) -> None:
    scored = [decision for decision in decisions if decision.robustness_score is not None]
    if not scored:
        return
    scored.sort(key=lambda decision: decision.robustness_score)
    n = len(scored)
    for idx, decision in enumerate(scored):
        decision.robustness_quartile = min(4, int(idx * 4 / n) + 1)


def _rationale(decision: _WorkingDecision) -> str:
    if decision.final_size_pct == 0:
        last = decision.sizing_adjustments[-1].step if decision.sizing_adjustments else "unknown"
        detail = (
            f"Portfolio rejected {decision.underlying}: final size is zero after "
            f"{last}."
        )
    elif decision.final_size_pct < decision.proposed_size_pct * 0.95:
        steps = ", ".join(adj.step for adj in decision.sizing_adjustments) or "portfolio caps"
        detail = (
            f"Reduced from {decision.proposed_size_pct:.1%} to "
            f"{decision.final_size_pct:.1%} of NAV due to {steps}."
        )
    else:
        detail = (
            f"Execute at proposed size of {decision.final_size_pct:.1%} of NAV; "
            "no portfolio constraint materially reduced the trade."
        )
    if decision.notes:
        detail += " " + " ".join(decision.notes)
    return detail


def _to_public_decision(decision: _WorkingDecision) -> PortfolioTradeDecision:
    if decision.final_size_pct == 0:
        classification = "rejected_portfolio"
    elif decision.final_size_pct < decision.proposed_size_pct * 0.95:
        classification = "reduced"
    else:
        classification = "execute"
    return PortfolioTradeDecision(
        trade_id=decision.trade_id,
        underlying=decision.underlying,
        priority_theme=decision.priority_theme,
        proposed_size_pct=decision.proposed_size_pct,
        robustness_score=decision.robustness_score,
        robustness_quartile=decision.robustness_quartile,
        scenario_weighted_expected_return=decision.scenario_weighted_expected_return,
        scenario_weight_source=decision.scenario_weight_source,
        scenario_weights_used=decision.scenario_weights_used,
        scenario_weight_warning=decision.scenario_weight_warning,
        existing_position_pct=decision.existing_position_pct,
        final_size_pct=decision.final_size_pct,
        sizing_adjustments=decision.sizing_adjustments,
        decision=classification,
        rationale_summary=_rationale(decision),
    )


def construct_portfolio(
    accepted_trades: list[TradeIdea],
    scenario_analyses: list[TradeScenarioAnalysis],
    positions: PositionsSnapshot | None,
    trader_profile: TraderProfile,
    scenario_set: ScenarioSet | None,
    cycle_id: str,
) -> PortfolioPlan:
    """
    Build a deterministic portfolio plan from accepted trades.

    Missing scenarios or positions are treated as explicit no-data cases; the
    constraint pipeline still applies the profile-level caps it can evaluate.
    """
    analyses = _scenario_analysis_by_trade_id(scenario_analyses)
    decisions: list[_WorkingDecision] = []
    binding_constraints: list[str] = []

    for trade in accepted_trades:
        try:
            if trade.expression is None or trade.proposed_sizing is None:
                logger.info("skipping non-expressed trade in portfolio plan: %s", trade.underlying)
                continue
            tid = _trade_id(trade)
            analysis = analyses.get(tid) or analyses.get(trade.underlying)
            decision = _WorkingDecision(
                trade=trade,
                trade_id=tid,
                underlying=trade.underlying,
                priority_theme=_priority_theme(trade),
                proposed_size_pct=trade.proposed_sizing.base_size_pct,
                final_size_pct=trade.proposed_sizing.base_size_pct,
                robustness_score=analysis.robustness_score if analysis else None,
                scenario_weighted_expected_return=analysis.expected_return if analysis else None,
                scenario_weight_source=analysis.scenario_weight_source if analysis else None,
                scenario_weights_used=analysis.scenario_weights_used if analysis else {},
                scenario_weight_warning=analysis.scenario_weight_warning if analysis else None,
            )
            if analysis is None:
                decision.notes.append(
                    "Scenario scoring was unavailable; no robustness demotion applied."
                )
            decisions.append(decision)
        except Exception as exc:
            logger.warning("portfolio initial sizing skipped trade %s: %s", trade.underlying, exc)

    _assign_robustness_quartiles(decisions)

    # Step 2: robustness demotion.
    scored = [decision for decision in decisions if decision.robustness_score is not None]
    if scored:
        scored.sort(key=lambda decision: decision.robustness_score)
        bottom_count = max(
            1,
            math.ceil(
                len(scored)
                * trader_profile.robustness.demotion_quartile_threshold
            ),
        )
        for decision in scored[:bottom_count]:
            _scale_decision(
                decision,
                step="robustness_demotion",
                scale_factor=trader_profile.robustness.demotion_factor,
                rationale=(
                    "Bottom-quartile scenario robustness; size demoted by "
                    f"{trader_profile.robustness.demotion_factor:.0%}."
                ),
            )
            _bind(binding_constraints, "robustness_demotion")

    # Step 3: existing-position overlap cap.
    if positions is None:
        for decision in decisions:
            decision.notes.append(
                "No positions snapshot was available; existing-position overlap was not capped."
            )
    else:
        for decision in decisions:
            decision.existing_position_pct = _existing_position_pct(
                decision.underlying,
                positions,
            )
            headroom = max(
                0.0,
                trader_profile.constraints.max_position_pct
                - decision.existing_position_pct,
            )
            if decision.final_size_pct > headroom:
                before = decision.final_size_pct
                decision.final_size_pct = headroom
                _add_adjustment(
                    decision,
                    step="existing_overlap_cap",
                    size_before=before,
                    size_after=headroom,
                    rationale=(
                        f"Existing {decision.underlying} position is "
                        f"{decision.existing_position_pct:.1%}; headroom to "
                        f"{trader_profile.constraints.max_position_pct:.1%} cap is "
                        f"{headroom:.1%}."
                    ),
                )
                _bind(binding_constraints, f"existing_overlap_cap:{decision.underlying}")

    # Step 4: per-priority concentration cap.
    by_priority: dict[str, list[_WorkingDecision]] = {}
    for decision in decisions:
        by_priority.setdefault(decision.priority_theme, []).append(decision)
    for theme, group in by_priority.items():
        group_total = sum(decision.final_size_pct for decision in group)
        cap = trader_profile.portfolio_constraints.max_priority_pct
        if group_total > cap and group_total > 0:
            scale = cap / group_total
            for decision in group:
                _scale_decision(
                    decision,
                    step="priority_concentration_cap",
                    scale_factor=scale,
                    rationale=(
                        f"Priority group {theme!r} totaled {group_total:.1%}, "
                        f"above {cap:.1%} cap; scaled by {scale:.1%}."
                    ),
                )
            _bind(binding_constraints, f"priority_concentration:{theme}")

    # Step 5: options allocation cap.
    option_decisions = [decision for decision in decisions if _is_option_trade(decision.trade)]
    options_total = sum(decision.final_size_pct for decision in option_decisions)
    options_cap = trader_profile.constraints.max_options_pct
    if options_total > options_cap and options_total > 0:
        scale = options_cap / options_total
        for decision in option_decisions:
            _scale_decision(
                decision,
                step="options_allocation_cap",
                scale_factor=scale,
                rationale=(
                    f"Options allocation totaled {options_total:.1%}, above "
                    f"{options_cap:.1%} cap; scaled by {scale:.1%}."
                ),
            )
        _bind(binding_constraints, "options_allocation_cap")

    # Step 6: total new deployment cap.
    total = sum(decision.final_size_pct for decision in decisions)
    total_cap = trader_profile.portfolio_constraints.max_total_new_deployment_pct
    if total > total_cap and total > 0:
        scale = total_cap / total
        for decision in decisions:
            _scale_decision(
                decision,
                step="total_deployment_cap",
                scale_factor=scale,
                rationale=(
                    f"Total new deployment was {total:.1%}, above {total_cap:.1%} "
                    f"cap; scaled by {scale:.1%}."
                ),
            )
        _bind(binding_constraints, "total_deployment_cap")

    # Step 7: minimum tradeable size floor.
    floor = trader_profile.portfolio_constraints.min_tradeable_size_pct
    for decision in decisions:
        if 0.0 < decision.final_size_pct < floor:
            before = decision.final_size_pct
            decision.final_size_pct = 0.0
            _add_adjustment(
                decision,
                step="min_size_floor",
                size_before=before,
                size_after=0.0,
                rationale=(
                    f"Final size {before:.2%} is below minimum tradeable size "
                    f"{floor:.2%}; zeroed."
                ),
            )
            _bind(binding_constraints, "min_size_floor")

    public_decisions = [_to_public_decision(decision) for decision in decisions]
    per_priority = {
        theme: sum(decision.final_size_pct for decision in group)
        for theme, group in by_priority.items()
    }
    total_new_deployment_pct = sum(decision.final_size_pct for decision in decisions)
    nav = positions.total_nav_usd if positions is not None else 0.0
    cash = positions.cash_usd if positions is not None else 0.0
    return PortfolioPlan(
        created_at=datetime.now(timezone.utc),
        cycle_id=cycle_id,
        nav_unlevered_usd=nav,
        cash_usd=cash,
        existing_positions_snapshot_id=positions.id if positions is not None else None,
        scenario_set_basis=scenario_set.regime_id_basis if scenario_set is not None else None,
        trade_decisions=public_decisions,
        total_new_deployment_pct=total_new_deployment_pct,
        total_new_deployment_usd=total_new_deployment_pct * nav,
        per_priority_deployment_pct=per_priority,
        binding_constraints=binding_constraints,
        n_executed=sum(1 for decision in public_decisions if decision.decision == "execute"),
        n_reduced=sum(1 for decision in public_decisions if decision.decision == "reduced"),
        n_rejected_portfolio=sum(
            1 for decision in public_decisions if decision.decision == "rejected_portfolio"
        ),
    )
