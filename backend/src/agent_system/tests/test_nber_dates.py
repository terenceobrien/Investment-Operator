from __future__ import annotations

import pandas as pd
import pytest

from src.agent_system.forecasting.scenario_classifier.nber_dates import (
    NBERDateError,
    pre_crisis_quarters,
    recession_within,
)


def test_pre_crisis_quarters_excludes_peak_quarters():
    dates = pre_crisis_quarters(exclude_exogenous=False)

    assert pd.Period("2007Q4", freq="Q") not in dates
    assert pd.Period("2007Q3", freq="Q") in dates


def test_pre_crisis_quarters_drops_2019_window_when_exogenous_excluded():
    excluded = pre_crisis_quarters(exclude_exogenous=True)
    included = pre_crisis_quarters(exclude_exogenous=False)

    assert pd.Period("2019Q3", freq="Q") not in excluded
    assert pd.Period("2019Q3", freq="Q") in included
    assert pd.Period("2019Q4", freq="Q") not in included


def test_recession_within_detects_2007_peak_inside_horizon():
    assert recession_within("2006Q4", 8, max_known_quarter="2010Q4") is True


def test_recession_within_returns_false_for_benign_window():
    assert recession_within("2013Q1", 8, max_known_quarter="2020Q2") is False


def test_recession_within_raises_when_future_is_unknown():
    with pytest.raises(NBERDateError, match="beyond max_known_quarter"):
        recession_within("2025Q1", 8, max_known_quarter="2026Q2")
