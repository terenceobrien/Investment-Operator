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
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
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
    build_narrative_analysis,
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.orchestration.cycle_status import (
    CycleStatusEmitter,
    StageName,
    StageStatus,
)
from src.agent_system.forecasting.macro_scenario_source import (
    CurrentConditionsView,
    MacroScenarioSource,
    MacroScenarioSourceConfig,
    get_macro_scenario_source,
    load_latest_narrative_macro_forecast_result,
    load_macro_scenario_source_config,
    preflight_ensemble_source,
    regime_curation_payload_from_macro_source,
    scenario_probabilities_from_macro_forecast,
)
from src.agent_system.forecasting.behavioral_scenarios_loader import (
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
    load_behavioral_scenarios,
)
from src.agent_system.rules.constraints import check_portfolio_constraints
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.rules.fundamental_screen import (
    screen_candidate,
    screen_to_minimal_fundamental_analysis,
)
from src.agent_system.positions.loader import load_latest_positions
from src.agent_system.scenarios.scorer import score_trade_against_scenarios
from src.agent_system.scenarios.types import (
    FactorImplications,
    Scenario,
    ScenarioSet,
    TradeScenarioAnalysis,
)
from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.fundamental_screen import (
    Archetype,
    FundamentalScreen,
    ScreenVerdict,
)
from src.agent_system.schemas.macro_forecast import MacroForecastResult
from src.agent_system.schemas.monte_carlo import MonteCarloConfig, MonteCarloPathResult
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    ResearchPriority,
    RegimeState as PydanticRegimeState,
)
from src.agent_system.schemas.thematic import ThematicMap
from src.agent_system.schemas.portfolio_plan import PortfolioPlan
from src.agent_system.schemas.trade import TradeProvenance
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.services.exposure_enrichment import ExposureEnrichmentService
from src.agent_system.services.existing_position_filter import (
    ExistingPositionCheck,
    ExistingPositionVerdict,
    apply_existing_position_filter,
    existing_position_filter_config,
    format_existing_position_filter_report,
)
from src.agent_system.services.held_position_registry import get_held_positions
from src.agent_system.services.monte_carlo_engine import MonteCarloEngine
from src.agent_system.services.scenario_assumptions_loader import ScenarioAssumptionsLoader
from src.agent_system.services.scenario_translation import translate_narrative_to_behavioral
from src.agent_system.services.shadow_outcome_builder import build_shadow_outcome
from src.agent_system.services.trade_outcome_builder import build_trade_outcome
from src.agent_system.paths import cycles_dir
from src.agent_system.storage.repository import (
    load_trade_outcome,
    save_decision_log_entry,
    save_schema,
    save_trade_outcome,
)

logger = logging.getLogger("agent_system.cycle")


def _ensure_status_emitter(
    cycle_id: str | None,
    emitter: CycleStatusEmitter | None,
    *,
    user_inputs: list[str] | None = None,
) -> tuple[str, CycleStatusEmitter]:
    if emitter is not None:
        if cycle_id is not None and cycle_id != emitter.cycle_id:
            raise ValueError(
                "cycle_id and emitter.cycle_id must match when both are supplied"
            )
        return emitter.cycle_id, emitter

    resolved_cycle_id = cycle_id or str(uuid4())
    return resolved_cycle_id, CycleStatusEmitter(
        resolved_cycle_id,
        user_inputs=user_inputs,
    )


def _frontend_cycle_url(cycle_id: str) -> str:
    base_url = os.getenv("AGENT_SYSTEM_FRONTEND_URL", "http://localhost:3000")
    return f"{base_url.rstrip('/')}/agent-system?cycle={cycle_id}"


def _print_cli_cycle_start(cycle_id: str, emitter: CycleStatusEmitter) -> None:
    print(f"Cycle ID: {cycle_id}")
    print(f"Frontend: {_frontend_cycle_url(cycle_id)}")
    print(f"Status file: {emitter.path}")
    print()


