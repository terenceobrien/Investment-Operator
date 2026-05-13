from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

UNIVERSE_DIR = Path(__file__).resolve().parents[2] / "data" / "universe"
UNIVERSE_FILES = (
    ("S&P 500", UNIVERSE_DIR / "sp500.csv"),
    ("Nasdaq-100", UNIVERSE_DIR / "nasdaq100.csv"),
)

TICKER_ALIASES: Dict[str, str] = {
    "BRK.B": "BRK-B",
    "BRK/B": "BRK-B",
    "BF.B": "BF-B",
    "BF/B": "BF-B",
}


def normalize_ticker(value: str | None) -> str:
    ticker = re.sub(r"\s+", "", str(value or "").strip().upper())
    ticker = TICKER_ALIASES.get(ticker, ticker)
    return ticker


def _split_memberships(value: str | None, fallback: str) -> Set[str]:
    raw = str(value or fallback)
    return {part.strip() for part in re.split(r"[|,;]", raw) if part.strip()}


def _clean_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


@lru_cache(maxsize=1)
def _load_universe() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {
        "SPY": {
            "ticker": "SPY",
            "company_name": "S&P 500 ETF",
            "index_memberships": ["Broad Market"],
            "sector": "Broad Market",
            "industry": "Large Cap Blend",
            "exchange": "NYSEARCA",
        }
    }

    for fallback_membership, path in UNIVERSE_FILES:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ticker = normalize_ticker(row.get("ticker"))
                if not ticker:
                    continue
                memberships = _split_memberships(row.get("index_memberships"), fallback_membership)
                existing = out.get(ticker)
                if existing:
                    existing_memberships = set(existing.get("index_memberships") or [])
                    existing["index_memberships"] = sorted(existing_memberships | memberships)
                    for key in ("company_name", "sector", "industry", "exchange"):
                        if not existing.get(key) and row.get(key):
                            existing[key] = _clean_name(row.get(key))
                    continue

                out[ticker] = {
                    "ticker": ticker,
                    "company_name": _clean_name(row.get("company_name")),
                    "index_memberships": sorted(memberships),
                    "sector": _clean_name(row.get("sector")),
                    "industry": _clean_name(row.get("industry")),
                    "exchange": _clean_name(row.get("exchange")),
                }

    # GOOG and GOOGL can both appear in public index files. If only one exists,
    # keep the other as a supported alias to avoid user confusion.
    if "GOOGL" in out and "GOOG" not in out:
        goog = dict(out["GOOGL"])
        goog["ticker"] = "GOOG"
        goog["company_name"] = "Alphabet Class C"
        out["GOOG"] = goog
    elif "GOOG" in out and "GOOGL" not in out:
        googl = dict(out["GOOG"])
        googl["ticker"] = "GOOGL"
        googl["company_name"] = "Alphabet Class A"
        out["GOOGL"] = googl

    return out


def get_supported_tickers() -> Set[str]:
    return set(_load_universe().keys())


def is_supported_ticker(ticker: str | None) -> bool:
    return normalize_ticker(ticker) in _load_universe()


def get_universe_metadata(ticker: str | None) -> Optional[Dict[str, Any]]:
    normalized = normalize_ticker(ticker)
    meta = _load_universe().get(normalized)
    return dict(meta) if meta else None


def all_universe_metadata() -> Iterable[Dict[str, Any]]:
    return (dict(v) for v in _load_universe().values())
