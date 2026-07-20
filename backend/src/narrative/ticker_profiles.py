from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from src.narrative.universe import (
    all_universe_metadata,
    get_supported_tickers as _universe_supported_tickers,
    get_universe_metadata,
    is_supported_ticker as _universe_is_supported_ticker,
    normalize_ticker as _universe_normalize_ticker,
)

MAGNIFICENT_7: List[str] = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]

TICKER_ALIASES: Dict[str, str] = {}

SECTOR_ETF_MAP: Dict[str, str] = {
    "information technology": "XLK",
    "technology": "XLK",
    "communication services": "XLC",
    "consumer discretionary": "XLY",
    "consumer staples": "XLP",
    "energy": "XLE",
    "financials": "XLF",
    "health care": "XLV",
    "healthcare": "XLV",
    "industrials": "XLI",
    "materials": "XLB",
    "real estate": "XLRE",
    "utilities": "XLU",
}

SECTOR_THEMES: Dict[str, List[str]] = {
    "information technology": ["enterprise spending", "AI adoption", "semiconductor cycle", "software demand", "margins"],
    "communication services": ["advertising demand", "engagement", "content spend", "AI investment", "regulation"],
    "consumer discretionary": ["consumer demand", "pricing", "margins", "rates sensitivity", "inventory cycle"],
    "consumer staples": ["pricing power", "volume trends", "input costs", "defensive demand"],
    "energy": ["oil prices", "natural gas", "capital discipline", "free cash flow", "geopolitics"],
    "financials": ["net interest margins", "credit quality", "capital markets", "loan growth", "regulation"],
    "health care": ["pipeline", "regulatory approvals", "utilization", "pricing", "patent cycle"],
    "industrials": ["orders", "backlog", "capex cycle", "supply chain", "infrastructure demand"],
    "materials": ["commodity prices", "China demand", "input costs", "volume trends"],
    "real estate": ["rates", "occupancy", "cap rates", "credit conditions", "leasing demand"],
    "utilities": ["rates", "regulated returns", "power demand", "defensive yield"],
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
    "QQQ": {
        "ticker": "QQQ",
        "name": "Nasdaq-100 ETF",
        "subject_type": "market",
        "sector": "Growth / Mega-cap Technology",
        "sector_etf": "XLK",
        "benchmark": "QQQ",
        "broad_market": "SPY",
        "peers": ["SPY", "XLK", "XLC", *MAGNIFICENT_7],
        "themes": [
            "Nasdaq-100",
            "mega-cap tech",
            "AI capex",
            "growth leadership",
            "duration sensitivity",
            "software demand",
            "semiconductor cycle",
        ],
        "company_aliases": ["QQQ", "Nasdaq 100", "Nasdaq-100", "mega-cap tech"],
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

SUPPORTED_TICKERS: Set[str] = set(TICKER_PROFILES.keys()) | set(_universe_supported_tickers())


def normalize_ticker(value: str | None) -> str:
    ticker = _universe_normalize_ticker(value)
    return TICKER_ALIASES.get(ticker, ticker)


def is_supported_ticker(ticker: str | None) -> bool:
    normalized = normalize_ticker(ticker)
    return normalized in TICKER_PROFILES or _universe_is_supported_ticker(normalized)


def _simple_company_alias(name: str) -> str:
    alias = re.sub(
        r"\b(incorporated|inc|corp|corporation|company|co|class\s+[abc]|plc|ltd|limited|holdings?|group|the)\b\.?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    alias = re.sub(r"[,.\s]+", " ", alias).strip()
    return alias or name


def _sector_etf(sector: str) -> str:
    key = str(sector or "").lower().strip()
    for needle, etf in SECTOR_ETF_MAP.items():
        if needle in key:
            return etf
    return "SPY"


def _sector_themes(sector: str, industry: str) -> List[str]:
    key = str(sector or "").lower().strip()
    themes: List[str] = []
    for needle, values in SECTOR_THEMES.items():
        if needle in key:
            themes.extend(values)
            break
    if industry:
        themes.insert(0, industry)
    return themes[:8] or [sector or "company fundamentals", "earnings", "guidance", "margins"]


def _auto_peers(ticker: str, sector: str, industry: str, max_peers: int = 8) -> List[str]:
    ticker_u = normalize_ticker(ticker)
    industry_l = str(industry or "").lower().strip()
    sector_l = str(sector or "").lower().strip()
    same_industry: List[str] = []
    same_sector: List[str] = []

    for meta in all_universe_metadata():
        peer = normalize_ticker(meta.get("ticker"))
        if not peer or peer == ticker_u:
            continue
        peer_industry = str(meta.get("industry") or "").lower().strip()
        peer_sector = str(meta.get("sector") or "").lower().strip()
        if industry_l and peer_industry == industry_l:
            same_industry.append(peer)
        elif sector_l and peer_sector == sector_l:
            same_sector.append(peer)

    out: List[str] = []
    seen: Set[str] = set()
    for peer in [*same_industry, *same_sector]:
        if peer not in seen:
            seen.add(peer)
            out.append(peer)
        if len(out) >= max_peers:
            break
    return out


def _auto_profile(ticker: str) -> Optional[Dict[str, Any]]:
    meta = get_universe_metadata(ticker)
    if not meta:
        return None
    ticker_u = normalize_ticker(meta.get("ticker"))
    name = str(meta.get("company_name") or ticker_u)
    sector = str(meta.get("sector") or "")
    industry = str(meta.get("industry") or "")
    memberships = list(meta.get("index_memberships") or [])
    sector_etf = _sector_etf(sector)
    growth_sector = sector_etf in {"XLK", "XLC", "XLY"} or "Nasdaq-100" in memberships
    simple_alias = _simple_company_alias(name)

    return {
        "ticker": ticker_u,
        "name": name,
        "subject_type": "ticker",
        "sector": sector,
        "industry": industry,
        "sector_etf": sector_etf,
        "benchmark": "QQQ" if growth_sector else "SPY",
        "broad_market": "SPY",
        "peers": _auto_peers(ticker_u, sector, industry),
        "themes": _sector_themes(sector, industry),
        "company_aliases": [x for x in [name, simple_alias] if x],
        "universe_memberships": memberships,
        "exchange": meta.get("exchange"),
    }


def get_ticker_profile(ticker: str | None) -> Optional[Dict[str, Any]]:
    normalized = normalize_ticker(ticker)
    profile = TICKER_PROFILES.get(normalized)
    if profile:
        merged = dict(profile)
        meta = get_universe_metadata(normalized)
        if meta:
            merged.setdefault("industry", meta.get("industry"))
            merged.setdefault("universe_memberships", meta.get("index_memberships"))
            merged.setdefault("exchange", meta.get("exchange"))
        return merged
    return _auto_profile(normalized)


def supported_ticker_label() -> str:
    return "S&P 500 and Nasdaq-100 constituents"


def get_supported_tickers() -> Set[str]:
    return set(_universe_supported_tickers()) | set(TICKER_PROFILES.keys())


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
        "ticker", "name", "subject_type", "sector", "industry", "sector_etf",
        "benchmark", "broad_market", "peers", "themes", "company_aliases",
        "universe_memberships", "exchange",
    )
    return {k: profile.get(k) for k in keys if profile.get(k) is not None}
