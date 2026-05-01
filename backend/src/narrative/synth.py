"""
synth.py — Pipeline B narrative synthesis.

Conceptual flow
---------------
    bundle["items"]
      → dedupe + rank          (selects WHICH items make it through)
      → classify by role       (decides WHICH LEDGER each item belongs to)
      → build information_ledgers
            fundamental / policy / narrative / price / alternative_views
      → LLM prompt asks the model to COMPARE ledgers
        and detect narrative–fundamental–price gaps
      → output NarrativeStateV1 (existing schema)

Why ranking and role classification are separate jobs
-----------------------------------------------------
- rank_score filters out low-signal items.
- information_role routes signal into the correct evidence ledger.
  A high-rank_score item from CNBC stays in the *narrative* ledger; its
  rank does not promote it to fundamental evidence.

Why ledgers
-----------
Treating all items as one undifferentiated article-ranking pool conflates:
  (1) what reality / policy / company evidence says,
  (2) what story the market and media are telling,
  (3) what price action is actually doing.
The product's goal is to detect divergences between these three layers.
The LLM cannot do that if the input is a flat ranked list — it needs the
separation made explicit.

Schema decisions
----------------
We keep NarrativeStateV1 unchanged. The richer outputs (REALITY / STORY /
PRICE / GAP / ARCHETYPE / FALSIFIER lines) are encoded as prefixed strings
inside the existing freeform fields (raw_takeaways, per-narrative
takeaways, what_would_change). If future product needs justify it, we can
add explicit fields — but defer that until the prompted prefixes prove
insufficient.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from src.narrative.schema import NarrativeStateV1


_DEFAULT_CLIENT: OpenAI | None = None


def _get_default_client() -> OpenAI:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = OpenAI()
    return _DEFAULT_CLIENT


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_str_from_iso(iso_ts: Optional[str]) -> str:
    if not iso_ts:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def narrative_snapshot_path(base_dir: str | Path, date_str: str) -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"narrative_state_{date_str}.json"


def save_narrative_snapshot(
    state: Dict[str, Any],
    base_dir: str | Path = "data/snapshots",
    date_str: Optional[str] = None,
) -> Path:
    if date_str is None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = narrative_snapshot_path(base_dir, date_str)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return path


def load_latest_narrative_snapshot(
    base_dir: str | Path = "data/snapshots",
    today_date_str: Optional[str] = None,
    max_lookback_days: int = 14,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    today = datetime.strptime(today_date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"), "%Y-%m-%d").date()

    for i in range(1, max_lookback_days + 1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        p = narrative_snapshot_path(base_dir, d)
        if p.exists():
            try:
                return d, json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue

    return None, None


def _normalize_title(x: Any) -> str:
    s = str(x or "").lower()
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[^a-z0-9 ]+", "", s)
    return s


# ---------------------------------------------------------------------------
# Information-role classification
# ---------------------------------------------------------------------------
#
# Each role describes the *epistemic position* the item occupies — i.e. what
# kind of evidence it is, NOT how interesting or recent it is.
#
# A given source's role is mostly stable (BLS releases are official_macro_data
# every time; CNBC top news is major_financial_press every time). Title-level
# overrides handle the common exceptions (e.g. a CNBC item that's clearly a
# market-close recap is reclassified as market_reaction).
#
# Roles are intentionally coarse — fewer categories means fewer
# misclassifications. Add new roles only when an existing ledger genuinely
# can't host the new evidence type.
# ---------------------------------------------------------------------------

_CB_PATTERNS = re.compile(
    r"\b(fed(eral reserve)?|fomc|ecb|european central bank|boe|bank of england|"
    r"boj|bank of japan|snb|swiss national bank|rba|reserve bank of australia|"
    r"pboc|bank of canada|boc)\b",
    flags=re.IGNORECASE,
)

_OFFICIAL_DATA_PATTERNS = re.compile(
    r"\b(bls|bureau of labor|bea|bureau of economic|treasury|"
    r"census bureau|federal reserve economic data|fred|"
    r"bank of england statistics|eurostat|"
    r"labor statistics|economic analysis)\b",
    flags=re.IGNORECASE,
)

_BLOG_SOURCES = {
    "marginal revolution",
    "calculated risk",
    "ft alphaville",
    "seeking alpha wall street breakfast",
    "seekingalpha",
    "seeking alpha",
}

_MARKET_RECAP_PATTERNS = re.compile(
    r"\b(stocks (?:fell|rose|close[ds]?|surge|tumble|sink|jump|slip|drop)|"
    r"wall street (?:closes?|ends?|opens?)|"
    r"market(?:s)? (?:close|end|open|rally|sell.?off|tumble)|"
    r"dow (?:jumps|falls|rises|drops|tumbles|closes)|"
    r"s&p (?:closes|jumps|falls|rises|drops)|"
    r"nasdaq (?:closes|jumps|falls|rises|drops))\b",
    flags=re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Content-type classification — patterns, helpers, and aliases
# ---------------------------------------------------------------------------
#
# IMPORTANT: Source type ≠ content type.
# infer_information_role() classifies the *epistemic position* of the source
# (e.g. CNBC is major_financial_press — that never changes for CNBC).
# infer_content_tags() classifies *what kind of information* the article
# contains — earnings data, macro data, guidance, etc.
#
# Why both matter:
#   A CNBC article reporting an earnings beat is simultaneously:
#     (a) major_financial_press → goes to narrative_ledger (framing/story)
#     (b) reporting hard company results → ALSO belongs in fundamental_ledger
#   Without content-type classification, the fundamental_ledger would only
#   contain items from specialized/earnings channels and miss the large
#   volume of fundamental facts reported by mainstream financial press.
#
# Content tags are used to:
#   1. Duplicate press items with hard data into fundamental_ledger.
#   2. Filter/penalize boilerplate, paywall, and low-relevance alt-view items.
#   3. Enrich _meta for debug/calibration.
# ---------------------------------------------------------------------------

_EARNINGS_PATTERNS = re.compile(
    r"\b(earn(?:ings?)?|eps|revenue|net sales?|quarterly results?|"
    r"q[1-4] results?|full.?year results?|annual results?|"
    r"beat(?:s)? (?:estimates?|expectations?)|miss(?:ed)? (?:estimates?|expectations?)|"
    r"blows? past|topped? (?:estimates?|expectations?)|"
    r"net income|operating income|gross profit|adjusted profit|"
    r"diluted eps|adjusted eps|per.?share earnings?)\b",
    flags=re.IGNORECASE,
)

_GUIDANCE_PATTERNS = re.compile(
    r"\b(guid(?:ance)?|outlook|raises? (?:guidance|outlook|forecast)|"
    r"lowers? (?:guidance|outlook|forecast)|narrows? (?:guidance|outlook)|"
    r"hikes? (?:guidance|outlook|forecast)|reaffirm(?:s|ed)? guidance|"
    r"updates? guidance|capex|capital expenditure|"
    r"full.?year (?:outlook|forecast|guidance))\b",
    flags=re.IGNORECASE,
)

_COMPANY_FUNDAMENTAL_PATTERNS = re.compile(
    r"\b(balance sheet|cash flow|free cash flow|buyback|share repurchase|"
    r"dividend|merger|acquisition|spinoff|spin.off|takeover|"
    r"same.?store sales?|comp(?:arable)? sales?|"
    r"r&d|research and development|pricing power|price hike|"
    r"gross margin|operating margin|ebitda|ebit|"
    r"inventory|supply chain|production output|shipment(?:s)?)\b",
    flags=re.IGNORECASE,
)

_MACRO_DATA_PATTERNS = re.compile(
    r"\b(pmi|ism|retail sales?|"
    r"industrial (?:production|output)|factory (?:output|activity|orders?)|"
    r"manufacturing (?:index|data|output|pmi)|trade (?:deficit|balance|data)|"
    r"current account|consumer confidence|business confidence|"
    r"purchasing managers?|economic (?:data|report|activity))\b",
    flags=re.IGNORECASE,
)

_INFLATION_PATTERNS = re.compile(
    r"\b(inflat(?:ion)?|cpi|pce|core inflation|headline inflation|"
    r"price (?:index|level|pressure)|disinflat(?:ion)?|deflat(?:ion)?|"
    r"cost of living|wage(?:s)? (?:growth|inflation)|price(?:s)? (?:rose?|fell?|surged?|jumped?))\b",
    flags=re.IGNORECASE,
)

_LABOR_PATTERNS = re.compile(
    r"\b(payrolls?|nonfarm|employment report|unemployment (?:rate|data|report)|"
    r"job(?:s)? (?:report|data|growth|market)|initial claims?|"
    r"jobless claims?|continuing claims?|hourly earnings?|"
    r"hiring|layoffs?|labor market|labour market)\b",
    flags=re.IGNORECASE,
)

_GROWTH_PATTERNS = re.compile(
    r"\b(gdp (?:growth|data|report|estimate|print)|"
    r"economic (?:growth|expansion|contraction|slowdown)|"
    r"growth (?:disappoint|beat|slows?|accelerates?)|"
    r"recession|soft landing|hard landing|output gap|"
    r"consumer spending|business investment|domestic demand)\b",
    flags=re.IGNORECASE,
)

_CREDIT_PATTERNS = re.compile(
    r"\b(credit (?:spread|risk|standard|condition|tighten|loosen)|"
    r"corporate (?:bond|debt|credit|issuance)|"
    r"high yield|investment grade|ig spread|hy spread|"
    r"cds|default (?:rate|risk|swap)|"
    r"lending (?:standard|condition|rate)|bank lending)\b",
    flags=re.IGNORECASE,
)

_COMMODITY_PATTERNS = re.compile(
    r"\b(crude oil|brent|wti|oil prices?|oil (?:market|output|production)|"
    r"natural gas prices?|lng prices?|opec|opec\+|"
    r"gold prices?|copper prices?|iron ore|"
    r"commodity prices?|energy prices?|input costs?|raw material costs?)\b",
    flags=re.IGNORECASE,
)

_POLICY_SIGNAL_PATTERNS = re.compile(
    r"\b(rate (?:cut|hike|hold|pause|decision|path|expectation)|"
    r"interest rate (?:outlook|decision)|monetary policy|"
    r"quantitative (?:easing|tightening)|balance sheet reduction|"
    r"forward guidance|hawkish|dovish|policy pivot|"
    r"tightening cycle|easing cycle)\b",
    flags=re.IGNORECASE,
)

_PRICE_REACTION_PATTERNS = re.compile(
    r"\b((?:stock|share)s? (?:rose?|fell?|surged?|tumbled?|jumped?|slipped?|dropped?|rallied?)|"
    r"(?:up|down) \d+(?:\.\d+)?%|"
    r"gain(?:s|ed)? \d+(?:\.\d+)?%|"
    r"(?:lost?|shed|fell?) \d+(?:\.\d+)?%|"
    r"stock (?:price|reaction)|market reaction)\b",
    flags=re.IGNORECASE,
)

# Phrases that mean an item is pure paywall/template with no investment substance.
_BOILERPLATE_PHRASES: List[str] = [
    "register to unlock this article",
    "trial $1 for 4 weeks",
    "complete digital access",
    "explore our recommended subscriptions",
    "standard digital",
    "premium digital",
    "why the ft?",
    "seeking alpha's transcripts team is responsible",
    "the following slide deck was published",
    "thanks, sa transcripts team",
]

# Low market-relevance signal — culture/general-interest topics.
_LOW_MARKET_RELEVANCE_PATTERNS = re.compile(
    r"\b(philosophy of everyday|recipe(?:s)?|cooking tips?|"
    r"travel guide|garden(?:ing)?|"
    r"book review|movie review|film review|"
    r"sports(?:man)?|football score|soccer match|basketball game|baseball score|"
    r"museum exhibit|poetry collection)\b",
    flags=re.IGNORECASE,
)

# Keywords that indicate market/investment relevance — used to score tier C items.
_MARKET_RELEVANCE_KEYWORDS = re.compile(
    r"\b(inflation|interest rate|fed|ecb|boj|oil|energy|gdp|pmi|ism|"
    r"payroll|earnings|revenue|eps|guidance|capex|credit|spread|"
    r"recession|consumer|liquidity|equit(?:y|ies)|"
    r"stock|bond|yield|dollar|gold|commodit(?:y|ies)|"
    r"semiconductor|financials?|bank(?:ing)?|market|invest|trade|tariff|"
    r"portfolio|hedge|asset|sector|monetary|fiscal|"
    r"macro|valuation|multiple)\b",
    flags=re.IGNORECASE,
)

# Content tags that qualify a press/narrative item to be duplicated into
# fundamental_ledger — i.e. the item is reporting hard factual data, not
# just interpreting or commenting on it.
_FUNDAMENTAL_DUPLICATE_TAGS = frozenset({
    "earnings_result",
    "guidance_update",
    "company_fundamental",
    "macro_data",
    "inflation_data",
    "labor_data",
    "growth_data",
    "credit_data",
    "commodity_fundamental",
})

# Tickers already in the standard SECTORS/CROSS download universe.
# Exclude from extract_tickers_from_items — they are always fetched separately.
_STANDARD_UNIVERSE_TICKERS = frozenset({
    "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLC", "XLRE",
    "SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "USO", "BTC-USD",
})

# Company-name → ticker alias map.
# Context note: all items come from financial news sources, so company-name
# false positives (e.g. "apple" for the fruit, "ford" as a surname) are very
# rare and acceptable — the worst case is one extra ticker fetch.
# Longer / more specific names are listed first so word-boundary matching
# picks them up before shorter substrings (e.g. "eli lilly" before "lilly").
COMPANY_TICKER_ALIASES: Dict[str, str] = {
    "novo nordisk": "NVO",
    "johnson & johnson": "JNJ",
    "bank of america": "BAC",
    "goldman sachs": "GS",
    "jpmorgan chase": "JPM",
    "jp morgan": "JPM",
    "jpmorgan": "JPM",
    "home depot": "HD",
    "unitedhealth": "UNH",
    "eli lilly": "LLY",
    "berkshire hathaway": "BRK-B",
    "berkshire": "BRK-B",
    "qualcomm": "QCOM",
    "microsoft": "MSFT",
    "alphabet": "GOOGL",
    "broadcom": "AVGO",
    "chipotle": "CMG",
    "facebook": "META",
    "unilever": "UL",
    "salesforce": "CRM",
    "caterpillar": "CAT",
    "chevron": "CVX",
    "pfizer": "PFE",
    "netflix": "NFLX",
    "walmart": "WMT",
    "disney": "DIS",
    "hershey": "HSY",
    "amazon": "AMZN",
    "nvidia": "NVDA",
    "google": "GOOGL",
    "tesla": "TSLA",
    "boeing": "BA",
    "abbott": "ABT",
    "exxon": "XOM",
    "apple": "AAPL",
    "merck": "MRK",
    "sofi": "SOFI",
    "intel": "INTC",
    "palantir": "PLTR",
    "coinbase": "COIN",
    "uber": "UBER",
    "airbnb": "ABNB",
    "shopify": "SHOP",
    "asml": "ASML",
    "tsmc": "TSM",
    "amd": "AMD",
    "meta": "META",
    "ford": "F",
    "lilly": "LLY",
}

# Regex for explicit ticker patterns in text:
#   $AAPL  →  group(1)
#   NYSE:AAPL / NASDAQ:AAPL  →  group(2)
#   (AAPL)  →  group(3) — require ≥2 chars to reduce false positives
_EXPLICIT_TICKER_RE = re.compile(
    r"(?:\$([A-Z]{1,5}(?:-[A-Z]{1,2})?)"
    r"|(?:NYSE|NASDAQ|AMEX|OTC):([A-Z]{1,5})"
    r"|\(([A-Z]{2,5})\))",
    flags=re.ASCII,
)

# Common English words / acronyms that match ticker patterns but are not tickers.
# Applied to group(3) of _EXPLICIT_TICKER_RE to block "(AI)", "(IT)", etc.
_TICKER_BLOCKLIST = frozenset({
    "A", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN",
    "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AI", "PM", "AM", "TV", "OK", "UK", "EU", "UN",
    "THE", "AND", "BUT", "FOR", "NOT", "ARE", "WAS", "HAS", "HAD",
    "ITS", "HIS", "HER", "OUR", "YOU", "WHO", "ALL", "CAN", "GET",
    "HIT", "NEW", "OLD", "NOW", "TOP", "SET", "SAY", "ONE", "TWO",
    "CEO", "CFO", "IPO", "ETF", "GDP", "CPI", "PMI", "PCE", "FED",
    "ECB", "BOJ", "IMF", "SEC", "DOJ", "FDA", "ESG", "EPS", "YOY",
    "QOQ", "YTD", "BPS", "FOMC", "OPEC", "NATO",
    "RATE", "RISE", "FALL", "SELL", "CALL", "PUTS", "JOBS",
    "CASH", "DEBT", "LOAN", "BOND", "SWAP", "DEAL", "PLAN",
    "DATA", "CUTS", "CUT", "TAX", "BIG", "LOW", "HIGH",
    "SAYS", "SAID", "WILL", "WELL", "ALSO", "JUST",
})


def infer_content_tags(item: Dict[str, Any]) -> set[str]:
    """
    Return a set of content-type tags describing WHAT the article contains.

    This is intentionally separate from infer_information_role(), which
    classifies the source's epistemic position.  A CNBC article reporting
    earnings results carries 'earnings_result' here while still being
    classified as 'major_financial_press' by infer_information_role().

    Tags:
        earnings_result         — reports Q/annual revenue, EPS, profit figures
        guidance_update         — capex plans, forward guidance, raised/lowered outlook
        company_fundamental     — M&A, buybacks, margins, same-store sales, dividends
        macro_data              — PMI, ISM, factory output, trade data, retail sales
        inflation_data          — CPI, PCE, price indices, pricing power
        labor_data              — payrolls, unemployment, wages
        growth_data             — GDP, recession/expansion signals
        credit_data             — credit spreads, lending standards, bond markets
        commodity_fundamental   — oil/gas/gold prices, OPEC, energy costs
        policy_signal           — rate decisions, QE/QT, hawkish/dovish signals
        price_reaction          — article primarily describes a % move or price event
        boilerplate_or_paywall  — paywall page or transcript-team template
        low_market_relevance    — likely off-topic with no economic/investment angle
    """
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    text = f"{title} {summary}"
    text_lc = text.lower()
    raw = item.get("raw") or {}

    tags: set[str] = set()

    # --- Boilerplate / paywall (short-circuit if found) ---
    for phrase in _BOILERPLATE_PHRASES:
        if phrase.lower() in text_lc:
            tags.add("boilerplate_or_paywall")
            break
    if "boilerplate_or_paywall" not in tags:
        if raw.get("paywall") and not raw.get("extraction_success"):
            tags.add("boilerplate_or_paywall")

    # --- Financial content tags ---
    if _EARNINGS_PATTERNS.search(text):
        tags.add("earnings_result")
    if _GUIDANCE_PATTERNS.search(text):
        tags.add("guidance_update")
    if _COMPANY_FUNDAMENTAL_PATTERNS.search(text):
        tags.add("company_fundamental")
    if _MACRO_DATA_PATTERNS.search(text):
        tags.add("macro_data")
    if _INFLATION_PATTERNS.search(text):
        tags.add("inflation_data")
    if _LABOR_PATTERNS.search(text):
        tags.add("labor_data")
    if _GROWTH_PATTERNS.search(text):
        tags.add("growth_data")
    if _CREDIT_PATTERNS.search(text):
        tags.add("credit_data")
    if _COMMODITY_PATTERNS.search(text):
        tags.add("commodity_fundamental")
    if _POLICY_SIGNAL_PATTERNS.search(text):
        tags.add("policy_signal")
    if _PRICE_REACTION_PATTERNS.search(text):
        tags.add("price_reaction")

    # --- Low market relevance ---
    # Only flag when there are no positive financial content tags
    has_financial_signal = bool(tags - {"boilerplate_or_paywall", "price_reaction"})
    if not has_financial_signal:
        if _LOW_MARKET_RELEVANCE_PATTERNS.search(text_lc):
            tags.add("low_market_relevance")
        elif not _MARKET_RELEVANCE_KEYWORDS.search(text):
            # No market keywords at all → likely off-topic
            tags.add("low_market_relevance")

    return tags


def is_low_value_content(item: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Return (True, reason) when an item is boilerplate, paywall, or carries
    no investment-relevant content.

    Used to pre-filter items before ranking.  Only hard-excludes items where
    there is very high confidence they are noise — when in doubt, the item
    is passed through and ranked normally.

    Reasons:
        "paywall_no_content"    — paywall flag set, extraction failed, no summary
        "boilerplate_phrase"    — recognized paywall/template boilerplate in text
        "seeking_alpha_empty"   — SA item with no extractable content
        "no_title_no_summary"   — completely empty item
    """
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()
    raw = item.get("raw") or {}
    source = (item.get("source") or "").lower()

    if not title and not summary:
        return True, "no_title_no_summary"

    text_lc = f"{title} {summary}".lower()

    # Recognized paywall/template phrases
    for phrase in _BOILERPLATE_PHRASES:
        if phrase.lower() in text_lc:
            return True, f"boilerplate_phrase:{phrase[:40]}"

    # Paywalled with no summary extracted
    if raw.get("paywall") and raw.get("extraction_success") is False and not summary:
        return True, "paywall_no_content"

    # Seeking Alpha: no extractable content and effectively no summary
    if "seeking alpha" in source:
        word_count = raw.get("word_count") or 0
        has_real_summary = summary and len(summary) > 40
        if not has_real_summary and (raw.get("extraction_success") is False or word_count < 30):
            return True, "seeking_alpha_empty"

    return False, None


