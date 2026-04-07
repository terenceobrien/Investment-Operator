from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.narrative.schema import NarrativeStateV1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_str_from_iso(iso_ts: Optional[str]) -> str:
    if not iso_ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def narrative_snapshot_path(base_dir: str | Path, date_str: str) -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"narrative_state_{date_str}.json"


def save_narrative_snapshot(
    state: Dict[str, Any],
    base_dir: str | Path = "data/snapshots",
    date_str: Optional[str] = None,
) -> Path:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = narrative_snapshot_path(base_dir, date_str)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def load_latest_narrative_snapshot(
    base_dir: str | Path = "data/snapshots",
    today_date_str: Optional[str] = None,
    max_lookback_days: int = 14,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    today = datetime.strptime(today_date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"), "%Y-%m-%d").date()

    for i in range(1, max_lookback_days + 1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        p = narrative_snapshot_path(base_dir, d)
        if p.exists():
            try:
                return d, json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

    return None, None


def _normalize_title(x: Any) -> str:
    s = str(x or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return s


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
        "raw_date": (it.get("raw") or {}).get("date"),
    }


def _item_key(it: Dict[str, Any]) -> str:
    url = it.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    src = str(it.get("source") or "")
    return f"{src}::{_normalize_title(it.get('title'))}"


def _age_hours(it: Dict[str, Any], now_utc: datetime) -> Optional[float]:
    ts = it.get("timestamp_utc")
    if isinstance(ts, (int, float)) and ts > 0:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return max(0.0, (now_utc - dt).total_seconds() / 3600.0)
    return None


def _event_keyword_score(it: Dict[str, Any]) -> float:
    text = f"{it.get('title') or ''} {it.get('summary') or ''}".lower()
    keywords = [
        "cpi", "pce", "fomc", "fed", "rate", "yields", "treasury",
        "guidance", "earnings", "downgrade", "upgrade", "warning", "miss", "beat",
        "tariff", "sanction", "ceasefire", "opec", "ai", "semiconductor",
        "buyback", "issuance", "default", "bank", "liquidity",
    ]
    hits = sum(1 for k in keywords if k in text)
    return min(2.0, 0.35 * hits)


def _prior_evidence_keys(prior_state: Optional[Dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    if not prior_state:
        return out

    for n in prior_state.get("dominant_narratives", []) or []:
        for e in n.get("evidence", []) or []:
            key = e.get("url") or _normalize_title(e.get("title"))
            if key:
                out.add(str(key))
    return out


def _summarize_market_moves(market_moves: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    moves = market_moves or []
    clean = []
    for m in moves:
        try:
            clean.append(
                {
                    "ticker": str(m.get("ticker") or "").upper(),
                    "chg_pct_1d": float(m.get("chg_pct_1d")),
                    "last": float(m.get("last")),
                }
            )
        except Exception:
            continue

    if not clean:
        return {"top_up": [], "top_down": []}

    clean.sort(key=lambda x: x["chg_pct_1d"], reverse=True)
    return {
        "top_up": clean[:5],
        "top_down": list(reversed(clean[-5:])),
    }


def _dedupe_and_rank(
    items: List[Dict[str, Any]],
    prior_evidence_keys: set[str],
    watch_tickers: set[str],
    lookback_hours: int,
    limit: int = 80,
    per_channel_cap: int = 35,
) -> List[Dict[str, Any]]:
    """
    Rank items for LLM synthesis with emphasis on incremental (today) changes:
      - recency
      - novelty vs prior snapshot evidence
      - watchlist ticker relevance
      - event keyword density
    """
    seen = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = _item_key(it)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    now_utc = datetime.now(timezone.utc)

    def score(it: Dict[str, Any]) -> float:
        ch = (it.get("channel") or "").lower()
        base = {
            "ticker_news": 2.0,
            "news": 1.2,
            "earnings": 1.7,
        }.get(ch, 0.5)

        age_h = _age_hours(it, now_utc)
        recency = 0.0
        if age_h is not None:
            if age_h <= 6:
                recency = 3.0
            elif age_h <= 24:
                recency = 2.0
            elif age_h <= 48:
                recency = 1.2
            elif age_h <= 72:
                recency = 0.6
            else:
                recency = -0.5
            if age_h > lookback_hours:
                recency -= 0.75

        novelty = 1.6 if _item_key(it) not in prior_evidence_keys else -0.5

        tks = {str(t).upper() for t in (it.get("tickers") or []) if str(t).strip()}
        overlap = len(tks.intersection(watch_tickers))
        ticker_relevance = min(1.5, 0.4 * overlap)

        content_quality = 0.35 if it.get("summary") else 0.0
        eventness = _event_keyword_score(it)

        return base + recency + novelty + ticker_relevance + content_quality + eventness

    ranked = []
    for it in uniq:
        it2 = dict(it)
        sc = score(it2)
        age_h = _age_hours(it2, now_utc)
        it2["_meta"] = {
            "rank_score": round(sc, 3),
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "is_new_vs_prior": _item_key(it2) not in prior_evidence_keys,
        }
        ranked.append(it2)

    ranked.sort(key=lambda x: x["_meta"]["rank_score"], reverse=True)

    selected: List[Dict[str, Any]] = []
    channel_counts = {"news": 0, "ticker_news": 0, "earnings": 0}
    for it in ranked:
        ch = (it.get("channel") or "").lower()
        if ch in channel_counts and channel_counts[ch] >= per_channel_cap:
            continue
        selected.append(it)
        if ch in channel_counts:
            channel_counts[ch] += 1
        if len(selected) >= limit:
            break

    return selected


def synthesize_narrative_state(
    bundle: Dict[str, Any],
    market_state_summary: Optional[Dict[str, Any]] = None,
    market_moves: Optional[List[Dict[str, Any]]] = None,
    prior_state: Optional[Dict[str, Any]] = None,
    max_items: int = 80,
    lookback_hours: int = 36,
    model: str = "gpt-4o",
) -> Dict[str, Any]:
    """
    Returns a JSON dict matching NarrativeStateV1,
    with stronger delta-aware prompting and item filtering.
    """
    raw_items = bundle.get("items") or []
    watch_tickers = {str(x).upper() for x in (bundle.get("watch_tickers") or [])}
    compact = [_compact_item(it) for it in raw_items]

    prior_keys = _prior_evidence_keys(prior_state)
    selected_items = _dedupe_and_rank(
        compact,
        prior_evidence_keys=prior_keys,
        watch_tickers=watch_tickers,
        lookback_hours=lookback_hours,
        limit=max_items,
    )

    prior_titles = []
    prior_asof = None
    prior_summary = None
    if prior_state:
        prior_titles = [n.get("title") for n in (prior_state.get("dominant_narratives") or []) if n.get("title")]
        prior_asof = prior_state.get("asof_utc")
        prior_summary = prior_state.get("one_paragraph_summary")

    system = (
        "You are a senior portfolio manager writing a daily narrative delta note for an investment team. "
        "Assume baseline market context is already known. "
        "Your task is to isolate what changed today, why it changed, and how that maps to observed moves. "
        "Avoid generic macro recaps unless the regime itself changed today. "
        "Ground every claim in provided evidence; if linkage to price action is weak, state that explicitly."
    )

    payload = {
        "asof_utc": bundle.get("asof_utc") or _utc_now_iso(),
        "lookback_hours": int(lookback_hours),
        "market_state": market_state_summary or {},
        "market_moves": _summarize_market_moves(market_moves),
        "prior_context": {
            "asof_utc": prior_asof,
            "summary": prior_summary,
            "dominant_titles": prior_titles,
        },
        "items": selected_items,
        "instructions": {
            "one_paragraph_summary": "Start with today's net delta vs prior context in 3-6 sentences.",
            "dominant_narratives": (
                "Return 1-4 narratives. Each 'why_now' must explicitly identify what is new today "
                "and how it plausibly maps to top_up/top_down moves."
            ),
            "raw_takeaways": (
                "3-8 bullets, each focused on an incremental change today. "
                "Prefix each bullet with one of: CHANGE, CONFIRMATION, INVALIDATION, or UNCLEAR."
            ),
            "counter_narratives": "List serious alternative explanations; avoid strawmen.",
            "unknowns": "List unresolved data points that would change sizing or conviction.",
            "style": "concise, PM desk note, no fluff",
        },
    }

    from openai import OpenAI
    client = OpenAI()
    resp = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ],
        response_format=NarrativeStateV1,
    )
    out = resp.choices[0].message.parsed.model_dump()
    out["_meta"] = {
        "total_items_in_bundle": len(raw_items),
        "items_selected_for_llm": len(selected_items),
        "lookback_hours": int(lookback_hours),
        "prior_snapshot_found": bool(prior_state),
    }
    return out
