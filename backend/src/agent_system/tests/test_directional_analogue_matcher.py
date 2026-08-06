from __future__ import annotations

import math

import pandas as pd
import pytest

from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    AnalogueMatcherError,
    compute_pairwise_distances,
    feature_columns,
    level_feature_columns,
    load_directional_feature_library,
    match_analogues,
    pre_crisis_clustering_diagnostic,
    summarize_pairwise_distances,
    threshold_distance_from_percentile,
    trend_feature_columns,
)


def _library() -> pd.DataFrame:
    dates = [str(item) for item in pd.period_range("1999Q1", periods=16, freq="Q")]
    rows: list[dict[str, float | str]] = []
    for idx, date in enumerate(dates):
        row: dict[str, float | str] = {"as_of": date}
        for column in level_feature_columns():
            row[column] = 0.10 + idx * 0.03
        for column in trend_feature_columns():
            row[column] = 0.00
        rows.append(row)

    # Make one older date a trend analogue but not a level analogue.
    for column in trend_feature_columns():
        rows[4][column] = 2.0
        rows[11][column] = 2.0
    for column in level_feature_columns():
        rows[4][column] = 0.05
        rows[11][column] = 0.90

    # Make another older date a level analogue but not a trend analogue.
    for column in level_feature_columns():
        rows[5][column] = 0.90
    for column in trend_feature_columns():
        rows[5][column] = -2.0

    return pd.DataFrame(rows)


def test_load_directional_feature_library_validates_required_columns():
    frame = _library().drop(columns=[feature_columns()[0]])

    with pytest.raises(AnalogueMatcherError, match="missing feature columns"):
        load_directional_feature_library(frame)


def test_compute_pairwise_distances_keeps_level_and_trend_components():
    pairwise = compute_pairwise_distances(_library(), w=0.5)

    assert len(pairwise) == math.comb(16, 2)
    assert {"date_a", "date_b", "level_distance", "trend_distance", "distance"} <= set(pairwise.columns)
    assert (pairwise["level_distance"] >= 0).all()
    assert (pairwise["trend_distance"] >= 0).all()
    assert pairwise["distance"].notna().all()


def test_threshold_distance_comes_from_empirical_distribution():
    pairwise = compute_pairwise_distances(_library(), w=0.5)
    threshold = threshold_distance_from_percentile(pairwise, 10)
    summary = summarize_pairwise_distances(pairwise, w=0.5, bins=4)

    assert threshold == pytest.approx(summary.distribution["p10"])
    assert summary.n_pairs == len(pairwise)
    assert len(summary.histogram) == 4


def test_match_analogues_enforces_point_in_time_forward_buffer():
    result = match_analogues(
        "2001Q4",
        library=_library(),
        threshold_percentile=100,
        forward_buffer_quarters=4,
    )

    assert result.metadata["candidate_cutoff"] == "2000Q4"
    assert result.metadata["point_in_time_ok"] is True
    assert result.matches
    assert all(pd.Period(match.analogue_date, freq="Q") <= pd.Period("2000Q4", freq="Q") for match in result.matches)


def test_match_analogues_weight_controls_level_vs_trend_ranking():
    level_only = match_analogues(
        "2001Q4",
        library=_library(),
        w=0.0,
        threshold_percentile=100,
        forward_buffer_quarters=4,
    )
    trend_only = match_analogues(
        "2001Q4",
        library=_library(),
        w=1.0,
        threshold_percentile=100,
        forward_buffer_quarters=4,
    )

    assert level_only.matches[0].analogue_date == "2000Q2"
    assert trend_only.matches[0].analogue_date == "2000Q1"


def test_match_analogues_fails_loud_when_no_pit_candidates():
    with pytest.raises(AnalogueMatcherError, match="no point-in-time candidates"):
        match_analogues("1999Q2", library=_library(), forward_buffer_quarters=4)


def test_pre_crisis_diagnostic_reports_missing_labels_without_imputing():
    diagnostic = pre_crisis_clustering_diagnostic(
        _library(),
        pre_crisis_ranges=(("1999Q2", "1999Q3"), ("2007Q2", "2007Q4")),
        k=3,
    )

    assert diagnostic["pre_crisis_dates_present"] == ("1999Q2", "1999Q3")
    assert diagnostic["pre_crisis_dates_omitted"] == ("2007Q2", "2007Q3", "2007Q4")
    assert "summary" in diagnostic