def market_relevance_score(item: Dict[str, Any], tags: set[str]) -> float:
    """
    Estimate investment relevance of a Tier C / alternative-view item.

    Applied ONLY to alternative_or_blog_interpretation items to filter
    culture/general-interest posts with no economic angle.  NOT applied
    to Tier A/B items where false negatives are unacceptable.

    Score:   >= 1.5  clearly relevant  |  0.5–1.5  borderline  |  < 0.0  filter candidate
    """
    title = item.get("title") or ""
    summary = item.get("summary") or ""
    text = f"{title} {summary}"

    score = 0.0

    # Market/economic keyword density (capped at 2.0)
    kw_hits = len(_MARKET_RELEVANCE_KEYWORDS.findall(text))
    score += min(2.0, kw_hits * 0.35)

    # Explicit company tickers → clear investment relevance
    if item.get("tickers"):
        score += 0.8

    # Fundamental content tag bonus
    if tags & _FUNDAMENTAL_DUPLICATE_TAGS:
        score += 1.0

    # Penalties
    if "boilerplate_or_paywall" in tags:
        score -= 3.0
    if "low_market_relevance" in tags:
        score -= 2.0
    if not _MARKET_RELEVANCE_KEYWORDS.search(text):
        score -= 1.5

    return round(score, 2)