def _print_research_priorities(regime: PydanticRegimeState) -> None:
    """Print the research priorities at cycle start for operator verification."""

    priorities = regime.research_priorities
    if not priorities:
        print("=== RESEARCH PRIORITIES ===")
        print("  (none - cycle will run with no priorities)")
        print()
        return

    print(f"=== RESEARCH PRIORITIES ({len(priorities)}) ===")
    for priority in priorities:
        theme = priority.theme if len(priority.theme) <= 110 else priority.theme[:107] + "..."
        edge_preview = priority.edge_hypothesis
        if len(edge_preview) > 180:
            edge_preview = edge_preview[:177] + "..."
        scenarios = ", ".join(priority.source_scenario_ids) if priority.source_scenario_ids else "n/a"
        print(f"  {priority.priority_rank}. {theme}")
        print(f"     Edge decay: {priority.expected_edge_decay.value}")
        print(f"     Source scenarios: {scenarios}")
        print(f"     Edge: {edge_preview}")
        print()


def _print_scenario_probabilities(probabilities: dict[str, float] | None) -> None:
    """Print the macro scenario probabilities that will drive this cycle."""

    print("=== MACRO SCENARIO PROBABILITIES ===")
    if not probabilities:
        print("  (none - cycle will use fallback priors)")
        print()
        return
    for scenario_id, probability in sorted(probabilities.items(), key=lambda kv: -kv[1]):
        print(f"  {scenario_id}: {probability:.1%}")
    print()


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
        details = [f"proposed {decision.proposed_size_pct:.1%}"]
        if decision.scenario_weighted_expected_return is not None:
            details.append(
                f"scenario-weighted exp. return {decision.scenario_weighted_expected_return:.1%}"
            )
        else:
            details.append("scenario-weighted exp. return n/a")
        if decision.scenario_weight_source:
            details.append(f"weights={decision.scenario_weight_source}")
        lines.append(
            f"  {status:<8} {decision.underlying:<6} {trade_desc:<38} "
            f"{decision.final_size_pct:.1%} of NAV "
            f"({'; '.join(details)})"
        )
    return "\n".join(lines)


def _load_latest_macro_forecast_result() -> tuple[MacroForecastResult, Path] | None:
    loaded = load_latest_narrative_macro_forecast_result()
    if loaded is None:
        logger.warning("No readable narrative macro forecast JSON files found")
    return loaded


def _scenario_probabilities_from_macro_forecast(
    result: MacroForecastResult,
) -> dict[str, float] | None:
    return scenario_probabilities_from_macro_forecast(result)


def _load_latest_macro_forecast_probabilities() -> dict[str, float] | None:
    loaded = _load_latest_macro_forecast_result()
    if loaded is None:
        return None
    result, path = loaded
    probabilities = _scenario_probabilities_from_macro_forecast(result)
    if probabilities:
        return probabilities
    logger.warning("Macro forecast %s has no scenario probabilities", path)
    return None


def _regime_with_macro_source(
    regime: PydanticRegimeState,
    macro_source: MacroScenarioSource,
    *,
    include_seed_priorities: bool = False,
) -> PydanticRegimeState:
    updates: dict[str, object] = {
        "scenario_probabilities": dict(macro_source.scenario_probabilities),
        "scenario_probability_source": "macro_forecast",
    }
    if include_seed_priorities:
        updates["research_priorities"] = list(macro_source.seed_research_priorities)
    read = macro_source.current_conditions.current_regime_read
    if macro_source.taxonomy == "narrative_v0":
        for field_name in ("regime_id", "regime_label", "headline", "summary", "risk_summary"):
            value = read.get(field_name)
            if value:
                updates[field_name] = value
        confidence = read.get("regime_call_confidence")
        if confidence is not None:
            updates["regime_call_confidence"] = confidence
    elif macro_source.taxonomy == "behavioral_v1":
        primary = str(read.get("primary_behavioral_scenario") or "")
        label_by_id = {scenario.id: scenario.label for scenario in macro_source.scenario_set.scenarios}
        summary = str(read.get("narrative_summary") or "")
        if primary:
            updates["regime_id"] = primary
            updates["regime_label"] = label_by_id.get(primary, primary)
        if summary:
            updates["headline"] = summary[:1000]
            updates["summary"] = summary[:3000]
        tail_watch = macro_source.current_conditions.tail_watch
        if tail_watch:
            updates["risk_summary"] = "Tail watch: " + ", ".join(tail_watch)
    return regime.model_copy_validate(updates)


