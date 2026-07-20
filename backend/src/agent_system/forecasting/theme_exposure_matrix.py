"""Static v1 scenario exposure matrix and ranking helpers."""
from __future__ import annotations

from collections.abc import Mapping

from src.agent_system.schemas.macro_forecast import (
    FactorForecast,
    MacroInputSignal,
    RankingContribution,
    SectorForecast,
    ThemeForecast,
    ThemeScenarioContribution,
)


THEME_LABELS: dict[str, str] = {
    "grid_power_infrastructure": "Grid and power infrastructure",
    "quality_ai": "Quality AI leaders",
    "high_beta_ai_semis": "High-beta AI semiconductors",
    "memory_semis": "Memory semiconductors",
    "energy_oil_beta": "Energy and oil beta",
    "defense_geopolitics": "Defense and geopolitics",
    "healthcare_defensives": "Healthcare defensives",
    "quality_ex_ai_cash_flow": "Quality ex-AI cash flow",
    "small_caps": "Small caps",
    "long_duration_growth": "Long-duration growth",
    "cash_short_duration": "Cash and short duration",
    "commodities_real_assets": "Commodities and real assets",
}


SCENARIO_THEME_EXPOSURES: dict[str, dict[str, float]] = {
    "reopening_soft_landing": {
        "grid_power_infrastructure": 2,
        "quality_ai": 1,
        "high_beta_ai_semis": 1,
        "memory_semis": 1,
        "energy_oil_beta": -1,
        "defense_geopolitics": 0,
        "healthcare_defensives": 0,
        "quality_ex_ai_cash_flow": 1,
        "small_caps": 2,
        "long_duration_growth": 2,
        "cash_short_duration": -1,
        "commodities_real_assets": 0,
    },
    "sticky_late_cycle_ai": {
        "grid_power_infrastructure": 3,
        "quality_ai": 3,
        "high_beta_ai_semis": 1,
        "memory_semis": 1,
        "energy_oil_beta": 1,
        "defense_geopolitics": 1,
        "healthcare_defensives": 1,
        "quality_ex_ai_cash_flow": 2,
        "small_caps": -2,
        "long_duration_growth": -1,
        "cash_short_duration": 2,
        "commodities_real_assets": 1,
    },
    "oil_inflation_tail": {
        "grid_power_infrastructure": 1,
        "quality_ai": -1,
        "high_beta_ai_semis": -2,
        "memory_semis": -1,
        "energy_oil_beta": 3,
        "defense_geopolitics": 2,
        "healthcare_defensives": 1,
        "quality_ex_ai_cash_flow": 1,
        "small_caps": -3,
        "long_duration_growth": -3,
        "cash_short_duration": 2,
        "commodities_real_assets": 3,
    },
    "late_cycle_risk_off": {
        "grid_power_infrastructure": -1,
        "quality_ai": -1,
        "high_beta_ai_semis": -3,
        "memory_semis": -2,
        "energy_oil_beta": -1,
        "defense_geopolitics": 1,
        "healthcare_defensives": 2,
        "quality_ex_ai_cash_flow": 2,
        "small_caps": -3,
        "long_duration_growth": -2,
        "cash_short_duration": 3,
        "commodities_real_assets": 1,
    },
    "ai_capex_rollover": {
        "grid_power_infrastructure": -2,
        "quality_ai": -2,
        "high_beta_ai_semis": -3,
        "memory_semis": -2,
        "energy_oil_beta": 0,
        "defense_geopolitics": 0,
        "healthcare_defensives": 1,
        "quality_ex_ai_cash_flow": 2,
        "small_caps": 1,
        "long_duration_growth": 0,
        "cash_short_duration": 1,
        "commodities_real_assets": 0,
    },
}


