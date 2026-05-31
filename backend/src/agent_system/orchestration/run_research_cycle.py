"""
Run one research cycle end-to-end.

The thematic translation step uses the real thematic agent by default, and
the fundamental step uses the deterministic financial-health screen by default.
Explicit stub flags preserve a no-LLM/no-provider execution spine for tests
and local smoke runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from src.agent_system.agents.macro_agent import (
    MacroAgentValidationError,
    translate_to_priority,
)
from src.agent_system.agents.trade_expression_agent import (
    TradeExpressionComponents,
    TradeExpressionRejection,
    express_trade,
)
from src.agent_system.agents.portfolio_agent import construct_portfolio
from src.agent_system.agents.thematic_agent import (
    ThematicAgentValidationError,
    translate_priority_to_candidates,
)
from src.agent_system.config.trader_profile import load_trader_profile
from src.agent_system.data import get_fundamental_data, get_market_data
from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.orchestration.cycle_status import (
    CycleStatusEmitter,
    StageName,
    StageStatus,
)
from src.agent_system.rules.constraints import check_portfolio_constraints
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.rules.fundamental_screen import (
    screen_candidate,
    screen_to_minimal_fundamental_analysis,
)
from src.agent_system.positions.loader import load_latest_positions
from src.agent_system.scenarios.loader import load_current_scenarios
from src.agent_system.scenarios.scorer import score_trade_against_scenarios
from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.fundamental_screen import (
    Archetype,
    FundamentalScreen,
    ScreenVerdict,
)
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    ResearchPriority,
    RegimeState as PydanticRegimeState,
)
from src.agent_system.schemas.thematic import ThematicMap
from src.agent_system.schemas.portfolio_plan import PortfolioPlan
from src.agent_system.schemas.trade import TradeProvenance
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.storage.repository import save_decision_log_entry, save_schema

logger = logging.getLogger("agent_system.cycle")


def _decision_label(rating: ConvictionRating) -> str:
    return "rejected" if rating in (ConvictionRating.PASS, ConvictionRating.WEAK) else "accepted"


def _rejection_stage_from_conviction(conviction) -> str:
    return {
        "thematic": "thematic",
        "fundamental": "single_name",
        "narrative": "narrative",
    }.get(conviction.weakest_link, "construction")


def _placeholder_screen(candidate) -> FundamentalScreen:
    return FundamentalScreen(
        created_at=datetime.now(timezone.utc),
        ticker=candidate.ticker,
        archetype=Archetype.ESTABLISHED,
        verdict=ScreenVerdict.PASS,
        reason="Stub fundamental path; no real financial-health screen available",
        metrics_used={"source": "stub_fundamental"},
        data_was_sufficient=False,
        notes="Generated only to satisfy trade-expression agent inputs.",
    )


def _trade_from_expression_components(
    *,
    candidate,
    priority,
    fundamental,
    narrative,
    regime,
    conviction,
    components: TradeExpressionComponents,
) -> TradeIdea:
    return TradeIdea(
        underlying=candidate.ticker,
        fundamental=fundamental,
        narrative=narrative,
        research_priority=priority,
        regime=regime,
        combined_conviction=conviction,
        expression=components.expression,
        proposed_sizing=components.proposed_sizing,
        expected_holding_period=components.expected_holding_period,
        thesis_review_cadence=components.thesis_review_cadence,
        next_review_trigger=components.expression.exit_time_stop,
        trade_falsifiers=components.trade_falsifiers,
        invalidation_price=None,
        invalidation_thesis=components.invalidation_thesis,
        provenance=components.provenance,
    )


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _portfolio_summary_text(plan: PortfolioPlan) -> str:
    nav = plan.nav_unlevered_usd
    deployment_usd = plan.total_new_deployment_usd
    cash_remaining = plan.cash_usd - deployment_usd
    cash_remaining_pct = cash_remaining / nav if nav else 0.0
    lines = [
        "═══ PORTFOLIO PLAN ═══",
        f"NAV: {_money(nav)}",
        (
            f"New deployment: {_money(deployment_usd)} "
            f"({plan.total_new_deployment_pct:.1%} of NAV)"
        ),
        (
            f"Cash remaining if executed: {_money(cash_remaining)} "
            f"({cash_remaining_pct:.1%} of NAV)"
        ),
        "",
        "By priority:",
    ]
    by_priority_counts: dict[str, int] = {}
    for decision in plan.trade_decisions:
        theme = decision.priority_theme or "unknown_priority"
        by_priority_counts[theme] = by_priority_counts.get(theme, 0) + 1
    for theme, deployment in plan.per_priority_deployment_pct.items():
        lines.append(
            f"  {theme}: {by_priority_counts.get(theme, 0)} trades, "
            f"{deployment:.1%} of NAV"
        )
    lines.extend(
        [
            "",
            "Binding constraints: "
            + (", ".join(plan.binding_constraints) if plan.binding_constraints else "none"),
            "",
            "Decisions:",
        ]
    )
    for decision in plan.trade_decisions:
        status = decision.decision.upper().replace("_PORTFOLIO", "")
        trade_desc = decision.underlying
        lines.append(
            f"  {status:<8} {decision.underlying:<6} {trade_desc:<38} "
            f"{decision.final_size_pct:.1%} of NAV "
            f"(proposed {decision.proposed_size_pct:.1%})"
        )
    return "\n".join(lines)


def _execute_cycle(
    regime: PydanticRegimeState,
    *,
    cycle_id: str | None = None,
    regime_source: str,
    fallback_reason: Optional[str],
    use_stub_thematic: bool = False,
    use_stub_fundamental: bool = False,
    use_stub_trade_expression: bool = False,
    skip_portfolio_construction: bool = False,
    emitter: CycleStatusEmitter | None = None,
) -> dict:
    cycle_id = cycle_id or (emitter.cycle_id if emitter is not None else str(uuid4()))
    if emitter is not None:
        macro_stage = next(
            (stage for stage in emitter.state.stages if stage.stage == StageName.MACRO),
            None,
        )
        if macro_stage is not None and macro_stage.status == StageStatus.PENDING:
            emitter.skip_stage(StageName.MACRO, "priorities loaded from regime state")

    regime_id = save_schema(regime)
    regime = regime.model_copy(update={"id": regime_id})

    thematic_maps = 0
    candidates_considered = 0
    trade_ideas_saved = 0
    decision_log_entries = 0
    accepted_underlyings: list[str] = []
    rejected_underlyings: list[str] = []
    thematic_agent_errors = 0
    clarifications_received = 0
    fundamental_screened = 0
    fundamental_eliminated = 0
    fundamental_passed = 0
    crowding_flags = 0
    trade_expressions_attempted = 0
    trade_expressions_succeeded = 0
    trade_expressions_failed = 0
    trade_expressions_fallback_used = 0
    trade_options_selected = 0
    trade_stocks_selected = 0
    trade_rejections_pre_expression = 0
    trade_rejections_post_expression = 0
    trade_rejections_direction_misalignment = 0
    portfolio_trades_executed = 0
    portfolio_trades_reduced = 0
    portfolio_trades_rejected = 0
    portfolio_total_deployment_pct = 0.0
    portfolio_binding_constraints: list[str] = []
    portfolio_plan_summary: str | None = None
    accepted_trades: list[TradeIdea] = []
    trader_profile = load_trader_profile()
    screen_stage_started = False
    conviction_stage_started = False
    trade_expression_stage_started = False

    if emitter is not None:
        emitter.start_stage(
            StageName.THEMATIC,
            f"translating {len(regime.research_priorities)} priorities to candidates",
        )

    for priority_index, priority in enumerate(regime.research_priorities, 1):
        if emitter is not None:
            emitter.update_stage(
                StageName.THEMATIC,
                message=f"working on priority {priority_index}: {priority.theme[:100]}",
                current=priority_index,
                total=len(regime.research_priorities),
            )
        priority_id = save_schema(priority)
        if use_stub_thematic:
            thematic_map = make_stub_thematic_map(regime).model_copy_validate(
                {"source_priority_id": priority_id}
            )
        else:
            try:
                agent_result = asyncio.run(
                    translate_priority_to_candidates(
                        priority=priority,
                        regime_state=regime,
                    )
                )
            except ThematicAgentValidationError as e:
                logger.warning(
                    "thematic agent failed for priority %s: %s",
                    priority.theme[:80],
                    e,
                )
                thematic_agent_errors += 1
                continue

            if isinstance(agent_result, ClarificationRequest):
                logger.info(
                    "thematic agent returned clarification for priority %s: %s",
                    priority.theme[:80],
                    agent_result.question[:120],
                )
                clarifications_received += 1
                save_schema(agent_result)
                continue

            assert isinstance(agent_result, ThematicMap)
            thematic_map = agent_result.model_copy_validate(
                {"source_priority_id": priority_id}
            )

        thematic_map_id = save_schema(thematic_map)
        thematic_maps += 1

        for candidate in thematic_map.candidates:
            candidates_considered += 1
            bundle = None
            screen = None
            if emitter is not None:
                if not screen_stage_started:
                    emitter.start_stage(StageName.SCREEN, "screening candidates")
                    screen_stage_started = True
                emitter.update_stage(
                    StageName.SCREEN,
                    message=f"screening {candidate.ticker}",
                    current=candidates_considered,
                    total=None,
                )
            if use_stub_fundamental:
                fundamental = make_stub_fundamental_analysis(candidate)
                fundamental_id = save_schema(fundamental)
            else:
                bundle = get_fundamental_data(candidate.ticker)
                screen = screen_candidate(bundle)
                save_schema(screen)
                fundamental_screened += 1
                if screen.crowding_flag:
                    crowding_flags += 1
                if screen.verdict == ScreenVerdict.ELIMINATE:
                    fundamental_eliminated += 1
                    rejected_underlyings.append(candidate.ticker)
                    continue

                fundamental_passed += 1
                fundamental = screen_to_minimal_fundamental_analysis(
                    candidate,
                    screen,
                )
                fundamental_id = save_schema(fundamental)

            narrative = make_stub_narrative_analysis(candidate)
            narrative_id = save_schema(narrative)
            if emitter is not None:
                if not conviction_stage_started:
                    emitter.start_stage(StageName.CONVICTION, "evaluating conviction gates")
                    conviction_stage_started = True
                emitter.update_stage(
                    StageName.CONVICTION,
                    message=f"evaluating conviction for {candidate.ticker}",
                    current=candidates_considered,
                    total=None,
                )
            conviction = evaluate_conviction(
                candidate=candidate,
                fundamental=fundamental,
                narrative=narrative,
                regime=regime,
            )
            if use_stub_trade_expression:
                trade = construct_trade_idea(
                    candidate=candidate,
                    fundamental=fundamental,
                    narrative=narrative,
                    regime=regime,
                    conviction=conviction,
                )
                if conviction.rating in (ConvictionRating.PASS, ConvictionRating.WEAK):
                    trade_rejections_pre_expression += 1
            elif conviction.rating in (ConvictionRating.PASS, ConvictionRating.WEAK):
                trade_rejections_pre_expression += 1
                trade = TradeIdea(
                    underlying=candidate.ticker,
                    fundamental=fundamental,
                    narrative=narrative,
                    research_priority=priority,
                    regime=regime,
                    combined_conviction=conviction,
                    rejection_reason=conviction.reasoning,
                    rejection_stage=_rejection_stage_from_conviction(conviction),  # type: ignore[arg-type]
                    rejection_rule_fired=conviction.rule_applied,
                )
            else:
                trade_expressions_attempted += 1
                if emitter is not None:
                    if not trade_expression_stage_started:
                        emitter.start_stage(
                            StageName.TRADE_EXPRESSION,
                            "constructing trade expressions",
                        )
                        trade_expression_stage_started = True
                    emitter.update_stage(
                        StageName.TRADE_EXPRESSION,
                        message=f"expressing trade for {candidate.ticker}",
                        current=trade_expressions_attempted,
                        total=None,
                    )
                if bundle is None:
                    bundle = get_fundamental_data(candidate.ticker)
                if screen is None:
                    screen = _placeholder_screen(candidate)
                market = get_market_data(candidate.ticker)
                components = asyncio.run(
                    express_trade(
                        candidate=candidate,
                        screen=screen,
                        fundamentals=bundle,
                        market=market,
                        regime=regime,
                        trader_profile=trader_profile,
                        priority=priority,
                    )
                )
                if isinstance(components, TradeExpressionRejection):
                    trade_rejections_direction_misalignment += 1
                    conviction = Conviction(
                        rating=ConvictionRating.PASS,
                        rule_applied=components.rejection_rule_fired,
                        weakest_link="thematic",
                        reasoning=components.misalignment_reason,
                    )
                    trade = TradeIdea(
                        underlying=candidate.ticker,
                        fundamental=fundamental,
                        narrative=narrative,
                        research_priority=priority,
                        regime=regime,
                        combined_conviction=conviction,
                        rejection_reason=components.misalignment_reason,
                        rejection_stage=components.rejection_stage,
                        rejection_rule_fired=components.rejection_rule_fired,
                    )
                else:
                    if components.fallback_used:
                        trade_expressions_failed += 1
                        trade_expressions_fallback_used += 1
                    else:
                        trade_expressions_succeeded += 1
                    if components.selected_strategy == "long_stock":
                        trade_stocks_selected += 1
                    elif components.selected_strategy in {
                        "long_call",
                        "long_put",
                        "long_call_spread",
                        "long_put_spread",
                        "covered_call",
                        "cash_secured_put",
                    }:
                        trade_options_selected += 1
                    trade = _trade_from_expression_components(
                        candidate=candidate,
                        priority=priority,
                        fundamental=fundamental,
                        narrative=narrative,
                        regime=regime,
                        conviction=conviction,
                        components=components,
                    )
            provenance = TradeProvenance(
                research_priority_id=priority_id,
                thematic_map_id=thematic_map_id,
                fundamental_analysis_id=fundamental_id,
                narrative_analysis_id=narrative_id,
                regime_state_id=regime_id,
            )
            trade = trade.model_copy_validate({"provenance": provenance})
            trade_id = save_schema(trade)
            trade = trade.model_copy(update={"id": trade_id})
            trade_ideas_saved += 1

            constraint = check_portfolio_constraints(
                proposed_trade=trade,
                portfolio_state=None,
            )
            decision = _decision_label(conviction.rating)
            if decision == "accepted" and constraint.allowed:
                accepted_underlyings.append(candidate.ticker)
                accepted_trades.append(trade)
            else:
                rejected_underlyings.append(candidate.ticker)

            save_decision_log_entry(
                {
                    "cycle_id": cycle_id,
                    "candidate": candidate.ticker,
                    "decision": decision if constraint.allowed or decision == "rejected" else "rejected",
                    "conviction_rating": conviction.rating.value,
                    "rule_applied": conviction.rule_applied,
                    "weakest_link": conviction.weakest_link,
                    "summary": conviction.reasoning,
                    "trade_idea_id": trade_id,
                    "portfolio_constraint": constraint.model_dump(mode="json"),
                    "review_notes": "",
                }
            )
            decision_log_entries += 1

    if emitter is not None:
        emitter.complete_stage(
            StageName.THEMATIC,
            f"created {thematic_maps} thematic map(s)",
        )
        if screen_stage_started:
            emitter.complete_stage(
                StageName.SCREEN,
                f"screened {fundamental_screened} candidate(s)",
            )
        else:
            emitter.skip_stage(StageName.SCREEN, "no candidates to screen")
        if conviction_stage_started:
            emitter.complete_stage(
                StageName.CONVICTION,
                f"saved {trade_ideas_saved} trade idea(s)",
            )
        else:
            emitter.skip_stage(StageName.CONVICTION, "no candidates reached conviction")
        if trade_expression_stage_started:
            emitter.complete_stage(
                StageName.TRADE_EXPRESSION,
                f"attempted {trade_expressions_attempted} trade expression(s)",
            )
        else:
            emitter.skip_stage(
                StageName.TRADE_EXPRESSION,
                "no candidates reached trade expression",
            )

    if not skip_portfolio_construction:
        scenario_set = load_current_scenarios()
        scenario_analyses = []
        if scenario_set is None:
            logger.warning("no current scenarios loaded; skipping scenario scoring")
            if emitter is not None:
                emitter.skip_stage(
                    StageName.SCENARIO_SCORING,
                    "no current scenarios loaded",
                )
        else:
            if not accepted_trades:
                if emitter is not None:
                    emitter.skip_stage(
                        StageName.SCENARIO_SCORING,
                        "no accepted trades to score",
                    )
            elif emitter is not None:
                emitter.start_stage(
                    StageName.SCENARIO_SCORING,
                    f"scoring {len(accepted_trades)} accepted trade(s)",
                )
            for trade_index, trade in enumerate(accepted_trades, 1):
                if emitter is not None:
                    emitter.update_stage(
                        StageName.SCENARIO_SCORING,
                        message=f"scoring scenarios for {trade.underlying}",
                        current=trade_index,
                        total=len(accepted_trades),
                    )
                analysis = asyncio.run(
                    score_trade_against_scenarios(trade, scenario_set)
                )
                scenario_analyses.append(analysis)
                save_schema(analysis, schema_type="TradeScenarioAnalysis")
            if emitter is not None and accepted_trades:
                emitter.complete_stage(
                    StageName.SCENARIO_SCORING,
                    f"scored {len(accepted_trades)} trade(s)",
                )

        positions = load_latest_positions()
        if positions is None:
            logger.info("no positions snapshot available; overlap caps skipped")
        else:
            positions_id = save_schema(positions, schema_type="PositionsSnapshot")
            positions = positions.model_copy(update={"id": positions_id})

        if emitter is not None:
            emitter.start_stage(StageName.PORTFOLIO, "constructing portfolio plan")
        plan = construct_portfolio(
            accepted_trades=accepted_trades,
            scenario_analyses=scenario_analyses,
            positions=positions,
            trader_profile=trader_profile,
            scenario_set=scenario_set,
            cycle_id=cycle_id,
        )
        save_schema(plan, schema_type="PortfolioPlan")
        portfolio_trades_executed = plan.n_executed
        portfolio_trades_reduced = plan.n_reduced
        portfolio_trades_rejected = plan.n_rejected_portfolio
        portfolio_total_deployment_pct = plan.total_new_deployment_pct
        portfolio_binding_constraints = plan.binding_constraints
        portfolio_plan_summary = _portfolio_summary_text(plan)
        if emitter is not None:
            emitter.complete_stage(
                StageName.PORTFOLIO,
                f"portfolio plan executed {portfolio_trades_executed} trade(s)",
            )
    elif emitter is not None:
        emitter.skip_stage(StageName.SCENARIO_SCORING, "portfolio construction skipped")
        emitter.skip_stage(StageName.PORTFOLIO, "portfolio construction skipped")

    summary = {
        "cycle_id": cycle_id,
        "regime_id": regime_id,
        "thematic_maps": thematic_maps,
        "candidates_considered": candidates_considered,
        "trade_ideas_saved": trade_ideas_saved,
        "accepted": len(accepted_underlyings),
        "rejected": len(rejected_underlyings),
        "decision_log_entries": decision_log_entries,
        "accepted_underlyings": accepted_underlyings,
        "rejected_underlyings": rejected_underlyings,
        "regime_source": regime_source,
        "regime_asof_date": regime.asof_date,
        "fallback_reason": fallback_reason,
        "thematic_agent_errors": thematic_agent_errors,
        "clarifications_received": clarifications_received,
        "fundamental_screened": fundamental_screened,
        "fundamental_eliminated": fundamental_eliminated,
        "fundamental_passed": fundamental_passed,
        "crowding_flags": crowding_flags,
        "trade_expressions_attempted": trade_expressions_attempted,
        "trade_expressions_succeeded": trade_expressions_succeeded,
        "trade_expressions_failed": trade_expressions_failed,
        "trade_expressions_fallback_used": trade_expressions_fallback_used,
        "trade_options_selected": trade_options_selected,
        "trade_stocks_selected": trade_stocks_selected,
        "trade_rejections_pre_expression": trade_rejections_pre_expression,
        "trade_rejections_post_expression": trade_rejections_post_expression,
        "trade_rejections_direction_misalignment": trade_rejections_direction_misalignment,
        "portfolio_trades_executed": portfolio_trades_executed,
        "portfolio_trades_reduced": portfolio_trades_reduced,
        "portfolio_trades_rejected": portfolio_trades_rejected,
        "portfolio_total_deployment_pct": portfolio_total_deployment_pct,
        "portfolio_binding_constraints": portfolio_binding_constraints,
        "_portfolio_summary_text": portfolio_plan_summary,
    }
    if emitter is not None:
        emitter.set_summary(summary)
        emitter.complete_cycle()
    return summary


def _select_regime_state(
    asof_date: Optional[str] = None,
) -> tuple[PydanticRegimeState, str, Optional[str]]:
    """
    Try to load and adapt a real regime snapshot. Fall back to the stub
    if anything goes wrong. Always returns a tuple of (regime,
    regime_source, fallback_reason).

    regime_source is one of: "real_snapshot", "stub_fallback", "stub".
    fallback_reason is None unless regime_source == "stub_fallback".
    """
    try:
        from src.state.regime_state import RegimeState as DataclassRegimeState
    except ImportError as e:
        return make_stub_regime_state(), "stub_fallback", f"import_failed: {e}"

    try:
        if asof_date is not None:
            dataclass_state = DataclassRegimeState.load_snapshot(asof_date)
        else:
            dataclass_state = DataclassRegimeState.load_latest_snapshot()
    except Exception as e:
        return (
            make_stub_regime_state(),
            "stub_fallback",
            f"snapshot_load_failed: {e}",
        )

    if dataclass_state is None:
        return make_stub_regime_state(), "stub_fallback", "no_snapshot_found"

    try:
        from src.agent_system.adapters.regime import adapt_regime_state
        from src.agent_system.builders.forward_context import ForwardContextBuilder

        forward_context = ForwardContextBuilder().build()
        pydantic_state = adapt_regime_state(
            dataclass_state,
            forward_context=forward_context,
        )
        return pydantic_state, "real_snapshot", None
    except Exception as e:
        return make_stub_regime_state(), "stub_fallback", f"adapter_failed: {e}"


def run_research_cycle(
    *,
    asof_date: Optional[str] = None,
    force_stub: bool = False,
    use_stub_thematic: bool = False,
    use_stub_fundamental: bool = False,
    use_stub_trade_expression: bool = False,
    skip_portfolio_construction: bool = False,
    cycle_id: str | None = None,
    research_priorities: list[ResearchPriority] | None = None,
    emitter: CycleStatusEmitter | None = None,
) -> dict:
    """
    Run one research cycle.

    By default, attempts to load the latest real snapshot. If no
    snapshot is available, the adapter fails, or force_stub=True,
    falls back to the deterministic regime stub. The real thematic agent
    remains the default unless use_stub_thematic=True. The deterministic
    financial-health screen remains the default unless
    use_stub_fundamental=True.

    Args:
        asof_date: Optional override to load a specific snapshot date
            in "YYYY-MM-DD" format. None means latest.
        force_stub: If True, skip the real path entirely and use the
            stub regime. This does not by itself disable thematic LLM calls.
        use_stub_thematic: If True, use the deterministic thematic map
            instead of the real thematic agent. For test and dev determinism.
        use_stub_fundamental: If True, use the deterministic fundamental stub
            instead of the real financial-health screen.
        use_stub_trade_expression: If True, use the deterministic trade
            construction stub instead of the real trade expression agent.
        skip_portfolio_construction: If True, skip scenario scoring,
            positions loading, and portfolio-plan construction.
        cycle_id: Optional externally assigned id, used by API background jobs.
        research_priorities: Optional in-memory priorities to use instead of
            the regime state's YAML-loaded priorities.
        emitter: Optional status emitter. When None, CLI behavior is unchanged.

    Returns:
        Cycle summary dict with regime_source, regime_asof_date, and
        fallback_reason added.
    """
    if force_stub:
        regime = make_stub_regime_state()
        regime_source = "stub"
        fallback_reason = None
    else:
        regime, regime_source, fallback_reason = _select_regime_state(
            asof_date=asof_date
        )

    if research_priorities is not None:
        regime = regime.model_copy_validate({"research_priorities": research_priorities})

    return _execute_cycle(
        regime,
        cycle_id=cycle_id,
        regime_source=regime_source,
        fallback_reason=fallback_reason,
        use_stub_thematic=use_stub_thematic,
        use_stub_fundamental=use_stub_fundamental,
        use_stub_trade_expression=use_stub_trade_expression,
        skip_portfolio_construction=skip_portfolio_construction,
        emitter=emitter,
    )


def run_cycle_with_inputs(
    *,
    user_inputs: list[str],
    cycle_id: str | None = None,
    emitter: CycleStatusEmitter | None = None,
    asof_date: Optional[str] = None,
    force_stub: bool = False,
    use_stub_thematic: bool = False,
    use_stub_fundamental: bool = False,
    use_stub_trade_expression: bool = False,
    skip_portfolio_construction: bool = False,
) -> dict:
    """
    Run a cycle from free-text user inputs.

    The macro agent converts inputs to in-memory ResearchPriority objects; the
    existing cycle then consumes those priorities directly without mutating
    current_regime.yaml.
    """
    cycle_id = cycle_id or str(uuid4())
    cleaned_inputs = [text.strip() for text in user_inputs if text.strip()]
    if not cleaned_inputs:
        raise ValueError("At least one non-empty user input is required")

    if force_stub:
        regime = make_stub_regime_state()
        regime_source = "stub"
        fallback_reason = None
    else:
        regime, regime_source, fallback_reason = _select_regime_state(
            asof_date=asof_date
        )

    priorities: list[ResearchPriority] = []
    clarifications_received = 0
    if emitter is not None:
        emitter.start_stage(
            StageName.MACRO,
            f"translating {len(cleaned_inputs)} input(s) into priorities",
        )

    try:
        for idx, user_input in enumerate(cleaned_inputs, 1):
            if emitter is not None:
                emitter.update_stage(
                    StageName.MACRO,
                    message=f"translating input {idx}: {user_input[:100]}",
                    current=idx,
                    total=len(cleaned_inputs),
                )
            result = asyncio.run(
                translate_to_priority(
                    user_input=user_input,
                    regime_state=regime,
                    enable_clarification=True,
                )
            )
            if isinstance(result, ResearchPriority):
                priorities.append(result)
            elif isinstance(result, ClarificationRequest):
                clarifications_received += 1
                save_schema(result)
            else:  # pragma: no cover - defensive guard for future return types
                raise MacroAgentValidationError(
                    f"Unexpected macro agent result type: {type(result).__name__}"
                )
    except Exception as exc:
        if emitter is not None:
            emitter.fail_stage(StageName.MACRO, str(exc))
        raise

    if emitter is not None:
        emitter.complete_stage(
            StageName.MACRO,
            (
                f"produced {len(priorities)} priorit"
                f"{'y' if len(priorities) == 1 else 'ies'}"
                f" and {clarifications_received} clarification(s)"
            ),
        )

    if not priorities:
        summary = {
            "cycle_id": cycle_id,
            "regime_source": regime_source,
            "regime_asof_date": regime.asof_date,
            "fallback_reason": fallback_reason,
            "macro_priorities": 0,
            "clarifications_received": clarifications_received,
            "thematic_maps": 0,
            "candidates_considered": 0,
            "trade_ideas_saved": 0,
            "accepted": 0,
            "rejected": 0,
        }
        if emitter is not None:
            for stage in (
                StageName.THEMATIC,
                StageName.SCREEN,
                StageName.CONVICTION,
                StageName.TRADE_EXPRESSION,
                StageName.SCENARIO_SCORING,
                StageName.PORTFOLIO,
            ):
                emitter.skip_stage(stage, "no macro priorities available")
            emitter.set_summary(summary)
            emitter.complete_cycle()
        return summary

    return _execute_cycle(
        regime.model_copy_validate({"research_priorities": priorities}),
        cycle_id=cycle_id,
        regime_source=regime_source,
        fallback_reason=fallback_reason,
        use_stub_thematic=use_stub_thematic,
        use_stub_fundamental=use_stub_fundamental,
        use_stub_trade_expression=use_stub_trade_expression,
        skip_portfolio_construction=skip_portfolio_construction,
        emitter=emitter,
    )


def run_stub_research_cycle(
    *,
    use_stub_thematic: bool = True,
    use_stub_fundamental: bool = True,
    use_stub_trade_expression: bool = True,
    skip_portfolio_construction: bool = False,
    emitter: CycleStatusEmitter | None = None,
) -> dict:
    """
    Execute one local deterministic cycle and persist schemas/log entries.

    This explicitly stub-named convenience entry point retains stub thematic
    and fundamental defaults so existing tests and smoke runs cannot incur LLM
    or provider-data cost. Pass a stub flag as False only when deliberately
    exercising a real component.

    Returns a summary that is intentionally compact enough for CLI output and
    tests, while detailed artifacts live in JSONL storage.
    """
    return _execute_cycle(
        make_stub_regime_state(),
        regime_source="stub",
        fallback_reason=None,
        use_stub_thematic=use_stub_thematic,
        use_stub_fundamental=use_stub_fundamental,
        use_stub_trade_expression=use_stub_trade_expression,
        skip_portfolio_construction=skip_portfolio_construction,
        emitter=emitter,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run a research cycle (real thematic agent by default)."
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Force the deterministic stub regime instead of loading a snapshot.",
    )
    parser.add_argument(
        "--asof-date",
        default=None,
        help="Optional YYYY-MM-DD snapshot date. Defaults to latest snapshot.",
    )
    parser.add_argument(
        "--use-stub-thematic",
        action="store_true",
        help=(
            "Use the stub thematic map instead of the real agent. "
            "Useful for testing downstream agents without LLM cost. "
            "Default: use the real agent."
        ),
    )
    parser.add_argument(
        "--use-stub-fundamental",
        action="store_true",
        help=(
            "Use the stub FundamentalAnalysis instead of the real "
            "financial-health screen. Useful for testing downstream agents "
            "without provider-data fetches. Default: use the real screen."
        ),
    )
    parser.add_argument(
        "--use-stub-trade-expression",
        action="store_true",
        help=(
            "Use the stub trade construction path instead of the real trade "
            "expression agent. Useful for cheap downstream smoke runs. "
            "Default: use the real trade expression agent."
        ),
    )
    parser.add_argument(
        "--skip-portfolio-construction",
        action="store_true",
        help=(
            "Skip scenario scoring, positions loading, and deterministic "
            "portfolio construction. Useful for cheap upstream iteration."
        ),
    )
    args = parser.parse_args()
    summary = run_research_cycle(
        asof_date=args.asof_date,
        force_stub=args.stub,
        use_stub_thematic=args.use_stub_thematic,
        use_stub_fundamental=args.use_stub_fundamental,
        use_stub_trade_expression=args.use_stub_trade_expression,
        skip_portfolio_construction=args.skip_portfolio_construction,
    )
    portfolio_summary = summary.pop("_portfolio_summary_text", None)
    print(
        json.dumps(
            summary,
            indent=2,
            sort_keys=True,
        )
    )
    if portfolio_summary:
        print()
        print(portfolio_summary)