def _run_monte_carlo(
    *,
    plan: PortfolioPlan,
    accepted_trades: list[TradeIdea],
    scenario_analyses: list[TradeScenarioAnalysis],
    macro_scenario_probabilities: dict[str, float] | None,
    cycle_id: str,
    n_paths: int | None = None,
) -> MonteCarloPathResult:
    analyses_by_trade_id = {
        analysis.trade_id: analysis
        for analysis in scenario_analyses
    }
    final_sizes = {
        decision.trade_id: decision.final_size_pct
        for decision in plan.trade_decisions
        if decision.decision != "rejected_portfolio" and decision.final_size_pct > 0
    }
    enrichment = ExposureEnrichmentService()
    exposures = []
    for trade in accepted_trades:
        if trade.id is None or trade.id not in final_sizes:
            continue
        scenario_analysis = analyses_by_trade_id.get(trade.id)
        if scenario_analysis is None:
            continue
        exposures.append(
            enrichment.enrich(
                trade,
                scenario_analysis,
                final_sizes[trade.id],
            )
        )
    if not exposures:
        raise ValueError("No enrichable trades after portfolio construction")

    if macro_scenario_probabilities:
        scenario_probabilities = macro_scenario_probabilities
    else:
        raise ValueError(
            "Monte Carlo cannot run without macro scenario probabilities; "
            "fallback DEFAULT_SCENARIO_PRIORS is retired by the two_source_v1 rewire."
        )
    scenario_probabilities = translate_narrative_to_behavioral(scenario_probabilities)

    loader = ScenarioAssumptionsLoader()
    engine = MonteCarloEngine(
        assumptions_loader=loader,
        config=MonteCarloConfig(n_paths=n_paths) if n_paths is not None else None,
    )
    result = engine.run(exposures, scenario_probabilities)
    output_path = cycles_dir() / cycle_id / "monte_carlo_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return result


