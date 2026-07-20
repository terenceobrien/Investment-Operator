"""Historical path construction and validation harness."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np
import pandas as pd
import yaml

from src.agent_system.forecasting.scenario_classifier.classifier import (
    ScenarioClassifier,
)
from src.agent_system.forecasting.scenario_classifier.data import (
    load_signature_histories,
)
from src.agent_system.forecasting.scenario_classifier.deltas import (
    BASELINE_MODES,
    parse_quarter,
    series_value,
    to_baseline_deltas,
)
from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
)


class ValidationError(RuntimeError):
    """Raised when historical validation inputs are missing or inconsistent."""


@dataclass(frozen=True)
class ValidationEpisode:
    start: str
    expected: str
    must_pass: bool = False
    note: str | None = None


@dataclass(frozen=True)
class EpisodeClassification:
    episode: ValidationEpisode
    baseline_mode: str
    assigned: str
    expected: str
    margin: float
    correct: bool
    distances: pd.DataFrame
    contributions: pd.DataFrame


def default_validation_episodes_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "validation_episodes.yaml"


def load_validation_episodes(path: str | Path | None = None) -> list[ValidationEpisode]:
    source_path = Path(path) if path is not None else default_validation_episodes_path()
    if not source_path.is_file():
        raise ValidationError(f"validation episodes config not found: {source_path}")
    with source_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or not isinstance(raw.get("episodes"), list):
        raise ValidationError(
            f"validation episodes config must contain an episodes list: {source_path}"
        )
    episodes: list[ValidationEpisode] = []
    for index, item in enumerate(raw["episodes"]):
        if not isinstance(item, dict):
            raise ValidationError(f"episode {index} must be a mapping in {source_path}")
        start = item.get("start")
        expected = item.get("expected")
        if not isinstance(start, str) or not start.strip():
            raise ValidationError(f"episode {index} missing non-empty start")
        if not isinstance(expected, str) or not expected.strip():
            raise ValidationError(f"episode {index} missing non-empty expected")
        episodes.append(
            ValidationEpisode(
                start=start.strip(),
                expected=expected.strip(),
                must_pass=bool(item.get("must_pass", False)),
                note=item.get("note") if isinstance(item.get("note"), str) else None,
            )
        )
    return episodes


def load_histories_for_classifier(
    registry: VariableRegistry,
    classifier: ScenarioClassifier,
    *,
    cache_dir: str | Path | None = None,
) -> dict[str, pd.Series]:
    return load_signature_histories(
        registry,
        variables=classifier.active_variables,
        cache_dir=cache_dir,
    )


def construct_historical_path(
    histories: dict[str, pd.Series],
    *,
    start: str,
    horizon_quarters: int,
    variables: list[str],
    baseline_mode: str,
) -> np.ndarray:
    if baseline_mode not in BASELINE_MODES:
        raise ValidationError(
            f"unknown baseline_mode '{baseline_mode}'. Valid modes: {sorted(BASELINE_MODES)}"
        )
    t0 = parse_quarter(start)
    rows: list[list[float]] = []
    for offset in range(1, horizon_quarters + 1):
        row: list[float] = []
        target_quarter = t0 + offset
        for variable in variables:
            series = histories.get(variable)
            if series is None:
                raise ValidationError(f"missing transformed history for variable '{variable}'")
            row.append(series_value(series, target_quarter, variable))
        rows.append(row)
    return to_baseline_deltas(
        np.asarray(rows, dtype=float),
        variables=variables,
        anchor_history=histories,
        anchor_quarter=t0,
        baseline_mode=baseline_mode,
    )


def classify_episode(
    classifier: ScenarioClassifier,
    histories: dict[str, pd.Series],
    episode: ValidationEpisode,
    *,
    baseline_mode: str,
) -> EpisodeClassification:
    path = construct_historical_path(
        histories,
        start=episode.start,
        horizon_quarters=classifier.scales.horizon_quarters,
        variables=classifier.active_variables,
        baseline_mode=baseline_mode,
    )
    distances = classifier.classify(path.reshape(1, *path.shape), path_ids=[episode.start])
    row = distances.iloc[0]
    assigned = str(row["assigned"])
    margin = float(row["margin"])
    contributions = classifier.variable_contributions(path)
    return EpisodeClassification(
        episode=episode,
        baseline_mode=baseline_mode,
        assigned=assigned,
        expected=episode.expected,
        margin=margin,
        correct=assigned == episode.expected,
        distances=distances,
        contributions=contributions,
    )


def run_validation(
    classifier: ScenarioClassifier,
    histories: dict[str, pd.Series],
    episodes: list[ValidationEpisode],
    *,
    baseline_modes: list[str] | None = None,
    stream: TextIO,
) -> bool:
    modes = baseline_modes or ["t0_change", "trailing_trend"]
    for mode in modes:
        if mode not in BASELINE_MODES:
            raise ValidationError(
                f"unknown baseline_mode '{mode}'. Valid modes: {sorted(BASELINE_MODES)}"
            )
    results_by_mode: dict[str, list[EpisodeClassification]] = {mode: [] for mode in modes}
    for mode in modes:
        for episode in episodes:
            results_by_mode[mode].append(
                classify_episode(
                    classifier,
                    histories,
                    episode,
                    baseline_mode=mode,
                )
            )

    for mode in modes:
        print(f"\nValidation mode: {mode}", file=stream)
        _print_episode_table(results_by_mode[mode], stream=stream)
        for result in results_by_mode[mode]:
            if not result.correct:
                print(
                    f"\nMiss: {result.episode.start} expected={result.expected} "
                    f"assigned={result.assigned}",
                    file=stream,
                )
                print_variable_contributions(
                    result.contributions,
                    scenarios=[result.expected, result.assigned],
                    stream=stream,
                )

    if "t0_change" in results_by_mode and "trailing_trend" in results_by_mode:
        print("\nMode disagreement notes:", file=stream)
        any_disagreement = False
        paired = zip(results_by_mode["t0_change"], results_by_mode["trailing_trend"])
        for left, right in paired:
            if left.assigned != right.assigned:
                any_disagreement = True
                print(
                    f"  {left.episode.start}: t0_change={left.assigned}, "
                    f"trailing_trend={right.assigned}",
                    file=stream,
                )
        if not any_disagreement:
            print("  none", file=stream)

    mode_passes: dict[str, bool] = {}
    for mode, results in results_by_mode.items():
        must_pass_ok = all(
            result.correct and result.margin > 0
            for result in results
            if result.episode.must_pass
        )
        correct_count = sum(1 for result in results if result.correct)
        mode_passes[mode] = must_pass_ok and correct_count >= 4
        print(
            f"{mode}: correct={correct_count}/{len(results)} "
            f"must_pass_ok={must_pass_ok}",
            file=stream,
        )

    passed = all(mode_passes.values())
    print(f"\nFINAL VERDICT: {'PASS' if passed else 'FAIL'}", file=stream)
    return passed


def print_distance_table(result: pd.DataFrame, *, stream: TextIO) -> None:
    print(result.to_string(index=False), file=stream)
    metadata = getattr(result, "metadata", None) or result.attrs.get("metadata", {})
    if metadata.get("warnings"):
        for warning in metadata["warnings"]:
            print(warning, file=stream)


def print_variable_contributions(
    contributions: pd.DataFrame,
    *,
    scenarios: list[str] | None = None,
    stream: TextIO,
) -> None:
    frame = contributions
    if scenarios:
        frame = frame[frame["scenario"].isin(scenarios)]
    if frame.empty:
        print("  no contribution rows", file=stream)
        return
    pivot = frame.pivot_table(
        index="variable",
        columns="scenario",
        values="contribution",
        aggfunc="sum",
    ).fillna(0.0)
    print(pivot.to_string(float_format=lambda value: f"{value:.3f}"), file=stream)


def _print_episode_table(
    results: list[EpisodeClassification],
    *,
    stream: TextIO,
) -> None:
    rows = [
        {
            "start": result.episode.start,
            "expected": result.expected,
            "assigned": result.assigned,
            "margin": result.margin,
            "correct": result.correct,
            "must_pass": result.episode.must_pass,
            "note": result.episode.note or "",
        }
        for result in results
    ]
    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False), file=stream)

