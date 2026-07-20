"""Scenario compatibility from theme exposure-vector similarity."""
from __future__ import annotations

import math

from src.agent_system.forecasting.theme_exposure_matrix import SCENARIO_THEME_EXPOSURES


def _theme_universe() -> list[str]:
    themes: set[str] = set()
    for exposures in SCENARIO_THEME_EXPOSURES.values():
        themes.update(exposures)
    return sorted(themes)


def _vector_for_scenario(scenario_id: str, themes: list[str]) -> list[float]:
    exposures = SCENARIO_THEME_EXPOSURES.get(scenario_id, {})
    return [float(exposures.get(theme, 0.0)) for theme in themes]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    numerator = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return numerator / (norm_a * norm_b)


def _build_scenario_correlation_matrix() -> dict[str, dict[str, float]]:
    themes = _theme_universe()
    vectors = {
        scenario_id: _vector_for_scenario(scenario_id, themes)
        for scenario_id in SCENARIO_THEME_EXPOSURES
    }
    matrix: dict[str, dict[str, float]] = {}
    for scenario_a, vector_a in vectors.items():
        matrix[scenario_a] = {}
        for scenario_b, vector_b in vectors.items():
            matrix[scenario_a][scenario_b] = _cosine_similarity(vector_a, vector_b)
    return matrix


SCENARIO_CORRELATION_MATRIX = _build_scenario_correlation_matrix()


def scenario_correlation_matrix() -> dict[str, dict[str, float]]:
    """Cached scenario x scenario cosine-similarity matrix."""

    return SCENARIO_CORRELATION_MATRIX


def scenario_correlation(scenario_a: str, scenario_b: str) -> float:
    return float(SCENARIO_CORRELATION_MATRIX.get(scenario_a, {}).get(scenario_b, 0.0))


def scenarios_compatible(
    scenarios_a: list[str],
    scenarios_b: list[str],
    *,
    threshold: float = 0.0,
) -> tuple[bool, float]:
    """Determine if two sets of scenario drivers are compatible.

    The returned score is the average pairwise cosine similarity across the
    supplied scenario sets. Neutral scores are treated as compatible by default.
    """

    unique_a = list(dict.fromkeys(scenarios_a))
    unique_b = list(dict.fromkeys(scenarios_b))
    if not unique_a or not unique_b:
        return True, 0.0

    scores = [
        scenario_correlation(scenario_a, scenario_b)
        for scenario_a in unique_a
        for scenario_b in unique_b
    ]
    correlation_score = sum(scores) / len(scores) if scores else 0.0
    if correlation_score < -abs(threshold):
        return False, correlation_score
    return True, correlation_score