def _execute_cycle(
    regime: PydanticRegimeState,
    *,
    cycle_id: str | None = None,
    regime_source: str,
    fallback_reason: Optional[str],
    macro_source_config: MacroScenarioSourceConfig | None = None,
    macro_source: MacroScenarioSource | None = None,
    use_stub_thematic: bool = False,
    use_stub_fundamental: bool = False,
    use_stub_trade_expression: bool = False,
    skip_portfolio_construction: bool = False,
    emitter: CycleStatusEmitter | None = None,
) -> dict:
    cycle_id = cycle_id or (emitter.cycle_id if emitter is not None else str(uuid4()))
    cycle_date = str(regime.asof_date)[:10]
    if macro_source is None:
        macro_source = _macro_source_for_cycle_date(cycle_date, macro_source_config)
    macro_scenario_probabilities = dict(macro_source.scenario_probabilities)
    scenario_set = macro_source.scenario_set
    regime = _regime_with_macro_source(regime, macro_source)
    _print_research_priorities(regime)
    narrative_forecast: MacroForecastResult | None = None
    if macro_source.taxonomy == "narrative_v0":
        narrative_path = macro_source.provenance.get("narrative_forecast_path")
        if narrative_path:
            try:
                payload = json.loads(Path(str(narrative_path)).read_text(encoding="utf-8"))
                narrative_forecast = MacroForecastResult.model_validate(payload)
            except Exception as exc:
                logger.warning(
                    "Shadow forecast comparison skipped: could not reload narrative forecast %s: %s",
                    narrative_path,
                    exc,
                )
    _print_scenario_probabilities(macro_scenario_probabilities)
    # SHADOW MODE: run ensemble alongside, log comparison, consume nothing.
    try:
        if narrative_forecast is not None:
            from src.agent_system.forecasting.macro_forecast_comparison import (
                build_forecast_comparison,
            )
            from src.agent_system.forecasting.macro_forecast_shadow import (
                cycle_date_to_asof_quarter,
                run_shadow_forecast,
            )

            asof_quarter = cycle_date_to_asof_quarter(cycle_date)
            shadow = run_shadow_forecast(cycle_id, cycle_date, asof_quarter)
            if shadow is not None:
                build_forecast_comparison(
                    narrative_forecast,
                    shadow,
                    cycle_id,
                    cycle_date,
                )
        else:
            logger.warning(
                "Shadow forecast comparison skipped: no live narrative macro forecast artifact loaded."
            )
    except Exception as exc:
        logger.warning(
            "Shadow forecast failed (non-fatal, live path unaffected): %s",
            exc,
            exc_info=True,
        )
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
    monte_carlo_result: MonteCarloPathResult | None = None
    accepted_trades: list[TradeIdea] = []
    all_trade_idea_lookup: dict[str, TradeIdea] = {}
    cycle_decision_log_entries: list[dict] = []
    trader_profile = load_trader_profile()
    screen_stage_started = False
    conviction_stage_started = False
    trade_expression_stage_started = False
    existing_position_checks: list[ExistingPositionCheck] = []
    try:
        existing_position_config = existing_position_filter_config()
        held_positions_by_ticker = (
            get_held_positions(
                include_watching=True,
                recently_closed_window_days=existing_position_config.same_priority_recently_closed_window_days,
            )
            if existing_position_config.enabled
            else {}
        )
    except Exception as exc:
        logger.warning("Existing position filter disabled after setup failure: %s", exc, exc_info=True)
        existing_position_config = None
        held_positions_by_ticker = {}

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
        priority = priority.model_copy_validate({"id": priority_id})
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

            narrative = build_narrative_analysis(candidate)
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
            if existing_position_config is not None and existing_position_config.enabled:
                application = apply_existing_position_filter(
                    candidate=candidate,
                    priority=priority,
                    conviction=conviction,
                    held_records=held_positions_by_ticker.get(candidate.ticker.upper(), []),
                )
                candidate = application.candidate
                conviction = application.conviction
                existing_position_checks.extend(application.checks)
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
            conviction_id = save_schema(conviction, schema_type="Conviction")
            conviction = conviction.model_copy(update={"id": conviction_id})
            trade = trade.model_copy_validate(
                {
                    "combined_conviction": conviction,
                    "provenance": provenance,
                }
            )
            trade_id = save_schema(trade)
            trade = trade.model_copy(update={"id": trade_id})
            all_trade_idea_lookup[trade_id] = trade
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

            decision_log_entry = {
                "cycle_id": cycle_id,
                "candidate": candidate.ticker,
                "decision": (
                    decision
                    if constraint.allowed or decision == "rejected"
                    else "rejected"
                ),
                "conviction_rating": conviction.rating.value,
                "rule_applied": conviction.rule_applied,
                "weakest_link": conviction.weakest_link,
                "summary": conviction.reasoning,
                "trade_idea_id": trade_id,
                "portfolio_constraint": constraint.model_dump(mode="json"),
                "review_notes": "",
            }
            save_decision_log_entry(decision_log_entry)
            cycle_decision_log_entries.append(decision_log_entry)
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
                    score_trade_against_scenarios(
                        trade,
                        scenario_set,
                        regime=regime,
                        scenario_probabilities=macro_scenario_probabilities,
                    )
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
        try:
            trade_idea_lookup = {t.id: t for t in accepted_trades if t.id}
            cycle_date = str(regime.asof_date)[:10]
            for decision in plan.trade_decisions:
                try:
                    trade_idea = trade_idea_lookup.get(decision.trade_id)
                    if trade_idea is None:
                        continue
                    outcome = build_trade_outcome(
                        trade_idea=trade_idea,
                        decision=decision,
                        cycle_id=cycle_id,
                        cycle_date=cycle_date,
                    )
                    if outcome is not None:
                        save_trade_outcome(outcome)
                except Exception as exc:
                    logger.warning(
                        "Failed to create TradeOutcome for trade_id=%s: %s",
                        decision.trade_id,
                        exc,
                        exc_info=True,
                    )
            for decision_log_entry in cycle_decision_log_entries:
                if decision_log_entry.get("decision") != "rejected":
                    continue
                trade_id = decision_log_entry.get("trade_idea_id")
                if not trade_id or load_trade_outcome(trade_id) is not None:
                    continue
                trade_idea = all_trade_idea_lookup.get(trade_id)
                if trade_idea is None:
                    continue
                try:
                    shadow = build_shadow_outcome(
                        trade_idea=trade_idea,
                        decision_log_entry=decision_log_entry,
                        cycle_id=cycle_id,
                        cycle_date=cycle_date,
                    )
                    if shadow is not None:
                        save_trade_outcome(shadow)
                except Exception as exc:
                    logger.warning(
                        "Failed to create shadow TradeOutcome for trade_id=%s: %s",
                        trade_id,
                        exc,
                        exc_info=True,
                    )
        except Exception as exc:
            logger.warning(
                "TradeOutcome creation block failed: %s",
                exc,
                exc_info=True,
            )
        if not skip_portfolio_construction and accepted_trades and scenario_analyses:
            if emitter is not None:
                emitter.start_stage(
                    StageName.MONTE_CARLO,
                    "running portfolio Monte Carlo simulation",
                )
            try:
                monte_carlo_result = _run_monte_carlo(
                    plan=plan,
                    accepted_trades=accepted_trades,
                    scenario_analyses=scenario_analyses,
                    macro_scenario_probabilities=macro_scenario_probabilities,
                    cycle_id=cycle_id,
                )
                if emitter is not None:
                    emitter.complete_stage(
                        StageName.MONTE_CARLO,
                        (
                            "simulation complete: expected return "
                            f"{monte_carlo_result.portfolio_expected_return:.1%}, "
                            f"P10 {monte_carlo_result.portfolio_p10:.1%}, "
                            f"P90 {monte_carlo_result.portfolio_p90:.1%}"
                        ),
                    )
            except Exception as exc:
                logger.warning(
                    "Monte Carlo simulation failed: %s",
                    exc,
                    exc_info=True,
                )
                if emitter is not None:
                    emitter.skip_stage(
                        StageName.MONTE_CARLO,
                        f"simulation failed: {exc}",
                    )
        elif emitter is not None:
            emitter.skip_stage(
                StageName.MONTE_CARLO,
                "insufficient data for simulation",
            )
        try:
            from src.agent_system.services.excel_sync import ExcelSync

            report = ExcelSync().sync()
            logger.info(
                "Excel sync after cycle: %d edits read, %d updates written, %d appended",
                len(report.user_edits_applied),
                len(report.system_fields_written),
                len(report.outcomes_appended),
            )
        except FileNotFoundError:
            logger.info("Excel log not found; skipping sync")
        except Exception as exc:
            logger.warning("Excel sync failed: %s", exc, exc_info=True)
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
        emitter.skip_stage(StageName.MONTE_CARLO, "portfolio construction skipped")

    existing_position_report = format_existing_position_filter_report(existing_position_checks)
    existing_position_counts = {
        "demoted_same_hypothesis": sum(
            1
            for check in existing_position_checks
            if check.verdict
            in {
                ExistingPositionVerdict.SAME_PRIORITY_HELD,
                ExistingPositionVerdict.SAME_PRIORITY_WATCHING,
            }
            and check.conviction_after != check.conviction_before
        ),
        "same_hypothesis_recently_closed": sum(
            1
            for check in existing_position_checks
            if check.verdict == ExistingPositionVerdict.SAME_PRIORITY_RECENTLY_CLOSED
        ),
        "cross_hypothesis_confirming": sum(
            1
            for check in existing_position_checks
            if check.verdict == ExistingPositionVerdict.CROSS_HYPOTHESIS_CONFIRMING
        ),
        "cross_hypothesis_tension": sum(
            1
            for check in existing_position_checks
            if check.verdict == ExistingPositionVerdict.CROSS_HYPOTHESIS_TENSION
        ),
    }

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
        "macro_scenario_source": macro_source.provenance.get("macro_forecast_source"),
        "macro_scenario_taxonomy": macro_source.taxonomy,
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
        "existing_position_filter_enabled": (
            bool(existing_position_config.enabled)
            if existing_position_config is not None
            else False
        ),
        "existing_position_filter": existing_position_counts,
        "monte_carlo_result": (
            monte_carlo_result.model_dump(mode="json")
            if monte_carlo_result
            else None
        ),
        "_existing_position_filter_report": existing_position_report,
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


