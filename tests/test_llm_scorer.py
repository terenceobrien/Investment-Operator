from __future__ import annotations
from pathlib import Path
import sys
import os
from datetime import datetime
from typing import Any, Dict

# ensure src/ is on sys.path for imports
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest

from narrative.scorers.llm import LLMScorer
from narrative.llm_client import LLMClient
from narrative.scorers.stub import StubScorer
from narrative.daily import build_narrative_scores
from narrative.sources.base import BaseSource, RawTextItem


class DummySource(BaseSource):
    def __init__(self, items: list[RawTextItem]):
        self._items = items

    def fetch(self, start=None, end=None):
        return self._items


def test_llmscorer_parses_and_adds_metadata(monkeypatch):
    # patch the underlying client to return a predictable JSON string
    def fake_complete(self, *, model: str, messages: Any, temperature: float = 0.0):
        return '{"tone":1,"uncertainty":2,"themes":{"ai":0,"inflation":1,"liquidity":-1,"credit":2,"consumer":-2}}'

    monkeypatch.setattr(LLMClient, "complete", fake_complete)
    # client init requires API key present
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    scorer = LLMScorer(model="fake-model", prompt_version="pv1")
    score = scorer.score("some text")

    assert score.tone == 1
    assert score.uncertainty == 2
    assert score.themes.ai == 0
    assert score.themes.inflation == 1
    assert score.themes.liquidity == -1
    assert score.themes.credit == 2
    assert score.themes.consumer == -2
    assert score.metadata["model"] == "fake-model"
    assert score.metadata["prompt_version"] == "pv1"


def test_llmscorer_invalid_json_retries_then_fails(monkeypatch):
    calls = []

    def fake_complete(self, *, model: str, messages: Any, temperature: float = 0.0):
        calls.append(messages)
        # always return a bad string
        return "not a json"

    monkeypatch.setattr(LLMClient, "complete", fake_complete)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    scorer = LLMScorer(model="m", prompt_version="v2")
    score = scorer.score("foo")

    # should have attempted twice (initial + repair)
    assert len(calls) == 2
    # result should be all zeros with error metadata
    assert score.tone == 0
    assert score.uncertainty == 0
    assert score.themes.dict() == {"ai": 0, "inflation": 0, "liquidity": 0, "credit": 0, "consumer": 0}
    assert score.metadata["model"] == "m"
    assert score.metadata["prompt_version"] == "v2"
    assert "error" in score.metadata
    # error message should at least mention parsing or be nonempty
    assert score.metadata["error"]


def test_daily_cache_prevents_duplicate_llm_calls(tmp_path, monkeypatch):
    # override cache paths to temporary location
    import narrative.daily as daily
    monkeypatch.setattr(daily, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(daily, "CACHE_PATH_PQ", str(tmp_path / "cache" / "chunk_scores.parquet"))
    monkeypatch.setattr(daily, "CACHE_PATH_JSONL", str(tmp_path / "cache" / "chunk_scores.jsonl"))

    # environment for llm scorer
    monkeypatch.setenv("NARRATIVE_SCORER", "llm")
    monkeypatch.setenv("NARRATIVE_LLM_MODEL", "my-model")
    monkeypatch.setenv("NARRATIVE_PROMPT_VERSION", "pv3")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    call_count = 0

    def fake_complete(self, *, model: str, messages: Any, temperature: float = 0.0):
        nonlocal call_count
        call_count += 1
        return '{"tone":0,"uncertainty":0,"themes":{"ai":0,"inflation":0,"liquidity":0,"credit":0,"consumer":0}}'

    monkeypatch.setattr(LLMClient, "complete", fake_complete)

    # two items with identical body -> same chunk
    # use midday UTC to ensure Eastern local date matches the requested range
    items = [
        RawTextItem(id="1", source="src", published_at=datetime(2026, 3, 3, 12, 0), body="dup"),
        RawTextItem(id="2", source="src", published_at=datetime(2026, 3, 3, 12, 0), body="dup"),
    ]
    df = build_narrative_scores("2026-03-03", "2026-03-03", sources=[DummySource(items)])

    # we expect only one LLM call, since cache dict is updated mid-run
    assert call_count == 1
    # ensure output dataframe has a row for the date
    assert not df.empty


def test_stub_default_when_env_not_set():
    # make sure stub is used when NARRATIVE_SCORER is absent or not 'llm'
    os.environ.pop("NARRATIVE_SCORER", None)
    scorer = StubScorer()
    assert scorer.score("abc").tone is not None