SECTOR_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "XLK": {"quality_ai": 0.45, "high_beta_ai_semis": 0.25, "memory_semis": 0.15, "long_duration_growth": 0.15},
    "SMH": {"high_beta_ai_semis": 0.55, "quality_ai": 0.25, "memory_semis": 0.20},
    "XLI": {"grid_power_infrastructure": 0.55, "defense_geopolitics": 0.25, "quality_ex_ai_cash_flow": 0.20},
    "XLU": {"grid_power_infrastructure": 0.65, "quality_ex_ai_cash_flow": 0.20, "cash_short_duration": 0.15},
    "XLE": {"energy_oil_beta": 0.75, "commodities_real_assets": 0.25},
    "XLV": {"healthcare_defensives": 0.75, "quality_ex_ai_cash_flow": 0.25},
    "IWM": {"small_caps": 0.80, "long_duration_growth": 0.20},
    "SHY": {"cash_short_duration": 1.00},
    "DBC": {"commodities_real_assets": 0.70, "energy_oil_beta": 0.30},
}


FACTOR_THEME_WEIGHTS: dict[str, dict[str, float]] = {
    "quality": {"quality_ai": 0.35, "quality_ex_ai_cash_flow": 0.35, "healthcare_defensives": 0.30},
    "high_beta_growth": {"high_beta_ai_semis": 0.35, "memory_semis": 0.25, "long_duration_growth": 0.25, "small_caps": 0.15},
    "duration": {"long_duration_growth": 0.70, "small_caps": 0.30},
    "defensive": {"healthcare_defensives": 0.45, "cash_short_duration": 0.35, "quality_ex_ai_cash_flow": 0.20},
    "commodities": {"commodities_real_assets": 0.55, "energy_oil_beta": 0.45},
    "cash": {"cash_short_duration": 1.00},
    "small_cap_beta": {"small_caps": 1.00},
}


def _scenario_label(scenario_id: str) -> str:
    labels = {
        "reopening_soft_landing": "Reopening / Soft Landing",
        "sticky_late_cycle_ai": "Sticky Late Cycle AI",
        "oil_inflation_tail": "Oil Inflation Tail",
        "late_cycle_risk_off": "Late Cycle Risk-Off",
        "ai_capex_rollover": "AI Capex Rollover",
    }
    return labels.get(scenario_id, scenario_id.replace("_", " ").title())


def _positioning_assessment(theme_id: str, input_signals: list[MacroInputSignal]) -> str:
    positives = 0.0
    negatives = 0.0
    for signal in input_signals:
        if signal.category != "positioning":
            continue
        for impact in signal.affected_themes:
            if impact.theme_id != theme_id:
                continue
            if impact.direction == "positive":
                positives += impact.strength * signal.confidence
            elif impact.direction == "negative":
                negatives += impact.strength * signal.confidence
    if negatives > positives and negatives >= 0.20:
        return "crowded"
    if positives > negatives and positives >= 0.20:
        return "underowned"
    if positives or negatives:
        return "neutral"
    return "unknown"


def _narrative_assessment(theme_id: str, input_signals: list[MacroInputSignal]) -> str:
    positives = 0.0
    negatives = 0.0
    for signal in input_signals:
        if signal.category not in {"narrative", "earnings"}:
            continue
        for impact in signal.affected_themes:
            if impact.theme_id != theme_id:
                continue
            if impact.direction == "positive":
                positives += impact.strength * signal.confidence
            elif impact.direction == "negative":
                negatives += impact.strength * signal.confidence
    if positives > negatives and positives >= 0.20:
        return "improving"
    if negatives > positives and negatives >= 0.20:
        return "deteriorating"
    if positives or negatives:
        return "ignored"
    return "unknown"


def _theme_contribution_summary(contributions: list[ThemeScenarioContribution]) -> str:
    if not contributions:
        return "no scenario contribution data"
    ordered = sorted(contributions, key=lambda item: abs(item.contribution), reverse=True)
    return "; ".join(
        f"{item.scenario_label} {item.contribution:+.2f}"
        for item in ordered
    )