def _cycle_date_from_dataclass_regime(
    dataclass_state,
    *,
    fallback: str | None = None,
) -> str:
    for field_name in ("asof_date", "as_of_date", "date"):
        value = getattr(dataclass_state, field_name, None)
        if value:
            return str(value)[:10]
    if fallback:
        return str(fallback)[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _macro_source_for_cycle_date(
    cycle_date: str,
    macro_source_config: MacroScenarioSourceConfig | None,
) -> MacroScenarioSource:
    source_config = macro_source_config or load_macro_scenario_source_config()
    if source_config.macro_forecast_source == "ensemble":
        preflight_ensemble_source(
            cycle_date=cycle_date,
            config=source_config,
        )
    return get_macro_scenario_source(
        cycle_date=cycle_date,
        config=source_config,
    )


def _stub_behavioral_macro_source(cycle_date: str) -> MacroScenarioSource:
    """Explicit force-stub macro source with behavioral-v1 IDs only."""

    probabilities = {
        "expansion_disinflation": 0.24,
        "late_cycle_expansion": 0.40,
        "inflation_shock": 0.14,
        "stagflation": 0.08,
        "growth_scare_no_credit": 0.10,
        "credit_led_recession": 0.04,
    }
    scenarios = load_behavioral_scenarios()
    scenario_models: list[Scenario] = []
    for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS:
        scenario = scenarios[scenario_id]
        scenario_models.append(
            Scenario(
                id=scenario_id,
                label=scenario.label,
                probability=probabilities[scenario_id],
                description=scenario.definition,
                factor_implications=FactorImplications(
                    rates=str(scenario.factor_implications["rates"]),
                    equities=str(scenario.factor_implications["equities"]),
                    dollar=str(scenario.factor_implications["dollar"]),
                    credit=str(scenario.factor_implications["credit"]),
                    commodities=str(scenario.factor_implications["commodities"]),
                ),
            )
        )
    scenario_set = ScenarioSet(
        generated_at=datetime.now(timezone.utc),
        regime_id_basis="force_stub_behavioral",
        horizon_months=12,
        scenarios=scenario_models,
    )
    seed_research_priorities = [
        priority.model_copy_validate(
            {
                "source_scenario_ids": [
                    "late_cycle_expansion",
                    "expansion_disinflation",
                ],
                "source_macro_forecast_id": "force_stub_behavioral",
            }
        )
        for priority in make_stub_regime_state().research_priorities
    ]
    current_conditions = CurrentConditionsView(
        taxonomy="behavioral_v1",
        as_of=str(cycle_date)[:10],
        regime_id_basis="force_stub_behavioral",
        current_regime_read={
            "primary_behavioral_scenario": "late_cycle_expansion",
            "secondary_behavioral_scenario": "expansion_disinflation",
            "narrative_summary": (
                "Explicit force-stub behavioral macro source for deterministic tests and local smoke runs."
            ),
            "tail_watch": ["credit_led_recession"],
        },
        tail_watch=["credit_led_recession"],
        operator_prior_note="force_stub macro source; no production fallback was used.",
        source_path=None,
    )
    return MacroScenarioSource(
        taxonomy="behavioral_v1",
        scenario_probabilities=probabilities,
        scenario_set=scenario_set,
        current_conditions=current_conditions,
        seed_research_priorities=seed_research_priorities,
        provenance={
            "macro_forecast_source": "force_stub",
            "cycle_date": str(cycle_date)[:10],
            "probability_note": (
                "Explicit force_stub behavioral probabilities for deterministic test/dev runs only."
            ),
        },
    )


def _macro_source_for_regime(
    regime: PydanticRegimeState,
    macro_source_config: MacroScenarioSourceConfig | None,
    *,
    cycle_date: str | None = None,
) -> MacroScenarioSource:
    resolved_cycle_date = cycle_date or str(regime.asof_date)[:10]
    return _macro_source_for_cycle_date(resolved_cycle_date, macro_source_config)


def _select_regime_state_with_macro_source(
    *,
    asof_date: Optional[str] = None,
    macro_source_config: MacroScenarioSourceConfig | None = None,
) -> tuple[PydanticRegimeState, str, Optional[str], MacroScenarioSource | None]:
    """
    Live-cycle regime selector.

    Unlike the compatibility `_select_regime_state()`, this path never lets the
    adapter independently read current_regime.yaml. It builds the coherent
    MacroScenarioSource first and passes a source-derived curation payload into
    the adapter.
    """
    try:
        from src.state.regime_state import RegimeState as DataclassRegimeState
    except ImportError as e:
        regime = make_stub_regime_state()
        cycle_date = asof_date or str(regime.asof_date)[:10]
        macro_source = _stub_behavioral_macro_source(cycle_date)
        return (
            _regime_with_macro_source(regime, macro_source, include_seed_priorities=True),
            "stub_fallback",
            f"import_failed: {e}",
            macro_source,
        )

    try:
        if asof_date is not None:
            dataclass_state = DataclassRegimeState.load_snapshot(asof_date)
        else:
            dataclass_state = DataclassRegimeState.load_latest_snapshot()
    except Exception as e:
        regime = make_stub_regime_state()
        cycle_date = asof_date or str(regime.asof_date)[:10]
        macro_source = _stub_behavioral_macro_source(cycle_date)
        return (
            _regime_with_macro_source(regime, macro_source, include_seed_priorities=True),
            "stub_fallback",
            f"snapshot_load_failed: {e}",
            macro_source,
        )

    if dataclass_state is None:
        regime = make_stub_regime_state()
        cycle_date = asof_date or str(regime.asof_date)[:10]
        macro_source = _stub_behavioral_macro_source(cycle_date)
        return (
            _regime_with_macro_source(regime, macro_source, include_seed_priorities=True),
            "stub_fallback",
            "no_snapshot_found",
            macro_source,
        )

    cycle_date = _cycle_date_from_dataclass_regime(dataclass_state, fallback=asof_date)
    macro_source = _macro_source_for_cycle_date(cycle_date, macro_source_config)
    curation_payload = regime_curation_payload_from_macro_source(macro_source)
    try:
        from src.agent_system.adapters.regime import adapt_regime_state
        from src.agent_system.builders.forward_context import ForwardContextBuilder

        forward_context = ForwardContextBuilder().build()
        pydantic_state = adapt_regime_state(
            dataclass_state,
            forward_context=forward_context,
            curation_payload=curation_payload,
            scenario_probability_source="macro_forecast",
        )
        return pydantic_state, "real_snapshot", None, macro_source
    except Exception as e:
        if (
            macro_source_config is not None
            and macro_source_config.macro_forecast_source == "ensemble"
        ):
            raise
        regime = make_stub_regime_state()
        return (
            _regime_with_macro_source(regime, macro_source, include_seed_priorities=True),
            "stub_fallback",
            f"adapter_failed: {e}",
            macro_source,
        )


def run_research_cycle(
    *,
    asof_date: Optional[str] = None,
    macro_forecast_source: str | None = None,
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
        macro_forecast_source: Optional "narrative" or "ensemble" override.
            Defaults to backend/src/agent_system/config/research_cycle.yaml.
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
        emitter: Optional status emitter. When None, one is created so every
            cycle emits frontend-readable status.

    Returns:
        Cycle summary dict with regime_source, regime_asof_date, and
        fallback_reason added.
    """
    cycle_id, emitter = _ensure_status_emitter(cycle_id, emitter)
    macro_source_config = load_macro_scenario_source_config(
        macro_forecast_source=macro_forecast_source,
    )

    if force_stub:
        regime = make_stub_regime_state()
        regime_source = "stub"
        fallback_reason = None
        cycle_date = asof_date or str(regime.asof_date)[:10]
        macro_source = _stub_behavioral_macro_source(cycle_date)
        regime = _regime_with_macro_source(
            regime,
            macro_source,
            include_seed_priorities=True,
        )
    else:
        regime, regime_source, fallback_reason, macro_source = (
            _select_regime_state_with_macro_source(
                asof_date=asof_date,
                macro_source_config=macro_source_config,
            )
        )

    if research_priorities is not None:
        regime = regime.model_copy_validate({"research_priorities": research_priorities})

    return _execute_cycle(
        regime,
        cycle_id=cycle_id,
        regime_source=regime_source,
        fallback_reason=fallback_reason,
        macro_source_config=macro_source_config,
        macro_source=macro_source,
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
    macro_forecast_source: str | None = None,
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
    cleaned_inputs = [text.strip() for text in user_inputs if text.strip()]
    if not cleaned_inputs:
        raise ValueError("At least one non-empty user input is required")
    cycle_id, emitter = _ensure_status_emitter(
        cycle_id,
        emitter,
        user_inputs=cleaned_inputs,
    )
    macro_source_config = load_macro_scenario_source_config(
        macro_forecast_source=macro_forecast_source,
    )

    if force_stub:
        regime = make_stub_regime_state()
        regime_source = "stub"
        fallback_reason = None
        cycle_date = asof_date or str(regime.asof_date)[:10]
        macro_source = _stub_behavioral_macro_source(cycle_date)
        regime = _regime_with_macro_source(
            regime,
            macro_source,
            include_seed_priorities=True,
        )
    else:
        regime, regime_source, fallback_reason, macro_source = (
            _select_regime_state_with_macro_source(
                asof_date=asof_date,
                macro_source_config=macro_source_config,
            )
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
                StageName.MONTE_CARLO,
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
        macro_source_config=macro_source_config,
        macro_source=macro_source,
        use_stub_thematic=use_stub_thematic,
        use_stub_fundamental=use_stub_fundamental,
        use_stub_trade_expression=use_stub_trade_expression,
        skip_portfolio_construction=skip_portfolio_construction,
        emitter=emitter,
    )


def run_stub_research_cycle(
    *,
    macro_forecast_source: str | None = None,
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
    cycle_id, emitter = _ensure_status_emitter(None, emitter)
    macro_source_config = load_macro_scenario_source_config(
        macro_forecast_source=macro_forecast_source,
    )
    regime = make_stub_regime_state()
    macro_source = _stub_behavioral_macro_source(str(regime.asof_date)[:10])
    regime = _regime_with_macro_source(
        regime,
        macro_source,
        include_seed_priorities=True,
    )
    return _execute_cycle(
        regime,
        cycle_id=cycle_id,
        regime_source="stub",
        fallback_reason=None,
        macro_source_config=macro_source_config,
        macro_source=macro_source,
        use_stub_thematic=use_stub_thematic,
        use_stub_fundamental=use_stub_fundamental,
        use_stub_trade_expression=use_stub_trade_expression,
        skip_portfolio_construction=skip_portfolio_construction,
        emitter=emitter,
    )


def _main_preflight_ensemble(argv: list[str]) -> dict:
    parser = argparse.ArgumentParser(
        description="Preflight the ensemble macro scenario source for a cycle date."
    )
    parser.add_argument(
        "--cycle-date",
        default=datetime.now(timezone.utc).date().isoformat(),
        help="Cycle date in YYYY-MM-DD form. Defaults to today.",
    )
    args = parser.parse_args(argv)
    config = load_macro_scenario_source_config(macro_forecast_source="ensemble")
    report = preflight_ensemble_source(cycle_date=args.cycle_date, config=config)
    print(json.dumps(report, indent=2, sort_keys=True))
    return report


def main(argv: list[str] | None = None) -> dict:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] == "preflight-ensemble":
        return _main_preflight_ensemble(raw_args[1:])

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
        "--cycle-date",
        default=None,
        help="Alias for --asof-date; used to make ensemble anchor selection explicit.",
    )
    parser.add_argument(
        "--macro-forecast-source",
        choices=("narrative", "ensemble"),
        default=None,
        help=(
            "Override research_cycle.yaml macro_forecast_source. Defaults to ensemble; "
            "narrative remains available as rollback while v0 modules are present."
        ),
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
    args = parser.parse_args(raw_args)
    if args.asof_date and args.cycle_date and args.asof_date != args.cycle_date:
        raise ValueError("--asof-date and --cycle-date must match when both are supplied")
    resolved_asof_date = args.asof_date or args.cycle_date
    cycle_id = str(uuid4())
    emitter = CycleStatusEmitter(cycle_id)
    _print_cli_cycle_start(cycle_id, emitter)
    try:
        summary = run_research_cycle(
            asof_date=resolved_asof_date,
            macro_forecast_source=args.macro_forecast_source,
            force_stub=args.stub,
            use_stub_thematic=args.use_stub_thematic,
            use_stub_fundamental=args.use_stub_fundamental,
            use_stub_trade_expression=args.use_stub_trade_expression,
            skip_portfolio_construction=args.skip_portfolio_construction,
            cycle_id=cycle_id,
            emitter=emitter,
        )
    except Exception:
        emitter.fail_cycle(traceback.format_exc())
        raise

    portfolio_summary = summary.get("_portfolio_summary_text")
    existing_position_filter_report = summary.get("_existing_position_filter_report")
    printable_summary = {
        key: value
        for key, value in summary.items()
        if key not in {"_portfolio_summary_text", "_existing_position_filter_report"}
    }
    print(
        json.dumps(
            printable_summary,
            indent=2,
            sort_keys=True,
        )
    )
    if existing_position_filter_report:
        print()
        print(existing_position_filter_report)
    if portfolio_summary:
        print()
        print(portfolio_summary)
    return summary


if __name__ == "__main__":
    main()
