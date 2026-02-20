from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from src.narrative.schema import NarrativeStateV1

# Uses Responses API + Structured Outputs (JSON Schema)
# Docs: Structured Outputs guide and Responses API reference. :contentReference[oaicite:0]{index=0}

def get_openai_client():
    return OpenAI()

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """Strip raw payload + keep only what the LLM needs."""
    return {
        "channel": it.get("channel"),
        "source": it.get("source"),
        "timestamp_utc": it.get("timestamp_utc"),
        "title": it.get("title"),
        "summary": it.get("summary"),
        "tickers": it.get("tickers") or [],
        "url": it.get("url"),
    }


def _dedupe_and_rank(items: List[Dict[str, Any]], limit: int = 60) -> List[Dict[str, Any]]:
    """
    v1 heuristic:
      - dedupe by url or (source,title)
      - prefer earnings > ticker_news > news
      - prefer items with tickers and summaries
    """
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = it.get("url") or (it.get("source"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    def score(it: Dict[str, Any]) -> float:
        ch = (it.get("channel") or "").lower()
        base = 0.0
        if ch == "earnings":
            base += 3.0
        elif ch == "ticker_news":
            base += 2.0
        elif ch == "news":
            base += 1.0

        if it.get("tickers"):
            base += 0.7
        if it.get("summary"):
            base += 0.4

        # mild boost for recency if timestamp exists
        ts = it.get("timestamp_utc")
        if isinstance(ts, (int, float)) and ts > 0:
            base += 0.2
        return base

    uniq.sort(key=score, reverse=True)
    return uniq[:limit]


# JSON schema the model must follow
NARRATIVE_SCHEMA: Dict[str, Any] = {
    "name": "narrative_state_v1",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "asof_utc": {"type": "string"},
            "dominant_narratives": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "stance": {"type": "string", "enum": ["risk_on", "risk_off", "mixed"]},
                        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                        "why_now": {"type": "string"},
                        "key_catalysts": {
                            "type": "array",
                            "maxItems": 6,
                            "items": {"type": "string"},
                        },
                        "tickers": {
                            "type": "array",
                            "maxItems": 20,
                            "items": {"type": "string"},
                        },
                        "evidence": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 8,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "channel": {"type": "string"},
                                    "source": {"type": "string"},
                                    "title": {"type": "string"},
                                    "url": {"type": ["string", "null"]},
                                },
                                "required": ["channel", "source", "title", "url"],
                            },
                        },
                        "what_would_change": {
                            "type": "array",
                            "maxItems": 5,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["title", "stance", "confidence", "why_now", "key_catalysts", "tickers", "evidence", "what_would_change"],
                },
            },
            "market_tone": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "risk_appetite": {"type": "string", "enum": ["high", "medium", "low"]},
                    "fragility": {"type": "string", "enum": ["stable", "fragile", "very_fragile"]},
                    "positioning_guess": {"type": "string", "enum": ["clean", "crowded", "unclear"]},
                },
                "required": ["risk_appetite", "fragility", "positioning_guess"],
            },
            "signals": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "headline_intensity": {"type": "integer", "minimum": 0, "maximum": 100},
                    "earnings_intensity": {"type": "integer", "minimum": 0, "maximum": 100},
                    "macro_intensity": {"type": "integer", "minimum": 0, "maximum": 100},
                },
                "required": ["headline_intensity", "earnings_intensity", "macro_intensity"],
            },
            "one_paragraph_summary": {"type": "string"},
        },
        "required": ["asof_utc", "dominant_narratives", "market_tone", "signals", "one_paragraph_summary"],
    },
    "strict": True,
}


def synthesize_narrative_state(
    bundle: Dict[str, Any],
    market_state_summary: Optional[Dict[str, Any]] = None,
    max_items: int = 60,
    model: str = "gpt-4o-mini",
) -> Dict[str, Any]:
    """
    Returns a JSON dict matching NARRATIVE_SCHEMA.
    """
    raw_items = bundle.get("items") or []
    items = [_compact_item(it) for it in raw_items]
    items = _dedupe_and_rank(items, limit=max_items)

    system = (
        "You are a buy-side market narrative analyst. "
        "Your job is to infer the dominant story/stories shaping market behavior today. "
        "Be honest about uncertainty.  If there is no single dominant story, say so."
        "Do not list every headline. Cluster them into 1–3 narratives, optionally up to 5. "
        "Ground claims in the provided evidence items only. "
        "If evidence conflicts, mark stance='mixed' and lower confidence. "
        "Return a structured response in the requested format."
    )

    user_payload = {
        "asof_utc": bundle.get("asof_utc") or _utc_now_iso(),
        "items": items,
        "market_state": market_state_summary or {},
        "instructions": (
            "Produce: (1) one_paragraph_summary, (2) dominant_narratives (0–6), "
            "(3) raw_takeaways, (4) counter_narratives, (5) unknowns, "
            "(6) market_tone, (7) signals intensities. "
            "For each narrative, include takeaways and cite supporting evidence items where possible."
        ),
    }

    client = OpenAI()
    
    resp = client.responses.parse(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": str(user_payload)},
        ],
        text_format=NarrativeStateV1,
    )
    # The SDK returns parsed JSON in resp.output_text for simple cases, but safest is:
    return resp.output_parsed.model_dump()
