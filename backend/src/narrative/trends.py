"""
narrative/trends.py

Google Trends scanner for narrative confirmation and divergence detection.

Two term pools run in parallel:
  1. Static financial taxonomy — always-on baseline attention monitoring
  2. Dynamic narrative-derived terms — extracted from the latest NarrativeStateV1
     snapshot and converted to searchable queries via a lightweight LLM call

Each term produces a TrendSignal with current interest, 4-week z-score, slope
direction, and a narrative_alignment flag when the term came from the synthesis
and its trend direction matches the narrative's stance.

Rate-limit design:
  - pytrends batches max 5 terms per request
  - Randomized 3–8s delay between batches
  - Anchor term ("stock market") included in every batch for cross-batch
    normalization (since each call returns relative 0–100 within the batch)
  - Results cached to parquet; cache is keyed by ISO week so stale data is
    never served but the same week is never re-fetched
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("narrative.trends")
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Static financial taxonomy
# Term groups are thematically coherent; each group is a list of query strings.
# Keys are used as group labels in output.
# ---------------------------------------------------------------------------

STATIC_TERM_GROUPS: Dict[str, List[str]] = {
    # Macro anxiety — the Preis/Da-style terms with demonstrated market correlation
    "macro_anxiety": [
        "recession",
        "economic crisis",
        "stock market crash",
        "market sell off",
        "bear market",
    ],
    "debt_credit": [
        "debt crisis",
        "credit crunch",
        "bank failure",
        "bank run",
        "bankruptcy",
    ],
    "fed_policy": [
        "federal reserve interest rates",
        "rate hike",
        "quantitative tightening",
        "fed pivot",
        "inflation federal reserve",
    ],
    "inflation": [
        "inflation",
        "cpi inflation",
        "cost of living",
        "consumer prices",
        "stagflation",
    ],
    "geopolitical_stress": [
        "war",
        "military conflict",
        "sanctions",
        "trade war",
        "tariffs",
    ],
    "energy": [
        "oil price",
        "gas prices",
        "energy crisis",
        "opec",
        "crude oil",
    ],
    "tech_ai": [
        "artificial intelligence stocks",
        "tech layoffs",
        "semiconductor shortage",
        "nvidia stock",
        "ai bubble",
    ],
    "safe_haven": [
        "gold price",
        "treasury bonds",
        "dollar safe haven",
        "vix volatility",
        "buy gold",
    ],
}

# Anchor term included in every pytrends batch for cross-call normalization.
# Must be stable, high-volume, and financially relevant.
ANCHOR_TERM = "stock market"

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class TrendSignal:
    term: str
    group: str                         # static group name or "narrative_dynamic"
    source: str                        # "static" | "dynamic"
    narrative_title: Optional[str]     # which DominantNarrative this came from (dynamic only)
    narrative_stance: Optional[str]    # stance of that narrative ("risk_on" | "risk_off" | ...)

    # Current week's anchor-normalized interest score (0–100 relative to anchor)
    current_score: float
    # Scores for the trailing N weeks (oldest first), anchor-normalized
    history: List[float]

    # Derived
    zscore_4w: float                   # z-score vs trailing 4-week window
    zscore_12w: float                  # z-score vs trailing 12-week window
    slope_direction: str               # "rising" | "flat" | "falling"
    slope_magnitude: float             # normalized slope (units: score-points per week)

    # Alignment: True when source=="dynamic" and trend direction matches narrative stance
    # rising + risk_off stance → aligned (fear spreading)
    # falling + risk_off stance → diverging (fear fading before narrative resolved)
    narrative_alignment: Optional[bool]
    alignment_note: str

    fetched_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrendScanResult:
    asof_utc: str
    snapshot_date: Optional[str]       # date of the narrative snapshot used
    static_signals: List[TrendSignal]
    dynamic_signals: List[TrendSignal]
    dynamic_terms_raw: List[str]       # LLM-generated query strings before Trends fetch
    meta: Dict[str, Any] = field(default_factory=dict)

    def all_signals(self) -> List[TrendSignal]:
        return self.static_signals + self.dynamic_signals

    def aligned_signals(self) -> List[TrendSignal]:
        return [s for s in self.dynamic_signals if s.narrative_alignment is True]

    def diverging_signals(self) -> List[TrendSignal]:
        return [s for s in self.dynamic_signals if s.narrative_alignment is False]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asof_utc": self.asof_utc,
            "snapshot_date": self.snapshot_date,
            "static_signals": [s.to_dict() for s in self.static_signals],
            "dynamic_signals": [s.to_dict() for s in self.dynamic_signals],
            "dynamic_terms_raw": self.dynamic_terms_raw,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

CACHE_DIR = os.path.join("data", "narrative", "cache")
TRENDS_CACHE_PATH = os.path.join(CACHE_DIR, "trends_cache.parquet")
TRENDS_JSONL_PATH = os.path.join(CACHE_DIR, "trends_cache.jsonl")


def _iso_week(dt: Optional[datetime] = None) -> str:
    """Return ISO week string like '2025-W14' for cache keying."""
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%G-W%V")


def _load_trends_cache() -> Dict[Tuple[str, str], List[float]]:
    """
    Load cached trend histories.
    Key: (term, iso_week) → list of weekly scores (oldest first, up to 52 weeks).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache: Dict[Tuple[str, str], List[float]] = {}
    try:
        if os.path.exists(TRENDS_CACHE_PATH):
            df = pd.read_parquet(TRENDS_CACHE_PATH)
            for _, row in df.iterrows():
                key = (str(row["term"]), str(row["iso_week"]))
                scores_raw = row.get("scores_json", "[]")
                try:
                    cache[key] = json.loads(scores_raw)
                except Exception:
                    cache[key] = []
            logger.debug("Loaded %d trend cache entries (parquet)", len(cache))
            return cache
    except Exception:
        logger.debug("Parquet trend cache unavailable, trying jsonl")

    if os.path.exists(TRENDS_JSONL_PATH):
        with open(TRENDS_JSONL_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                    key = (obj["term"], obj["iso_week"])
                    cache[key] = obj.get("scores", [])
                except Exception:
                    continue
    logger.debug("Loaded %d trend cache entries (jsonl/empty)", len(cache))
    return cache


def _save_trends_cache(cache: Dict[Tuple[str, str], List[float]]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    try:
        records = [
            {"term": k[0], "iso_week": k[1], "scores_json": json.dumps(v)}
            for k, v in cache.items()
        ]
        df = pd.DataFrame.from_records(records)
        df = df.drop_duplicates(subset=["term", "iso_week"], keep="last")
        df.to_parquet(TRENDS_CACHE_PATH, index=False)
        return
    except Exception:
        logger.debug("Parquet trend cache write failed, using jsonl")

    with open(TRENDS_JSONL_PATH, "w", encoding="utf-8") as fh:
        for (term, week), scores in cache.items():
            fh.write(json.dumps({"term": term, "iso_week": week, "scores": scores}) + "\n")


# ---------------------------------------------------------------------------
# pytrends fetching
# ---------------------------------------------------------------------------

def _fetch_batch(
    terms: List[str],
    timeframe: str = "today 3-m",
    geo: str = "US",
    delay_range: Tuple[float, float] = (3.0, 8.0),
    use_finance_category: bool = True,
) -> Dict[str, pd.Series]:
    """
    Fetch a single batch of ≤5 terms from Google Trends.
    Always includes ANCHOR_TERM for normalization.
    Returns dict: term → pd.Series of weekly interest (index=date, values 0–100).

    Raises ImportError if pytrends not installed.
    Raises RuntimeError on fetch failure after retries.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError as e:
        raise ImportError(
            "pytrends is required for trend scanning. "
            "Install with: pip install pytrends"
        ) from e

    # Ensure anchor is in the batch; dedupe; enforce max 5
    batch = list(dict.fromkeys([ANCHOR_TERM] + [t for t in terms if t != ANCHOR_TERM]))[:5]

    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30), retries=2, backoff_factor=1.5)

    cat = 7 if use_finance_category else 0

    for attempt in range(3):
        try:
            pytrends.build_payload(batch, cat=cat, timeframe=timeframe, geo=geo)
            df = pytrends.interest_over_time()
            if df is None or df.empty:
                raise RuntimeError("Empty response from Google Trends")
            break
        except Exception as exc:
            if attempt == 2:
                raise RuntimeError(f"pytrends fetch failed after 3 attempts: {exc}") from exc
            wait = delay_range[0] + random.random() * (delay_range[1] - delay_range[0])
            logger.warning("pytrends attempt %d failed (%s), retrying in %.1fs", attempt + 1, exc, wait)
            time.sleep(wait)

    # Normalize each term relative to anchor so scores are comparable across batches
    anchor_series = df.get(ANCHOR_TERM)
    result: Dict[str, pd.Series] = {}
    for term in terms:
        if term not in df.columns:
            logger.warning("Term '%s' missing from Trends response", term)
            continue
        raw = df[term].astype(float)
        if anchor_series is not None and anchor_series.max() > 0:
            # Scale: term_score / anchor_score * 100, so anchor is always 100
            normalized = (raw / anchor_series.replace(0, np.nan) * 100.0).fillna(0.0)
        else:
            normalized = raw
        result[term] = normalized

    return result


def fetch_terms(
    terms: List[str],
    timeframe: str = "today 3-m",
    geo: str = "US",
    delay_range: Tuple[float, float] = (3.0, 8.0),
    use_finance_category: bool = True,
) -> Dict[str, pd.Series]:
    """
    Fetch interest-over-time for an arbitrary list of terms, auto-batching into
    groups of 4 (leaving 1 slot for the anchor) with rate-limiting delays.

    use_finance_category: when True, restricts to cat=7 (Finance). Static
    taxonomy calls should pass True; dynamic narrative-derived terms should
    pass False because queries like "Iran war" return no data under cat=7.
    """
    BATCH_SIZE = 4  # max 4 non-anchor terms per call (anchor takes the 5th slot)
    batches = [terms[i : i + BATCH_SIZE] for i in range(0, len(terms), BATCH_SIZE)]
    all_results: Dict[str, pd.Series] = {}

    for i, batch in enumerate(batches):
        if i > 0:
            delay = delay_range[0] + random.random() * (delay_range[1] - delay_range[0])
            logger.debug("Rate-limit delay: %.1fs before batch %d/%d", delay, i + 1, len(batches))
            time.sleep(delay)

        try:
            batch_result = _fetch_batch(
                batch, timeframe=timeframe, geo=geo, delay_range=delay_range,
                use_finance_category=use_finance_category,
            )
            all_results.update(batch_result)
        except Exception as exc:
            logger.error("Batch %d/%d failed: %s. Skipping terms: %s", i + 1, len(batches), exc, batch)

    return all_results


# ---------------------------------------------------------------------------
# Signal derivation
# ---------------------------------------------------------------------------

def _derive_signal(
    term: str,
    group: str,
    source: str,
    series: pd.Series,
    narrative_title: Optional[str] = None,
    narrative_stance: Optional[str] = None,
) -> TrendSignal:
    """
    Derive a TrendSignal from a raw weekly interest series.
    """
    values = series.dropna().tolist()

    if not values:
        return TrendSignal(
            term=term, group=group, source=source,
            narrative_title=narrative_title, narrative_stance=narrative_stance,
            current_score=0.0, history=[],
            zscore_4w=0.0, zscore_12w=0.0,
            slope_direction="flat", slope_magnitude=0.0,
            narrative_alignment=None,
            alignment_note="no data",
        )

    current = float(values[-1])

    # Z-scores
    def _zscore(window: int) -> float:
        recent = values[-window:] if len(values) >= window else values
        if len(recent) < 2:
            return 0.0
        mu = np.mean(recent[:-1])  # exclude current from mean/std
        sigma = np.std(recent[:-1], ddof=0)
        if sigma == 0:
            return 0.0
        return float((current - mu) / sigma)

    zscore_4w = _zscore(4)
    zscore_12w = _zscore(12)

    # Slope: linear regression over last 4 weeks
    recent_4 = values[-4:] if len(values) >= 4 else values
    if len(recent_4) >= 2:
        x = np.arange(len(recent_4), dtype=float)
        slope = float(np.polyfit(x, recent_4, 1)[0])
    else:
        slope = 0.0

    slope_magnitude = round(slope, 3)
    if slope > 1.5:
        slope_direction = "rising"
    elif slope < -1.5:
        slope_direction = "falling"
    else:
        slope_direction = "flat"

    # Narrative alignment logic
    alignment: Optional[bool] = None
    alignment_note = ""

    if source == "dynamic" and narrative_stance is not None:
        stance = narrative_stance.lower()
        if stance == "risk_off":
            # Fear-driven narrative: we expect public search anxiety to be rising
            if slope_direction == "rising" and zscore_4w > 0.5:
                alignment = True
                alignment_note = "Rising search anxiety confirms risk-off narrative"
            elif slope_direction == "falling" or zscore_4w < -0.5:
                alignment = False
                alignment_note = "Declining search interest diverges from risk-off narrative — fear may be peaking"
            else:
                alignment_note = "Flat search trend, inconclusive vs risk-off narrative"
        elif stance == "risk_on":
            # Growth/bullish narrative: search anxiety terms should be declining
            if slope_direction == "falling" or zscore_4w < -0.3:
                alignment = True
                alignment_note = "Declining search concern confirms risk-on narrative"
            elif slope_direction == "rising" and zscore_4w > 0.5:
                alignment = False
                alignment_note = "Rising search anxiety diverges from risk-on narrative — public not bought in"
            else:
                alignment_note = "Flat search trend, inconclusive vs risk-on narrative"
        else:
            alignment_note = f"Stance '{stance}' — no directional alignment rule defined"
    elif source == "static":
        alignment_note = "Static term — no narrative alignment check"

    return TrendSignal(
        term=term,
        group=group,
        source=source,
        narrative_title=narrative_title,
        narrative_stance=narrative_stance,
        current_score=round(current, 2),
        history=[round(v, 2) for v in values],
        zscore_4w=round(zscore_4w, 3),
        zscore_12w=round(zscore_12w, 3),
        slope_direction=slope_direction,
        slope_magnitude=slope_magnitude,
        narrative_alignment=alignment,
        alignment_note=alignment_note,
    )


# ---------------------------------------------------------------------------
# Dynamic term extraction from NarrativeStateV1
# ---------------------------------------------------------------------------

def extract_narrative_query_terms(
    snapshot: Dict[str, Any],
    model: Optional[str] = None,
    max_terms_per_narrative: int = 3,
    openai_client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Extract Google-searchable query strings from a NarrativeStateV1 snapshot.

    For each DominantNarrative, sends the title, why_now, and key_catalysts to
    a cheap LLM call that converts them into 1–3 concrete search queries a
    worried retail investor might actually type into Google.

    Returns list of dicts:
        {"term": str, "narrative_title": str, "narrative_stance": str, "confidence": int}
    """
    narratives = snapshot.get("dominant_narratives") or []
    if not narratives:
        logger.info("No dominant narratives in snapshot — skipping dynamic term extraction")
        return []

    # Also extract tickers as direct search terms (e.g. "NVDA stock" is a valid Trends query)
    ticker_terms: List[Dict[str, Any]] = []
    for n in narratives:
        stance = n.get("stance", "unclear")
        title = n.get("title", "")
        for ticker in (n.get("tickers") or [])[:3]:  # cap at 3 tickers per narrative
            ticker_terms.append({
                "term": f"{ticker} stock",
                "narrative_title": title,
                "narrative_stance": stance,
                "confidence": n.get("confidence", 50),
            })

    # LLM call to convert narrative prose into search queries
    system = (
        "You convert financial market narrative descriptions into Google search queries. "
        "Output ONLY a JSON array of objects. Each object has: "
        "'term' (the search query string, 1-5 words, as a retail investor would type it), "
        "'narrative_title' (copied from input), "
        "'narrative_stance' (copied from input). "
        "Make queries specific and searchable. Avoid jargon. "
        "Bad: 'monetary policy transmission mechanism'. "
        "Good: 'federal reserve rate hike recession'. "
        "Return only the JSON array, no other text."
    )

    narrative_inputs = []
    for n in narratives:
        narrative_inputs.append({
            "title": n.get("title", ""),
            "stance": n.get("stance", "unclear"),
            "confidence": n.get("confidence", 50),
            "why_now": (n.get("why_now") or "")[:300],  # truncate for token efficiency
            "key_catalysts": (n.get("key_catalysts") or [])[:4],
        })

    prompt = (
        f"For each narrative below, generate {max_terms_per_narrative} Google search queries "
        f"that a worried retail investor might search RIGHT NOW about this topic.\n\n"
        f"Narratives:\n{json.dumps(narrative_inputs, indent=2)}"
    )

    llm_terms: List[Dict[str, Any]] = []
    try:
        from src.narrative.runtime_config import assert_llm_calls_allowed
        assert_llm_calls_allowed("narrative trend query generation")
        if openai_client is None:
            from openai import OpenAI
            openai_client = OpenAI()
        if not model:
            from src.narrative.config import PREPROCESSING_MODEL
            model = PREPROCESSING_MODEL

        resp = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        raw = resp.choices[0].message.content or ""
        # Strip markdown fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and "term" in item:
                    llm_terms.append({
                        "term": str(item["term"]).strip().lower()[:80],
                        "narrative_title": item.get("narrative_title", ""),
                        "narrative_stance": item.get("narrative_stance", "unclear"),
                        "confidence": 50,
                    })
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Dynamic term extraction LLM call failed: %s", exc)

    all_terms = llm_terms + ticker_terms
    # Dedupe by term string
    seen = set()
    deduped = []
    for t in all_terms:
        key = t["term"].lower().strip()
        if key not in seen and key:
            seen.add(key)
            deduped.append(t)

    logger.info("Extracted %d dynamic terms from narrative snapshot (%d from LLM, %d from tickers)",
                len(deduped), len(llm_terms), len(ticker_terms))
    return deduped


# ---------------------------------------------------------------------------
# Main scan function
# ---------------------------------------------------------------------------

def run_trend_scan(
    snapshot: Optional[Dict[str, Any]] = None,
    snapshot_date: Optional[str] = None,
    geo: str = "US",
    timeframe: str = "today 3-m",
    delay_range: Tuple[float, float] = (3.0, 8.0),
    llm_model: Optional[str] = None,
    openai_client: Optional[Any] = None,
    skip_static: bool = False,
    skip_dynamic: bool = False,
    use_cache: bool = True,
) -> TrendScanResult:
    """
    Run the full trend scan.

    Args:
        snapshot: NarrativeStateV1 dict (from synth.py output). If None, only
                  static terms are scanned.
        snapshot_date: ISO date string for the snapshot (used in output metadata).
        geo: Google Trends geo code (default "US").
        timeframe: pytrends timeframe string (default "today 3-m" = 90 days).
        delay_range: (min, max) seconds to wait between pytrends batches.
        llm_model: Model to use for dynamic term extraction.
        openai_client: Optional pre-initialized OpenAI client.
        skip_static: Skip static taxonomy scan (for testing dynamic only).
        skip_dynamic: Skip dynamic term extraction (static only).
        use_cache: Whether to use/write the parquet cache.

    Returns:
        TrendScanResult with all signals.
    """
    asof = datetime.now(timezone.utc).isoformat()
    current_week = _iso_week()

    # Load cache
    cache = _load_trends_cache() if use_cache else {}

    static_signals: List[TrendSignal] = []
    dynamic_signals: List[TrendSignal] = []
    dynamic_terms_raw: List[str] = []
    meta: Dict[str, Any] = {"geo": geo, "timeframe": timeframe, "iso_week": current_week}

    # ── 1. Static taxonomy ──────────────────────────────────────────────────
    if not skip_static:
        all_static_terms = []
        term_to_group: Dict[str, str] = {}
        for group, terms in STATIC_TERM_GROUPS.items():
            for t in terms:
                all_static_terms.append(t)
                term_to_group[t] = group

        # Check cache first — skip terms we already fetched this week
        uncached = [t for t in all_static_terms if (t, current_week) not in cache]
        cached_hits = len(all_static_terms) - len(uncached)
        logger.info("Static terms: %d total, %d cached, %d to fetch",
                    len(all_static_terms), cached_hits, len(uncached))

        if uncached:
            fetched = fetch_terms(uncached, timeframe=timeframe, geo=geo,
                                  delay_range=delay_range, use_finance_category=True)
            for term, series in fetched.items():
                cache[(term, current_week)] = series.tolist()
            if use_cache:
                _save_trends_cache(cache)

        # Build signals from cache
        for term in all_static_terms:
            cached_scores = cache.get((term, current_week), [])
            if not cached_scores:
                logger.warning("No data for static term '%s'", term)
                continue
            series = pd.Series(cached_scores)
            sig = _derive_signal(
                term=term,
                group=term_to_group[term],
                source="static",
                series=series,
            )
            static_signals.append(sig)

        meta["static_terms_fetched"] = len(all_static_terms)
        meta["static_cache_hits"] = cached_hits

    # ── 2. Dynamic narrative-derived terms ─────────────────────────────────
    if not skip_dynamic and snapshot is not None:
        extracted = extract_narrative_query_terms(
            snapshot,
            model=llm_model,
            openai_client=openai_client,
        )
        dynamic_terms_raw = [e["term"] for e in extracted]

        uncached_dyn = [e["term"] for e in extracted if (e["term"], current_week) not in cache]
        logger.info("Dynamic terms: %d total, %d to fetch", len(extracted), len(uncached_dyn))

        if uncached_dyn:
            fetched_dyn = fetch_terms(uncached_dyn, timeframe=timeframe, geo=geo,
                                      delay_range=delay_range, use_finance_category=False)
            for term, series in fetched_dyn.items():
                cache[(term, current_week)] = series.tolist()
            if use_cache:
                _save_trends_cache(cache)

        for entry in extracted:
            term = entry["term"]
            cached_scores = cache.get((term, current_week), [])
            if not cached_scores:
                logger.warning("No Trends data returned for dynamic term '%s'", term)
                continue
            series = pd.Series(cached_scores)
            sig = _derive_signal(
                term=term,
                group="narrative_dynamic",
                source="dynamic",
                series=series,
                narrative_title=entry.get("narrative_title"),
                narrative_stance=entry.get("narrative_stance"),
            )
            dynamic_signals.append(sig)

        meta["dynamic_terms_extracted"] = len(extracted)
        meta["dynamic_terms_with_data"] = len(dynamic_signals)

    logger.info(
        "Trend scan complete: %d static signals, %d dynamic signals (%d aligned, %d diverging)",
        len(static_signals),
        len(dynamic_signals),
        sum(1 for s in dynamic_signals if s.narrative_alignment is True),
        sum(1 for s in dynamic_signals if s.narrative_alignment is False),
    )

    return TrendScanResult(
        asof_utc=asof,
        snapshot_date=snapshot_date,
        static_signals=static_signals,
        dynamic_signals=dynamic_signals,
        dynamic_terms_raw=dynamic_terms_raw,
        meta=meta,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

SCAN_OUTPUT_DIR = os.path.join("data", "narrative", "trends")


def save_scan_result(result: TrendScanResult, base_dir: str = SCAN_OUTPUT_DIR) -> Path:
    """Save a TrendScanResult as a dated JSON snapshot."""
    out_dir = Path(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = (result.snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    path = out_dir / f"trends_{date_str}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    logger.info("Saved trend scan result to %s", path)
    return path


def load_scan_result(date_str: str, base_dir: str = SCAN_OUTPUT_DIR) -> Optional[Dict[str, Any]]:
    """Load a saved TrendScanResult dict by date."""
    path = Path(base_dir) / f"trends_{date_str}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load trend scan for %s: %s", date_str, exc)
        return None


def build_trend_history_df(base_dir: str = SCAN_OUTPUT_DIR) -> pd.DataFrame:
    """
    Read all saved trend scan JSON files and assemble a long-form DataFrame
    suitable for time-series analysis and plotting.

    Columns: date, term, group, source, current_score, zscore_4w, zscore_12w,
             slope_direction, slope_magnitude, narrative_alignment, narrative_title
    """
    records = []
    scan_dir = Path(base_dir)
    if not scan_dir.exists():
        return pd.DataFrame()

    for path in sorted(scan_dir.glob("trends_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            date_str = data.get("snapshot_date") or path.stem.replace("trends_", "")
            for sig in data.get("static_signals", []) + data.get("dynamic_signals", []):
                records.append({
                    "date": date_str,
                    "term": sig["term"],
                    "group": sig["group"],
                    "source": sig["source"],
                    "current_score": sig["current_score"],
                    "zscore_4w": sig["zscore_4w"],
                    "zscore_12w": sig["zscore_12w"],
                    "slope_direction": sig["slope_direction"],
                    "slope_magnitude": sig["slope_magnitude"],
                    "narrative_alignment": sig.get("narrative_alignment"),
                    "narrative_title": sig.get("narrative_title"),
                    "narrative_stance": sig.get("narrative_stance"),
                    "alignment_note": sig.get("alignment_note", ""),
                })
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", path, exc)

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame.from_records(records)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "source", "term"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# CLI entry point  (python -m narrative.trends --snapshot path/to/state.json)
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    from dotenv import load_dotenv
    load_dotenv()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    p = argparse.ArgumentParser(description="Run Google Trends narrative scan")
    p.add_argument("--snapshot", default=None, help="Path to NarrativeStateV1 JSON snapshot")
    p.add_argument("--snapshot-date", default=None, help="Date label for output (YYYY-MM-DD)")
    p.add_argument("--geo", default="US", help="Google Trends geo code")
    p.add_argument("--timeframe", default="today 3-m", help="pytrends timeframe string")
    p.add_argument("--skip-static", action="store_true")
    p.add_argument("--skip-dynamic", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--output-dir", default=SCAN_OUTPUT_DIR)
    args = p.parse_args(argv)

    snapshot = None
    if args.snapshot:
        with open(args.snapshot, "r", encoding="utf-8") as fh:
            snapshot = json.load(fh)

    result = run_trend_scan(
        snapshot=snapshot,
        snapshot_date=args.snapshot_date,
        geo=args.geo,
        timeframe=args.timeframe,
        skip_static=args.skip_static,
        skip_dynamic=args.skip_dynamic,
        use_cache=not args.no_cache,
    )

    out_path = save_scan_result(result, base_dir=args.output_dir)

    # Summary printout
    print(f"\nTrend scan complete — {result.asof_utc}")
    print(f"Static signals:  {len(result.static_signals)}")
    print(f"Dynamic signals: {len(result.dynamic_signals)}")
    if result.dynamic_signals:
        aligned = result.aligned_signals()
        diverging = result.diverging_signals()
        print(f"  Aligned:   {len(aligned)}")
        print(f"  Diverging: {len(diverging)}")
        if diverging:
            print("\nDivergence alerts (narrative vs public attention):")
            for s in diverging:
                print(f"  [{s.narrative_stance}] '{s.term}' — {s.alignment_note}")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
