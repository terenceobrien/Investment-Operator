from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.agent_system.forecasting.scenario_classifier import forward_outcomes
from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    AnalogueMatch,
    AnalogueMatchResult,
    level_feature_columns,
    trend_feature_columns,
)
from src.agent_system.forecasting.scenario_classifier.forward_outcomes import (
    compute_forward_outcome_results,
    compute_metric_summary,
    compute_neighbor_recession_share,
    eligible_query_dates,
    shrink_neighbor_share,
    spearman_rank_correlation,
)


def _library(start: str = "2006Q1", periods: int = 44) -> pd.DataFrame:
    dates = [str(item) for item in pd.period_range(start, periods=periods, freq="Q")]
    rows: list[dict[str, float | str]] = []
    for idx, date in enumerate(dates):
        row: dict[str, float | str] = {"as_of": date}
        for column in level_feature_columns():
            row[column] = float(idx)
        for column in trend_feature_columns():
            row[column] = float(idx) / 10.0
        rows.append(row)
    return pd.DataFrame(rows)


def _credit_spread(start: str = "2006Q1", periods: int = 44) -> pd.Series:
    index = pd.period_range(start, periods=periods, freq="Q")
    return pd.Series(np.arange(periods, dtype=float), index=index)


def test_eligible_query_dates_respects_max_date_minus_horizon():
    dates = eligible_query_dates(_library(), horizon=8)

    assert dates[0] == pd.Period("2007Q1", freq="Q")
    assert dates[-1] == pd.Period("2014Q4", freq="Q")


def test_neighbor_recession_share_scores_recession_bound_and_benign(monkeypatch):
    def fake_match(query_date, **_kwargs):
        query = str(pd.Period(query_date, freq="Q"))
        if query == "2008Q1":
            matches = (
                AnalogueMatch("2006Q3", 0.1, 0.1, 0.1, 0.25),
                AnalogueMatch("2006Q4", 0.1, 0.1, 0.1, 0.75),
            )
        elif query == "2014Q1":
            matches = (
                AnalogueMatch("2011Q4", 0.1, 0.1, 0.1, 0.4),
                AnalogueMatch("2012Q1", 0.1, 0.1, 0.1, 0.6),
            )
        else:
            matches = tuple()
        return AnalogueMatchResult(query, matches, {})

    monkeypatch.setattr(forward_outcomes, "match_analogues", fake_match)

    results = compute_forward_outcome_results(
        _library(),
        horizon=8,
        min_pool=1,
        credit_spread_series=_credit_spread(),
    )

    recession_bound = results.loc[results["query_date"] == "2008Q1"].iloc[0]
    benign = results.loc[results["query_date"] == "2014Q1"].iloc[0]
    assert recession_bound.status == "ok"
    assert recession_bound.neighbor_recession_share_in_sample_raw == pytest.approx(1.0)
    assert benign.status == "ok"
    assert benign.neighbor_recession_share_in_sample_raw == pytest.approx(0.0)


def test_empty_match_set_records_unprecedented_without_raising(monkeypatch):
    def fake_match(query_date, **_kwargs):
        query = str(pd.Period(query_date, freq="Q"))
        return AnalogueMatchResult(query, tuple(), {})

    monkeypatch.setattr(forward_outcomes, "match_analogues", fake_match)

    results = compute_forward_outcome_results(
        _library(),
        horizon=8,
        min_pool=1,
        credit_spread_series=_credit_spread(),
    )

    assert "unprecedented_state" in set(results["status"])
    assert "no_matches" not in set(results["status"])
    row = results.loc[results["status"] == "unprecedented_state"].iloc[0]
    assert row.n_matches == 0
    assert pd.isna(row.neighbor_recession_share_in_sample_raw)


def test_manual_spearman_uses_average_ranks():
    value = spearman_rank_correlation([10, 20, 20, 40], [1, 4, 2, 3])

    assert value == pytest.approx(0.6324555320336759)


def test_pit_observable_drops_unresolved_neighbor_but_in_sample_keeps_it(monkeypatch):
    def fake_match(query_date, **_kwargs):
        query = str(pd.Period(query_date, freq="Q"))
        if query == "2008Q4":
            matches = (
                AnalogueMatch("2007Q4", 0.1, 0.1, 0.1, 1.0),
                AnalogueMatch("1995Q1", 0.1, 0.1, 0.1, 1.0),
            )
        else:
            matches = tuple()
        return AnalogueMatchResult(query, matches, {})

    monkeypatch.setattr(forward_outcomes, "match_analogues", fake_match)

    results = compute_forward_outcome_results(
        _library(start="1995Q1", periods=96),
        horizon=8,
        min_pool=1,
        credit_spread_series=_credit_spread(start="1995Q1", periods=96),
    )

    row = results.loc[results["query_date"] == "2008Q4"].iloc[0]
    assert row.neighbor_recession_share_in_sample_raw == pytest.approx(0.5)
    assert row.neighbor_recession_share_pit_observable_raw == pytest.approx(0.0)
    assert row.dropped_unresolved_count == 1
    assert row.evaluable_neighbor_count_pit_observable == 1


