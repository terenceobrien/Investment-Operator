from __future__ import annotations

import pandas as pd
import pytest

from src.agent_system.forecasting.scenario_classifier import analogue_fan
from src.agent_system.forecasting.scenario_classifier.analogue_fan import (
    AnalogueFanError,
    compute_analogue_fan,
)
from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    AnalogueMatch,
    AnalogueMatchResult,
    level_feature_columns,
    trend_feature_columns,
)
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    DIRECTIONAL_VARIABLES,
)


def _library(start: str = "2000Q1", periods: int = 16) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for idx, period in enumerate(pd.period_range(start, periods=periods, freq="Q")):
        row: dict[str, float | str] = {"as_of": str(period)}
        for column in level_feature_columns():
            row[column] = float(idx) / 10.0
        for column in trend_feature_columns():
            row[column] = float(idx) / 100.0
        rows.append(row)
    return pd.DataFrame(rows)


def _histories(periods: list[str], values: list[float]) -> dict[str, pd.Series]:
    index = pd.PeriodIndex(periods, freq="Q")
    return {
        variable: pd.Series(values, index=index, dtype=float, name=variable)
        for variable in DIRECTIONAL_VARIABLES
    }


def test_fan_reanchors_paths_and_computes_weighted_percentiles(monkeypatch):
    matches = (
        AnalogueMatch("2000Q4", 0.1, 0.1, 0.1, 1.0),
        AnalogueMatch("2001Q1", 0.2, 0.2, 0.2, 3.0),
    )

    def fake_match(query_date, **_kwargs):
        return AnalogueMatchResult(str(pd.Period(query_date, freq="Q")), matches, {})

    monkeypatch.setattr(analogue_fan, "match_analogues", fake_match)
    histories = _histories(
        [
            "2000Q4",
            "2001Q1",
            "2001Q2",
            "2001Q3",
            "2002Q4",
        ],
        [
            10.0,
            20.0,
            21.0,
            23.0,
            100.0,
        ],
    )

    fan = compute_analogue_fan(
        "2002Q4",
        horizon_quarters=2,
        library=_library(),
        histories=histories,
    )
    credit = fan.variables["credit_spread"]

    assert credit.query_anchor_value == pytest.approx(100.0)
    assert credit.percentiles["p50"][0] == pytest.approx(101.0)
    assert credit.percentiles["p90"][0] == pytest.approx(110.0)
    assert credit.percentiles["p50"][1] == pytest.approx(103.0)
    assert credit.effective_n == pytest.approx((4.0, 4.0))
    assert credit.median_benign is None
    assert "no resolved neighbors" in credit.subset_notes["benign"]


def test_fan_truncates_late_horizons_without_error(monkeypatch):
    matches = (
        AnalogueMatch("2000Q1", 0.1, 0.1, 0.1, 1.0),
        AnalogueMatch("2000Q2", 0.2, 0.2, 0.2, 2.0),
    )

    def fake_match(query_date, **_kwargs):
        return AnalogueMatchResult(str(pd.Period(query_date, freq="Q")), matches, {})

    monkeypatch.setattr(analogue_fan, "match_analogues", fake_match)
    histories = _histories(
        [
            "2000Q1",
            "2000Q2",
            "2000Q3",
            "2000Q4",
            "2001Q1",
            "2001Q2",
            "2002Q4",
        ],
        [
            10.0,
            20.0,
            12.0,
            22.0,
            14.0,
            16.0,
            100.0,
        ],
    )

    fan = compute_analogue_fan(
        "2002Q4",
        horizon_quarters=8,
        library=_library(),
        histories=histories,
    )
    activity = fan.variables["activity"]

    assert activity.effective_n[0] == pytest.approx(3.0)
    assert activity.effective_n[4] == pytest.approx(1.0)
    assert activity.percentiles["p50"][4] == pytest.approx(106.0)


def test_fan_fails_loud_when_h1_has_no_effective_weight(monkeypatch):
    matches = (AnalogueMatch("2000Q1", 0.1, 0.1, 0.1, 1.0),)

    def fake_match(query_date, **_kwargs):
        return AnalogueMatchResult(str(pd.Period(query_date, freq="Q")), matches, {})

    monkeypatch.setattr(analogue_fan, "match_analogues", fake_match)
    histories = _histories(["2000Q1", "2002Q4"], [10.0, 100.0])

    with pytest.raises(AnalogueFanError, match="zero effective_n at h=1"):
        compute_analogue_fan(
            "2002Q4",
            horizon_quarters=2,
            library=_library(),
            histories=histories,
        )
