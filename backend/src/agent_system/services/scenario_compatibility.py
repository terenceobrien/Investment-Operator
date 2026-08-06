"""Scenario compatibility from theme exposure-vector similarity."""
from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
)
from src.agent_system.forecasting.theme_exposure_matrix import get_scenario_theme_exposures


def _infer_taxonomy(scenario_ids: list[str]) -> str | None:
    scenario_set = set(scenario_ids)
    if not scenario_set:
        return None
    narrative_ids = set(get_scenario_theme_exposures("narrative_v0"))
    behavioral_ids = set(EXPECTED_BEHAVIORAL_SCENARIO_IDS)
    if scenario_set <= narrative_ids:
        return "narrative_v0"
    if scenario_set <= behavioral_ids:
        return "behavioral_v1"
    return None


def _theme_universe(taxonomy: str) -> list[str]:
    themes: set[str] = set()
    for exposures in get_scenario_theme_exposures(taxonomy).values():
        themes.update(exposures)
    return sorted(themes)


def _vector_for_scenario(scenario_id: str, themes: list[str], taxonomy: str) -> list[float]:
    exposures = get_scenario_theme_exposures(taxonomy).get(scenario_id, {})
    return [float(exposures.get(theme, 0.0)) for theme in themes]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    numerator = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return numerator / (norm_a * norm_b)


def _build_scenario_correlation_matrix(taxonomy: str) -> dict[str, dict[str, float]]:
    exposure_matrix = get_scenario_theme_exposures(taxonomy)
    themes = _theme_universe(taxonomy)
    vectors = {
        scenario_id: _vector_for_scenario(scenario_id, themes, taxonomy)
        for scenario_id in exposure_matrix
    }
    matrix: dict[str, dict[str, float]] = {}
    for scenario_a, vector_a in vectors.items():
        matrix[scenario_a] = {}
        for scenario_b, vector_b in vectors.items():
            matrix[scenario_a][scenario_b] = _cosine_similarity(vector_a, vector_b)
    return matrix


@lru_cache(maxsize=None)
def _cached_scenario_correlation_matrix(taxonomy: str) -> dict[str, dict[str, float]]:
    return _build_scenario_correlation_matrix(taxonomy)


class _LazyCorrelationMatrix(Mapping):
    def __init__(self, taxonomy: str):
        self._taxonomy = taxonomy

    def _data(self) -> dict[str, dict[str, float]]:
        return _cached_scenario_correlation_matrix(self._taxonomy)

    def __getitem__(self, key: str) -> dict[str, float]:
        return self._data()[key]

    def __iter__(self):
        return iter(self._data())

    def __len__(self) -> int:
        return len(self._data())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._taxonomy!r})"


SCENARIO_CORRELATION_MATRIX_NARRATIVE = _cached_scenario_correlation_matrix("narrative_v0")
SCENARIO_CORRELATION_MATRIX_BEHAVIORAL: Mapping[str, dict[str, float]] = _LazyCorrelationMatrix("behavioral_v1")

# Backward-compatible alias for legacy narrative callers.
SCENARIO_CORRELATION_MATRIX = SCENARIO_CORRELATION_MATRIX_NARRATIVE


def scenario_correlation_matrix(
    taxonomy: str = "narrative_v0",
) -> dict[str, dict[str, float]]:
    """Cached scenario x scenario cosine-similarity matrix."""

    if taxonomy == "narrative_v0":
        return SCENARIO_CORRELATION_MATRIX_NARRATIVE
    if taxonomy == "behavioral_v1":
        return _cached_scenario_correlation_matrix("behavioral_v1")
    raise ValueError(
        "scenario compatibility taxonomy must be 'narrative_v0' or 'behavioral_v1'; "
        f"got {taxonomy!r}"
    )


def scenario_correlation(
    scenario_a: str,
    scenario_b: str,
    *,
    taxonomy: str | None = None,
) -> float:
    resolved_taxonomy = taxonomy or _infer_taxonomy([scenario_a, scenario_b])
    if resolved_taxonomy is None:
        return 0.0
    matrix = scenario_correlation_matrix(resolved_taxonomy)
    return float(matrix.get(scenario_a, {}).get(scenario_b, 0.0))


def scenarios_compatible(
    scenarios_a: list[str],
    scenarios_b: list[str],
    *,
    taxonomy: str | None = None,
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
    resolved_taxonomy = taxonomy or _infer_taxonomy(unique_a + unique_b)
    if resolved_taxonomy is None:
        return True, 0.0

    scores = [
        scenario_correlation(scenario_a, scenario_b, taxonomy=resolved_taxonomy)
        for scenario_a in unique_a
        for scenario_b in unique_b
    ]
    correlation_score = sum(scores) / len(scores) if scores else 0.0
    if correlation_score < -abs(threshold):
        return False, correlation_score
    return True, correlation_score