def should_duplicate_to_fundamental_ledger(
    item: Dict[str, Any], role: str, tags: set[str]
) -> bool:
    """
    Return True when a press/narrative item should ALSO appear in
    fundamental_ledger because it reports hard factual data.

    This enables e.g. a Reuters article that reports an earnings beat to
    contribute evidence to fundamental_ledger (the fact) while ALSO staying
    in narrative_ledger (the framing).  The LLM receives both views and can
    distinguish reality from story.

    Only duplicates from narrative-type source roles — items already going
    to fundamental_ledger or policy_ledger are never duplicated.
    """
    _NARRATIVE_ROLES = frozenset({
        "major_financial_press",
        "sell_side_or_specialist_analysis",
        "headline_only",
        "alternative_or_blog_interpretation",
        "market_reaction",
        "unknown",
    })
    if role not in _NARRATIVE_ROLES:
        return False
    return bool(tags & _FUNDAMENTAL_DUPLICATE_TAGS)


def extract_tickers_from_items(
    items: List[Dict[str, Any]],
    max_tickers: int = 25,
) -> List[str]:
    """
    Extract single-name tickers from bundle items for use as watch_tickers
    in build_price_context().

    Sources (in confidence order):
      1. item["tickers"] field — pre-resolved, highest confidence
      2. Explicit patterns: $AAPL, NYSE:AAPL, (AAPL)
      3. Company-name alias lookup (COMPANY_TICKER_ALIASES)

    Excludes tickers already in the standard SECTORS/CROSS universe.
    Returns a deduplicated list capped at max_tickers, preserving order of
    first occurrence (higher-ranked items appear earlier).
    """
    seen: set[str] = set()
    result: List[str] = []

    def _add(raw_ticker: str) -> None:
        t = raw_ticker.strip().upper()
        if (not t
                or len(t) > 6
                or t in _STANDARD_UNIVERSE_TICKERS
                or t in _TICKER_BLOCKLIST
                or t in seen):
            return
        seen.add(t)
        result.append(t)

    for it in items:
        if len(result) >= max_tickers:
            break

        # 1. Explicit tickers field (highest confidence)
        for tk in (it.get("tickers") or []):
            if len(result) >= max_tickers:
                break
            _add(str(tk))

        # 2. Explicit ticker patterns in title + summary
        text = f"{it.get('title') or ''} {it.get('summary') or ''}"
        for m in _EXPLICIT_TICKER_RE.finditer(text):
            if len(result) >= max_tickers:
                break
            tk = m.group(1) or m.group(2) or m.group(3) or ""
            if tk and tk not in _TICKER_BLOCKLIST:
                _add(tk)

        # 3. Company-name alias lookup
        text_lc = text.lower()
        for name, ticker in COMPANY_TICKER_ALIASES.items():
            if len(result) >= max_tickers:
                break
            if re.search(r"\b" + re.escape(name) + r"\b", text_lc):
                _add(ticker)

    return result


