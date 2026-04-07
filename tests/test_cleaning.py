from pathlib import Path
import sys
import hashlib
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from narrative.cleaning import (
    strip_price_move_sentences,
    normalize_whitespace,
    clean_text,
    dedupe_items,
)
from narrative.sources import RawTextItem


def test_price_language_removed_deterministically():
    text = "Company reported earnings. Shares rose 5% to $10. Management said growth will continue."
    out = strip_price_move_sentences(text)
    assert "rose" not in out.lower()
    # non-price sentences remain
    assert "Company reported earnings" in out
    assert "Management said growth will continue" in out


def test_non_price_sentences_remain():
    text = "This is a normal sentence. Another informative sentence."
    out = strip_price_move_sentences(text)
    assert "normal sentence" in out
    assert "Another informative sentence" in out


def test_normalize_whitespace():
    s = "This   has \n multiple\tspaces. "
    assert normalize_whitespace(s) == "This has multiple spaces."


def test_dedupe_collapses_duplicates():
    a = RawTextItem.parse_obj(
        {
            "id": "1",
            "source": "fixture",
            "published_at": "2023-01-01T00:00:00Z",
            "body": "Story text. Shares rose 5% to $10.",
        }
    )
    b = RawTextItem.parse_obj(
        {
            "id": "2",
            "source": "fixture",
            "published_at": "2023-01-02T00:00:00Z",
            # extra whitespace and same meaningful content once price sentence is stripped
            "body": " Story   text.  Shares rose 5% to $10. ",
        }
    )
    out = dedupe_items([a, b])
    assert len(out) == 1
    assert out[0].id == "1"


def test_dedupe_rerun_is_deterministic():
    a = RawTextItem.parse_obj(
        {
            "id": "1",
            "source": "fixture",
            "published_at": "2023-01-01T00:00:00Z",
            "body": "Story text.",
        }
    )
    b = RawTextItem.parse_obj(
        {
            "id": "2",
            "source": "fixture",
            "published_at": "2023-01-02T00:00:00Z",
            "body": "Story text.",
        }
    )
    first = dedupe_items([a, b])
    second = dedupe_items([a, b])
    assert [i.id for i in first] == [i.id for i in second]
    h1 = hashlib.sha256("".join(i.id for i in first).encode()).hexdigest()
    h2 = hashlib.sha256("".join(i.id for i in second).encode()).hexdigest()
    assert h1 == h2