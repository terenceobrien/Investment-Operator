from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis import analogues
from src.analysis import conditional_probability
from src.analysis.rolling_composite import _weighted_aggregate_stats


def _base_row(**overrides):
    values = {
        "date": pd.Timestamp("2021-01-04"),
        "score_total": 55.0,
        "confidence": 70.0,
        "environment": "Mixed / Neutral",
        "score_delta": 1.0,
        "vix_level": 18.0,
        "vix_z_20d": 0.2,
        "sectors_green": 7,
        "dispersion": 0.01,
        "spy_close": 100.0,
        "layer_monetary": 6.0,
        "layer_credit": 6.0,
        "layer_volatility": 5.0,
        "layer_breadth": 7.0,
        "layer_positioning": 5.0,
        "fwd_ret_cc_1d": 0.001,
        "fwd_ret_cc_5d": 0.005,
        "fwd_ret_cc_10d": 0.01,
        "fwd_ret_cc_21d": 0.02,
        "fwd_ret_cc_63d": 0.04,
        "fwd_ret_cc_126d": 0.06,
        "fwd_ret_cc_252d": 0.10,
        "fwd_5d_max_drawdown_pct": -0.01,
        "fwd_5d_max_upside_pct": 0.02,
    }
    values.update(overrides)
    return values


def test_enriched_analogue_extracts_long_forward_horizons():
    df = pd.DataFrame(
        [
            _base_row(date=pd.Timestamp("2021-01-04"), spy_close=100.0),
            _base_row(date=pd.Timestamp("2021-01-05"), spy_close=101.0),
        ]
    )
    enriched = analogues._enrich_row(df.iloc[0], df, similarity=1.0)

    assert enriched["forward_returns"]["63d"] == 4.0
    assert enriched["forward_returns"]["126d"] == 6.0
    assert enriched["forward_returns"]["252d"] == 10.0


def test_missing_long_horizon_values_are_per_horizon_not_global_exclusions():
    rows = [
        _base_row(date=pd.Timestamp("2021-01-04"), fwd_ret_cc_252d=0.10),
        _base_row(date=pd.Timestamp("2021-01-05"), fwd_ret_cc_252d=np.nan),
        _base_row(date=pd.Timestamp("2021-01-06"), fwd_ret_cc_252d=np.nan),
    ]
    df = pd.DataFrame(rows)
    enriched = [
        analogues._enrich_row(row, df, similarity=1.0)
        for _, row in df.iterrows()
    ]

    aggregate = analogues._aggregate_stats(enriched, data_columns=df.columns)

    assert aggregate["forward_returns"]["21d"]["n"] == 3
    assert aggregate["forward_returns"]["252d"]["n"] == 1
    assert "252d" not in aggregate["missing_horizons"]


def test_missing_entire_horizon_column_adds_warning_without_crashing():
    df = pd.DataFrame([_base_row(), _base_row(), _base_row()]).drop(columns=["fwd_ret_cc_252d"])
    enriched = [
        analogues._enrich_row(row, df, similarity=1.0)
        for _, row in df.iterrows()
    ]

    aggregate = analogues._aggregate_stats(enriched, data_columns=df.columns)

    assert aggregate["forward_returns"]["252d"]["n"] == 0
    assert "252d" in aggregate["missing_horizons"]
    assert any("fwd_ret_cc_252d unavailable" in warning for warning in aggregate["warnings"])


def test_weighted_aggregate_stats_support_macro_horizons_with_separate_samples():
    analogues_payload = [
        {
            "composite_weight": 2.0,
            "forward_returns": {"1d": 0.1, "5d": 0.5, "10d": 1.0, "21d": 2.0, "63d": 4.0, "126d": 6.0, "252d": 8.0},
            "risk_profile": {},
            "environment": "Mixed",
        },
        {
            "composite_weight": 1.0,
            "forward_returns": {"1d": -0.1, "5d": -0.5, "10d": -1.0, "21d": -2.0, "63d": -4.0, "126d": -6.0, "252d": None},
            "risk_profile": {},
            "environment": "Risk-Off",
        },
    ]

    aggregate = _weighted_aggregate_stats(analogues_payload)

    assert set(["21d", "63d", "126d", "252d"]).issubset(aggregate["forward_returns"])
    assert aggregate["forward_returns"]["21d"]["n"] == 2
    assert aggregate["forward_returns"]["21d"]["weight_sum"] == 3.0
    assert aggregate["forward_returns"]["252d"]["n"] == 1
    assert aggregate["forward_returns"]["252d"]["weight_sum"] == 2.0
    assert aggregate["macro_forward_returns"]["63d"]["n"] == 2


def test_conditional_probability_includes_126d_252d_and_warns_for_missing_columns():
    subset = pd.DataFrame(
        {
            "fwd_ret_cc_1d": [0.01, -0.01, 0.02],
            "fwd_ret_cc_5d": [0.02, -0.02, 0.03],
            "fwd_ret_cc_10d": [0.03, -0.03, 0.04],
            "fwd_ret_cc_21d": [0.04, -0.04, 0.05],
            "fwd_ret_cc_63d": [0.05, -0.05, 0.06],
            "fwd_ret_cc_252d": [0.10, None, -0.08],
        }
    )
    warnings: list[str] = []

    stats = conditional_probability._build_return_table(subset, warnings)

    assert "126d" in conditional_probability.HORIZONS
    assert "252d" in stats
    assert stats["252d"]["n"] == 2
    assert any("fwd_ret_cc_126d unavailable" in warning for warning in warnings)


def test_covid_crash_forward_window_overlap_excludes_jan_2020_63d():
    assert analogues.forward_window_overlaps_shock("2020-01-15", "63d")
    assert not analogues.forward_window_overlaps_shock("2020-01-15", "21d")

    rows = [
        _base_row(date=pd.Timestamp("2020-01-15"), fwd_ret_cc_63d=-0.25),
        _base_row(date=pd.Timestamp("2020-05-12"), fwd_ret_cc_63d=0.08),
        _base_row(date=pd.Timestamp("2021-01-04"), fwd_ret_cc_63d=0.05),
    ]
    df = pd.DataFrame(rows)
    enriched = [analogues._enrich_row(row, df, similarity=1.0) for _, row in df.iterrows()]

    aggregate = analogues._aggregate_stats(enriched, data_columns=df.columns)

    assert aggregate["forward_returns"]["63d"]["n"] == 2
    diagnostics = aggregate["shock_window_diagnostics"]
    assert "2020-01-15" in diagnostics["excluded_dates_by_horizon"]["63d"]
    assert "2020-05-12" not in diagnostics["excluded_dates_by_horizon"].get("63d", [])


def test_may_2020_row_is_not_excluded_by_covid_crash_overlap():
    assert not analogues.forward_window_overlaps_shock("2020-05-12", "63d")
    assert not analogues.forward_window_overlaps_shock("2020-05-12", "126d")


def test_longer_horizons_exclude_more_rows_than_21d():
    payload = [
        {"date": "2019-08-01", "forward_returns": {"21d": 1.0, "252d": 4.0}},
        {"date": "2019-12-02", "forward_returns": {"21d": 1.0, "252d": 4.0}},
        {"date": "2020-02-03", "forward_returns": {"21d": -3.0, "252d": -8.0}},
        {"date": "2021-01-04", "forward_returns": {"21d": 2.0, "252d": 7.0}},
    ]

    diagnostics = analogues.shock_window_diagnostics_for_analogues(
        payload,
        horizons=["21d", "252d"],
    )

    assert diagnostics["rows_excluded_by_horizon"]["252d"] > diagnostics["rows_excluded_by_horizon"]["21d"]
