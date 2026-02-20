from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple

from src.data.news_finnhub import fetch_market_news, fetch_company_news, normalize_news_item
from src.data.earnings_finnhub import fetch_earnings_calendar, normalize_earnings_item


@dataclass
class NarrativeBundle:
    asof_utc: str
    items: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Simple dedupe: by URL if present, else by (source,title).
    """
    seen = set()
    out = []
    for it in items:
        key = it.get("url") or (it.get("source"), it.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def build_narrative_bundle(
    watch_tickers: List[str],
    news_category: str = "general",
    news_limit: int = 30,
    ticker_news_limit: int = 10,
    earnings_days_ahead: int = 7,
) -> NarrativeBundle:
    # ---- News: general market ----
    items: List[Dict[str, Any]] = []
    market_news_raw = fetch_market_news(category=news_category, limit=news_limit)
    items += [normalize_news_item(x, channel="news") for x in market_news_raw]

    # ---- News: per ticker (last 1 day) ----
    today = date.today()
    yesterday = today - timedelta(days=1)
    for t in watch_tickers:
        raw = fetch_company_news(symbol=t, from_date=yesterday, to_date=today, limit=ticker_news_limit)
        items += [normalize_news_item(x, channel="ticker_news") for x in raw]

    # ---- Earnings: next N days ----
    to_dt = today + timedelta(days=earnings_days_ahead)
    earnings_raw = fetch_earnings_calendar(from_date=today, to_date=to_dt, symbol=None)
    items += [normalize_earnings_item(x) for x in earnings_raw]

    items = _dedupe_items(items)

    return NarrativeBundle(asof_utc=_utc_now_iso(), items=items)

def top_n_by_channel(items: list[dict], n: int = 20) -> dict[str, list[dict]]:
    """
    Returns dict with keys: news, ticker_news, earnings
    Keeps order as-is (assumes items already ranked).
    """
    out = {"news": [], "ticker_news": [], "earnings": []}
    for it in items:
        ch = (it.get("channel") or "").lower()
        if ch not in out:
            continue
        if len(out[ch]) < n:
            out[ch].append(it)
    return out

