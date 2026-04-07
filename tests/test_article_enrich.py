from __future__ import annotations
from pathlib import Path
import sys
import os
from datetime import datetime

# ensure src is importable
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import pytest

from narrative.sources.base import RawTextItem
import narrative.enrich.article_fetch as af
from hashlib import sha256


def read_fixture(name: str) -> str:
    path = ROOT / "tests" / "fixtures" / "articles" / name
    return path.read_text(encoding="utf-8")


def test_successful_extraction_replaces_body(tmp_path, monkeypatch):
    # patch cache paths
    monkeypatch.setattr(af, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(af, "CACHE_PATH_PQ", str(tmp_path / "cache" / "article_text_cache.parquet"))
    monkeypatch.setattr(af, "CACHE_PATH_JSONL", str(tmp_path / "cache" / "article_text_cache.jsonl"))

    html = read_fixture("full_article.html")
    # simulate fetch_html returning our fixture
    monkeypatch.setattr(af, "fetch_html", lambda url, session, timeout=15: html)

    item = RawTextItem(id="1", source="rss", published_at=datetime(2026,3,3,12,0), body="summary text", url="http://example.com/full")
    out = af.enrich_items([item])[0]
    assert "full article text" in out.body
    assert out.body != "summary text"
    assert out.metadata["content_type"] == "full_article"
    assert out.metadata["full_text_extraction_success"]
    assert out.metadata["article_word_count"] > 50
    assert out.metadata.get("article_fetch_error") is None
    # also check cache was written
    cache = af._load_article_cache()
    h = sha256(out.url.encode("utf-8")).hexdigest()
    assert h in cache
    assert cache[h]["extraction_success"]


def test_failed_extraction_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(af, "CACHE_PATH_PQ", str(tmp_path / "cache" / "article_text_cache.parquet"))
    monkeypatch.setattr(af, "CACHE_PATH_JSONL", str(tmp_path / "cache" / "article_text_cache.jsonl"))

    # fetch_html returns short html so extraction will produce low-word count
    html = read_fixture("short_article.html")
    monkeypatch.setattr(af, "fetch_html", lambda url, session, timeout=15: html)
    # also monkeypatch extract_article_text to return minimal text
    monkeypatch.setattr(af, "extract_article_text", lambda html, url=None: "short")

    item = RawTextItem(id="2", source="rss", published_at=datetime(2026,3,3,12,0), body="summary", url="http://example.com/short")
    out = af.enrich_items([item])[0]
    assert out.body == "summary"
    assert out.metadata["content_type"] == "rss_summary"
    assert out.metadata["full_text_extraction_success"] is False
    assert out.metadata["article_fetch_error"] in ("extracted text too short", "") or out.metadata["article_fetch_error"] is not None


def test_cached_url_avoids_refetch(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(af, "CACHE_PATH_PQ", str(tmp_path / "cache" / "article_text_cache.parquet"))
    monkeypatch.setattr(af, "CACHE_PATH_JSONL", str(tmp_path / "cache" / "article_text_cache.jsonl"))

    fetch_calls = {
        "count": 0
    }
    def fake_fetch(url, session, timeout=15):
        fetch_calls["count"] += 1
        return read_fixture("full_article.html")
    monkeypatch.setattr(af, "fetch_html", fake_fetch)

    item = RawTextItem(id="3", source="rss", published_at=datetime(2026,3,3,12,0), body="sum", url="http://example.com/full2")
    out1 = af.enrich_items([item])[0]
    assert fetch_calls["count"] == 1
    # second enrichment should read from cache and not increment
    out2 = af.enrich_items([out1])[0]
    assert fetch_calls["count"] == 1
    assert out2.metadata["full_text_extraction_success"]


def test_metadata_fields_present(monkeypatch, tmp_path):
    monkeypatch.setattr(af, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(af, "CACHE_PATH_PQ", str(tmp_path / "cache" / "article_text_cache.parquet"))
    monkeypatch.setattr(af, "CACHE_PATH_JSONL", str(tmp_path / "cache" / "article_text_cache.jsonl"))

    html = read_fixture("full_article.html")
    monkeypatch.setattr(af, "fetch_html", lambda url, session, timeout=15: html)
    item = RawTextItem(id="4", source="rss", published_at=datetime(2026,3,3,12,0), body="summary", url="http://example.com/full3")
    out = af.enrich_items([item])[0]

    for key in ["rss_summary", "content_type", "full_text_extraction_success", "article_word_count"]:
        assert key in out.metadata
    assert out.metadata["content_type"] == "full_article"
