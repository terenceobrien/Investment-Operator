from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.agent_system.forecasting.scenario_classifier.directional_features import (
    DIRECTIONAL_VARIABLES,
    SPINE_VARIABLES,
    DirectionalFeatureCache,
    DirectionalFeatureError,
    build_directional_feature_library,
    compute_directional_features,
    compute_directional_features_batch,
)


def _series(values: list[float], start: str = "2000Q1") -> pd.Series:
    index = pd.period_range(start, periods=len(values), freq="Q")
    return pd.Series(values, index=index, dtype=float)


def _cache(tmp_path: Path, periods: int = 24) -> DirectionalFeatureCache:
    base = np.arange(periods, dtype=float)
    histories = {
        "activity": _series((100.0 + base + 0.03 * base**2).tolist()),
        "lur": _series((8.0 - base * 0.05 + 0.01 * np.sin(base)).tolist()),
        "core_pce": _series((2.0 + np.sin(base / 3.0)).tolist()),
        "credit_spread": _series((1.0 + base * 0.02 + 0.01 * np.sin(base / 2.0)).tolist()),
        "fed_funds": _series((3.0 + base * 0.04 + 0.025 * base**1.2).tolist()),
        "ten_year": _series((5.0 + base * 0.01 + 0.003 * base**1.1).tolist()),
        "nfci": _series((-0.5 + base * 0.03 + 0.02 * np.cos(base / 2.0)).tolist()),
    }
    histories["curve_slope"] = histories["ten_year"] - histories["fed_funds"]
    histories["curve_slope"].name = "curve_slope"
    return DirectionalFeatureCache(
        cache_dir=tmp_path,
        registry_path=tmp_path / "state_vector.yaml",
        histories=histories,
    )


def test_directional_feature_vector_has_spine_plus_curve_slope(tmp_path):
    cache = _cache(tmp_path)

    vector = compute_directional_features("2005Q4", cache=cache)

    assert vector.variables == DIRECTIONAL_VARIABLES
    assert len(vector.flat_vector) == 16
    assert vector.flat_feature_names[0] == "activity.level_percentile"
    assert vector.flat_feature_names[-1] == "curve_slope.trend_slope"
    assert vector.window_quarters_used == ("2005Q1", "2005Q2", "2005Q3", "2005Q4")
    assert vector.features["curve_slope"].source == "derived"
    assert vector.features["curve_slope"].current_value == pytest.approx(
        vector.features["ten_year"].current_value - vector.features["fed_funds"].current_value
    )


def test_trend_slope_is_signed_and_normalized(tmp_path):
    cache = _cache(tmp_path)

    vector = compute_directional_features("2005Q4", cache=cache)

    assert vector.features["activity"].trend_slope > 0
    assert vector.features["curve_slope"].trend_slope < 0
    assert 0.0 <= vector.features["credit_spread"].level_percentile <= 1.0


def test_compute_directional_features_fails_loud_on_early_history(tmp_path):
    cache = _cache(tmp_path, periods=12)

    with pytest.raises(DirectionalFeatureError, match="activity.*2002Q4"):
        compute_directional_features("2002Q4", cache=cache)


def test_compute_directional_features_fails_loud_on_missing_window(tmp_path):
    cache = _cache(tmp_path)
    broken = dict(cache.histories)
    broken["credit_spread"] = broken["credit_spread"].drop(pd.Period("2005Q2", freq="Q"))
    broken_cache = DirectionalFeatureCache(
        cache_dir=tmp_path,
        registry_path=cache.registry_path,
        histories=broken,
    )

    with pytest.raises(DirectionalFeatureError, match="credit_spread.*2005Q4.*2005Q2"):
        compute_directional_features("2005Q4", cache=broken_cache)


def test_batch_and_library_output_are_dense(tmp_path):
    cache = _cache(tmp_path)

    vectors = compute_directional_features_batch(["2004Q4", "2005Q1"], cache=cache)
    frame, path = build_directional_feature_library(
        start="2004Q4",
        end="2005Q1",
        cache=cache,
        output_path=tmp_path / "library.csv",
    )

    assert [vector.as_of for vector in vectors] == ["2004Q4", "2005Q1"]
    assert path == tmp_path / "library.csv"
    assert path.is_file()
    assert len(frame) == 2
    assert not frame.isna().any().any()
    for variable in SPINE_VARIABLES + ("curve_slope",):
        assert f"{variable}.level_percentile" in frame.columns
        assert f"{variable}.trend_slope" in frame.columns
