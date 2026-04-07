from __future__ import annotations
import os
import json
import re
from datetime import datetime
from hashlib import sha256
from typing import Optional, List, Dict

import pandas as pd
import requests
from trafilatura import extract

from narrative.sources.http import make_session
from narrative.sources.base import RawTextItem


CACHE_DIR = os.path.join("data", "narrative", "cache")
CACHE_PATH_PQ = os.path.join(CACHE_DIR, "article_text_cache.parquet")
CACHE_PATH_JSONL = os.path.join(CACHE_DIR, "article_text_cache.jsonl")


def _load_article_cache() -> Dict[str, Dict]:
    """Return mapping url_hash -> cache record."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache: Dict[str, Dict] = {}
    try:
        if os.path.exists(CACHE_PATH_PQ):
            df = pd.read_parquet(CACHE_PATH_PQ)
            for _, r in df.iterrows():
                cache[r["url_hash"]] = {
                    "url": r["url"],
                    "fetched_at": r.get("fetched_at"),
                    "extraction_success": bool(r.get("extraction_success")),
                    "extracted_text": r.get("extracted_text", ""),
                    "word_count": int(r.get("word_count", 0)),
                    "error": r.get("error", None),
                }
            return cache
    except Exception:
        pass
    # fallback jsonl
    if os.path.exists(CACHE_PATH_JSONL):
        with open(CACHE_PATH_JSONL, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    cache[obj["url_hash"]] = obj
                except Exception:
                    continue
    return cache


def _append_article_cache(new_entries: List[Dict]):
    if not new_entries:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        records = []
        for rec in new_entries:
            records.append({
                "url_hash": rec.get("url_hash"),
                "url": rec.get("url"),
                "fetched_at": rec.get("fetched_at"),
                "extraction_success": bool(rec.get("extraction_success")),
                "extracted_text": rec.get("extracted_text", ""),
                "word_count": int(rec.get("word_count", 0)),
                "error": rec.get("error", None),
            })
        df_new = pd.DataFrame.from_records(records)
        if os.path.exists(CACHE_PATH_PQ):
            try:
                df_old = pd.read_parquet(CACHE_PATH_PQ)
                df = pd.concat([df_old, df_new], ignore_index=True)
            except Exception:
                df = df_new
        else:
            df = df_new
        df = df.drop_duplicates(subset=["url_hash"], keep="first")
        df.to_parquet(CACHE_PATH_PQ, index=False)
        return
    except Exception:
        pass
    # fallback jsonl
    with open(CACHE_PATH_JSONL, "a", encoding="utf-8") as fh:
        for rec in new_entries:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def fetch_html(url: str, session: requests.Session, timeout: int = 15) -> Optional[str]:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code == 200 and resp.text:
            return resp.text
    except Exception:
        return None
    return None


def extract_article_text(html: str, url: Optional[str] = None) -> Optional[str]:
    try:
        txt = extract(html, url=url)
        return txt
    except Exception:
        return None


def enrich_item_with_full_text(item: RawTextItem, cache: Dict[str, Dict], session: requests.Session) -> RawTextItem:
    # preserve original summary
    item.metadata = item.metadata or {}
    item.metadata.setdefault("rss_summary", item.body)

    if not item.url:
        item.metadata["content_type"] = "rss_summary"
        item.metadata["full_text_extraction_success"] = False
        item.metadata["article_word_count"] = 0
        item.metadata["article_fetch_error"] = None
        return item

    url_hash = sha256(item.url.encode("utf-8")).hexdigest()
    if url_hash in cache:
        rec = cache[url_hash]
        if rec.get("extraction_success"):
            extracted = rec.get("extracted_text", "")
            item.body = extracted or item.body
            item.metadata["content_type"] = "full_article"
            item.metadata["full_text_extraction_success"] = True
            item.metadata["article_word_count"] = rec.get("word_count", 0)
            item.metadata["article_fetch_error"] = rec.get("error")
        else:
            item.metadata["content_type"] = "rss_summary"
            item.metadata["full_text_extraction_success"] = False
            item.metadata["article_word_count"] = rec.get("word_count", 0)
            item.metadata["article_fetch_error"] = rec.get("error")
        return item

    # not cached: try to fetch and extract
    rec: Dict[str, Any] = {
        "url_hash": url_hash,
        "url": item.url,
        "fetched_at": datetime.utcnow().isoformat(),
        "extraction_success": False,
        "extracted_text": "",
        "word_count": 0,
        "error": None,
    }

    html = None
    try:
        html = fetch_html(item.url, session)
        if html:
            txt = extract_article_text(html, url=item.url)
            if txt:
                clean = re.sub(r"\s+", " ", txt).strip()
                wc = len(clean.split())
                rec["word_count"] = wc
                if wc > 50 or len(clean) > 300:
                    item.body = clean
                    rec["extraction_success"] = True
                    rec["extracted_text"] = clean
                    item.metadata["content_type"] = "full_article"
                    item.metadata["full_text_extraction_success"] = True
                    item.metadata["article_word_count"] = wc
                    item.metadata["article_fetch_error"] = None
                else:
                    item.metadata["content_type"] = "rss_summary"
                    item.metadata["full_text_extraction_success"] = False
                    item.metadata["article_word_count"] = wc
                    item.metadata["article_fetch_error"] = "extracted text too short"
            else:
                item.metadata["content_type"] = "rss_summary"
                item.metadata["full_text_extraction_success"] = False
                item.metadata["article_word_count"] = 0
                item.metadata["article_fetch_error"] = "no extraction"
        else:
            item.metadata["content_type"] = "rss_summary"
            item.metadata["full_text_extraction_success"] = False
            item.metadata["article_word_count"] = 0
            item.metadata["article_fetch_error"] = "fetch failed"
    except Exception as e:  # noqa: BLE001
        item.metadata["content_type"] = "rss_summary"
        item.metadata["full_text_extraction_success"] = False
        item.metadata["article_word_count"] = 0
        item.metadata["article_fetch_error"] = str(e)
        rec["error"] = str(e)

    cache[url_hash] = rec
    return item


def enrich_items(items: List[RawTextItem]) -> List[RawTextItem]:
    if not items:
        return items
    cache = _load_article_cache()
    session = make_session()
    updated = []
    new_entries: List[Dict] = []
    for it in items:
        enriched = enrich_item_with_full_text(it, cache, session)
        updated.append(enriched)
    # append any new records (cache now contains all including old)
    # we can diff but simpler: write whole cache if new entries not empty
    # compute entries that weren't in original cache by checking a flag
    for v in cache.values():
        # existing records remain in cache; we simply persist everything
        new_entries.append(v)
    _append_article_cache(new_entries)
    return updated
