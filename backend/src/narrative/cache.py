"""
cache.py — File-based cache for narrative synthesis results.

Layout:
    {CACHE_DIR}/{TICKER}/{YYYY-MM-DD}.json

Each record bundles the synthesis output with model/prompt/source-version
metadata so cached outputs are auditable and roll automatically when the
versioning constants in config.py are bumped.

Contract: read/write helpers never raise — they log and return None on
failure. Callers can safely use them inside request paths.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from src.narrative.config import CACHE_DIR

logger = logging.getLogger("narrative.cache")


def _ticker_dir(ticker: str) -> Path:
    return CACHE_DIR / ticker.upper().strip()


def cache_path(ticker: str, date_str: str) -> Path:
    base = _ticker_dir(ticker)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{date_str}.json"


def load_cache(ticker: str, date_str: str) -> Optional[Dict[str, Any]]:
    p = cache_path(ticker, date_str)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to read cache %s: %s", p, exc)
        return None


def save_cache(ticker: str, date_str: str, record: Dict[str, Any]) -> Path:
    p = cache_path(ticker, date_str)
    p.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return p


def load_latest_cache(
    ticker: str, max_lookback_days: int = 14
) -> Optional[Dict[str, Any]]:
    """
    Find the most recent cached record for ticker.

    Used as the stale-fallback when today's generation fails — surfaces the
    last good read instead of crashing the page.
    """
    base = _ticker_dir(ticker)
    if not base.exists():
        return None
    files = sorted(base.glob("*.json"), reverse=True)
    for f in files[: max_lookback_days]:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Skipping unreadable cache %s: %s", f, exc)
            continue
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
        },
    }
