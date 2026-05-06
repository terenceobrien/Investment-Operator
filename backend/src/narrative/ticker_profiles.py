from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

MAGNIFICENT_7: List[str] = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]

TICKER_ALIASES: Dict[str, str] = {
    "GOOG": "GOOGL",
}

TICKER_PROFILES: Dict[str, Dict[str, Any]] = {
    "SPY": {
        "ticker": "SPY",
        "name": "S&P 500 ETF",
        "subject_type": "market",
        "sector": "Broad Market",
        "sector_etf": "SPY",
        "benchmark": "SPY",
        "broad_market": "SPY",
        "peers": ["QQQ", "IWM", "DIA", "TLT", "HYG"],
        "themes": ["S&P 500", "broad market", "risk appetite", "earnings breadth", "credit", "rates"],
        "company_aliases": ["SPY", "S&P 500", "S&P", "broad market"],
    },
    "AAPL": {
        "ticker": "AAPL",
        "name": "Apple",
        "subject_type": "ticker",
        "sector": "Technology / Consumer Hardware",
        "sector_etf": "XLK",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["MSFT", "GOOGL", "META", "AMZN"],
        "themes": ["iPhone", "services", "AI features", "China demand", "hardware cycle", "buybacks", "margins"],
        "company_aliases": ["Apple", "Apple Inc.", "iPhone"],
    },
    "MSFT": {
        "ticker": "MSFT",
        "name": "Microsoft",
        "subject_type": "ticker",
        "sector": "Technology / Software",
        "sector_etf": "XLK",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["GOOGL", "AMZN", "ORCL", "CRM", "NVDA"],
        "themes": ["Azure", "cloud", "AI capex", "Copilot", "enterprise software", "margins", "OpenAI"],
        "company_aliases": ["Microsoft", "Azure", "Copilot"],
    },
    "NVDA": {
        "ticker": "NVDA",
        "name": "Nvidia",
        "subject_type": "ticker",
        "sector": "Semiconductors",
        "sector_etf": "SMH",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["AMD", "AVGO", "TSM", "QCOM", "MSFT", "GOOGL"],
        "themes": ["AI accelerators", "data center", "GPU demand", "Blackwell", "semiconductors", "AI capex", "gross margins", "export controls"],
        "company_aliases": ["Nvidia", "NVIDIA", "GPU", "Blackwell"],
    },
    "AMZN": {
        "ticker": "AMZN",
        "name": "Amazon",
        "subject_type": "ticker",
        "sector": "Consumer Discretionary / Cloud",
        "sector_etf": "XLY",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["MSFT", "GOOGL", "WMT", "SHOP", "META"],
        "themes": ["AWS", "cloud", "e-commerce", "advertising", "retail margins", "AI capex", "consumer demand", "logistics"],
        "company_aliases": ["Amazon", "AWS", "Amazon Web Services"],
    },
    "GOOGL": {
        "ticker": "GOOGL",
        "name": "Alphabet",
        "subject_type": "ticker",
        "sector": "Communication Services / Internet",
        "sector_etf": "XLC",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["MSFT", "META", "AMZN", "AAPL"],
        "themes": ["Google Search", "advertising", "YouTube", "Google Cloud", "AI capex", "Gemini", "antitrust", "margins"],
        "company_aliases": ["Alphabet", "Google", "YouTube", "Gemini", "Google Cloud"],
    },
    "META": {
        "ticker": "META",
        "name": "Meta Platforms",
        "subject_type": "ticker",
        "sector": "Communication Services / Social Media",
        "sector_etf": "XLC",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["GOOGL", "SNAP", "PINS", "AMZN", "MSFT"],
        "themes": ["advertising", "Instagram", "Facebook", "Reels", "AI capex", "metaverse", "Reality Labs", "margins", "engagement"],
        "company_aliases": ["Meta", "Meta Platforms", "Facebook", "Instagram", "Reels", "Reality Labs"],
    },
    "TSLA": {
        "ticker": "TSLA",
        "name": "Tesla",
        "subject_type": "ticker",
        "sector": "Consumer Discretionary / Autos",
        "sector_etf": "XLY",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["GM", "F", "RIVN", "LCID", "BYDDF", "AAPL", "NVDA"],
        "themes": ["EV demand", "deliveries", "margins", "pricing", "FSD", "robotaxi", "energy storage", "China", "Elon Musk"],
        "company_aliases": ["Tesla", "Elon Musk", "EV", "FSD", "robotaxi"],
    },
}

SUPPORTED_TICKERS: Set[str] = set(TICKER_PROFILES.keys())


def normalize_ticker(value: str | None) -> str:
    ticker = (value or "").upper().strip()
    ticker = re.sub(r"\s+", "", ticker)
    return TICKER_ALIASES.get(ticker, ticker)


def is_supported_ticker(ticker: str | None) -> bool:
    return normalize_ticker(ticker) in SUPPORTED_TICKERS


def get_ticker_profile(ticker: str | None) -> Optional[Dict[str, Any]]:
    normalized = normalize_ticker(ticker)
    profile = TICKER_PROFILES.get(normalized)
    return dict(profile) if profile else None


def supported_ticker_label() -> str:
    return "SPY and the Magnificent 7 (AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA)"


def get_supported_tickers() -> List[str]:
    return ["SPY", *MAGNIFICENT_7]


def watch_tickers_for_profile(profile: Dict[str, Any]) -> List[str]:
    ordered = [
        profile.get("ticker"),
        profile.get("broad_market"),
        profile.get("benchmark"),
        profile.get("sector_etf"),
        *(profile.get("peers") or []),
    ]
    out: List[str] = []
    seen: Set[str] = set()
    for raw in ordered:
        ticker = normalize_ticker(str(raw or ""))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def profile_terms(profile: Dict[str, Any]) -> List[str]:
    terms: List[str] = []
    for key in ("ticker", "name", "sector", "sector_etf", "benchmark", "broad_market"):
        value = profile.get(key)
        if value:
            terms.append(str(value))
    terms.extend(str(x) for x in (profile.get("peers") or []))
    terms.extend(str(x) for x in (profile.get("themes") or []))
    terms.extend(str(x) for x in (profile.get("company_aliases") or []))

    seen: Set[str] = set()
    compact: List[str] = []
    for term in terms:
        normalized = term.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            compact.append(normalized)
    return compact


def prompt_subject_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "ticker", "name", "subject_type", "sector", "sector_etf",
        "benchmark", "broad_market", "peers", "themes", "company_aliases",
    )
    return {k: profile.get(k) for k in keys if profile.get(k) is not None}
