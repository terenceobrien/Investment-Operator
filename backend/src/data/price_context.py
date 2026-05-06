"""
price_context.py — Reusable price context builder for backend use.

Shared by:
  1. /api/prices/heatmap  — returns sector/cross-asset returns for the UI
  2. Narrative synthesis  — populates price_ledger so the LLM can compare
                           narrative/fundamentals against actual market behavior

Nothing in here depends on auth, database, or HTTP request context.

Contract: build_price_context and build_price_context_sync NEVER raise.
If all price fetching fails, they return the empty-result skeleton with an
"errors" list so callers can log what went wrong without crashing.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger("data.price_context")

# ---------------------------------------------------------------------------
# Universes
# ---------------------------------------------------------------------------

SECTORS: Dict[str, str] = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Technology",
    "XLP": "Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Discretionary",
    "XLC": "Comm Services",
    "XLRE": "Real Estate",
}

CROSS: Dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "TLT": "20Y+ Treas",
    "HYG": "High Yield",
    "GLD": "Gold",
    "USO": "Oil",
    "BTC-USD": "Bitcoin",
}

# Trading-day count per horizon label.  "YTD" is handled specially.
_HORIZON_DAYS: Dict[str, Any] = {
    "1D": 1,
    "5D": 5,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
    "YTD": "YTD",
}

_SECONDARY_HORIZONS = ["5D", "1M"]


def _empty_result(horizon: str, errors: List[str]) -> Dict[str, Any]:
    """Canonical empty result returned when all price fetching fails."""
    return {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "cross_asset": [],
        "sectors": [],
        "single_names": [],
        "relationships": [],
        "secondary_horizons": {},
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def calc_return(series: pd.Series, h: Any) -> Optional[float]:
    """
    Percentage return over horizon h (int trading days, or "YTD").
    Returns None when the series is too short or all-NaN.
    """
    try:
        s = series.dropna()
        if s.empty:
            return None
        if h == "YTD":
            start_of_year = pd.Timestamp(datetime.now().year, 1, 1)
            ytd = s[s.index >= start_of_year]
            if len(ytd) < 2:
                return None
            return float((ytd.iloc[-1] / ytd.iloc[0] - 1) * 100)
        n = int(h)
        if len(s) <= n:
            return None
        return float((s.iloc[-1] / s.iloc[-(n + 1)] - 1) * 100)
    except Exception as exc:
        logger.debug("calc_return failed: %s", exc)
        return None


def _last_price(series: pd.Series) -> Optional[float]:
    try:
        s = series.dropna()
        return float(s.iloc[-1]) if not s.empty else None
    except Exception:
        return None


def _extract_closes(data: Any, tickers: List[str]) -> pd.DataFrame:
    """
    Normalize a yfinance download result to a DataFrame of Close prices,
    one column per ticker.

    yfinance can return data in several layouts:
      A. MultiIndex(level0=field, level1=ticker)  ← most common for multi-ticker
      B. MultiIndex(level0=ticker, level1=field)  ← seen in some yfinance versions
      C. Flat columns with "Close" column          ← single ticker
      D. Flat columns without "Close"              ← already just prices

    Tries each layout in order; falls back to an empty DataFrame on failure.
    """
    if data is None or (hasattr(data, "empty") and data.empty):
        return pd.DataFrame()

    try:
        if isinstance(data.columns, pd.MultiIndex):
            lvl0 = list(data.columns.get_level_values(0).unique())
            lvl1 = list(data.columns.get_level_values(1).unique())

            if "Close" in lvl0:
                # Layout A: (field, ticker)
                return data.xs("Close", axis=1, level=0)

            if "Close" in lvl1:
                # Layout B: (ticker, field)
                return data.xs("Close", axis=1, level=1)

            logger.warning(
                "_extract_closes: 'Close' not found in either MultiIndex level. "
                "level0 sample=%s, level1 sample=%s",
                lvl0[:5],
                lvl1[:5],
            )
            return pd.DataFrame()

        # Flat columns
        if "Close" in data.columns:
            closes = data[["Close"]].copy()
            # Single-ticker downloads have the column named "Close", not the ticker
            if len(tickers) == 1:
                closes.columns = [tickers[0]]
            return closes

        # Last resort: assume data is already a price frame
        return data.copy()

    except Exception as exc:
        logger.error(
            "_extract_closes failed: %s\n%s",
            exc,
            traceback.format_exc(),
        )
        return pd.DataFrame()


def _download_closes_sync(tickers: List[str]) -> pd.DataFrame:
    """
    Blocking yfinance download of 2 years of daily closes.
    Call via asyncio.to_thread — do not await directly.
    Logs full traceback on failure; always returns a DataFrame (may be empty).
    """
    import yfinance as yf

    try:
        data = yf.download(
            tickers,
            period="2y",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
        if data is None or (hasattr(data, "empty") and data.empty):
            logger.warning("_download_closes_sync: yfinance returned empty data for %s", tickers[:5])
            return pd.DataFrame()
        result = _extract_closes(data, tickers)
        if result.empty:
            logger.warning("_download_closes_sync: _extract_closes returned empty for %s", tickers[:5])
        else:
            logger.debug(
                "_download_closes_sync: OK — %d tickers, %d rows",
                len(result.columns),
                len(result),
            )
        return result
    except Exception as exc:
        logger.error(
            "_download_closes_sync failed for tickers=%s: %s\n%s",
            tickers[:8],
            exc,
            traceback.format_exc(),
        )
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# Relationship signals
# ---------------------------------------------------------------------------

def _relationship(
    name: str,
    value: float,
    positive_read: str,
    negative_read: str,
) -> Dict[str, Any]:
    return {
        "name": name,
        "value": round(value, 3),
        "interpretation": positive_read if value >= 0 else negative_read,
    }


def _build_relationships(returns: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    """
    Six cross-asset pairwise signals.  Each is only included when both
    tickers have a non-None return.
    """
    def diff(a: str, b: str) -> Optional[float]:
        ra, rb = returns.get(a), returns.get(b)
        if ra is None or rb is None:
            return None
        return ra - rb

    specs = [
        ("QQQ minus SPY", "QQQ", "SPY",
         "growth/mega-cap tech leadership",
         "growth/mega-cap tech lagging broad market"),
        ("IWM minus SPY", "IWM", "SPY",
         "small-cap breadth and risk appetite leading",
         "small-cap underperformance / narrow mega-cap leadership"),
        ("HYG minus TLT", "HYG", "TLT",
         "credit/risk-on outperforming duration",
         "credit/risk appetite weaker than duration / flight to safety"),
        ("XLE minus SPY", "XLE", "SPY",
         "energy/oil sector leadership",
         "energy lagging broad market"),
        ("XLK minus SPY", "XLK", "SPY",
         "technology sector leadership",
         "technology underperformance vs broad market"),
        ("XLY minus XLP", "XLY", "XLP",
         "cyclical consumer outperforming staples / risk appetite",
         "defensive consumer outperforming discretionary / risk-off rotation"),
    ]

    out: List[Dict[str, Any]] = []
    for name, a, b, pos, neg in specs:
        try:
            v = diff(a, b)
            if v is not None:
                out.append(_relationship(name, v, pos, neg))
        except Exception as exc:
            logger.debug("relationship '%s' failed: %s", name, exc)
    return out


# ---------------------------------------------------------------------------
# Main builder — never raises
# ---------------------------------------------------------------------------

async def build_price_context(
    horizon: str = "1D",
    watch_tickers: Optional[List[str]] = None,
    include_secondary_horizons: bool = True,
) -> Dict[str, Any]:
    """
    Async price context builder.  One yfinance download covers all universes.

    CONTRACT: This function never raises.  If a step fails, the error is
    recorded in result["errors"] and processing continues with the data
    that is available.  Callers can check result["errors"] to determine
    whether any data is missing.

    Parameters
    ----------
    horizon : str
        Primary horizon label ("1D", "5D", "1M", "3M", "YTD", ...).
    watch_tickers : list[str] | None
        Additional single-name tickers (e.g. the narrative watchlist).
        Tickers already in SECTORS or CROSS are deduplicated.
    include_secondary_horizons : bool
        When True, also computes 5D and 1M returns from the same dataset.

    Returns
    -------
    {
        "asof_utc": str,
        "horizon": str,
        "cross_asset": [{"ticker", "name", "return", "last"}, ...],
        "sectors":     [{"ticker", "name", "return", "last"}, ...],
        "single_names":[{"ticker", "name", "return", "last"}, ...],
        "relationships":[{"name", "value", "interpretation"}, ...],
        "secondary_horizons": {"5D": {...}, "1M": {...}},
        "errors": [],   # non-empty if any step failed
    }
    "return" and "last" are None for tickers where data was unavailable.
    """
    errors: List[str] = []
    h_days = _HORIZON_DAYS.get(horizon, 1)

    # Tickers in watch_tickers not already in the standard universes
    extra_tickers: List[str] = [
        t for t in (watch_tickers or [])
        if t not in SECTORS and t not in CROSS
    ]
    all_tickers = list(SECTORS.keys()) + list(CROSS.keys()) + extra_tickers

    # --- Download ---
    closes = pd.DataFrame()
    try:
        closes = await asyncio.to_thread(_download_closes_sync, all_tickers)
        if closes.empty:
            errors.append(
                f"yfinance returned empty closes for {len(all_tickers)} tickers "
                f"(horizon={horizon}, first 5: {all_tickers[:5]})"
            )
            logger.error(
                "build_price_context: empty closes — horizon=%s, tickers=%s",
                horizon, all_tickers[:8],
            )
        else:
            logger.info(
                "build_price_context: download OK — %d tickers, %d rows, horizon=%s",
                len(closes.columns), len(closes), horizon,
            )
    except Exception as exc:
        tb = traceback.format_exc()
        msg = f"download exception: {type(exc).__name__}: {exc}"
        errors.append(msg)
        logger.error(
            "build_price_context: %s\nhorizon=%s, watch_tickers=%s\n%s",
            msg, horizon, watch_tickers, tb,
        )

    # If download completely failed, return empty skeleton
    if closes.empty and not all_tickers:
        return _empty_result(horizon, errors)

    # Per-ticker return cache for relationship calculations
    _returns: Dict[str, Optional[float]] = {}

    def _row(ticker: str, name: str) -> Dict[str, Any]:
        try:
            ret = calc_return(closes[ticker], h_days) if ticker in closes else None
            last = _last_price(closes[ticker]) if ticker in closes else None
        except Exception as exc:
            logger.debug("_row failed for %s: %s", ticker, exc)
            ret, last = None, None
        _returns[ticker] = ret
        return {"ticker": ticker, "name": name, "return": ret, "last": last}

    # --- Build output lists ---
    cross_asset: List[Dict[str, Any]] = []
    try:
        cross_asset = [_row(t, name) for t, name in CROSS.items()]
    except Exception as exc:
        errors.append(f"cross_asset build failed: {exc}")
        logger.error("build_price_context cross_asset: %s", exc, exc_info=True)

    sectors: List[Dict[str, Any]] = []
    try:
        sectors = [_row(t, name) for t, name in SECTORS.items()]
    except Exception as exc:
        errors.append(f"sectors build failed: {exc}")
        logger.error("build_price_context sectors: %s", exc, exc_info=True)

    single_names: List[Dict[str, Any]] = []
    try:
        single_names = [_row(t, t) for t in extra_tickers]
    except Exception as exc:
        errors.append(f"single_names build failed: {exc}")
        logger.error("build_price_context single_names: %s", exc, exc_info=True)

    relationships: List[Dict[str, Any]] = []
    try:
        relationships = _build_relationships(_returns)
    except Exception as exc:
        errors.append(f"relationships build failed: {exc}")
        logger.error("build_price_context relationships: %s", exc, exc_info=True)

    # --- Secondary horizons ---
    secondary_horizons: Dict[str, Any] = {}
    if include_secondary_horizons:
        for sec_h in _SECONDARY_HORIZONS:
            sec_days = _HORIZON_DAYS.get(sec_h, 1)
            try:
                secondary_horizons[sec_h] = {
                    "cross_asset": [
                        {
                            "ticker": t,
                            "name": CROSS[t],
                            "return": calc_return(closes[t], sec_days) if t in closes else None,
                        }
                        for t in CROSS
                    ],
                    "sectors": [
                        {
                            "ticker": t,
                            "name": SECTORS[t],
                            "return": calc_return(closes[t], sec_days) if t in closes else None,
                        }
                        for t in SECTORS
                    ],
                }
            except Exception as exc:
                errors.append(f"secondary horizon {sec_h} failed: {exc}")
                logger.warning("build_price_context: secondary horizon %s failed: %s", sec_h, exc)

    result = {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "cross_asset": cross_asset,
        "sectors": sectors,
        "single_names": single_names,
        "relationships": relationships,
        "secondary_horizons": secondary_horizons,
    }
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# Multi-timeframe price context
# ---------------------------------------------------------------------------

_MULTI_HORIZONS: List[str] = ["1D", "5D", "1M", "3M", "YTD", "1Y"]

_MTF_RELATIONSHIP_SPECS = [
    ("QQQ minus SPY",  "QQQ", "SPY",
     "growth/mega-cap tech leadership",
     "growth/mega-cap tech lagging broad market"),
    ("IWM minus SPY",  "IWM", "SPY",
     "small-cap breadth and risk appetite leading",
     "small-cap underperformance / narrow mega-cap leadership"),
    ("HYG minus TLT",  "HYG", "TLT",
     "credit/risk-on outperforming duration",
     "credit/risk appetite weaker than duration / flight to safety"),
    ("XLE minus SPY",  "XLE", "SPY",
     "energy/oil sector leadership",
     "energy lagging broad market"),
    ("XLK minus SPY",  "XLK", "SPY",
     "technology sector leadership",
     "technology underperformance vs broad market"),
    ("XLY minus XLP",  "XLY", "XLP",
     "cyclical consumer outperforming staples / risk appetite",
     "defensive consumer outperforming discretionary / risk-off rotation"),
]


def _profile_relationship_specs(subject_profile: Optional[Dict[str, Any]]) -> List[tuple]:
    if not subject_profile:
        return []
    primary = str(subject_profile.get("ticker") or "").upper().strip()
    subject_type = str(subject_profile.get("subject_type") or "").lower()
    if not primary or subject_type != "ticker":
        return []

    specs: List[tuple] = []
    candidates = [
        (
            subject_profile.get("broad_market") or "SPY",
            "broad market",
            f"{primary} outperforming broad market",
            f"{primary} lagging broad market",
        ),
        (
            subject_profile.get("benchmark") or "QQQ",
            "growth benchmark",
            f"{primary} outperforming benchmark",
            f"{primary} lagging benchmark",
        ),
        (
            subject_profile.get("sector_etf"),
            "sector ETF",
            f"{primary} outperforming sector ETF",
            f"{primary} lagging sector ETF",
        ),
    ]
    seen: set[str] = set()
    for raw_bench, label, pos, neg in candidates:
        bench = str(raw_bench or "").upper().strip()
        if not bench or bench == primary or bench in seen:
            continue
        seen.add(bench)
        specs.append((f"{primary} minus {bench}", primary, bench, pos, neg))
    return specs


def _mtf_empty_result(horizons: List[str], errors: List[str]) -> Dict[str, Any]:
    return {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "format": "multi_timeframe",
        "horizons": horizons,
        "cross_asset": [],
        "sectors": [],
        "single_names": [],
        "relationships": [],
        "errors": errors,
    }


def classify_timeframe_context(returns: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """
    Produce coarse trend/timeframe labels from a multi-horizon returns dict.

    Inputs:  {"1D": 0.26, "5D": 1.82, "1M": 14.92, "3M": None, ...}
    Outputs: {short_term, intermediate, long_term, today_vs_trend, label}

    Rules encode common investment-context readings:
      1D- / 1M+ / YTD+   → short-term pullback within uptrend
      1D- / 1M- / YTD-   → downtrend continuation
      1D+ / 1M- / YTD-   → bounce within downtrend
      1D+ / 1M+ / YTD+   → trend continuation
      big 1M gain + 1D-   → possible exhaustion / high expectations
      big 1M loss + 1D+   → possible relief rally / capitulation bounce
    """
    r1d = returns.get("1D")
    r5d = returns.get("5D")  # noqa: F841 — reserved for future sub-rules
    r1m = returns.get("1M")
    r_long = returns.get("1Y") if returns.get("1Y") is not None else returns.get("YTD")

    def _sign(x: Optional[float], threshold: float = 0.1) -> int:
        if x is None:
            return 0
        return 1 if x > threshold else (-1 if x < -threshold else 0)

    s1d   = _sign(r1d)
    s1m   = _sign(r1m)
    s_lng = _sign(r_long)

    short_term   = "positive" if s1d > 0   else ("negative" if s1d < 0   else "flat")
    intermediate = "positive" if s1m > 0   else ("negative" if s1m < 0   else "flat/unknown")
    long_term    = "positive" if s_lng > 0 else ("negative" if s_lng < 0 else "flat/unknown")

    # Exhaustion / capitulation thresholds
    big_1m_gain = r1m is not None and r1m > 10.0
    big_1m_loss = r1m is not None and r1m < -10.0

    if s1d > 0 and s1m > 0 and s_lng >= 0:
        if big_1m_gain and r1d is not None and r1d < 0.5:
            label = "trend_continuation_possible_exhaustion"
            today_vs_trend = (
                f"trend continuation but {r1m:.1f}% 1M run — "
                "watch for high-expectation exhaustion"
            )
        else:
            label = "trend_continuation"
            today_vs_trend = "trend continuation — all timeframes aligned positive"

    elif s1d < 0 and s1m < 0 and s_lng <= 0:
        label = "downtrend_continuation"
        today_vs_trend = "downtrend continuation — all timeframes aligned negative"

    elif s1d < 0 and s1m > 0:
        if big_1m_gain:
            label = "pullback_possible_exhaustion"
            today_vs_trend = (
                f"short-term pullback after {r1m:.1f}% 1M run — "
                "possible high-expectation exhaustion"
            )
        else:
            label = "pullback_within_uptrend"
            today_vs_trend = "short-term pullback within uptrend — intermediate trend still positive"

    elif s1d > 0 and s1m < 0:
        if big_1m_loss and s_lng < 0:
            label = "relief_rally_capitulation_bounce"
            today_vs_trend = "relief rally / capitulation bounce — today positive but still in downtrend"
        else:
            label = "bounce_within_downtrend"
            today_vs_trend = "bounce within downtrend — intermediate trend still negative"

    elif s1d > 0 and s1m >= 0 and s_lng < 0:
        label = "bounce_below_long_downtrend"
        today_vs_trend = "positive today but long-term trend remains negative"

    elif s1d < 0 and s_lng > 0:
        label = "short_term_pullback_long_uptrend"
        today_vs_trend = "short-term weakness within longer uptrend"

    else:
        label = "mixed"
        today_vs_trend = "mixed signals across timeframes"

    return {
        "short_term":    short_term,
        "intermediate":  intermediate,
        "long_term":     long_term,
        "today_vs_trend": today_vs_trend,
        "label":         label,
    }


def _relative_returns_across_horizons(
    returns_a: Dict[str, Optional[float]],
    returns_b: Dict[str, Optional[float]],
    horizons: List[str],
) -> Dict[str, Optional[float]]:
    """Return (a − b) per horizon.  None when either leg is unavailable."""
    out: Dict[str, Optional[float]] = {}
    for h in horizons:
        ra, rb = returns_a.get(h), returns_b.get(h)
        out[h] = round(ra - rb, 3) if ra is not None and rb is not None else None
    return out


async def build_multi_timeframe_price_context(
    watch_tickers: Optional[List[str]] = None,
    horizons: Optional[List[str]] = None,
    subject_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Multi-timeframe price context for narrative synthesis.

    A single 2-year yfinance download covers all horizons (1D through 1Y),
    so there is no extra network cost vs. the single-horizon variant.

    CONTRACT: Never raises.  Errors collected in result["errors"]; data may
    be partial — callers check result["errors"] before assuming completeness.

    Returns
    -------
    {
        "format":   "multi_timeframe",
        "horizons": ["1D", "5D", "1M", "3M", "YTD", "1Y"],
        "cross_asset": [
            {
                "ticker": "QQQ", "name": "Nasdaq 100", "last": 450.12,
                "returns": {"1D": 0.26, "5D": 1.82, "1M": 14.92, ...},
                "trend_context": {
                    "short_term": "positive",
                    "intermediate": "positive",
                    "long_term": "positive",
                    "today_vs_trend": "trend continuation — all timeframes aligned positive",
                    "label": "trend_continuation",
                },
                "relative_returns": {
                    "vs_spy": {"1D": 0.12, "5D": 0.50, ...},
                },
            },
            ...
        ],
        "sectors":     [...],  # same shape as cross_asset
        "single_names":[...],  # same shape; only tickers not in SECTORS/CROSS
        "relationships": [
            {
                "name":          "QQQ minus SPY",
                "returns":       {"1D": 0.12, "5D": 0.50, ...},
                "interpretation":"growth/mega-cap tech leadership",
                "positive_read": "...",
                "negative_read": "...",
            },
            ...
        ],
        "errors": [],
    }
    """
    h_list = horizons or _MULTI_HORIZONS
    errors: List[str] = []

    requested = list(watch_tickers or [])
    if subject_profile:
        requested.extend([
            subject_profile.get("ticker"),
            subject_profile.get("broad_market"),
            subject_profile.get("benchmark"),
            subject_profile.get("sector_etf"),
            *(subject_profile.get("peers") or []),
        ])

    extra_tickers: List[str] = []
    seen_extra: set[str] = set()
    for raw in requested:
        t = str(raw or "").upper().strip()
        if not t or t in SECTORS or t in CROSS or t in seen_extra:
            continue
        seen_extra.add(t)
        extra_tickers.append(t)
    all_tickers = list(SECTORS.keys()) + list(CROSS.keys()) + extra_tickers

    closes = pd.DataFrame()
    try:
        closes = await asyncio.to_thread(_download_closes_sync, all_tickers)
        if closes.empty:
            errors.append(
                f"yfinance returned empty closes for {len(all_tickers)} tickers"
            )
            logger.error(
                "build_multi_timeframe_price_context: empty closes — tickers=%s",
                all_tickers[:8],
            )
        else:
            logger.info(
                "build_multi_timeframe_price_context: download OK — "
                "%d tickers, %d rows, horizons=%s",
                len(closes.columns), len(closes), h_list,
            )
    except Exception as exc:
        msg = f"download exception: {type(exc).__name__}: {exc}"
        errors.append(msg)
        logger.error(
            "build_multi_timeframe_price_context: %s\n%s",
            msg, traceback.format_exc(),
        )

    if closes.empty:
        return _mtf_empty_result(h_list, errors)

    # Pre-compute horizon-day lookups once
    h_days: Dict[str, Any] = {h: _HORIZON_DAYS.get(h, 1) for h in h_list}

    def _rets(ticker: str) -> Dict[str, Optional[float]]:
        if ticker not in closes:
            return {h: None for h in h_list}
        ser = closes[ticker]
        return {h: calc_return(ser, h_days[h]) for h in h_list}

    # Cache SPY and QQQ returns for relative-return computation
    spy_rets: Optional[Dict[str, Optional[float]]] = _rets("SPY") if "SPY" in closes else None
    qqq_rets: Optional[Dict[str, Optional[float]]] = _rets("QQQ") if "QQQ" in closes else None
    benchmark = str((subject_profile or {}).get("benchmark") or "").upper().strip()
    sector_etf = str((subject_profile or {}).get("sector_etf") or "").upper().strip()
    benchmark_rets = _rets(benchmark) if benchmark and benchmark in closes else None
    sector_rets = _rets(sector_etf) if sector_etf and sector_etf in closes else None

    def _asset_row(
        ticker: str,
        name: str,
        extra_vs: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    ) -> Dict[str, Any]:
        try:
            rets = _rets(ticker)
            last = _last_price(closes[ticker]) if ticker in closes else None
            trend = classify_timeframe_context(rets)
            rel: Dict[str, Any] = {}
            if spy_rets:
                rel["vs_spy"] = _relative_returns_across_horizons(rets, spy_rets, h_list)
            if extra_vs:
                for label, bench_rets in extra_vs.items():
                    rel[label] = _relative_returns_across_horizons(rets, bench_rets, h_list)
            return {
                "ticker": ticker,
                "name": name,
                "last": round(last, 4) if last is not None else None,
                "returns": rets,
                "trend_context": trend,
                "relative_returns": rel,
            }
        except Exception as exc:
            logger.debug("_asset_row failed for %s: %s", ticker, exc)
            return {
                "ticker": ticker, "name": name, "last": None,
                "returns": {h: None for h in h_list},
                "trend_context": {}, "relative_returns": {},
            }

    cross_asset: List[Dict[str, Any]] = []
    try:
        cross_asset = [_asset_row(t, name) for t, name in CROSS.items()]
    except Exception as exc:
        errors.append(f"cross_asset build failed: {exc}")
        logger.error("build_multi_timeframe_price_context cross_asset: %s", exc, exc_info=True)

    sectors: List[Dict[str, Any]] = []
    try:
        for t, name in SECTORS.items():
            # Tech and discretionary sectors also get vs_qqq for thematic context
            extra = {"vs_qqq": qqq_rets} if (qqq_rets and t in ("XLK", "XLY", "XLC")) else {}
            if benchmark_rets and benchmark and benchmark not in ("QQQ", t):
                extra[f"vs_{benchmark.lower()}"] = benchmark_rets
            if not extra:
                extra = None
            sectors.append(_asset_row(t, name, extra))
    except Exception as exc:
        errors.append(f"sectors build failed: {exc}")
        logger.error("build_multi_timeframe_price_context sectors: %s", exc, exc_info=True)

    single_names: List[Dict[str, Any]] = []
    try:
        for t in extra_tickers:
            extra: Dict[str, Dict[str, Optional[float]]] = {}
            if qqq_rets:
                extra["vs_qqq"] = qqq_rets
            if benchmark_rets and benchmark and benchmark != "QQQ":
                extra[f"vs_{benchmark.lower()}"] = benchmark_rets
            if sector_rets and sector_etf and sector_etf != t:
                extra["vs_sector"] = sector_rets
            single_names.append(_asset_row(t, t, extra or None))
    except Exception as exc:
        errors.append(f"single_names build failed: {exc}")
        logger.error("build_multi_timeframe_price_context single_names: %s", exc, exc_info=True)

    relationships: List[Dict[str, Any]] = []
    try:
        rel_specs = list(_MTF_RELATIONSHIP_SPECS) + _profile_relationship_specs(subject_profile)
        seen_rels: set[str] = set()
        for rel_name, a, b, pos_read, neg_read in rel_specs:
            if rel_name in seen_rels:
                continue
            seen_rels.add(rel_name)
            a_rets = _rets(a)
            b_rets = _rets(b)
            rel_rets = _relative_returns_across_horizons(a_rets, b_rets, h_list)
            r1d = rel_rets.get("1D")
            interp = pos_read if (r1d is not None and r1d >= 0) else neg_read
            relationships.append({
                "name":          rel_name,
                "returns":       rel_rets,
                "interpretation": interp,
                "positive_read": pos_read,
                "negative_read": neg_read,
            })
    except Exception as exc:
        errors.append(f"relationships build failed: {exc}")
        logger.error("build_multi_timeframe_price_context relationships: %s", exc, exc_info=True)

    result: Dict[str, Any] = {
        "asof_utc":    datetime.now(timezone.utc).isoformat(),
        "format":      "multi_timeframe",
        "horizons":    h_list,
        "cross_asset": cross_asset,
        "sectors":     sectors,
        "single_names": single_names,
        "relationships": relationships,
    }
    if subject_profile:
        result["subject"] = {
            k: subject_profile.get(k)
            for k in ("ticker", "name", "subject_type", "sector_etf", "benchmark", "broad_market", "peers")
            if subject_profile.get(k) is not None
        }
    if errors:
        result["errors"] = errors
    return result


