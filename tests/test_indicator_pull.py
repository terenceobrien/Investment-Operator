from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

# ensure src importable
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest
from src.data import indicator_pull as ip


def make_series(dates, vals):
    idx = pd.to_datetime(dates)
    return pd.Series(vals, index=idx)


def test_gather_with_various_freqs(monkeypatch, tmp_path):
    # fake indicator list
    fake_df = pd.DataFrame({
        "Indicator": ["A", "VIX term structure", "VIX term structure"],
        "Source": ["fred", "yahoo finance", "yahoo finance"],
        "ID": ["ID1", "^VIX", "^VIX3M"],
    })
    monkeypatch.setattr(ip, "_load_indicator_list", lambda path=None: fake_df)
    # fake fetcher returns two series for vix plus one weekly
    ser_weekly = make_series(["2020-01-01", "2020-01-08"], [1, 2])
    ser_vix = make_series(["2020-01-01", "2020-01-02"], [10, 20])
    ser_vix3m = make_series(["2020-01-01", "2020-01-02"], [5, 15])
    def fake_fetch(src, sid, start=None, end=None):
        if sid == "ID1":
            return ser_weekly
        if sid == "^VIX":
            return ser_vix
        if sid == "^VIX3M":
            return ser_vix3m
        return pd.Series(dtype=float)
    monkeypatch.setattr(ip, "fetch_indicator_series", fake_fetch)

    out_csv = str(tmp_path / "out.csv")
    df = ip.gather_all_indicators(out_csv)
    # should have distinct column names for vix and vix3m
    assert "VIX" in df.columns and "VIX 3M" in df.columns
    assert "A" in df.columns
    # and their percentile columns
    assert "VIX_percentile" in df.columns and "VIX 3M_percentile" in df.columns
    assert "A_percentile" in df.columns
    # and their bucket columns
    assert "VIX Bucket" in df.columns and "VIX 3M Bucket" in df.columns
    assert "A Bucket" in df.columns
    # weekly series forward-filled
    assert df.loc["2020-01-02", "A"] == 1
    assert df.loc["2020-01-01", "A"] == 1
    assert df.loc["2020-01-08", "A"] == 2
    # vix columns contain their respective values
    assert df.loc["2020-01-02", "VIX"] == 20
    assert df.loc["2020-01-02", "VIX 3M"] == 15
    # percentiles: for A, values 1 and 2 -> ranks 0.5 and 1.0
    assert df.loc["2020-01-01", "A_percentile"] == 0.5
    assert df.loc["2020-01-02", "A_percentile"] == 0.5  # forward-filled
    assert df.loc["2020-01-08", "A_percentile"] == 1.0
    # for VIX: 10 and 20 -> 0.5 and 1.0
    assert df.loc["2020-01-01", "VIX_percentile"] == 0.5
    assert df.loc["2020-01-02", "VIX_percentile"] == 1.0
    # for VIX 3M: 5 and 15 -> 0.5 and 1.0
    assert df.loc["2020-01-01", "VIX 3M_percentile"] == 0.5
    assert df.loc["2020-01-02", "VIX 3M_percentile"] == 1.0
    # buckets: percentile 0.5 -> bucket 5 ((0.4, 0.5]), 1.0 -> 10 ((0.9, 1.0])
    assert df.loc["2020-01-01", "A Bucket"] == 5
    assert df.loc["2020-01-02", "A Bucket"] == 5  # forward-filled
    assert df.loc["2020-01-08", "A Bucket"] == 10
    assert df.loc["2020-01-01", "VIX Bucket"] == 5
    assert df.loc["2020-01-02", "VIX Bucket"] == 10
    assert df.loc["2020-01-01", "VIX 3M Bucket"] == 5
    assert df.loc["2020-01-02", "VIX 3M Bucket"] == 10
    # file should exist
    assert Path(out_csv).exists()
    # returned csv should list the three indicators from fake_df
    ret_path = Path(out_csv).parent / "indicators_returned.csv"
    assert ret_path.exists()
    ret_df = pd.read_csv(ret_path)
    # the returned list should include each named indicator only once
    assert set(ret_df["Indicator"]) == {"A", "VIX term structure"}
    assert len(ret_df["Indicator"]) == ret_df["Indicator"].nunique()
