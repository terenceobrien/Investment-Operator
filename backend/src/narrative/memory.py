from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agent_system.paths import narrative_memory_dir

logger = logging.getLogger("narrative.memory")

MEMORY_DIR = narrative_memory_dir(create=False)


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _extract_watchpoints(output: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    items.extend(str(x) for x in _safe_list(output.get("unknowns")) if x)
    for theme in _safe_list(output.get("dominant_narratives")):
        if not isinstance(theme, dict):
            continue
        items.extend(str(x) for x in _safe_list(theme.get("risks_to_watch")) if x)
        items.extend(str(x) for x in _safe_list(theme.get("what_would_change")) if x)
    seen = set()
    out: List[str] = []
    for item in items:
        key = item[:100].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= 8:
            break
    return out


def _extract_falsifiers(output: Dict[str, Any]) -> List[str]:
    items: List[str] = []
    for row in _safe_list(output.get("inefficiency_map")):
        if isinstance(row, dict) and row.get("falsifier"):
            items.append(str(row["falsifier"]))
    for takeaway in _safe_list(output.get("raw_takeaways")):
        text = str(takeaway or "")
        if text.upper().startswith(("FALSIFIER", "INVALIDATION")):
            items.append(text.split(":", 1)[-1].strip())
    return list(dict.fromkeys([x for x in items if x]))[:8]


def memory_path(ticker: str, asof_date: str) -> Path:
    return MEMORY_DIR / ticker.upper().strip() / f"{asof_date}.json"


def build_memory_record(cache_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    output = cache_record.get("output")
    if not isinstance(output, dict):
        return None
    meta = output.get("_meta") if isinstance(output.get("_meta"), dict) else {}
    subject = cache_record.get("subject") or meta.get("subject") or {}
    ticker = str((subject or {}).get("ticker") or cache_record.get("ticker") or "").upper().strip()
    asof_date = str(cache_record.get("asof_date") or "")[:10]
    if not ticker or not asof_date:
        return None

    price_context = meta.get("price_context") or {}
    if not price_context:
        price_context = {
            "summary": cache_record.get("metadata", {}).get("price_context_active"),
            "ledgers": (meta.get("information_ledgers") or {}).get("price_ledger", []),
        }

    return {
        "ticker": ticker,
        "subject": subject,
        "asof_date": asof_date,
        "generated_at": cache_record.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        "prompt_version": cache_record.get("prompt_version"),
        "final_model": cache_record.get("final_model"),
        "executive_snapshot": output.get("executive_snapshot") or {},
        "inefficiency_map": output.get("inefficiency_map") or [],
        "price_summary": output.get("price_summary") or {},
        "top_falsifiers": _extract_falsifiers(output),
        "top_watchpoints": _extract_watchpoints(output),
        "initial_price_context": price_context,
        "outcomes": {
            "1d": None,
            "5d": None,
            "20d": None,
        },
        "falsifier_status": "pending",
        "resolution_type": None,
    }


def save_memory_record(cache_record: Dict[str, Any]) -> Optional[Path]:
    try:
        record = build_memory_record(cache_record)
        if not record:
            return None
        path = memory_path(str(record["ticker"]), str(record["asof_date"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return path
    except Exception as exc:
        logger.warning("Failed to save narrative memory record: %s", exc, exc_info=True)
        return None
