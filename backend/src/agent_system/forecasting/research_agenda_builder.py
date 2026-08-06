"""Deterministic research agenda generation from macro theme forecasts."""
from __future__ import annotations

import logging
from typing import Mapping

from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.macro_forecast import (
    ResearchPriorityRecommendation,
    ScenarioProbabilityUpdate,
    ThemeForecast,
)
from src.agent_system.schemas.regime import EdgeDecayHorizon, RegimeState
from src.state.config_loader import RESEARCH_PRIORITY_EXCLUSIONS


logger = logging.getLogger(__name__)
_LOGGED_RESEARCH_PRIORITY_EXCLUSIONS: set[str] = set()


def _scenario_label(theme: ThemeForecast, scenarios: list[str]) -> str:
    if not scenarios:
        return "no single dominant scenario"
    labels = {
        contribution.scenario_id: contribution.scenario_label
        for contribution in theme.scenario_contributions
    }
    return ", ".join(labels.get(scenario, scenario.replace("_", " ").title()) for scenario in scenarios)


def _top_scenario_summary(scenario_updates: list[ScenarioProbabilityUpdate]) -> str:
    top = sorted(
        scenario_updates,
        key=lambda item: item.posterior_probability,
        reverse=True,
    )[:3]
    return ", ".join(
        f"{item.scenario_id} {item.posterior_probability:.0%}"
        for item in top
    )


