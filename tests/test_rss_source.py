from pathlib import Path
import sys
import json
from datetime import datetime, timezone
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest
from narrative.sources.rss import RssSource
from narrative.sources.base import RawTextItem
import narrative.sources.http as httpmod

# load fixture bytes
FIXTURE_PATH = Path("tests") / "fixtures" / "rss" / "sample_rss.xml"
FIXTURE_BYTES = FIXTURE_PATH.read_bytes()


class DummyResp:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class DummySession:
    def __init__(self, content: bytes):
        self._content = content

    def get(self, url, timeout=None, headers=None):
        return DummyResp(self._content, 200)


def test_rss_source_parses_and_generates_ids(monkeypatch):
    # monkeypatch make_session to return dummy session that yields our fixture
    monkeypatch.setattr(httpmod, "make_session", lambda: DummySession(FIXTURE_BYTES))
    rss = RssSource(feeds=["http://example.com/rss"])
    items = rss.fetch()
    # fixture has 2 items
    assert len(items) == 2
    # first item has guid -> id preserved
    ids = [it.id for it in items]
    assert "item-1-guid" in ids
    # second item id exists as deterministic hash if no guid; in our fixture both have guid, but ensure id string not empty
    assert all(isinstance(i, str) and len(i) > 0 for i in ids)
    # published_at are timezone-aware
    for it in items:
        assert it.published_at.tzinfo is not None
        # should be UTC given fixture GMT
        assert it.published_at.utcoffset().total_seconds() == 0


def test_rss_start_end_filter(monkeypatch):
    monkeypatch.setattr(httpmod, "make_session", lambda: DummySession(FIXTURE_BYTES))
    rss = RssSource(feeds=[{"name": "ex", "url": "http://example.com/rss"}])
    # set start after first item date to filter it out
    start = datetime(2023, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
    items = rss.fetch(start=start)
    # only second item (2023-01-03T16:05:06) should remain
    assert len(items) == 1
    assert items[0].title == "Second Item"