def test_pit_observable_filters_unresolved_neighbor_before_recession_call(monkeypatch):
    calls: list[str] = []

    def raising_recession_within(quarter, horizon, *, max_known_quarter=None):
        calls.append(str(pd.Period(quarter, freq="Q")))
        if str(pd.Period(quarter, freq="Q")) == "2007Q4":
            raise AssertionError("unresolved neighbor should not be evaluated")
        return False

    monkeypatch.setattr(forward_outcomes, "recession_within", raising_recession_within)
    result = compute_neighbor_recession_share(
        [AnalogueMatch("2007Q4", 0.1, 0.1, 0.1, 1.0)],
        query="2008Q4",
        horizon=8,
        max_known_quarter="2012Q4",
        mode="pit_observable",
    )

    assert result["dropped_unresolved_count"] == 1
    assert result["evaluable_neighbor_count"] == 0
    assert pd.isna(result["share_raw"])
    assert calls == []


def test_share_shrunk_matches_hand_computed_value_and_limits():
    value = shrink_neighbor_share(
        1.0,
        2.0,
        base_rate=0.25,
        prior_strength=3.0,
    )

    assert value == pytest.approx((2.0 * 1.0 + 3.0 * 0.25) / 5.0)
    assert shrink_neighbor_share(0.75, 0.0, base_rate=0.25, prior_strength=3.0) == pytest.approx(0.25)
    assert shrink_neighbor_share(0.75, 1_000_000.0, base_rate=0.25, prior_strength=3.0) == pytest.approx(0.75, rel=1e-5)


def test_insufficient_pool_and_unprecedented_state_are_not_metric_inputs(monkeypatch):
    def fake_match(query_date, **_kwargs):
        query = str(pd.Period(query_date, freq="Q"))
        return AnalogueMatchResult(query, tuple(), {})

    monkeypatch.setattr(forward_outcomes, "match_analogues", fake_match)

    results = compute_forward_outcome_results(
        _library(start="2000Q1", periods=24),
        horizon=4,
        min_pool=3,
        credit_spread_series=_credit_spread(start="2000Q1", periods=24),
    )
    metric = compute_metric_summary(
        results,
        label="test",
        mode="in_sample",
        share_version="raw",
    )

    assert "insufficient_pool" in set(results["status"])
    assert "unprecedented_state" in set(results["status"])
    assert metric["scored_queries"] == 0
    assert metric["insufficient_pool"] > 0
    assert metric["unprecedented_state"] > 0
    assert results.loc[results["status"] == "unprecedented_state", "pit_candidate_pool_size"].min() >= 3


def test_forward_outcome_csv_schema_columns_present_for_scored_query(monkeypatch):
    def fake_match(query_date, **_kwargs):
        query = str(pd.Period(query_date, freq="Q"))
        if query == "2008Q4":
            matches = (
                AnalogueMatch("1995Q1", 0.1, 0.1, 0.1, 1.0),
                AnalogueMatch("1995Q2", 0.1, 0.1, 0.1, 1.0),
            )
        else:
            matches = tuple()
        return AnalogueMatchResult(query, matches, {})

    monkeypatch.setattr(forward_outcomes, "match_analogues", fake_match)

    results = compute_forward_outcome_results(
        _library(start="1995Q1", periods=96),
        horizon=8,
        min_pool=1,
        credit_spread_series=_credit_spread(start="1995Q1", periods=96),
    )
    row = results.loc[results["query_date"] == "2008Q4"].iloc[0]
    expected_columns = {
        "pit_candidate_pool_size",
        "neighbor_recession_share_in_sample_raw",
        "neighbor_recession_share_in_sample_shrunk",
        "neighbor_recession_share_pit_observable_raw",
        "neighbor_recession_share_pit_observable_shrunk",
        "evaluable_neighbor_count_pit_observable",
        "dropped_unresolved_count",
        "kernel_weight_sum_pit_observable",
    }
    retired_aliases = {
        "neighbor_recession_share_pit",
        "neighbor_recession_share_pit_raw",
        "neighbor_recession_share_pit_shrunk",
        "evaluable_neighbor_count_pit",
        "kernel_weight_sum_pit",
    }

    assert expected_columns <= set(results.columns)
    assert retired_aliases.isdisjoint(results.columns)
    assert row.status == "ok"
    assert pd.notna(row.neighbor_recession_share_in_sample_raw)
    assert pd.notna(row.neighbor_recession_share_in_sample_shrunk)
    assert pd.notna(row.neighbor_recession_share_pit_observable_raw)
    assert pd.notna(row.neighbor_recession_share_pit_observable_shrunk)
