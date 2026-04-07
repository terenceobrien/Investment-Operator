from pathlib import Path
import sys
import hashlib

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from narrative.chunking import chunk_text
from narrative.scorers.stub import StubScorer
import pytest


def test_chunking_splits_and_overlap_behavior():
    text = "X" * 450  # deterministic content
    max_chars = 100
    overlap = 20
    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    # no empty chunks
    assert all(len(c) > 0 for c in chunks)
    # deterministic on rerun
    chunks2 = chunk_text(text, max_chars=max_chars, overlap=overlap)
    assert chunks == chunks2
    # check overlap between adjacent chunks
    for a, b in zip(chunks, chunks[1:]):
        assert a.endswith(b[:overlap])


def test_stubscorer_deterministic_and_ranges():
    scorer = StubScorer()
    text = "Deterministic scoring text."
    s1 = scorer.score(text)
    s2 = scorer.score(text)
    # deterministic equality
    assert s1.dict() == s2.dict()
    # ranges
    assert -3 <= s1.tone <= 3
    assert 0 <= s1.uncertainty <= 3
    themes = s1.themes
    assert -2 <= themes.ai <= 2
    assert -2 <= themes.inflation <= 2
    assert -2 <= themes.liquidity <= 2
    assert -2 <= themes.credit <= 2
    assert -2 <= themes.consumer <= 2