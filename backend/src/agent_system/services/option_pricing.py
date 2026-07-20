"""Best-effort option description parsing and yfinance chain pricing."""
from __future__ import annotations

import calendar
import re
import time
from datetime import date
from typing import Optional


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def _third_friday(year: int, month: int) -> str:
    fridays = [
        day
        for day in range(1, calendar.monthrange(year, month)[1] + 1)
        if date(year, month, day).weekday() == 4
    ]
    return date(year, month, fridays[2]).isoformat()


def parse_option_from_description(description: str) -> Optional[dict]:
    """Parse an option description into structured fields."""

    pattern = re.compile(
        r"(?P<direction>\blong\b|\bshort\b)?\s*"
        r"(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"[a-z]*\s+"
        r"(?P<year>\d{4})\s+"
        r"\$(?P<strike1>\d+(?:\.\d+)?)"
        r"(?:\s*/\s*\$?(?P<strike2>\d+(?:\.\d+)?))?\s+"
        r"(?P<option>call|put)s?"
        r"(?:\s+(?P<spread>spread))?",
        re.IGNORECASE,
    )
    match = pattern.search(description or "")
    if not match:
        return None

    month = MONTHS.get(match.group("month").lower())
    if month is None:
        return None
    year = int(match.group("year"))
    strikes = [float(match.group("strike1"))]
    if match.group("strike2") is not None:
        strikes.append(float(match.group("strike2")))

    option = match.group("option").lower()
    option_type = option
    if len(strikes) == 2 or match.group("spread"):
        option_type = f"{option}_spread"

    return {
        "expiry": _third_friday(year, month),
        "strikes": strikes,
        "option_type": option_type,
        "direction": (match.group("direction") or "long").lower(),
    }


def _mid_for_strike(chain, strike: float) -> Optional[float]:
    if chain is None or getattr(chain, "empty", False):
        return None
    rows = chain.loc[(chain["strike"].astype(float) - float(strike)).abs() < 0.001]
    if rows.empty:
        return None
    row = rows.iloc[0]
    bid = row.get("bid")
    ask = row.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return float((bid + ask) / 2.0)
    last_price = row.get("lastPrice")
    if last_price is not None and last_price > 0:
        return float(last_price)
    return None


def _option_chain(underlying: str, expiry: str):
    import yfinance as yf

    return yf.Ticker(underlying).option_chain(expiry)


def fetch_option_chain_price(
    underlying: str,
    expiry: str,
    strikes: list[float],
    option_type: str,
) -> Optional[float]:
    """Fetch current mid-price for an option or spread from yfinance."""

    for attempt in range(2):
        try:
            chain = _option_chain(underlying, expiry)
            table = chain.calls if option_type.startswith("call") else chain.puts
            if option_type in {"call", "put"}:
                if len(strikes) != 1:
                    return None
                return _mid_for_strike(table, strikes[0])

            if len(strikes) != 2:
                return None
            lower, higher = sorted(float(strike) for strike in strikes)
            if option_type == "call_spread":
                long_mid = _mid_for_strike(table, lower)
                short_mid = _mid_for_strike(table, higher)
            elif option_type == "put_spread":
                long_mid = _mid_for_strike(table, higher)
                short_mid = _mid_for_strike(table, lower)
            else:
                return None
            if long_mid is None or short_mid is None:
                return None
            return float(long_mid - short_mid)
        except Exception:
            if attempt == 0:
                time.sleep(1.0)
                continue
    return None
