from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from .finnhub_client import get_finnhub_client


def fetch_earnings_calendar(from_date: date, to_date: date, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Returns earnings events within a window.
    Uses positional args to avoid keyword issues with 'from'.
    """
    client = get_finnhub_client()

    symbol_arg = symbol if symbol else ""

    resp = client.earnings_calendar(
        from_date.isoformat(),
        to_date.isoformat(),
        symbol_arg
    ) or {}

    return resp.get("earningsCalendar") or []


def normalize_earnings_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes earnings calendar items.
    Typical fields: date, epsActual, epsEstimate, hour, quarter, revenueActual, revenueEstimate, symbol, year
    """
    symbol = (item.get("symbol") or "").upper()

    # Build a compact headline-ish title
    title = f"{symbol} earnings"
    if item.get("hour"):
        title += f" ({item.get('hour')})"

    # Put numeric context in summary for the LLM
    summary_parts = []
    for k in ["epsEstimate", "epsActual", "revenueEstimate", "revenueActual", "quarter", "year"]:
        if item.get(k) is not None:
            summary_parts.append(f"{k}={item.get(k)}")
    summary = ", ".join(summary_parts) if summary_parts else None

    # Finnhub gives date as yyyy-mm-dd (session date)
    return {
        "channel": "earnings",
        "source": "Finnhub",
        "timestamp_utc": None,  # calendar item is date-based; keep null
        "title": title,
        "summary": summary,
        "tickers": [symbol] if symbol else [],
        "url": None,
        "raw": item,
    }
