from pathlib import Path
import sys
import hashlib
from datetime import datetime, timezone
from typing import List
import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from narrative.daily import build_narrative_scores
from narrative.sources.base import BaseSource, RawTextItem


class TestSource(BaseSource):
    def __init__(self, items: List[RawTextItem]):
        self._items = items

    def fetch(self, start: datetime = None, end: datetime = None) -> List[RawTextItem]:
        # honor start/end if provided
        out = []
        for it in self._items:
            dt = it.published_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if start and dt < start:
                continue
            if end and dt >= end:
                continue
            out.append(it)
        return out


def make_item(id: str, published_iso: str, body: str, source: str = "test"):
    return RawTextItem.parse_obj(
        {
            "id": id,
            "source": source,
            "published_at": published_iso,
            "title": None,
            "body": body,
            "url": None,
            "tickers": None,
            "metadata": {},
        }
    )


def test_build_narrative_end_to_end_and_ranges(tmp_path):
    # create one item that maps to a weekday (US/Eastern)
    # choose 2023-01-03 12:00:00Z (Tuesday)
    item = make_item("x1", "2023-01-03T12:00:00Z", "This is a test story. Shares rose 5% to $10.")
    src = TestSource([item])
    df = build_narrative_scores("2023-01-02", "2023-01-04", sources=[src])
    # weekdays in range: 2023-01-02, 2023-01-03, 2023-01-04
    assert len(df) == 3
    # find row for 2023-01-03
    row = df[df["date"] == "2023-01-03"].iloc[0]
    # n_items should be 1 for that day
    assert int(row["n_items"]) == 1
    # tone within -3..3 or NaN if no chunks (should have chunks)
    if not (row["tone"] != row["tone"]):  # not NaN
        assert -3.0 <= row["tone"] <= 3.0
    # conviction/cohesion within 0..3 when present
    if not (row["conviction"] != row["conviction"]):
        assert 0.0 <= row["conviction"] <= 3.0
    if not (row["cohesion"] != row["cohesion"]):
        assert 0.0 <= row["cohesion"] <= 3.0


def test_deterministic_rerun_and_persistence(tmp_path):
    item = make_item("x2", "2023-02-01T12:00:00Z", "Content for determinism.")
    src = TestSource([item])
    # first run
    df1 = build_narrative_scores("2023-02-01", "2023-02-01", sources=[src])
    # read written CSV
    csv_path = Path("data") / "narrative" / "narrative_daily.csv"
    assert csv_path.exists()
    c1 = csv_path.read_bytes()
    # second run
    df2 = build_narrative_scores("2023-02-01", "2023-02-01", sources=[src])
    c2 = csv_path.read_bytes()
    assert c1 == c2
    # DataFrame determinism: CSV hash equal
    h = hashlib.sha256(c1).hexdigest()
    assert h == hashlib.sha256(c2).hexdigest()
    # scores within expected bounds for the non-empty row
    row = df1[df1["date"] == "2023-02-01"].iloc[0]
    if not (row["tone"] != row["tone"]):
        assert -3.0 <= row["tone"] <= 3.0
    if not (row["conviction"] != row["conviction"]):
        assert 0.0 <= row["conviction"] <= 3.0
    if not (row["cohesion"] != row["cohesion"]):
        assert 0.0 <= row["cohesion"] <= 3.0