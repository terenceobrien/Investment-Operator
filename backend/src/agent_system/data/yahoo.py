"""Best-effort Yahoo Finance retrieval through yfinance."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from src.agent_system.data.cache import cache_get, cache_set
from src.agent_system.data.types import EarningsRecord

logger = logging.getLogger("agent_system.data.yahoo")

_USABLE_INFO_KEYS = {
    "symbol",
    "shortName",
    "longName",
    "quoteType",
    "currentPrice",
    "regularMarketPrice",
    "marketCap",
    "trailingPE",
    "forwardPE",
    "targetMeanPrice",
}


def _has_usable_info(raw: dict) -> bool:
    return any(raw.get(key) is not None for key in _USABLE_INFO_KEYS)


def fetch_yahoo_data(ticker: str, *, force_refresh: bool = False) -> dict:
    """Return yfinance ticker info, or an empty dict when Yahoo is unavailable."""

    key = ticker.strip().upper()
    if not force_refresh:
        cached = cache_get("yahoo_info", key, timedelta(minutes=5))
        if isinstance(cached, dict) and _has_usable_info(cached):
            return cached
    try:
        import yfinance as yf

        raw = yf.Ticker(key).info
        if isinstance(raw, dict) and _has_usable_info(raw):
            cache_set("yahoo_info", key, raw)
            return raw
    except Exception as exc:
        logger.warning("Yahoo info fetch failed for %s: %s", key, exc)
    return {}


def _number(raw: dict, *keys: str) -> float | None:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def parse_yahoo_data(raw_info: dict) -> dict:
    """Extract fields consumed by :class:`FundamentalDataBundle`."""

    opinion_count = raw_info.get("numberOfAnalystOpinions")
    recommendation = str(raw_info.get("recommendationKey", "")).lower()
    buys: int | None = None
    holds: int | None = None
    sells: int | None = None
    if isinstance(opinion_count, int) and opinion_count >= 0:
        if recommendation in {"buy", "strong_buy", "strongbuy"}:
            buys, holds, sells = opinion_count, 0, 0
        elif recommendation == "hold":
            buys, holds, sells = 0, opinion_count, 0
        elif recommendation in {"sell", "strong_sell", "strongsell"}:
            buys, holds, sells = 0, 0, opinion_count

    return {
        "current_price": _number(raw_info, "currentPrice", "regularMarketPrice"),
        "market_cap": _number(raw_info, "marketCap"),
        "trailing_pe": _number(raw_info, "trailingPE"),
        "forward_pe": _number(raw_info, "forwardPE"),
        "price_to_sales": _number(raw_info, "priceToSalesTrailing12Months"),
        "enterprise_value": _number(raw_info, "enterpriseValue"),
        "ev_to_ebitda": _number(raw_info, "enterpriseToEbitda"),
        "analyst_count_buy": buys,
        "analyst_count_hold": holds,
        "analyst_count_sell": sells,
        "mean_price_target": _number(raw_info, "targetMeanPrice"),
        "sector": (
            raw_info.get("sector") if isinstance(raw_info.get("sector"), str) else None
        ),
        "industry": (
            raw_info.get("industry")
            if isinstance(raw_info.get("industry"), str)
            else None
        ),
        "is_etf": str(raw_info.get("quoteType", "")).upper() == "ETF",
    }


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        try:
            return value.date()
        except TypeError:
            pass
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or str(value).lower() == "nan":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_earnings_history(
    ticker: str,
    max_count: int = 8,
    *,
    force_refresh: bool = False,
) -> list[EarningsRecord]:
    """Return recent historical earnings records from yfinance when available."""

    key = f"{ticker.strip().upper()}_{max_count}"
    if not force_refresh:
        cached = cache_get("yahoo_earnings", key, timedelta(days=1))
        if cached is not None:
            try:
                return [EarningsRecord.model_validate(item) for item in cached]
            except Exception:
                pass
    try:
        import yfinance as yf

        history = yf.Ticker(ticker.strip().upper()).earnings_history
        if history is None or getattr(history, "empty", True):
            return []
        records: list[EarningsRecord] = []
        rows = history.sort_index(ascending=False).head(max_count)
        for index, row in rows.iterrows():
            report_date = _as_date(row.get("reportedDate", index))
            if report_date is None:
                continue
            records.append(
                EarningsRecord(
                    report_date=report_date,
                    period_end=_as_date(row.get("periodEnd")),
                    eps_actual=_optional_float(row.get("epsActual")),
                    eps_estimate=_optional_float(row.get("epsEstimate")),
                    surprise_pct=_optional_float(row.get("surprisePercent")),
                )
            )
        cache_set(
            "yahoo_earnings",
            key,
            [record.model_dump(mode="json") for record in records],
        )
        return records
    except Exception as exc:
        logger.warning("Yahoo earnings-history fetch failed for %s: %s", ticker, exc)
        return []
