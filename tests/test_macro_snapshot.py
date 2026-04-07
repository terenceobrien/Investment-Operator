from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

# ensure src is importable
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest
from src.brief import macro_snapshot as ms


def make_series(values):
    # simple monthly series
    idx = pd.date_range("2020-01-01", periods=len(values), freq="M")
    return pd.Series(values, index=idx)


def test_assemble_snapshot_data_basic(monkeypatch):
    # patch all _fetch_series calls to return identical series
    fake = make_series([10, 20, 30])
    monkeypatch.setattr(ms, "_fetch_series", lambda sid: fake)
    data = ms.assemble_snapshot_data()
    assert isinstance(data, list)
    assert len(data) == len(ms._INDICATORS)
    for item in data:
        assert item["current"] == 30
        assert item["previous"] == 20
        assert item["delta"] == 10
        assert isinstance(item["history"], pd.Series)


def test_slice_history():
    s = make_series(list(range(24)))
    # slice last 1 year (~12 months)
    out = ms.slice_history(s, years=1)
    # should include at most roughly years*12+1 points (inclusive cutoff)
    assert len(out) <= 13
    assert out.index.max() == s.index.max()

