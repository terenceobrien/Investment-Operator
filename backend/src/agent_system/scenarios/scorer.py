"""TradeIdea scenario scoring."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.llm.client import parse_structured
from src.agent_system.llm.config import SCENARIO_AGENT_MODEL
from src.agent_system.scenarios.types import (
    ScenarioScore,
    ScenarioSet,
    ScenarioWeightSource,
    TradeScenarioAnalysis,
    compute_trade_scenario_metrics,
)
from src.agent_system.schemas.regime import RegimeState
from src.agent_system.schemas.trade import TradeIdea

logger = logging.getLogger("agent_system.scenarios.scorer")


class _ScenarioScoreBatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_scores: list[ScenarioScore] = Field(min_length=1, max_length=5)


SCORER_SYSTEM_PROMPT = """You are the scenario scorer for a structured \
investment research system. Score one TradeIdea against all supplied scenarios \
in a single batched response.

For each scenario, estimate the percentage return of the trade expression in \
that scenario. Use decimals: 0.15 means +15%, -0.30 means -30%. Respect the \
actual expression, sizing-independent payoff profile, direction, thesis, entry, \
stop, target, and falsifiers. Return exactly one ScenarioScore for each scenario \
id provided, in the same order.
"""


def _trade_summary(trade: TradeIdea) -> str:
    expression = trade.expression
    if expression is None:
        expression_text = "No expression; rejected trade idea."
    else:
        primary = expression.primary_instrument
        expression_text = (
            f"{primary.ticker} {primary.instrument_type.value} "
            f"{primary.direction.value}: {primary.description}\n"
            f"Rationale: {expression.rationale_for_instrument}\n"
            f"Entry: {expression.entry_logic}\n"
            f"Target: {expression.exit_target}\n"
            f"Stop: {expression.exit_stop}\n"
            f"Time stop: {expression.exit_time_stop}"
        )
    return (
        f"Trade id: {trade.id or '(unpersisted)'}\n"
        f"Underlying: {trade.underlying}\n"
        f"Conviction: {trade.combined_conviction.rating.value} / "
        f"{trade.combined_conviction.rule_applied}\n"
        f"Research priority: {trade.research_priority.theme if trade.research_priority else '(none)'}\n"
        f"Inval thesis: {trade.invalidation_thesis or '(none)'}\n"
        f"Expression:\n{expression_text}\n"
    )


def _scenario_summary(scenario_set: ScenarioSet) -> str:
    lines = [
        f"Horizon months: {scenario_set.horizon_months}",
        f"Regime basis: {scenario_set.regime_id_basis}",
    ]
    for scenario in scenario_set.scenarios:
        lines.append(
            f"- {scenario.id} ({scenario.probability:.2f}): "
            f"{scenario.label}. {scenario.description} "
            f"Factors={scenario.factor_implications}"
        )
    return "\n".join(lines)


def _build_analysis(
    *,
    trade: TradeIdea,
    scenario_set: ScenarioSet,
    scores: list[ScenarioScore],
    regime: RegimeState | None = None,
    scenario_probabilities: dict[str, float] | None = None,
    fallback_used: bool = False,
) -> TradeScenarioAnalysis:
    scenario_weight_source: ScenarioWeightSource | None = None
    if scenario_probabilities:
        scenario_weight_source = "macro_forecast"
    elif regime is not None and regime.scenario_probabilities:
        scenario_probabilities = dict(regime.scenario_probabilities)
        raw_source = regime.scenario_probability_source
        scenario_weight_source = raw_source if raw_source is not None else "macro_forecast"
    metrics = compute_trade_scenario_metrics(
        scores,
        scenario_set,
        scenario_probabilities=scenario_probabilities,
        scenario_weight_source=scenario_weight_source,
    )
    return TradeScenarioAnalysis(
        created_at=datetime.now(timezone.utc),
        trade_id=trade.id or trade.underlying,
        scenario_set_horizon_months=scenario_set.horizon_months,
        scenario_scores=scores,
        fallback_used=fallback_used,
        **metrics,
    )


def _neutral_fallback_analysis(
    trade: TradeIdea,
    scenario_set: ScenarioSet,
    regime: RegimeState | None = None,
    scenario_probabilities: dict[str, float] | None = None,
) -> TradeScenarioAnalysis:
    scores = [
        ScenarioScore(
            scenario_id=scenario.id,
            expected_pnl_pct=0.0,
            confidence="low",
            reasoning="LLM scoring failed; treating as neutral for this scenario.",
        )
        for scenario in scenario_set.scenarios
    ]
    return _build_analysis(
        trade=trade,
        scenario_set=scenario_set,
        scores=scores,
        regime=regime,
        scenario_probabilities=scenario_probabilities,
        fallback_used=True,
    )


def _validate_score_ids(batch: _ScenarioScoreBatch, scenario_set: ScenarioSet) -> None:
    expected = [scenario.id for scenario in scenario_set.scenarios]
    actual = [score.scenario_id for score in batch.scenario_scores]
    if actual != expected:
        raise ValueError(
            f"Scenario score ids must match scenario order. expected={expected}, actual={actual}"
        )


async def score_trade_against_scenarios(
    trade: TradeIdea,
    scenario_set: ScenarioSet,
    regime: RegimeState | None = None,
    scenario_probabilities: dict[str, float] | None = None,
) -> TradeScenarioAnalysis:
    """
    Score a TradeIdea across all scenarios in one batched LLM call.

    Never raises; on failure returns neutral fallback scores.
    """
    try:
        batch = parse_structured(
            system=SCORER_SYSTEM_PROMPT,
            user=(
                "# Trade\n"
                f"{_trade_summary(trade)}\n\n"
                "# Scenario set\n"
                f"{_scenario_summary(scenario_set)}"
            ),
            model=SCENARIO_AGENT_MODEL,
            response_schema=_ScenarioScoreBatch,
            purpose=f"scenario scoring: {trade.underlying}",
            temperature=0.3,
        )
        _validate_score_ids(batch, scenario_set)
        return _build_analysis(
            trade=trade,
            scenario_set=scenario_set,
            scores=batch.scenario_scores,
            regime=regime,
            scenario_probabilities=scenario_probabilities,
            fallback_used=False,
        )
    except Exception as exc:
        logger.warning("scenario scoring fallback for %s: %s", trade.underlying, exc)
        return _neutral_fallback_analysis(
            trade,
            scenario_set,
            regime=regime,
            scenario_probabilities=scenario_probabilities,
        )
