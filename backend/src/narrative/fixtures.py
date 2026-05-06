from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from src.narrative.ticker_profiles import (
    get_ticker_profile,
    normalize_ticker,
    prompt_subject_profile,
)

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "narrative"


def _adapt_fixture(base: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    """Create a compact ticker-shaped mock from the nearest available fixture."""
    record = deepcopy(base)
    subject = prompt_subject_profile(profile)
    ticker = subject["ticker"]
    name = subject.get("name") or ticker
    sector = subject.get("sector") or "Unknown"
    themes = subject.get("themes") or []
    primary_theme = themes[0] if themes else "company narrative"
    secondary_theme = themes[1] if len(themes) > 1 else "fundamentals"

    record.update({
        "ticker": ticker,
        "subject": subject,
        "subject_type": subject.get("subject_type", "ticker"),
        "requested_ticker": ticker,
        "cache_hit": False,
        "is_mock": True,
        "narrative_mode": "mock",
        "fixture_warning": f"Using adapted mock fixture for {ticker}; not a live market read.",
    })

    output = record.get("output") or record.get("result") or {}
    output["asof_utc"] = record.get("generated_at") or output.get("asof_utc")
    output["one_paragraph_summary"] = (
        f"Mock Helix read for {name} ({ticker}): the current setup centers on "
        f"{primary_theme}, {secondary_theme}, and relative performance versus "
        f"{subject.get('benchmark', 'QQQ')} and {subject.get('broad_market', 'SPY')}. "
        "This fixture is stable UI data and is not a current market recommendation."
    )
    output["executive_snapshot"] = {
        "regime_tone": "Ticker-specific preview",
        "primary_gap": f"{ticker} expectations are being compared against company evidence and price confirmation.",
        "primary_archetype": "Narrative-Fundamental Divergence",
        "price_confirmation": "Mixed",
        "confidence": 62,
        "executive_bullets": {
            "reality": f"{name} evidence is framed around {sector}, margins, guidance, and execution.",
            "story": f"The mock market story emphasizes {primary_theme} and {secondary_theme}.",
            "price": f"{ticker} is evaluated versus {subject.get('benchmark', 'QQQ')}, {subject.get('sector_etf', 'sector ETF')}, and SPY.",
        },
    }
    output["dominant_narratives"] = [
        {
            "title": f"{name} expectation reset",
            "stance": "mixed",
            "confidence": 64,
            "why_now": (
                f"REALITY: {name} fundamentals and execution are the primary evidence base. "
                f"STORY: Investors are focused on {primary_theme}. "
                f"PRICE: {ticker} should be read against {subject.get('benchmark', 'QQQ')} and {subject.get('sector_etf', 'sector ETF')}. "
                "GAP: The opportunity depends on whether price is confirming the company-specific story."
            ),
            "key_catalysts": [f"{name} earnings/guidance", f"{ticker} relative strength", f"{primary_theme} evidence"],
            "what_would_change": ["FALSIFIER: Company evidence weakens while price loses relative strength."],
            "price_action": f"Mock relative-price context for {ticker}.",
            "gap": "Ticker narrative and price confirmation are intentionally separated for UI testing.",
            "archetype": "Narrative-Fundamental Divergence",
        }
    ]
    output["inefficiency_map"] = [
        {
            "subject": ticker,
            "gap": f"Market expectations around {primary_theme} may be ahead of confirmed company evidence.",
            "archetype": "Narrative-Fundamental Divergence",
            "archetype_id": "narrative_fundamental_divergence",
            "confidence": 62,
            "evidence": "Mock fixture evidence board; not live market evidence.",
            "falsifier": f"{ticker} fundamentals and relative price action confirm the narrative.",
            "taxonomy_basis": "Fixture maps a company story versus fundamentals/price gap to the canonical taxonomy.",
            "underlying_gap_type": "unclear",
        }
    ]
    output["price_summary"] = {
        "cross_asset": f"{ticker} should be interpreted in context of SPY and QQQ.",
        "sector": f"{subject.get('sector_etf', 'Sector ETF')} is the sector reference for this mock read.",
        "timeframe": "Mock data includes multi-timeframe placeholders for UI review.",
        "relationship": f"Primary relationship checks are {ticker} minus SPY, benchmark, and sector ETF.",
    }
    output["_meta"] = {
        **((output.get("_meta") or {}) if isinstance(output.get("_meta"), dict) else {}),
        "subject": subject,
        "ticker_relevance": {
            "supported": True,
            "profile_terms": [ticker, name, *themes[:6]],
            "selected_item_relevance_summary": {"mock_fixture": True},
        },
    }
    record["output"] = output
    record["result"] = output
    return record


def load_narrative_fixture(ticker: str) -> Dict[str, Any]:
    ticker_u = normalize_ticker(ticker)
    profile: Optional[Dict[str, Any]] = get_ticker_profile(ticker_u)
    path = FIXTURE_DIR / f"{ticker_u}.json"
    if not path.exists() and profile and ticker_u != "SPY":
        path = FIXTURE_DIR / "MSFT.json"
        if not path.exists():
            path = FIXTURE_DIR / "SPY.json"
    if not path.exists():
        raise FileNotFoundError(f"No narrative fixture found for {ticker_u} at {path}")

    record = json.loads(path.read_text(encoding="utf-8"))
    record["requested_ticker"] = ticker_u
    if profile and record.get("ticker") != ticker_u:
        record = _adapt_fixture(record, profile)
    elif profile:
        subject = prompt_subject_profile(profile)
        record["subject"] = subject
        record["subject_type"] = subject.get("subject_type", record.get("subject_type"))
        output = record.get("output")
        if isinstance(output, dict):
            output.setdefault("_meta", {})
            if isinstance(output["_meta"], dict):
                output["_meta"].setdefault("subject", subject)
            record["result"] = output
    return record
