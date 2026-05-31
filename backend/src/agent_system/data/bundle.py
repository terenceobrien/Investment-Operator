"""Public composition entry point for SEC and Yahoo fundamental data."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from src.agent_system.data.sec import (
    fetch_company_facts,
    fetch_most_recent_filing,
    fetch_recent_8ks,
    fetch_submissions,
    parse_company_facts,
    ticker_to_cik,
)
from src.agent_system.data.types import FundamentalDataBundle
from src.agent_system.data.yahoo import (
    fetch_earnings_history,
    fetch_yahoo_data,
    parse_yahoo_data,
)

logger = logging.getLogger("agent_system.data.bundle")

_EMPTY_YAHOO = {
    "current_price": None,
    "market_cap": None,
    "trailing_pe": None,
    "forward_pe": None,
    "price_to_sales": None,
    "enterprise_value": None,
    "ev_to_ebitda": None,
    "analyst_count_buy": None,
    "analyst_count_hold": None,
    "analyst_count_sell": None,
    "mean_price_target": None,
    "sector": None,
    "industry": None,
    "is_etf": False,
}


def get_fundamental_data(
    ticker: str,
    force_refresh: bool = False,
) -> FundamentalDataBundle:
    """
    Fetch a complete fundamental bundle for one ticker without raising.

    SEC and Yahoo are independent data sources: either can fail while the
    other still populates a usable partial bundle.
    """

    started = time.monotonic()
    normalized_ticker = str(ticker).strip().upper()
    errors: list[str] = []

    raw_yahoo: dict = {}
    earnings_history = []
    try:
        raw_yahoo = fetch_yahoo_data(
            normalized_ticker, force_refresh=force_refresh
        )
    except Exception as exc:
        logger.warning("Unexpected Yahoo info failure for %s: %s", normalized_ticker, exc)
        errors.append(f"Yahoo info fetch failed: {exc}")
    if raw_yahoo:
        try:
            yahoo_values = parse_yahoo_data(raw_yahoo)
        except Exception as exc:
            yahoo_values = dict(_EMPTY_YAHOO)
            errors.append(f"Yahoo data parsing failed: {exc}")
    else:
        yahoo_values = dict(_EMPTY_YAHOO)
        errors.append("Yahoo info unavailable")

    try:
        earnings_history = fetch_earnings_history(
            normalized_ticker, force_refresh=force_refresh
        )
    except Exception as exc:
        logger.warning(
            "Unexpected Yahoo earnings failure for %s: %s", normalized_ticker, exc
        )
        errors.append(f"Yahoo earnings history fetch failed: {exc}")

    yahoo_success = bool(earnings_history) or bool(yahoo_values["is_etf"]) or any(
        yahoo_values[key] is not None
        for key in _EMPTY_YAHOO
        if key != "is_etf"
    )
    if raw_yahoo and not yahoo_success:
        errors.append("Yahoo response contained no usable quote data")
    is_etf = bool(yahoo_values["is_etf"])
    if is_etf:
        yahoo_values.update(
            {
                "analyst_count_buy": None,
                "analyst_count_hold": None,
                "analyst_count_sell": None,
                "mean_price_target": None,
            }
        )
        return FundamentalDataBundle(
            ticker=normalized_ticker,
            as_of=datetime.now(timezone.utc),
            is_etf=True,
            cik=None,
            company_name=None,
            most_recent_10k=None,
            most_recent_10q=None,
            recent_8ks=[],
            company_facts=None,
            earnings_history=earnings_history,
            sec_fetch_success=False,
            yahoo_fetch_success=yahoo_success,
            fetch_errors=errors,
            fetch_duration_ms=int((time.monotonic() - started) * 1000),
            **{key: yahoo_values[key] for key in _EMPTY_YAHOO if key != "is_etf"},
        )

    cik = None
    company_name = None
    most_recent_10k = None
    most_recent_10q = None
    recent_8ks = []
    company_facts = None
    sec_success = False

    try:
        cik = ticker_to_cik(normalized_ticker, force_refresh=force_refresh)
        if cik is None:
            errors.append("SEC CIK lookup unavailable")
        else:
            submissions = fetch_submissions(cik, force_refresh=force_refresh)
            raw_facts = fetch_company_facts(cik, force_refresh=force_refresh)
            if submissions:
                sec_success = True
                company_name = submissions.get("name")
                most_recent_10k = fetch_most_recent_filing(
                    submissions, ["10-K"], force_refresh=force_refresh
                )
                most_recent_10q = fetch_most_recent_filing(
                    submissions, ["10-Q"], force_refresh=force_refresh
                )
                recent_8ks = fetch_recent_8ks(
                    submissions, force_refresh=force_refresh
                )
                if most_recent_10k and most_recent_10k.extracted_text is None:
                    errors.append("SEC annual filing text unavailable")
                if most_recent_10q and most_recent_10q.extracted_text is None:
                    errors.append("SEC quarterly filing text unavailable")
                if any(filing.extracted_text is None for filing in recent_8ks):
                    errors.append("One or more SEC current-report texts unavailable")
            else:
                errors.append("SEC submissions unavailable")
            if raw_facts:
                sec_success = True
                company_name = company_name or raw_facts.get("entityName")
                company_facts = parse_company_facts(raw_facts)
            else:
                errors.append("SEC company facts unavailable")
    except Exception as exc:
        logger.warning("Unexpected SEC failure for %s: %s", normalized_ticker, exc)
        errors.append(f"SEC fetch failed: {exc}")

    return FundamentalDataBundle(
        ticker=normalized_ticker,
        as_of=datetime.now(timezone.utc),
        is_etf=False,
        cik=cik,
        company_name=company_name,
        most_recent_10k=most_recent_10k,
        most_recent_10q=most_recent_10q,
        recent_8ks=recent_8ks,
        company_facts=company_facts,
        earnings_history=earnings_history,
        sec_fetch_success=sec_success,
        yahoo_fetch_success=yahoo_success,
        fetch_errors=errors,
        fetch_duration_ms=int((time.monotonic() - started) * 1000),
        **{key: yahoo_values[key] for key in _EMPTY_YAHOO if key != "is_etf"},
    )