# Mapping from information_role → which ledger the item belongs in.
# Note: company_management_narrative is duplicated into both the fundamental
# and narrative ledgers (handled with is_hybrid=True in _build_ledgers).
_ROLE_TO_LEDGER: Dict[str, str] = {
    "official_macro_data": "fundamental_ledger",
    "central_bank_policy": "policy_ledger",
    "company_fundamentals": "fundamental_ledger",
    "company_management_narrative": "fundamental_ledger",  # plus narrative_ledger via hybrid
    "major_financial_press": "narrative_ledger",
    "market_reaction": "price_ledger",
    "sell_side_or_specialist_analysis": "narrative_ledger",
    "alternative_or_blog_interpretation": "alternative_views_ledger",
    "headline_only": "narrative_ledger",
    "unknown": "uncategorized",
}


def infer_information_role(item: Dict[str, Any]) -> str:
    """
    Infer the information role of a bundle item.

    Robust to missing fields: returns "unknown" if nothing classifiable.

    Precedence (highest first):
      1. Channel-based primary classification.
      2. Source-name pattern matching (refines policy → cb vs official data;
         refines analytical → blog vs specialist).
      3. Title pattern overrides (market-recap items even from wires).
      4. Headline-only fallback when summary is empty/very short.
    """
    channel = (item.get("channel") or "").strip().lower()
    source = (item.get("source") or "").strip()
    source_lc = source.lower()
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()

    # Title-level override: market recaps regardless of channel
    if title and _MARKET_RECAP_PATTERNS.search(title):
        return "market_reaction"

    # Channel-based primary classification
    if channel == "earnings":
        # Distinguish earnings calendar (release/scheduled) from transcripts /
        # call commentary using simple keywords.
        haystack = f"{title} {summary}".lower()
        if any(k in haystack for k in ("earnings call", "transcript", "ceo said", "cfo said", "guidance call")):
            return "company_management_narrative"
        return "company_fundamentals"

    if channel == "policy":
        if _CB_PATTERNS.search(source) or _CB_PATTERNS.search(title):
            return "central_bank_policy"
        if _OFFICIAL_DATA_PATTERNS.search(source) or _OFFICIAL_DATA_PATTERNS.search(title):
            return "official_macro_data"
        # Default for policy channel without clear sub-signal: treat as
        # central_bank_policy if the source name hints at policy, else
        # official_macro_data.
        return "official_macro_data"

    if channel == "analytical":
        if source_lc in _BLOG_SOURCES or any(b in source_lc for b in _BLOG_SOURCES):
            return "alternative_or_blog_interpretation"
        return "sell_side_or_specialist_analysis"

    if channel in ("wire", "news"):
        # Headline-only detection: very short summary AND extraction failed
        if summary and len(summary) < 50:
            raw = item.get("raw") or {}
            if raw.get("extraction_success") is False:
                return "headline_only"
        return "major_financial_press"

    if channel == "ticker_news":
        # Company-specific media: most are press write-ups → narrative.
        # Real PRs from issuers are rare in this channel; we don't try to
        # distinguish them here.
        return "major_financial_press"

    # Fallback: examine source-name patterns regardless of channel
    if _CB_PATTERNS.search(source):
        return "central_bank_policy"
    if _OFFICIAL_DATA_PATTERNS.search(source):
        return "official_macro_data"
    if source_lc in _BLOG_SOURCES:
        return "alternative_or_blog_interpretation"

    # Headline-only detector for unknown channels
    if title and (not summary or len(summary) < 50):
        return "headline_only"

    return "unknown"


def _evidence_strength_for_role(role: str, item: Dict[str, Any]) -> str:
    """
    Return an evidentiary-reliability label scoped to the role's ledger.

    NOTE: This describes how reliable the evidence is *within its ledger*,
    NOT how important the item is to the final narrative. A "high" strength
    BLS print and a "high" strength earnings release sit in the same
    fundamental ledger; the LLM weights them by topic relevance, not by
    a global score.
    """
    if role in ("official_macro_data", "central_bank_policy", "company_fundamentals"):
        return "high"
    if role == "company_management_narrative":
        return "medium_high"
    if role in ("major_financial_press", "sell_side_or_specialist_analysis"):
        # If the source is paywalled and we only have a summary, downgrade.
        raw = item.get("raw") or {}
        if raw.get("paywall") and not raw.get("extraction_success"):
            return "low_to_medium"
        return "medium"
    if role == "market_reaction":
        return "medium"  # the *interpretation* is medium; the price data itself comes from market_moves
    if role == "alternative_or_blog_interpretation":
        return "low_to_medium"
    if role == "headline_only":
        return "weak"
    return "unknown"