def build_multi_timeframe_price_context_sync(
    watch_tickers: Optional[List[str]] = None,
    horizons: Optional[List[str]] = None,
    subject_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synchronous wrapper around build_multi_timeframe_price_context.
    Use in non-async contexts (e.g. run_synth.py CLI).

    Has the same never-raise contract as the async variant.
    """
    try:
        return asyncio.run(
            build_multi_timeframe_price_context(
                watch_tickers=watch_tickers,
                horizons=horizons,
                subject_profile=subject_profile,
            )
        )
    except Exception as exc:
        tb = traceback.format_exc()
        msg = f"build_multi_timeframe_price_context_sync failed: {type(exc).__name__}: {exc}"
        logger.error("%s\n%s", msg, tb)
        return _mtf_empty_result(horizons or _MULTI_HORIZONS, [msg])


def build_price_context_sync(
    horizon: str = "1D",
    watch_tickers: Optional[List[str]] = None,
    include_secondary_horizons: bool = True,
) -> Dict[str, Any]:
    """
    Synchronous wrapper around build_price_context for callers that are not
    in an async context (e.g. run_synth.py CLI script).

    Uses asyncio.run() which creates a new event loop.  Do NOT call this
    from inside an already-running async context — use await build_price_context()
    directly instead.

    Has the same never-raise contract as build_price_context.
    """
    try:
        return asyncio.run(
            build_price_context(
                horizon=horizon,
                watch_tickers=watch_tickers,
                include_secondary_horizons=include_secondary_horizons,
            )
        )
    except Exception as exc:
        tb = traceback.format_exc()
        msg = f"build_price_context_sync failed: {type(exc).__name__}: {exc}"
        logger.error("%s\n%s", msg, tb)
        return _empty_result(horizon, [msg])