def rank_themes(
    scenario_probabilities: Mapping[str, float],
    input_signals: list[MacroInputSignal],
) -> list[ThemeForecast]:
    """Rank themes by pure probability-weighted macro/scenario support."""

    results: list[ThemeForecast] = []
    for theme_id, label in THEME_LABELS.items():
        scenario_contribution_values: dict[str, float] = {}
        scenario_contributions: list[ThemeScenarioContribution] = []
        for scenario_id, probability in scenario_probabilities.items():
            exposure = SCENARIO_THEME_EXPOSURES.get(scenario_id, {}).get(theme_id, 0.0)
            contribution = probability * exposure
            scenario_contribution_values[scenario_id] = contribution
            scenario_contributions.append(
                ThemeScenarioContribution(
                    scenario_id=scenario_id,
                    scenario_label=_scenario_label(scenario_id),
                    scenario_probability=probability,
                    theme_exposure_score=exposure,
                    contribution=contribution,
                    rationale=(
                        f"{_scenario_label(scenario_id)} probability {probability:.1%} "
                        f"x theme exposure {exposure:+.1f}."
                    ),
                )
            )
        macro_support_score = sum(item.contribution for item in scenario_contributions)
        positive_total = sum(item.contribution for item in scenario_contributions if item.contribution > 0)
        negative_total = sum(item.contribution for item in scenario_contributions if item.contribution < 0)
        best = [
            scenario_id
            for scenario_id, _ in sorted(
                scenario_contribution_values.items(),
                key=lambda item: item[1],
                reverse=True,
            )
            if scenario_contribution_values[scenario_id] > 0
        ][:3]
        worst = [
            scenario_id
            for scenario_id, _ in sorted(
                scenario_contribution_values.items(),
                key=lambda item: item[1],
            )
            if scenario_contribution_values[scenario_id] < 0
        ][:3]
        positive_count = sum(
            1
            for scenario_id in scenario_probabilities
            if SCENARIO_THEME_EXPOSURES.get(scenario_id, {}).get(theme_id, 0.0) > 0
        )
        negative_count = sum(
            1
            for scenario_id in scenario_probabilities
            if SCENARIO_THEME_EXPOSURES.get(scenario_id, {}).get(theme_id, 0.0) < 0
        )
        positioning = _positioning_assessment(theme_id, input_signals)
        narrative_assessment = _narrative_assessment(theme_id, input_signals)
        overlay_note = (
            "Crowding, valuation, and narrative overlays are intentionally excluded from "
            "macro forecast theme rankings and are evaluated downstream at the theme/ticker "
            "research stage."
        )
        results.append(
            ThemeForecast(
                theme_id=theme_id,
                label=label,
                probability_weighted_score=macro_support_score,
                macro_score=macro_support_score,
                macro_support_score=macro_support_score,
                ranking_score=macro_support_score,
                score_method="macro_support_only",
                crowding_score=None,
                valuation_score=None,
                narrative_score=None,
                overlay_adjustment=None,
                final_score=macro_support_score,
                overlay_used_in_ranking=False,
                overlay_note=overlay_note,
                adjustment_summary=overlay_note,
                overlay_confidence="absent",
                scenario_contributions=scenario_contributions,
                positive_contribution_total=positive_total,
                negative_contribution_total=negative_total,
                net_macro_support_score=macro_support_score,
                best_scenarios=best,
                worst_scenarios=worst,
                positive_scenario_count=positive_count,
                negative_scenario_count=negative_count,
                positioning_assessment=positioning,  # type: ignore[arg-type]
                narrative_assessment=narrative_assessment,  # type: ignore[arg-type]
                rationale=(
                    f"{label} has macro support score {macro_support_score:.2f}; "
                    f"best in {', '.join(best) if best else 'no positive scenarios'} "
                    f"and worst in {', '.join(worst) if worst else 'no negative scenarios'}. "
                    f"Contribution breakdown: {_theme_contribution_summary(scenario_contributions)}."
                ),
            )
        )

    return sorted(
        results,
        key=lambda item: (item.ranking_score, item.theme_id),
        reverse=True,
    )


