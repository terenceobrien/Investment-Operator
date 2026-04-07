from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .finnhub_client import get_finnhub_client


def fetch_market_news(category: str = "general", limit: int = 30) -> List[Dict[str, Any]]:
    """
    Finnhub categories: general, forex, crypto, merger
    Returns raw Finnhub dicts.
    """
    client = get_finnhub_client()
    items = client.general_news(category, min_id=0) or []
    return items[:limit]


def fetch_company_news(symbol: str, from_date: date, to_date: date, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Company-specific news within date range.
    """
    client = get_finnhub_client()
    items = client.company_news(symbol, _from=from_date.isoformat(), to=to_date.isoformat()) or []
    return items[:limit]


def normalize_news_item(item: Dict[str, Any], channel: str = "news") -> Dict[str, Any]:
    """
    Normalizes Finnhub news items into a consistent schema.
    Finnhub fields typically: datetime (unix), headline, summary, source, url, image, related
    """
    ts = item.get("datetime")  # unix seconds
    related = item.get("related") or ""  # sometimes comma-separated tickers

    tickers = [t.strip().upper() for t in related.split(",") if t.strip()] if isinstance(related, str) else []

    return {
        "channel": channel,
        "source": item.get("source"),
        "timestamp_utc": ts,
        "title": item.get("headline"),
        "summary": item.get("summary"),
        "tickers": tickers,
        "url": item.get("url"),
        "raw": item,  # keep raw for audit/debug
    }
