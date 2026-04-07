from pathlib import Path
import sys
import hashlib
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from narrative.sources import RawTextItem, LocalFileSource

def test_raw_text_item_validation():
    obj = {
        "id": "t1",
        "source": "fixture",
        "published_at": "2023-01-01T00:00:00Z",
        "title": "Title",
        "body": "text",
        "url": "http://example.com",
        "tickers": ["AAPL"],
        "metadata": {"k":"v"}
    }
    r = RawTextItem.parse_obj(obj)
    assert r.id == "t1"
    assert r.published_at.isoformat().startswith("2023-01-01")
    with pytest.raises(ValidationError):
        RawTextItem.parse_obj({**obj, "published_at": "not-a-date"})

def test_local_file_source_reads_jsonl():
    data_dir = ROOT / "data" / "narrative" / "raw"
    src = LocalFileSource(directory=data_dir)
    items = src.fetch()
    ids = [i.id for i in items]
    assert set(ids) == {"a1", "b1"}
    assert len(items) == 2

def test_deterministic_on_rerun():
    data_dir = ROOT / "data" / "narrative" / "raw"
    src = LocalFileSource(directory=data_dir)
    first = src.fetch()
    second = src.fetch()
    assert [i.id for i in first] == [i.id for i in second]
    h1 = hashlib.sha256("".join(i.id for i in first).encode()).hexdigest()
    h2 = hashlib.sha256("".join(i.id for i in second).encode()).hexdigest()
    assert h1 == h2