def _ranking_contributions(
    theme_weights: Mapping[str, float],
    theme_by_id: Mapping[str, ThemeForecast],
) -> list[RankingContribution]:
    contributions: list[RankingContribution] = []
    for theme_id, weight in theme_weights.items():
        theme = theme_by_id.get(theme_id)
        if theme is None:
            continue
        source_score = theme.ranking_score
        contribution = source_score * weight
        contributions.append(
            RankingContribution(
                source_id=theme_id,
                source_label=theme.label,
                weight=weight,
                source_score=source_score,
                contribution=contribution,
                rationale=f"{theme.label} macro support score {source_score:.2f} x weight {weight:.2f}.",
            )
        )
    return sorted(contributions, key=lambda item: abs(item.contribution), reverse=True)


def _driver_rationale(label: str, contributions: list[RankingContribution]) -> str:
    top = contributions[:3]
    if not top:
        return f"{label} score is derived from macro-supported theme scores only."
    drivers = ", ".join(
        f"{item.source_label} {item.contribution:+.2f}"
        for item in top
    )
    return f"{label} score is derived from macro-supported theme scores only. Top drivers: {drivers}."


def _weighted_sector_rankings(
    weights: Mapping[str, Mapping[str, float]],
    theme_by_id: Mapping[str, ThemeForecast],
) -> list[SectorForecast]:
    rankings: list[SectorForecast] = []
    for item_id, theme_weights in weights.items():
        contributions = _ranking_contributions(theme_weights, theme_by_id)
        score = sum(item.contribution for item in contributions)
        label = item_id
        rankings.append(
            SectorForecast(
                ticker=item_id,
                item_id=item_id,
                label=label,
                score=score,
                rationale=_driver_rationale(label, contributions),
                contributions=contributions,
                formula_notes=[
                    "sector_score = sum(theme_macro_support_score x sector_theme_weight)",
                    "Sector and factor rankings are derived from macro-supported theme scores only.",
                    "Crowding, valuation, narrative, and ticker-level fundamentals are evaluated downstream.",
                ],
            )
        )
    return sorted(rankings, key=lambda item: (item.score, item.item_id), reverse=True)


def rank_sectors(theme_rankings: list[ThemeForecast]) -> list[SectorForecast]:
    theme_by_id = {
        item.theme_id: item
        for item in theme_rankings
    }
    return _weighted_sector_rankings(SECTOR_THEME_WEIGHTS, theme_by_id)


def rank_factors(theme_rankings: list[ThemeForecast]) -> list[FactorForecast]:
    labels = {
        "quality": "Quality",
        "high_beta_growth": "High beta growth",
        "duration": "Duration sensitivity",
        "defensive": "Defensive factor",
        "commodities": "Commodity beta",
        "cash": "Cash and carry",
        "small_cap_beta": "Small-cap beta",
    }
    theme_by_id = {
        item.theme_id: item
        for item in theme_rankings
    }
    rankings: list[FactorForecast] = []
    for factor_id, theme_weights in FACTOR_THEME_WEIGHTS.items():
        contributions = _ranking_contributions(theme_weights, theme_by_id)
        score = sum(item.contribution for item in contributions)
        label = labels.get(factor_id, factor_id)
        rankings.append(
            FactorForecast(
                factor_id=factor_id,
                item_id=factor_id,
                label=label,
                score=score,
                rationale=_driver_rationale(label, contributions),
                contributions=contributions,
                formula_notes=[
                    "factor_score = sum(theme_macro_support_score x factor_theme_weight)",
                    "Sector and factor rankings are derived from macro-supported theme scores only.",
                    "Crowding, valuation, narrative, and ticker-level fundamentals are evaluated downstream.",
                ],
            )
        )
    return sorted(rankings, key=lambda item: (item.score, item.item_id), reverse=True)