def _top_probability_summary(scenario_probabilities: Mapping[str, float] | None) -> str:
    if not scenario_probabilities:
        return ""
    top = sorted(
        ((str(key), float(value)) for key, value in scenario_probabilities.items()),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    return ", ".join(f"{scenario_id} {probability:.0%}" for scenario_id, probability in top)


def _top_theme_contribution_summary(theme: ThemeForecast) -> str:
    contributions = sorted(
        theme.scenario_contributions,
        key=lambda item: abs(item.contribution),
        reverse=True,
    )[:3]
    if not contributions:
        return "none"
    return ",".join(
        f"{item.scenario_id}={item.contribution:+.3f}"
        for item in contributions
    )


def _evidence(
    theme: ThemeForecast,
    scenario_updates: list[ScenarioProbabilityUpdate],
    scenario_probabilities: Mapping[str, float] | None = None,
) -> DerivedEvidence:
    top_scenarios = _top_scenario_summary(scenario_updates) or _top_probability_summary(
        scenario_probabilities
    )
    return DerivedEvidence(
        claim=f"{theme.label} has a positive macro support score.",
        supports=True,
        computation="Static scenario/theme exposure score multiplied by updated scenario probabilities.",
        upstream_claims=[
            f"theme_id={theme.theme_id}",
            f"macro_support_score={theme.macro_support_score:.3f}",
            f"top_scenario_contributions={_top_theme_contribution_summary(theme)}",
            f"best_scenarios={','.join(theme.best_scenarios) or 'none'}",
            f"worst_scenarios={','.join(theme.worst_scenarios) or 'none'}",
            f"top_scenarios={top_scenarios or 'none'}",
        ],
    )


def _grid_priority(theme: ThemeForecast, scenario_updates: list[ScenarioProbabilityUpdate]) -> tuple[str, str, str, list[str]]:
    best = _scenario_label(theme, theme.best_scenarios)
    worst = _scenario_label(theme, theme.worst_scenarios)
    title = "Second-order grid and power infrastructure beneficiaries with cross-scenario support"
    rationale = (
        f"Grid/power ranks highly because it has positive macro support across {best}. "
        "Research should now test whether the best expressions are obvious AI-grid leaders or "
        "less-obvious second-order beneficiaries. Crowding, valuation, and narrative maturity should "
        f"be evaluated downstream. Worst scenarios to underwrite: {worst}."
    )
    edge = (
        "Macro support for grid and power infrastructure may create attractive research paths, but "
        "the edge depends on finding specific suppliers, service providers, or infrastructure names "
        "where ownership, valuation, revisions, and narrative maturity still leave room for upside."
    )
    questions = [
        "Which names have direct but under-discussed data-center, grid, or power exposure?",
        "Which names have positive estimate revision potential without extreme AI-infrastructure crowding?",
        "Which names remain resilient if AI capex continues but rates stay restrictive?",
        "Which names would fail if AI capex rollover probability rises?",
    ]
    return title, rationale, edge, questions


def _quality_ex_ai_priority(theme: ThemeForecast, scenario_updates: list[ScenarioProbabilityUpdate]) -> tuple[str, str, str, list[str]]:
    best = _scenario_label(theme, theme.best_scenarios)
    title = "Quality ex-AI cash-flow compounders with soft-landing and sticky-cycle resilience"
    rationale = (
        f"Quality ex-AI ranks highly because it performs well across {best}. Downstream research should "
        "test whether specific names are genuinely under-owned, attractively valued, and supported by revisions."
    )
    edge = (
        "Macro support may favor high-ROIC cash-generative businesses outside explicit AI leadership, "
        "but the actionable edge depends on downstream proof of under-ownership, valuation support, "
        "and durable estimate revisions."
    )
    questions = [
        "Which non-AI cash-flow compounders have positive estimate revision potential?",
        "Where are balance-sheet quality and free-cash-flow durability mispriced versus AI-led scarcity names?",
        "Which candidates still work if policy stays restrictive and broad beta remains uneven?",
        "Which names have hidden cyclicality that would fail in a late-cycle risk-off scenario?",
    ]
    return title, rationale, edge, questions


def _quality_ai_priority(theme: ThemeForecast, scenario_updates: list[ScenarioProbabilityUpdate]) -> tuple[str, str, str, list[str]]:
    best = _scenario_label(theme, theme.best_scenarios)
    title = "Quality AI leaders with downside discipline under capex-rollover tails"
    rationale = (
        f"Quality AI ranks highly because AI earnings resilience supports {best}. Downstream research should "
        "distinguish quality leaders with durable estimate support from crowded high-beta expressions."
    )
    edge = (
        "AI leadership remains supported, but the highest-EV expressions may be quality leaders with "
        "estimate support and lower downside asymmetry rather than high-beta crowded semis."
    )
    questions = [
        "Which AI leaders have estimate support that is not solely multiple expansion?",
        "Which names have the least downside asymmetry if capex rollover odds rise?",
        "Where does valuation still leave room for positive revisions?",
        "Which crowded AI expressions should be avoided despite positive macro fit?",
    ]
    return title, rationale, edge, questions


def _fallback_priority(theme: ThemeForecast, scenario_updates: list[ScenarioProbabilityUpdate]) -> tuple[str, str, str, list[str]]:
    best = _scenario_label(theme, theme.best_scenarios)
    worst = _scenario_label(theme, theme.worst_scenarios)
    title = f"{theme.label} candidates with explicit scenario asymmetry tests"
    rationale = (
        f"{theme.label} has a positive macro support score with support from {best}. "
        f"Research should focus on instruments that keep downside manageable in {worst}, then test "
        "crowding, valuation, narrative maturity, and bottom-up quality downstream."
    )
    edge = (
        f"The market may be underpricing {theme.label.lower()} exposures that benefit from the current "
        "scenario mix while retaining acceptable downside in the least favorable macro paths."
    )
    questions = [
        f"Which instruments provide the cleanest exposure to {theme.label}?",
        "Where do valuation and positioning leave room for upside rather than only macro beta?",
        f"What breaks the thesis in {worst}?",
    ]
    return title, rationale, edge, questions


def _template_for_theme(
    theme: ThemeForecast,
    scenario_updates: list[ScenarioProbabilityUpdate],
) -> tuple[str, str, str, list[str]]:
    if theme.theme_id == "grid_power_infrastructure":
        return _grid_priority(theme, scenario_updates)
    if theme.theme_id == "quality_ex_ai_cash_flow":
        return _quality_ex_ai_priority(theme, scenario_updates)
    if theme.theme_id == "quality_ai":
        return _quality_ai_priority(theme, scenario_updates)
    return _fallback_priority(theme, scenario_updates)


def build_research_priorities_from_theme_forecasts(
    theme_forecasts: list[ThemeForecast],
    scenario_updates: list[ScenarioProbabilityUpdate],
    regime_state: RegimeState,
    max_priorities: int = 3,
    source_macro_forecast_id: str | None = None,
    scenario_probabilities: Mapping[str, float] | None = None,
) -> list[ResearchPriorityRecommendation]:
    """Convert top macro-supported theme forecasts into deterministic research priorities."""

    ranked_positive_themes = sorted(
        [
            theme
            for theme in theme_forecasts
            if theme.ranking_score > 0
        ],
        key=lambda theme: theme.ranking_score,
        reverse=True,
    )
    eligible_themes: list[ThemeForecast] = []
    for theme in ranked_positive_themes:
        if theme.theme_id in RESEARCH_PRIORITY_EXCLUSIONS:
            reason = RESEARCH_PRIORITY_EXCLUSIONS[theme.theme_id]
            log_key = f"{theme.theme_id}:{reason}"
            if log_key not in _LOGGED_RESEARCH_PRIORITY_EXCLUSIONS:
                logger.warning(
                    "Research priority exclusion applied: %s (%s) skipped - %s",
                    theme.theme_id,
                    theme.label,
                    reason or "no reason provided",
                )
                _LOGGED_RESEARCH_PRIORITY_EXCLUSIONS.add(log_key)
            continue
        eligible_themes.append(theme)

    top_themes = eligible_themes[:max_priorities]
    regime_context = (
        f"Current regime: {regime_state.regime_label}. "
        f"Key drivers: {', '.join(driver.name for driver in regime_state.key_drivers[:3]) or 'not specified'}."
    )

    priorities: list[ResearchPriorityRecommendation] = []
    for rank, theme in enumerate(top_themes, 1):
        title, rationale, edge, questions = _template_for_theme(theme, scenario_updates)
        priorities.append(
            ResearchPriorityRecommendation(
                theme=title,
                rationale=f"{rationale} {regime_context}",
                edge_hypothesis=edge,
                sub_questions=questions,
                priority_rank=rank,
                expected_edge_decay=EdgeDecayHorizon.QUARTERS,
                supporting_evidence=[_evidence(theme, scenario_updates, scenario_probabilities)],
                source_theme_id=theme.theme_id,
                source_scenario_ids=list(theme.best_scenarios[:3]),
                source_macro_forecast_id=source_macro_forecast_id,
            )
        )
    return priorities
