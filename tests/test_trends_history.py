"""
tests/test_trends_history.py

Offline tests for narrative/trends_history.py.
No pytrends or yfinance calls — all tests use use_synthetic=True or
construct data directly.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from trends_history import (
    ALL_HISTORY_TERMS,
    BROAD_TERMS,
    DISTRESS_SPECIFIC_TERMS,
    INTERMEDIATE_TERMS,
    _classify_tier,
    _generate_synthetic_history,
    _stitch_windows,
    compute_asvi,
    plot_signal_quality,
    run_historical_backtest,
)


# ---------------------------------------------------------------------------
# test_synthetic_history_shape
# ---------------------------------------------------------------------------

def test_synthetic_history_shape():
    df = _generate_synthetic_history()

    expected_term_cols = set(ALL_HISTORY_TERMS)
    assert expected_term_cols.issubset(set(df.columns)), (
        f"Missing term columns: {expected_term_cols - set(df.columns)}"
    )
    assert "spy_return" in df.columns
    assert "spy_cumulative" in df.columns
    assert len(expected_term_cols) == 14, "Expected exactly 14 term columns"

    assert isinstance(df.index, pd.DatetimeIndex)
    assert len(df) >= 800, f"Expected >=800 rows, got {len(df)}"

    for col in ALL_HISTORY_TERMS + ["spy_return", "spy_cumulative"]:
        assert not df[col].isna().all(), f"Column '{col}' is entirely NaN"


# ---------------------------------------------------------------------------
# test_stitch_windows_correctness
# ---------------------------------------------------------------------------

def test_stitch_windows_correctness():
    # Three windows, 2-week overlap at each boundary
    # Dates:  1  2  3  4  5  (window A)
    #                  4  5  6  7  8  (window B)
    #                           7  8  9 10 11  (window C)
    base = pd.Timestamp("2020-01-06")
    week = pd.Timedelta(weeks=1)

    dates_a = pd.DatetimeIndex([base + i * week for i in range(5)])    # 1..5
    dates_b = pd.DatetimeIndex([base + i * week for i in range(3, 8)]) # 4..8
    dates_c = pd.DatetimeIndex([base + i * week for i in range(6, 11)]) # 7..11

    # anchor=100 everywhere so normalized = term value
    anchor_a = pd.Series([100.0] * 5, index=dates_a)
    anchor_b = pd.Series([100.0] * 5, index=dates_b)
    anchor_c = pd.Series([100.0] * 5, index=dates_c)

    val_a = pd.Series([10.0, 20.0, 30.0, 40.0,  50.0], index=dates_a)
    val_b = pd.Series([60.0, 70.0, 80.0, 90.0, 100.0], index=dates_b)
    val_c = pd.Series([110.0, 120.0, 130.0, 140.0, 150.0], index=dates_c)

    windows = [
        (dates_a, val_a, anchor_a),
        (dates_b, val_b, anchor_b),
        (dates_c, val_c, anchor_c),
    ]

    result = _stitch_windows(windows)

    # 11 unique dates
    assert len(result) == 11, f"Expected 11 unique dates, got {len(result)}"

    # Sorted
    assert list(result.index) == sorted(result.index), "Output not sorted by date"

    # date_a[3] == date_b[0]: mean(40, 60) = 50
    assert math.isclose(result.loc[dates_a[3]], 50.0, abs_tol=1e-6)
    # date_a[4] == date_b[1]: mean(50, 70) = 60
    assert math.isclose(result.loc[dates_a[4]], 60.0, abs_tol=1e-6)
    # date_b[3] == date_c[0]: mean(90, 110) = 100
    assert math.isclose(result.loc[dates_b[3]], 100.0, abs_tol=1e-6)
    # date_b[4] == date_c[1]: mean(100, 120) = 110
    assert math.isclose(result.loc[dates_b[4]], 110.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# test_asvi_near_zero_in_stable_period
# ---------------------------------------------------------------------------

def test_asvi_near_zero_in_stable_period():
    idx = pd.date_range("2020-01-06", periods=52, freq="W-MON")
    series = pd.Series([50.0] * 52, index=idx)
    asvi = compute_asvi(series, warmup=8)

    post_warmup = asvi.dropna()
    assert len(post_warmup) > 0, "Expected non-NaN values after warmup"
    assert (post_warmup.abs() <= 0.01).all(), (
        f"ASVI values not near zero in stable period: {post_warmup.abs().max():.6f}"
    )


# ---------------------------------------------------------------------------
# test_asvi_positive_on_spike
# ---------------------------------------------------------------------------

def test_asvi_positive_on_spike():
    idx = pd.date_range("2020-01-06", periods=22, freq="W-MON")
    vals = [10.0] * 20 + [80.0] + [10.0]
    series = pd.Series(vals, index=idx)
    asvi = compute_asvi(series, warmup=8)

    spike_asvi = asvi.iloc[20]
    assert spike_asvi > 1.5, (
        f"Expected ASVI > 1.5 at spike, got {spike_asvi:.4f}"
    )


# ---------------------------------------------------------------------------
# test_backtest_ranking_tier_order
# ---------------------------------------------------------------------------

def test_backtest_ranking_tier_order():
    result = run_historical_backtest(use_synthetic=True)

    distress_results = [r for r in result.term_results if r.tier == "distress_specific"]
    broad_results    = [r for r in result.term_results if r.tier == "broad"]

    assert distress_results, "No distress_specific results found"
    assert broad_results,    "No broad results found"

    min_distress_sq = min(r.signal_quality for r in distress_results)
    max_broad_sq    = max(r.signal_quality for r in broad_results)
    assert min_distress_sq > max_broad_sq, (
        f"Not all distress-specific terms outrank broad terms. "
        f"min distress={min_distress_sq:.4f}, max broad={max_broad_sq:.4f}"
    )

    for r in result.term_results:
        assert not math.isnan(r.corr_asvi_fwd_4w), f"corr_asvi_fwd_4w is NaN for {r.term}"
        assert r.corr_asvi_fwd_4w < 0, (
            f"Expected negative corr_asvi_fwd_4w for {r.term}, got {r.corr_asvi_fwd_4w:.4f}"
        )

    for r in distress_results:
        assert r.p_val_4w < 0.05, (
            f"Expected p_val_4w < 0.05 for distress term '{r.term}', got {r.p_val_4w:.4f}"
        )


# ---------------------------------------------------------------------------
# test_backtest_result_serialization
# ---------------------------------------------------------------------------

def test_backtest_result_serialization(tmp_path):
    result = run_historical_backtest(use_synthetic=True)
    save_path = str(tmp_path / "bt.json")
    result.save(save_path)

    raw = json.loads(Path(save_path).read_text(encoding="utf-8"))
    assert "term_results" in raw, "JSON missing 'term_results' key"
    assert isinstance(raw["term_results"], list)

    saved_terms = {r["term"] for r in raw["term_results"]}
    for r in result.term_results:
        assert r.term in saved_terms, f"Term '{r.term}' missing from saved JSON"

    saved_sq = {r["term"]: r["signal_quality"] for r in raw["term_results"]}
    for r in result.term_results:
        assert abs(r.signal_quality - saved_sq[r.term]) < 1e-4, (
            f"signal_quality round-trip loss for '{r.term}': "
            f"{r.signal_quality} vs {saved_sq[r.term]}"
        )


# ---------------------------------------------------------------------------
# test_plot_produces_file
# ---------------------------------------------------------------------------

def test_plot_produces_file(tmp_path):
    result = run_historical_backtest(use_synthetic=True)
    chart_path = str(tmp_path / "chart.png")
    result.plot(chart_path)
    p = Path(chart_path)
    assert p.exists(), "chart.png was not created"
    assert p.stat().st_size > 50_000, (
        f"chart.png too small: {p.stat().st_size} bytes (expected > 50KB)"
    )


# ---------------------------------------------------------------------------
# test_plot_signal_quality_produces_file
# ---------------------------------------------------------------------------

def test_plot_signal_quality_produces_file(tmp_path):
    result = run_historical_backtest(use_synthetic=True)
    chart_path = str(tmp_path / "sq.png")
    plot_signal_quality(result.term_results, chart_path)
    p = Path(chart_path)
    assert p.exists(), "sq.png was not created"
    assert p.stat().st_size > 30_000, (
        f"sq.png too small: {p.stat().st_size} bytes (expected > 30KB)"
    )


# ---------------------------------------------------------------------------
# test_classify_tier_coverage
# ---------------------------------------------------------------------------

def test_classify_tier_coverage():
    for term in BROAD_TERMS:
        assert _classify_tier(term) == "broad", f"Expected 'broad' for '{term}'"

    for term in INTERMEDIATE_TERMS:
        assert _classify_tier(term) == "intermediate", f"Expected 'intermediate' for '{term}'"

    for term in DISTRESS_SPECIFIC_TERMS:
        assert _classify_tier(term) == "distress_specific", (
            f"Expected 'distress_specific' for '{term}'"
        )

    assert _classify_tier("completely unrecognized term xyz") == "unknown"
