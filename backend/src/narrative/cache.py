"""
cache.py — File-based cache for narrative synthesis results.

Layout:
    {CACHE_DIR}/{TICKER}/{PROMPT_VERSION}/{YYYY-MM-DD}.json

Path-level prompt versioning is the primary invalidation mechanism: when
PROMPT_VERSION changes, the lookup automatically reads from a fresh
subdirectory and old records become unreachable without being deleted.
A defensive in-record version check is also performed in case a stale
record sneaks in via direct file write.

Each record bundles the synthesis output with model/prompt/source-version
metadata so cached outputs are auditable.

Contract: read/write helpers never raise — they log and return None on
failure. Callers can safely use them inside request paths.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.narrative.config import CACHE_DIR, PROMPT_VERSION

logger = logging.getLogger("narrative.cache")


def _ticker_dir(ticker: str, prompt_version: Optional[str] = None) -> Path:
    """Per-ticker, per-prompt-version cache directory."""
    return CACHE_DIR / ticker.upper().strip() / (prompt_version or PROMPT_VERSION)


def cache_path(
    ticker: str, date_str: str, prompt_version: Optional[str] = None,
) -> Path:
    base = _ticker_dir(ticker, prompt_version)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{date_str}.json"


def load_cache(
    ticker: str, date_str: str, prompt_version: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Load a cache record for (ticker, date) under the active prompt version.

    Returns None — and logs a warning — if the on-disk record's stored
    prompt_version does not match the active one (defense in depth on top of
    the path-level versioning).
    """
    p = cache_path(ticker, date_str, prompt_version)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to read cache %s: %s", p, exc)
        return None

    active = prompt_version or PROMPT_VERSION
    rec_version = rec.get("prompt_version")
    if rec_version and rec_version != active:
        logger.warning(
            "Cache prompt_version mismatch — file=%s record=%s active=%s; ignoring",
            p, rec_version, active,
        )
        return None
    return rec


def save_cache(
    ticker: str, date_str: str, record: Dict[str, Any],
    prompt_version: Optional[str] = None,
) -> Path:
    p = cache_path(ticker, date_str, prompt_version)
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return p


def load_latest_cache(
    ticker: str, max_lookback_days: int = 14,
    prompt_version: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Find the most recent cached record for (ticker, prompt_version).

    Scoped to the active prompt version so we never surface a v1 record as a
    stale fallback for a v3 page. Used as the stale fallback when today's
    generation fails.
    """
    base = _ticker_dir(ticker, prompt_version)
    if not base.exists():
        return None
    files = sorted(base.glob("*.json"), reverse=True)
    active = prompt_version or PROMPT_VERSION
    for f in files[: max_lookback_days]:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping unreadable cache %s: %s", f, exc)
            continue
        rec_version = rec.get("prompt_version")
        if rec_version and rec_version != active:
            # Path-level versioning should prevent this, but if mismatched
            # records ever appear we don't want to surface them silently.
            logger.warning(
                "Skipping cache with mismatched prompt_version — file=%s record=%s active=%s",
                f, rec_version, active,
            )
            continue
        return rec
    return None


def build_cache_record(
    ticker: str,
    asof_date: str,
    result: Dict[str, Any],
    *,
    final_model: str,
    preprocessing_model: str,
    prompt_version: str,
    source_config_version: str,
    input_snapshot_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Wrap a synthesis output into the canonical cache record shape.
    """
    meta = (result.get("_meta") or {}) if isinstance(result, dict) else {}
    ledgers = (meta.get("information_ledgers") or {}) if isinstance(meta, dict) else {}
    return {
        "subject": ticker.upper().strip(),
        "subject_type": "ticker",
        "asof_date": asof_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "final_model": final_model,
        "preprocessing_model": preprocessing_model,
        "prompt_version": prompt_version,
        "source_config_version": source_config_version,
        "input_snapshot_path": input_snapshot_path,
        "output": result,
        "metadata": {
            "source_count": meta.get("total_items_in_bundle"),
            "selected_count": meta.get("items_selected_for_llm"),
            "ledger_counts": meta.get("ledger_counts"),
            "price_context_active": bool(ledgers.get("price_ledger")),
            "inefficiency_taxonomy_version": meta.get("inefficiency_taxonomy_version"),
            "inefficiency_taxonomy_ids": meta.get("inefficiency_taxonomy_ids"),
        },
    }
