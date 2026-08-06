"""Taxonomy-aware scenario exposure matrices and ranking helpers."""
from __future__ import annotations

import csv
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
    default_behavioral_scenarios_path,
    load_behavioral_scenarios,
)
from src.agent_system.schemas.macro_forecast import (
    FactorForecast,
    MacroInputSignal,
    RankingContribution,
    SectorForecast,
    ThemeForecast,
    ThemeScenarioContribution,
)


logger = logging.getLogger(__name__)


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


SCENARIO_THEME_EXPOSURES_NARRATIVE: dict[str, dict[str, float]] = {
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
        "quality_ai": 2,
        "high_beta_ai_semis": 3,
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


# Backward-compatible alias for legacy narrative callers.
SCENARIO_THEME_EXPOSURES = SCENARIO_THEME_EXPOSURES_NARRATIVE


def _reference_data_root() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "reference"


def _scenario_theme_returns_path() -> Path:
    return _reference_data_root() / "scenario_theme_returns.csv"


def _theme_label(theme_id: str) -> str:
    return THEME_LABELS.get(theme_id) or theme_id.replace("_", " ").title()


def _return_to_exposure(expected_return: float) -> float:
    """Map 63-day expected returns to the legacy -3..+3 exposure scale.

    The narrative matrix uses coarse directional scores. Behavioral exposures
    keep that convention by bucketing calibrated expected returns:
    >=6% -> +3, >=3% -> +2, >=1% -> +1, between -1% and +1% -> 0,
    <=-6% -> -3, <=-3% -> -2, <=-1% -> -1.
    """

    if expected_return >= 0.06:
        return 3.0
    if expected_return >= 0.03:
        return 2.0
    if expected_return >= 0.01:
        return 1.0
    if expected_return > -0.01:
        return 0.0
    if expected_return > -0.03:
        return -1.0
    if expected_return > -0.06:
        return -2.0
    return -3.0


# Hand-authored behavioral exposures for legacy macro-cyclical themes that the
# analogue-calibrated CSV does not yet cover. These preserve theme signal for
# high-information macro exposures while keeping provenance honest:
# - energy_oil_beta: oil/energy beta wins in inflation/stagflation shocks, lags
#   in demand-destruction scares and credit recessions.
# - defense_geopolitics: supply-shock/geopolitical regimes support defense;
#   recessions give it a mild defensive bid, while clean expansion is neutral.
# - commodities_real_assets: inflation and stagflation support real assets;
#   growth/credit scares hurt demand-sensitive commodities despite gold safety.
# - healthcare_defensives: underperforms risk-on expansions, gains defensive bid
#   in weak-growth, credit, and stagflation outcomes.
# - memory_semis: cyclical/AI beta works in benign expansion, but is punished in
#   inflation shocks and recessionary paths.
HAND_AUTHORED_BEHAVIORAL_THEME_EXPOSURES: dict[str, dict[str, float]] = {
    "expansion_disinflation": {
        "commodities_real_assets": 0.0,
        "defense_geopolitics": 0.0,
        "energy_oil_beta": -1.0,
        "healthcare_defensives": -1.0,
        "memory_semis": 2.0,
    },
    "late_cycle_expansion": {
        "commodities_real_assets": 1.0,
        "defense_geopolitics": 1.0,
        "energy_oil_beta": 1.0,
        "healthcare_defensives": -1.0,
        "memory_semis": 2.0,
    },
    "inflation_shock": {
        "commodities_real_assets": 3.0,
        "defense_geopolitics": 2.0,
        "energy_oil_beta": 3.0,
        "healthcare_defensives": 1.0,
        "memory_semis": -2.0,
    },
    "stagflation": {
        "commodities_real_assets": 2.0,
        "defense_geopolitics": 2.0,
        "energy_oil_beta": 3.0,
        "healthcare_defensives": 2.0,
        "memory_semis": -3.0,
    },
    "growth_scare_no_credit": {
        "commodities_real_assets": -2.0,
        "defense_geopolitics": 1.0,
        "energy_oil_beta": -2.0,
        "healthcare_defensives": 2.0,
        "memory_semis": -2.0,
    },
    "credit_led_recession": {
        "commodities_real_assets": -2.0,
        "defense_geopolitics": 1.0,
        "energy_oil_beta": -3.0,
        "healthcare_defensives": 2.0,
        "memory_semis": -3.0,
    },
}


def _load_csv_behavioral_exposures() -> tuple[dict[str, dict[str, float]], set[str]]:
    path = _scenario_theme_returns_path()
    if not path.is_file():
        raise FileNotFoundError(f"behavioral scenario theme returns CSV not found: {path}")
    matrix: dict[str, dict[str, float]] = {
        scenario_id: {}
        for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS
    }
    themes: set[str] = set()
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"scenario_id", "theme_id", "expected_return"}
        missing_columns = required - set(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(
                f"{path} missing required columns: {sorted(missing_columns)}"
            )
        for row in reader:
            scenario_id = str(row.get("scenario_id") or "")
            theme_id = str(row.get("theme_id") or "")
            if scenario_id not in matrix or not theme_id:
                continue
            expected_return = float(row["expected_return"])
            matrix[scenario_id][theme_id] = _return_to_exposure(expected_return)
            themes.add(theme_id)
    return matrix, themes


def _reconcile_behavioral_exposures(
    matrix: dict[str, dict[str, float]],
    csv_themes: set[str],
) -> dict[str, Any]:
    narrative_themes = {
        theme
        for exposures in SCENARIO_THEME_EXPOSURES_NARRATIVE.values()
        for theme in exposures
    }
    conflicts: list[dict[str, Any]] = []
    yaml_only_fallbacks: list[dict[str, Any]] = []
    try:
        scenarios = load_behavioral_scenarios(default_behavioral_scenarios_path())
    except Exception as exc:
        logger.warning("Could not reconcile behavioral scenario YAML exposures: %s", exc)
        scenarios = {}
    for scenario_id, scenario in scenarios.items():
        scenario_exposures = matrix.setdefault(scenario_id, {})
        for theme_id in scenario.preferred_exposures:
            current = scenario_exposures.get(theme_id)
            if current is None:
                scenario_exposures[theme_id] = 2.0
                yaml_only_fallbacks.append(
                    {"scenario_id": scenario_id, "theme_id": theme_id, "designation": "preferred"}
                )
            elif current < 0:
                conflicts.append(
                    {
                        "scenario_id": scenario_id,
                        "theme_id": theme_id,
                        "yaml_designation": "preferred",
                        "csv_exposure": current,
                    }
                )
        for theme_id in scenario.vulnerable_exposures:
            current = scenario_exposures.get(theme_id)
            if current is None:
                scenario_exposures[theme_id] = -2.0
                yaml_only_fallbacks.append(
                    {"scenario_id": scenario_id, "theme_id": theme_id, "designation": "vulnerable"}
                )
            elif current > 0:
                conflicts.append(
                    {
                        "scenario_id": scenario_id,
                        "theme_id": theme_id,
                        "yaml_designation": "vulnerable",
                        "csv_exposure": current,
                    }
                )
    final_themes = {
        theme
        for exposures in matrix.values()
        for theme in exposures
    }
    hand_authored_themes = sorted(
        {
            theme
            for exposures in HAND_AUTHORED_BEHAVIORAL_THEME_EXPOSURES.values()
            for theme in exposures
        }
    )
    return {
        "missing_narrative_theme_coverage": sorted(narrative_themes - final_themes),
        "csv_missing_hand_authored_themes": sorted(
            theme for theme in hand_authored_themes if theme not in csv_themes
        ),
        "csv_yaml_sign_conflicts": conflicts,
        "yaml_only_fallbacks": yaml_only_fallbacks,
        "csv_theme_count": len(csv_themes),
        "hand_authored_themes": hand_authored_themes,
    }


def _apply_hand_authored_behavioral_exposures(
    matrix: dict[str, dict[str, float]],
) -> None:
    for scenario_id, exposures in HAND_AUTHORED_BEHAVIORAL_THEME_EXPOSURES.items():
        if scenario_id not in matrix:
            raise ValueError(
                f"hand-authored exposure scenario {scenario_id!r} is not a behavioral scenario"
            )
        for theme_id, exposure in exposures.items():
            matrix[scenario_id][theme_id] = float(exposure)


def _build_theme_exposure_source(csv_themes: set[str]) -> dict[str, str]:
    source = {theme_id: "calibrated" for theme_id in csv_themes}
    for exposures in HAND_AUTHORED_BEHAVIORAL_THEME_EXPOSURES.values():
        for theme_id in exposures:
            source[theme_id] = "hand_authored"
    return source


def _build_behavioral_exposure_matrix() -> tuple[dict[str, dict[str, float]], dict[str, Any], dict[str, str]]:
    matrix, csv_themes = _load_csv_behavioral_exposures()
    _apply_hand_authored_behavioral_exposures(matrix)
    reconciliation = _reconcile_behavioral_exposures(matrix, csv_themes)
    return matrix, reconciliation, _build_theme_exposure_source(csv_themes)


SCENARIO_THEME_EXPOSURES_BEHAVIORAL, BEHAVIORAL_EXPOSURE_RECONCILIATION, THEME_EXPOSURE_SOURCE = (
    _build_behavioral_exposure_matrix()
)


def behavioral_exposure_reconciliation_report() -> str:
    """Human-readable CSV-vs-YAML reconciliation report for operator review."""

    missing = BEHAVIORAL_EXPOSURE_RECONCILIATION["missing_narrative_theme_coverage"]
    hand_authored = BEHAVIORAL_EXPOSURE_RECONCILIATION["hand_authored_themes"]
    csv_missing_hand_authored = BEHAVIORAL_EXPOSURE_RECONCILIATION[
        "csv_missing_hand_authored_themes"
    ]
    conflicts = BEHAVIORAL_EXPOSURE_RECONCILIATION["csv_yaml_sign_conflicts"]
    fallbacks = BEHAVIORAL_EXPOSURE_RECONCILIATION["yaml_only_fallbacks"]
    lines = [
        "Behavioral exposure reconciliation",
        f"- CSV themes: {BEHAVIORAL_EXPOSURE_RECONCILIATION['csv_theme_count']}",
        f"- Narrative themes without final behavioral coverage: {missing or 'none'}",
        f"- Hand-authored themes: {hand_authored or 'none'}",
        f"- Hand-authored because CSV lacked coverage: {csv_missing_hand_authored or 'none'}",
        f"- CSV/YAML sign conflicts: {len(conflicts)}",
    ]
    for item in conflicts:
        lines.append(
            "  "
            f"{item['scenario_id']} / {item['theme_id']}: "
            f"yaml={item['yaml_designation']} csv_exposure={item['csv_exposure']:+.1f}"
        )
    lines.append(f"- YAML-only exposure fallbacks: {len(fallbacks)}")
    for item in fallbacks:
        lines.append(
            "  "
            f"{item['scenario_id']} / {item['theme_id']}: {item['designation']}"
        )
    return "\n".join(lines)


def print_behavioral_exposure_reconciliation_report() -> None:
    print(behavioral_exposure_reconciliation_report())


def get_scenario_theme_exposures(taxonomy: str = "behavioral_v1") -> dict[str, dict[str, float]]:
    if taxonomy == "behavioral_v1":
        return SCENARIO_THEME_EXPOSURES_BEHAVIORAL
    if taxonomy == "narrative_v0":
        return SCENARIO_THEME_EXPOSURES_NARRATIVE
    raise ValueError(
        "scenario theme exposure taxonomy must be 'narrative_v0' or 'behavioral_v1'; "
        f"got {taxonomy!r}"
    )


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


def _behavioral_scenario_labels() -> dict[str, str]:
    try:
        return {
            scenario_id: scenario.label
            for scenario_id, scenario in load_behavioral_scenarios(
                default_behavioral_scenarios_path()
            ).items()
        }
    except Exception:
        return {}


def _scenario_label(scenario_id: str, taxonomy: str = "behavioral_v1") -> str:
    narrative_labels = {
        "reopening_soft_landing": "Reopening / Soft Landing",
        "sticky_late_cycle_ai": "Sticky Late Cycle AI",
        "oil_inflation_tail": "Oil Inflation Tail",
        "late_cycle_risk_off": "Late Cycle Risk-Off",
        "ai_capex_rollover": "AI Capex Rollover",
    }
    if taxonomy == "behavioral_v1":
        return _behavioral_scenario_labels().get(
            scenario_id,
            scenario_id.replace("_", " ").title(),
        )
    return narrative_labels.get(scenario_id, scenario_id.replace("_", " ").title())


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
    *,
    taxonomy: str = "behavioral_v1",
) -> list[ThemeForecast]:
    """Rank themes by pure probability-weighted macro/scenario support."""

    results: list[ThemeForecast] = []
    exposure_matrix = get_scenario_theme_exposures(taxonomy)
    missing = sorted(set(scenario_probabilities) - set(exposure_matrix))
    if missing:
        raise ValueError(
            f"scenario probabilities contain ids missing from {taxonomy} exposure matrix: {missing}"
        )
    theme_ids = sorted(
        {
            theme_id
            for exposures in exposure_matrix.values()
            for theme_id in exposures
        }
    )
    for theme_id in theme_ids:
        label = _theme_label(theme_id)
        scenario_contribution_values: dict[str, float] = {}
        scenario_contributions: list[ThemeScenarioContribution] = []
        for scenario_id, probability in scenario_probabilities.items():
            exposure = exposure_matrix[scenario_id].get(theme_id, 0.0)
            contribution = probability * exposure
            scenario_contribution_values[scenario_id] = contribution
            scenario_contributions.append(
                ThemeScenarioContribution(
                    scenario_id=scenario_id,
                    scenario_label=_scenario_label(scenario_id, taxonomy),
                    scenario_probability=probability,
                    theme_exposure_score=exposure,
                    contribution=contribution,
                    rationale=(
                        f"{_scenario_label(scenario_id, taxonomy)} probability {probability:.1%} "
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
            if exposure_matrix[scenario_id].get(theme_id, 0.0) > 0
        )
        negative_count = sum(
            1
            for scenario_id in scenario_probabilities
            if exposure_matrix[scenario_id].get(theme_id, 0.0) < 0
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
