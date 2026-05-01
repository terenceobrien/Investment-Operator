from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone, date
from typing import Any, Dict, List, Optional, Tuple
import re

from src.data.news_finnhub import fetch_market_news, fetch_company_news, normalize_news_item
from src.data.earnings_finnhub import fetch_earnings_calendar, normalize_earnings_item

# Restrict Finnhub-republished content to publishers we can't get elsewhere.
# Reuters has no first-party RSS, so Finnhub is our only access path.
# All other Finnhub publishers (SeekingAlpha, CNBC, Yahoo, Benzinga, ChartMill)
# are either covered by Wave 1 RSS sources or judged low-signal.
FINNHUB_PUBLISHER_ALLOWLIST = {"Reuters"}


def _is_allowed_finnhub_publisher(item: dict) -> bool:
    src = (item.get("source") or "").strip()
    return src in FINNHUB_PUBLISHER_ALLOWLIST

@dataclass
class NarrativeBundle:
    asof_utc: str
    items: List[Dict[str, Any]]
    watch_tickers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Dedupe by URL if present, else source + normalized title.
    """
    def _norm_title(x: Any) -> str:
        s = str(x or "").lower()
        s = re.sub(r"\s+", " ", s).strip()
        s = re.sub(r"[^a-z0-9 ]+", "", s)
        return s

    seen = set()
    out = []
    for it in items:
        key = it.get("url") or (it.get("source"), _norm_title(it.get("title")))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def items_from_sources(
    source_specs: List[Tuple[Any, dict]],
    lookback_hours: int = 36,
) -> List[Dict[str, Any]]:
    """
    Fetch items from a list of (source, metadata) pairs, optionally enrich
    with full article text for non-paywalled sources, and return dicts in the
    shape build_narrative_bundle expects (channel, source, timestamp_utc,
    title, summary, tickers, url, raw).

    Lazy-imports enrich_items and normalize_whitespace to avoid module-level
    import-chain failures when trafilatura or cleaning's own dependencies are
    not yet installed.  Missing trafilatura raises ImportError immediately with
    a clear install hint — it is a required dependency for enrichment.
    """
    try:
        from src.narrative.enrich.article_fetch import enrich_items  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            f"Article enrichment dependency missing: {exc}. "
            "Install required packages: pip install trafilatura pandas"
        ) from exc

    def _normalize_ws(text: str) -> str:
        """Inline whitespace normalizer — equivalent to cleaning.normalize_whitespace."""
        if not text:
            return ""
        return re.sub(r"\s+", " ", text).strip()

    start = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    end = datetime.now(timezone.utc)

    # Collect raw items per source, preserving which meta dict they came from
    non_paywalled_pairs: List[Tuple[Any, dict]] = []  # (RawTextItem, meta)
    paywalled_pairs: List[Tuple[Any, dict]] = []

    for source, meta in source_specs:
        try:
            raw_items = source.fetch(start=start, end=end)
        except Exception as exc:
            import logging
            logging.getLogger("narrative.bundle").warning(
                "Failed to fetch from source %r: %s", meta.get("Source Name"), exc
            )
            raw_items = []
        if meta.get("Paywall"):
            paywalled_pairs.extend((it, meta) for it in raw_items)
        else:
            non_paywalled_pairs.extend((it, meta) for it in raw_items)

    # Enrich non-paywalled items (fetches full article text where possible)
    if non_paywalled_pairs:
        raw_non_pw = [it for it, _ in non_paywalled_pairs]
        enriched_non_pw = enrich_items(raw_non_pw)
    else:
        enriched_non_pw = []

    # Paywalled items keep their RSS summary body as-is
    enriched_paywalled = [it for it, _ in paywalled_pairs]

    def _to_bundle_dict(item: Any, meta: dict) -> Dict[str, Any]:
        ts: Optional[float] = None
        pub = getattr(item, "published_at", None)
        if pub is not None:
            try:
                ts = pub.timestamp()
            except Exception:
                ts = None
        summary = _normalize_ws(getattr(item, "body", "") or "")
        return {
            "channel": meta.get("Channel", ""),
            "source": meta.get("Source Name") or getattr(item, "source", ""),
            "timestamp_utc": ts,
            "title": getattr(item, "title", None),
            "summary": summary,
            "tickers": getattr(item, "tickers", None) or [],
            "url": getattr(item, "url", None),
            "raw": {
                "tier": meta.get("Tier"),
                "paywall": meta.get("Paywall"),
                "extraction_success": (getattr(item, "metadata", {}) or {}).get(
                    "full_text_extraction_success"
                ),
                "word_count": (getattr(item, "metadata", {}) or {}).get(
                    "article_word_count", 0
                ),
            },
        }

    result: List[Dict[str, Any]] = []
    for item, meta in zip(enriched_non_pw, (m for _, m in non_paywalled_pairs)):
        result.append(_to_bundle_dict(item, meta))
    for item, (_, meta) in zip(enriched_paywalled, paywalled_pairs):
        result.append(_to_bundle_dict(item, meta))

    return result


def build_narrative_bundle(
    watch_tickers: List[str],
    news_category: str = "general",
    news_limit: int = 30,
    ticker_news_limit: int = 10,
    earnings_days_ahead: int = 7,
    sources: Optional[List[Tuple[Any, dict]]] = None,
    lookback_hours: int = 36,
) -> NarrativeBundle:
    # ---- News: general market ----
    items: List[Dict[str, Any]] = []
    market_news_raw = fetch_market_news(category=news_category, limit=news_limit)
    market_news_filtered = [x for x in market_news_raw if _is_allowed_finnhub_publisher(x)]
    items += [normalize_news_item(x, channel="news") for x in market_news_filtered]

    # ---- News: per ticker (last 1 day) ----
    today = date.today()
    yesterday = today - timedelta(days=1)
    for t in watch_tickers:
        raw = fetch_company_news(symbol=t, from_date=yesterday, to_date=today, limit=ticker_news_limit)
        raw_filtered = [x for x in raw if _is_allowed_finnhub_publisher(x)]
        items += [normalize_news_item(x, channel="ticker_news") for x in raw_filtered]

    # ---- Earnings: next N days ----
    to_dt = today + timedelta(days=earnings_days_ahead)
    earnings_raw = fetch_earnings_calendar(from_date=today, to_date=to_dt, symbol=None)
    items += [normalize_earnings_item(x) for x in earnings_raw]

    # ---- External sources (RSS / local files) ----
    if sources is not None:
        rss_items = items_from_sources(sources, lookback_hours=lookback_hours)
        items += rss_items

    items = _dedupe_items(items)

    return NarrativeBundle(asof_utc=_utc_now_iso(), items=items, watch_tickers=list(watch_tickers))

def top_n_by_channel(items: list[dict], n: int = 20) -> dict[str, list[dict]]:
    """
    Returns dict with keys: news, ticker_news, earnings
    Sorts news channels by recency, then keeps top n per channel.
    """
    out = {"news": [], "ticker_news": [], "earnings": []}
    for it in items:
        ch = (it.get("channel") or "").lower()
        if ch not in out:
            continue
        out[ch].append(it)

    def _sort_key(it: dict) -> tuple:
        # News/ticker_news use unix timestamp; earnings may only have date in raw payload.
        ts = it.get("timestamp_utc")
        if isinstance(ts, (int, float)):
            return (1, float(ts))
        raw_date = (it.get("raw") or {}).get("date")
        if isinstance(raw_date, str):
            try:
                dt = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                return (0, dt.timestamp())
            except Exception:
                pass
        return (0, 0.0)

    for ch in out:
        out[ch] = sorted(out[ch], key=_sort_key, reverse=True)[:n]
    return out