# ---------------------------------------------------------------------------
# Compact item shaping
# ---------------------------------------------------------------------------

def _compact_item(it: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip raw payload but preserve fields needed for ledger routing and
    evidence reasoning. Backward compatible: missing fields default to
    sensible empty values; existing callers won't break.
    """
    raw = it.get("raw") or {}
    return {
        "channel": it.get("channel"),
        "source": it.get("source"),
        # Source metadata (may be missing on items that didn't come through
        # the new RSS path — keep optional)
        "source_name": it.get("source_name") or it.get("source"),
        "source_tier": it.get("source_tier") or raw.get("tier"),
        "tier": it.get("tier") or raw.get("tier"),
        "source_channel": it.get("source_channel") or it.get("channel"),
        "paywall": it.get("paywall") if "paywall" in it else raw.get("paywall"),
        "notes": it.get("notes"),
        "source_authority": it.get("source_authority"),
        "information_role": it.get("information_role"),  # if set upstream, preserve
        "evidence_role": it.get("evidence_role"),
        # Core content
        "timestamp_utc": it.get("timestamp_utc"),
        "title": it.get("title"),
        "summary": it.get("summary"),
        "tickers": it.get("tickers") or [],
        "url": it.get("url"),
        "raw_date": raw.get("date"),
        # Forward small useful raw signals for downstream classification
        "raw": {
            "tier": raw.get("tier"),
            "paywall": raw.get("paywall"),
            "extraction_success": raw.get("extraction_success"),
            "word_count": raw.get("word_count"),
            "date": raw.get("date"),
        },
    }


def _item_key(it: Dict[str, Any]) -> str:
    url = it.get("url")
    if isinstance(url, str) and url.strip():
        return url.strip()
    src = str(it.get("source") or "")
    return f"{src}::{_normalize_title(it.get('title'))}"


def _age_hours(it: Dict[str, Any], now_utc: datetime) -> Optional[float]:
    ts = it.get("timestamp_utc")
    if isinstance(ts, (int, float)) and ts > 0:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return max(0.0, (now_utc - dt).total_seconds() / 3600.0)
    return None


def _event_keyword_score(it: Dict[str, Any]) -> float:
    text = f"{it.get('title') or ''} {it.get('summary') or ''}".lower()
    keywords = [
        "cpi", "pce", "fomc", "fed", "rate", "yields", "treasury",
        "guidance", "earnings", "downgrade", "upgrade", "warning", "miss", "beat",
        "tariff", "sanction", "ceasefire", "opec", "ai", "semiconductor",
        "buyback", "issuance", "default", "bank", "liquidity",
    ]
    hits = sum(1 for k in keywords if k in text)
    return min(2.0, 0.35 * hits)


def _prior_evidence_keys(prior_state: Optional[Dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    if not prior_state:
        return out
    for n in prior_state.get("dominant_narratives", []) or []:
        for e in n.get("evidence", []) or []:
            key = e.get("url") or _normalize_title(e.get("title"))
            if key:
                out.add(str(key))
    return out


def _summarize_market_moves(market_moves: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    moves = market_moves or []
    clean = []
    for m in moves:
        try:
            clean.append(
                {
                    "ticker": str(m.get("ticker") or "").upper(),
                    "chg_pct_1d": float(m.get("chg_pct_1d")),
                    "last": float(m.get("last")),
                }
            )
        except Exception:
            continue

    if not clean:
        return {"top_up": [], "top_down": []}

    clean.sort(key=lambda x: x["chg_pct_1d"], reverse=True)
    return {
        "top_up": clean[:5],
        "top_down": list(reversed(clean[-5:])),
    }


# ---------------------------------------------------------------------------
# Ranking — selects WHICH items make it through to ledger construction.
# Ranking does NOT decide ledger membership; that is information_role's job.
# ---------------------------------------------------------------------------

def _dedupe_and_rank(
    items: List[Dict[str, Any]],
    prior_evidence_keys: set[str],
    watch_tickers: set[str],
    lookback_hours: int,
    limit: int = 80,
    per_channel_cap: int = 35,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Rank items for inclusion in synthesis input.

    Returns (selected_items, filtered_summary).

    Each surviving item is annotated with a `_meta` dict containing:
      rank_score, age_hours, is_new_vs_prior, information_role, ledger,
      evidence_strength, why_selected, content_tags, market_relevance_score.

    Pre-filtering (before ranking):
      - Boilerplate / paywall items (hard exclude regardless of tier)
      - Empty Seeking Alpha items (no extractable content)
      - Very-low market-relevance Tier C / blog items (hard exclude)

    Soft penalties (applied to score, item still competes):
      - Borderline-relevance alternative/blog items
    """
    # --- Dedupe ---
    seen: set[str] = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        key = _item_key(it)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    # --- Pre-filter: hard-exclude low-value / boilerplate items ---
    filtered_reasons: Dict[str, int] = {}
    kept: List[Dict[str, Any]] = []

    for it in uniq:
        low_value, reason = is_low_value_content(it)
        if low_value:
            bucket = (reason or "unknown").split(":")[0]
            filtered_reasons[bucket] = filtered_reasons.get(bucket, 0) + 1
            continue

        # For alternative/blog items check market relevance threshold
        role_prelim = infer_information_role(it)
        if role_prelim == "alternative_or_blog_interpretation":
            tags_prelim = infer_content_tags(it)
            mrs = market_relevance_score(it, tags_prelim)
            source_tier = (it.get("source_tier") or it.get("tier") or "").upper()
            # Hard-exclude very-low-relevance items from Tier C or untiered sources
            if mrs < -0.5 and source_tier in ("C", ""):
                bucket = "low_market_relevance_tier_c"
                filtered_reasons[bucket] = filtered_reasons.get(bucket, 0) + 1
                continue

        kept.append(it)

    filtered_summary: Dict[str, Any] = {
        "count": sum(filtered_reasons.values()),
        "reasons": filtered_reasons,
    }

    now_utc = datetime.now(timezone.utc)

    def score_components(it: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
        ch = (it.get("channel") or "").lower()
        base = {
            "ticker_news": 2.0,
            "news": 1.2,
            "wire": 1.2,
            "earnings": 1.7,
            "policy": 2.2,        # policy items are scarce; bias inclusion
            "analytical": 1.0,
        }.get(ch, 0.5)

        age_h = _age_hours(it, now_utc)
        recency = 0.0
        if age_h is not None:
            if age_h <= 6:
                recency = 3.0
            elif age_h <= 24:
                recency = 2.0
            elif age_h <= 48:
                recency = 1.2
            elif age_h <= 72:
                recency = 0.6
            else:
                recency = -0.5
            if age_h > lookback_hours:
                recency -= 0.75

        novelty = 1.6 if _item_key(it) not in prior_evidence_keys else -0.5

        tks = {str(t).upper() for t in (it.get("tickers") or []) if str(t).strip()}
        overlap = len(tks.intersection(watch_tickers))
        ticker_relevance = min(1.5, 0.4 * overlap)

        content_quality = 0.35 if it.get("summary") else 0.0
        eventness = _event_keyword_score(it)

        total = base + recency + novelty + ticker_relevance + content_quality + eventness
        return total, {
            "base": base,
            "recency": recency,
            "novelty": novelty,
            "ticker_relevance": ticker_relevance,
            "content_quality": content_quality,
            "eventness": eventness,
        }

    ranked: List[Dict[str, Any]] = []
    for it in kept:
        it2 = dict(it)
        sc, comps = score_components(it2)
        age_h = _age_hours(it2, now_utc)
        role = infer_information_role(it2)
        ledger = _ROLE_TO_LEDGER.get(role, "uncategorized")
        strength = _evidence_strength_for_role(role, it2)
        content_tags = infer_content_tags(it2)

        # Apply relevance soft-penalty for borderline alternative/blog items
        mrs: Optional[float] = None
        if role == "alternative_or_blog_interpretation":
            mrs = market_relevance_score(it2, content_tags)
            if mrs < 0.5:
                sc += mrs  # mrs is negative or near-zero — acts as penalty

        top_comp = max(comps.items(), key=lambda kv: kv[1])
        why_selected = f"role={role}; top_factor={top_comp[0]}({round(top_comp[1], 2)})"

        it2["_meta"] = {
            "rank_score": round(sc, 3),
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "is_new_vs_prior": _item_key(it2) not in prior_evidence_keys,
            "information_role": role,
            "ledger": ledger,
            "evidence_strength": strength,
            "why_selected": why_selected,
            # Content classification — used by _build_information_ledgers for
            # duplication and by callers for debug/calibration.
            "content_tags": sorted(content_tags),
            "market_relevance_score": mrs,
        }
        ranked.append(it2)

    ranked.sort(key=lambda x: x["_meta"]["rank_score"], reverse=True)

    selected: List[Dict[str, Any]] = []
    channel_counts: Dict[str, int] = {"news": 0, "ticker_news": 0, "earnings": 0, "wire": 0}
    for it in ranked:
        ch = (it.get("channel") or "").lower()
        if ch in channel_counts and channel_counts[ch] >= per_channel_cap:
            continue
        selected.append(it)
        if ch in channel_counts:
            channel_counts[ch] += 1
        if len(selected) >= limit:
            break

    return selected, filtered_summary


# ---------------------------------------------------------------------------
# Ledger construction — the conceptual core.
#
# Ledgers separate evidence by epistemic role so the LLM can compare them.
# Ranking already filtered the items; the job here is purely routing.
# ---------------------------------------------------------------------------

def _ledger_item_view(it: Dict[str, Any]) -> Dict[str, Any]:
    """Compact view used inside ledgers — minimal fields for LLM reasoning."""
    meta = it.get("_meta") or {}
    return {
        "title": it.get("title"),
        "source": it.get("source"),
        "source_tier": it.get("source_tier") or it.get("tier"),
        "summary": it.get("summary"),
        "url": it.get("url"),
        "tickers": it.get("tickers") or [],
        "timestamp_utc": it.get("timestamp_utc"),
        "evidence_strength": meta.get("evidence_strength"),
        "information_role": meta.get("information_role"),
        "content_tags": meta.get("content_tags") or [],
        "rank_score": meta.get("rank_score"),
        "is_new_vs_prior": meta.get("is_new_vs_prior"),
    }


def _build_information_ledgers(
    selected_items: List[Dict[str, Any]],
    market_state_summary: Optional[Dict[str, Any]],
    market_moves: Optional[List[Dict[str, Any]]],
    price_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build the ledger dict consumed by the LLM.

    Ledger semantics:
      fundamental_ledger        — what reality / company numbers / data say
      policy_ledger             — what central banks/policymakers signal
      narrative_ledger          — what the market and media are saying
      price_ledger              — what assets are actually doing (moves + recaps)
                                  price_context populates structured price evidence
                                  here so the LLM can compare narrative/fundamentals
                                  against actual market behavior.
      alternative_views_ledger  — blog/specialist counter-takes
      uncategorized             — items we couldn't classify (exposed for
                                  inspection, not for LLM consumption)
    """
    ledgers: Dict[str, List[Dict[str, Any]]] = {
        "fundamental_ledger": [],
        "policy_ledger": [],
        "narrative_ledger": [],
        "price_ledger": [],
        "alternative_views_ledger": [],
        "uncategorized": [],
    }

    for it in selected_items:
        meta = it.get("_meta") or {}
        role = meta.get("information_role") or infer_information_role(it)

        # Use pre-computed content_tags from _meta when available (set by
        # _dedupe_and_rank).  Fall back to fresh computation only for items
        # that didn't go through the ranker (e.g. in unit tests).
        raw_ct = meta.get("content_tags")
        item_tags: set[str] = set(raw_ct) if raw_ct is not None else infer_content_tags(it)

        view = _ledger_item_view(it)

        if role == "company_management_narrative":
            # Hybrid: contributes to both fundamentals and narrative.
            view_fund = dict(view)
            view_narr = dict(view)
            view_fund["is_hybrid"] = True
            view_narr["is_hybrid"] = True
            ledgers["fundamental_ledger"].append(view_fund)
            ledgers["narrative_ledger"].append(view_narr)
            continue

        target = _ROLE_TO_LEDGER.get(role, "uncategorized")
        ledgers.setdefault(target, []).append(view)

        # --- Content-aware duplication to fundamental_ledger ---
        # A CNBC/Reuters/blog item reporting hard earnings, macro data, or
        # guidance belongs in BOTH ledgers:
        #   narrative_ledger   — how media/analysts are framing the event
        #   fundamental_ledger — the reported data point itself
        # This lets the LLM distinguish reality (what numbers say) from story
        # (how the market is interpreting those numbers).
        # Duplicates are marked so the LLM knows they share a source.
        if should_duplicate_to_fundamental_ledger(it, role, item_tags):
            dup = dict(view)
            dup["is_duplicate_fundamental"] = True
            dup["original_ledger"] = target
            dup["content_tags"] = sorted(item_tags & _FUNDAMENTAL_DUPLICATE_TAGS)
            # Downgrade evidence strength vs. a primary fundamental source
            # (e.g. an actual BLS release or company filing)
            dup["evidence_strength"] = "medium"
            ledgers["fundamental_ledger"].append(dup)

    # Attach summarized market_moves to the price ledger so the LLM has
    # explicit revealed-market-reaction data alongside any market-recap text.
    moves_summary = _summarize_market_moves(market_moves)
    if moves_summary.get("top_up") or moves_summary.get("top_down"):
        ledgers["price_ledger"].insert(
            0,
            {
                "kind": "market_moves_snapshot",
                "top_up": moves_summary["top_up"],
                "top_down": moves_summary["top_down"],
                "evidence_strength": "high",
                "information_role": "market_reaction",
            },
        )

    # Also attach market_state_summary to price ledger if provided
    if market_state_summary:
        ledgers["price_ledger"].insert(
            0,
            {
                "kind": "market_state_summary",
                "data": market_state_summary,
                "evidence_strength": "high",
                "information_role": "market_reaction",
            },
        )

    # --- Populate price_ledger from structured price_context ---
    # price_context is built by src/data/price_context.py and gives the LLM
    # concrete cross-asset, sector, and relationship return data to compare
    # against narratives and fundamentals.
    # Two formats are supported:
    #   "multi_timeframe" — returns dict per asset across all horizons +
    #                        trend_context + relative_returns (preferred)
    #   legacy           — single "return" float per asset + secondary_horizons
    if price_context:
        if price_context.get("format") == "multi_timeframe":
            _build_price_ledger_mtf(price_context, ledgers)
        else:
            _build_price_ledger_legacy(price_context, ledgers)

    return ledgers


def _build_price_ledger_legacy(
    price_context: Dict[str, Any],
    ledgers: Dict[str, List[Dict[str, Any]]],
) -> None:
    """Populate price_ledger from the single-horizon (legacy) price_context format."""
    horizon = price_context.get("horizon", "1D")

    def _sorted_by_return(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            [x for x in items if x.get("return") is not None],
            key=lambda x: x["return"],  # type: ignore[arg-type]
            reverse=True,
        )

    ca_all = price_context.get("cross_asset") or []
    ca_sorted = _sorted_by_return(ca_all)
    ledgers["price_ledger"].append({
        "type": "cross_asset_returns",
        "horizon": horizon,
        "evidence_strength": "high",
        "information_role": "market_reaction",
        "items": {
            "top_up":   ca_sorted[:3],
            "top_down": list(reversed(ca_sorted[-3:])) if len(ca_sorted) >= 3 else list(reversed(ca_sorted)),
            "all":      ca_all,
        },
    })

    sec_all = price_context.get("sectors") or []
    sec_sorted = _sorted_by_return(sec_all)
    ledgers["price_ledger"].append({
        "type": "sector_returns",
        "horizon": horizon,
        "evidence_strength": "high",
        "information_role": "market_reaction",
        "items": {
            "leaders":  [x for x in sec_sorted if x.get("return", 0) > 0],
            "laggards": [x for x in sec_sorted if x.get("return", 0) < 0],
            "all":      sec_all,
        },
    })

    sn_all = price_context.get("single_names") or []
    if sn_all:
        sn_sorted = _sorted_by_return(sn_all)
        ledgers["price_ledger"].append({
            "type": "single_name_returns",
            "horizon": horizon,
            "evidence_strength": "high",
            "information_role": "market_reaction",
            "items": {
                "top_up":   sn_sorted[:5],
                "top_down": list(reversed(sn_sorted[-5:])) if len(sn_sorted) >= 5 else list(reversed(sn_sorted)),
                "all":      sn_all,
            },
        })

    rels = price_context.get("relationships") or []
    if rels:
        ledgers["price_ledger"].append({
            "type": "relationship_signals",
            "horizon": horizon,
            "evidence_strength": "medium_high",
            "information_role": "derived_market_reaction",
            "items": rels,
        })

    sec_horizons = price_context.get("secondary_horizons") or {}
    if sec_horizons:
        ledgers["price_ledger"].append({
            "type": "secondary_horizon_returns",
            "evidence_strength": "medium",
            "information_role": "market_reaction",
            "horizons": sec_horizons,
        })


def _build_price_ledger_mtf(
    price_context: Dict[str, Any],
    ledgers: Dict[str, List[Dict[str, Any]]],
) -> None:
    """
    Populate price_ledger from the multi-timeframe price_context format.

    Each asset has a "returns" dict across all horizons plus trend_context
    and relative_returns.  The LLM sees the full multi-horizon picture so
    it can distinguish today's move from the intermediate and long-term trend.
    """
    horizons = price_context.get("horizons") or ["1D", "5D", "1M", "3M", "YTD", "1Y"]

    def _r1d(asset: Dict[str, Any]) -> Optional[float]:
        return (asset.get("returns") or {}).get("1D")

    def _sorted_by_1d(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            [x for x in assets if _r1d(x) is not None],
            key=lambda x: _r1d(x),  # type: ignore[arg-type]
            reverse=True,
        )

    # --- Cross-asset ---
    ca_all = price_context.get("cross_asset") or []
    if ca_all:
        ca_sorted = _sorted_by_1d(ca_all)
        ledgers["price_ledger"].append({
            "type":             "cross_asset_returns",
            "horizons":         horizons,
            "evidence_strength": "high",
            "information_role": "market_reaction",
            "items": {
                "top_up":   ca_sorted[:3],
                "top_down": list(reversed(ca_sorted[-3:])) if len(ca_sorted) >= 3 else list(reversed(ca_sorted)),
                "all":      ca_all,
            },
        })

    # --- Sectors ---
    sec_all = price_context.get("sectors") or []
    if sec_all:
        sec_sorted = _sorted_by_1d(sec_all)
        ledgers["price_ledger"].append({
            "type":             "sector_returns",
            "horizons":         horizons,
            "evidence_strength": "high",
            "information_role": "market_reaction",
            "items": {
                "leaders":  [x for x in sec_sorted if (_r1d(x) or 0) > 0],
                "laggards": [x for x in sec_sorted if (_r1d(x) or 0) < 0],
                "all":      sec_all,
            },
        })

    # --- Single names ---
    sn_all = price_context.get("single_names") or []
    if sn_all:
        sn_sorted = _sorted_by_1d(sn_all)
        ledgers["price_ledger"].append({
            "type":             "single_name_returns",
            "horizons":         horizons,
            "evidence_strength": "high",
            "information_role": "market_reaction",
            "items": {
                "top_up":   sn_sorted[:5],
                "top_down": list(reversed(sn_sorted[-5:])) if len(sn_sorted) >= 5 else list(reversed(sn_sorted)),
                "all":      sn_all,
            },
        })

    # --- Relationship signals (multi-horizon) ---
    rels = price_context.get("relationships") or []
    if rels:
        ledgers["price_ledger"].append({
            "type":             "relationship_signals",
            "horizons":         horizons,
            "evidence_strength": "medium_high",
            "information_role": "derived_market_reaction",
            "items":            rels,
        })


# ---------------------------------------------------------------------------
# Synthesis entry point
# ---------------------------------------------------------------------------

def synthesize_narrative_state(
    bundle: Dict[str, Any],
    market_state_summary: Optional[Dict[str, Any]] = None,
    market_moves: Optional[List[Dict[str, Any]]] = None,
    prior_state: Optional[Dict[str, Any]] = None,
    max_items: int = 80,
    lookback_hours: int = 36,
    model: str = "gpt-5.5",
    client: Optional[Any] = None,
    price_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Returns a JSON dict matching NarrativeStateV1.

    Refactored flow:
      1. dedupe + rank items (selection only)
      2. classify each by information_role + assign ledger + evidence_strength
      3. build information_ledgers (fundamental/policy/narrative/price/alt)
         price_context populates the price_ledger with structured cross-asset,
         sector, and relationship return data.
      4. send ledgers (not flat items) to LLM with a comparison-oriented prompt

    price_context is optional — if None, the price_ledger is populated only
    from market_moves/market_state_summary as before (backward compatible).
    """
    client = client or _get_default_client()

    raw_items = bundle.get("items") or []
    watch_tickers = {str(x).upper() for x in (bundle.get("watch_tickers") or [])}
    compact = [_compact_item(it) for it in raw_items]

    prior_keys = _prior_evidence_keys(prior_state)

    # Step 1+2: dedupe/rank, with per-item _meta carrying role/ledger/strength
    selected_items, filtered_summary = _dedupe_and_rank(
        compact,
        prior_evidence_keys=prior_keys,
        watch_tickers=watch_tickers,
        lookback_hours=lookback_hours,
        limit=max_items,
    )

    # Step 3: build the ledgers (price_context populates price_ledger)
    information_ledgers = _build_information_ledgers(
        selected_items=selected_items,
        market_state_summary=market_state_summary,
        market_moves=market_moves,
        price_context=price_context,
    )

    prior_titles: List[str] = []
    prior_asof = None
    prior_summary = None
    if prior_state:
        prior_titles = [n.get("title") for n in (prior_state.get("dominant_narratives") or []) if n.get("title")]
        prior_asof = prior_state.get("asof_utc")
        prior_summary = prior_state.get("one_paragraph_summary")

    # ---------------- Prompt ----------------
    system = (
        "You are a senior portfolio manager writing a daily narrative-regime delta note "
        "for an investment team. Your job is NOT to summarize articles. Your job is to "
        "compare fundamental reality, policy/company evidence, market narrative, and "
        "observed price behavior, and to surface where they are aligned or misaligned.\n\n"
        "Do not treat official macro data, central bank communication, or earnings results "
        "as the market narrative by default. Treat them primarily as fundamental/policy/"
        "company evidence. Separately identify how investors, media, analysts, and price "
        "action are interpreting that evidence.\n\n"
        "Use price_ledger only for price claims.  Do not infer price implications from narrative"
        "or fundamental items; if you see a narrative or fundamental claim that implies a price move," 
        "label the claim as REALITY or STORY and mark the price implication as a GAP, then check it" 
        "against the price_ledger data to confirm or refute.\n\n"

        "For each major narrative, explicitly state whether: 1) price confirmed the narrative,"
        "2) price contradicted the narrative, 3) price partially confirmed the narrative, or "
        "4) price evidence was unavailable or too mixed to draw a conclusion.\n\n"
        "Use cross-asset and sector relationships to identify divergences, especially: "
        "1) equities vs bonds/credit, 2) growth vs. value, 3) large caps vs small caps, "
        "4) energy/oil vs broad equities, 5) defensives vs cyclicals, 6) tech vs the rest of the market, "
        "7) equal weight vs cap weighted indices, and"
        "and 8) single-name watchlist tickers vs their sector and vs the overall market.\n\n"

        "For every major theme, distinguish:\n"
        "  1. REALITY  — what hard fundamental/policy/company evidence says\n"
        "  2. STORY    — what the market, media, and analysts appear to believe\n"
        "  3. PRICE    — what assets are actually doing\n"
        "  4. GAP      — where reality, story, and price are aligned or misaligned\n"
        "  5. ARCHETYPE — if applicable, classify the setup (momentum persistence, "
        "panic/forced liquidation, crowded trade, narrative-fundamental divergence, "
        "regime shift, credit/equity divergence, value/neglect, vol risk premium, etc.)\n"
        "  6. FALSIFIER — what evidence would change the interpretation\n\n"
        "Ground every claim in the supplied ledgers. If linkage to price action is weak, "
        "state that explicitly. Avoid generic macro recaps unless the regime itself "
        "changed today."
    )

    payload = {
        "asof_utc": bundle.get("asof_utc") or _utc_now_iso(),
        "lookback_hours": int(lookback_hours),
        "market_state": market_state_summary or {},
        "market_moves": _summarize_market_moves(market_moves),
        "prior_context": {
            "asof_utc": prior_asof,
            "summary": prior_summary,
            "dominant_titles": prior_titles,
        },
        # Primary input: the structured ledgers.
        "information_ledgers": information_ledgers,
        # Kept for backwards-compat / debugging; the LLM is instructed to
        # rely on the ledgers, not this list.
        "items": selected_items,
        "instructions": {
            "one_paragraph_summary": (
                "Start with today's net delta vs prior context in 3-6 sentences. "
                "Lead with what changed in REALITY, then how the STORY shifted, then "
                "how PRICE responded, then the dominant GAP."
            ),
            "dominant_narratives": (
                "Return 1-4 narratives. Within each narrative's takeaways, include "
                "lines prefixed with REALITY:, STORY:, PRICE:, and GAP: covering that "
                "specific theme. The narrative's `why_now` must explicitly identify "
                "what is new today and how it plausibly maps to top_up/top_down moves. "
                "Place falsifiers under `what_would_change`."
            ),
            "raw_takeaways": (
                "5-10 bullets covering cross-cutting points. Prefix EACH bullet with "
                "one of: REALITY, STORY, PRICE, GAP, ARCHETYPE, CHANGE, CONFIRMATION, "
                "INVALIDATION, or UNCLEAR — followed by ': ' and the bullet text."
            ),
            "counter_narratives": (
                "List serious alternative explanations drawn from the alternative_views_ledger "
                "or implicit gaps you can defend. Avoid strawmen."
            ),
            "unknowns": (
                "List unresolved data points and falsifiers that would change sizing or "
                "conviction. Prefix entries with FALSIFIER: or UNKNOWN: where useful."
            ),
            "style": "concise, PM desk note, no fluff",
            "ledger_priority": (
                "Use fundamental_ledger and policy_ledger as the basis for REALITY claims. "
                "Use narrative_ledger for STORY claims. Use price_ledger for PRICE claims. "
                "Use alternative_views_ledger for COUNTER claims. Do not promote a "
                "narrative-ledger item to fundamental evidence; cite the actual fundamental "
                "or policy item if such an item exists, otherwise mark the linkage as weak."
            ),
        },
    }

    # ---------------- Debug dump ----------------
    # Captures the exact LLM input plus diagnostic counts so we can validate
    # routing (Fed/BLS/CNBC/blogs landing in the right ledgers).
    role_counts = Counter(
        (it.get("_meta") or {}).get("information_role") or "unknown"
        for it in selected_items
    )
    ledger_counts = {k: len(v) for k, v in information_ledgers.items()}
    tier_counts = Counter(
        (it.get("source_tier") or it.get("tier") or "untiered")
        for it in selected_items
    )
    content_tag_counts = Counter(
        tag
        for it in selected_items
        for tag in ((it.get("_meta") or {}).get("content_tags") or [])
    )

    try:
        date_str = _date_str_from_iso(payload.get("asof_utc"))
        input_dir = Path("data/snapshots").resolve()
        input_dir.mkdir(parents=True, exist_ok=True)
        input_path = input_dir / f"synth_input_{date_str}.json"
        debug_dump = {
            "system_prompt": system,
            "model": model,
            "payload": payload,
            "selected_item_keys": [_item_key(it) for it in selected_items],
            "selected_items_with_meta": [
                {
                    "key": _item_key(it),
                    "title": it.get("title"),
                    "source": it.get("source"),
                    "channel": it.get("channel"),
                    "_meta": it.get("_meta"),
                }
                for it in selected_items
            ],
            "information_ledgers": information_ledgers,
            "ledger_counts": ledger_counts,
            "price_ledger_count": ledger_counts.get("price_ledger", 0),
            "role_counts": dict(role_counts),
            "source_tier_counts": dict(tier_counts),
            # content_tag_counts shows which financial content types were detected
            # across selected items — use this to calibrate infer_content_tags.
            "content_tag_counts": dict(content_tag_counts),
            # filtered_items_summary shows what was excluded before ranking.
            # Non-zero counts here mean boilerplate/low-relevance items were
            # successfully removed before they could pollute ledgers.
            "filtered_items_summary": filtered_summary,
            # price_context_summary: quick sanity-check without parsing the full blob
            "price_context_summary": {
                "format":          (price_context or {}).get("format", "legacy"),
                "horizons":        (price_context or {}).get("horizons"),
                "cross_asset_count":  len((price_context or {}).get("cross_asset") or []),
                "sectors_count":      len((price_context or {}).get("sectors") or []),
                "single_names_count": len((price_context or {}).get("single_names") or []),
                "single_names":       [(x.get("ticker"), x.get("returns", {}).get("1D")) for x in ((price_context or {}).get("single_names") or [])],
                "relationships_count": len((price_context or {}).get("relationships") or []),
                "errors": (price_context or {}).get("errors") or [],
            },
            # price_context: full payload — omit to keep debug file small if needed
            "price_context": price_context,
            "price_context_errors": (price_context or {}).get("errors") or [],
        }
        input_path.write_text(
            json.dumps(debug_dump, indent=2, ensure_ascii=True, default=str),
            encoding="utf-8",
        )
        print(f"[synth] wrote input dump to {input_path}")
    except Exception as e:
        print(f"[synth] failed to write input dump: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    resp = client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ],
        response_format=NarrativeStateV1,
    )
    out = resp.choices[0].message.parsed.model_dump()
    out["_meta"] = {
        "total_items_in_bundle": len(raw_items),
        "items_selected_for_llm": len(selected_items),
        "lookback_hours": int(lookback_hours),
        "prior_snapshot_found": bool(prior_state),
        "ledger_counts": ledger_counts,
        "role_counts": dict(role_counts),
        "content_tag_counts": dict(content_tag_counts),
        "filtered_items_summary": filtered_summary,
        # Full ledger contents — compact views used by the UI for Evidence Board
        # and Price & Timeframe Context rendering.
        "information_ledgers": information_ledgers,
    }
    return out
