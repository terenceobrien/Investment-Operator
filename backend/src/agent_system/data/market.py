"""Market-data bundle fetcher and technical-context computation."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import yfinance as yf

from src.agent_system.data.cache import cache_get, cache_set
from src.agent_system.data.types import MarketDataBundle, TechnicalContext

logger = logging.getLogger("agent_system.data.market")

MARKET_HISTORY_TTL = timedelta(hours=1)


def _safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _rows_from_frame(frame: pd.DataFrame) -> list[dict]:
    rows: list[dict] = []
    if frame.empty:
        return rows
    for idx, row in frame.iterrows():
        date_value = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
        rows.append(
            {
                "date": date_value,
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": _safe_float(row.get("Close")),
                "volume": _safe_float(row.get("Volume")),
            }
        )
    return rows


def _frame_from_rows(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date").sort_index()
    frame = frame.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    return frame


def _trend_regime(
    current_price: float | None,
    sma_50: float | None,
    sma_200: float | None,
) -> str | None:
    if current_price is None or sma_50 is None or sma_200 is None:
        return None
    if current_price > sma_50 > sma_200:
        return "uptrend"
    if current_price < sma_50 < sma_200:
        return "downtrend"
    return "range"


def _compute_technicals(frame: pd.DataFrame) -> tuple[float | None, TechnicalContext | None]:
    if frame.empty or "Close" not in frame:
        return None, None

    close = pd.to_numeric(frame["Close"], errors="coerce")
    high = pd.to_numeric(frame["High"], errors="coerce")
    low = pd.to_numeric(frame["Low"], errors="coerce")
    current_price = _safe_float(close.dropna().iloc[-1]) if not close.dropna().empty else None

    sma_50 = _safe_float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
    sma_200 = _safe_float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None
    high_20d = _safe_float(high.tail(20).max()) if len(high.dropna()) >= 1 else None
    low_20d = _safe_float(low.tail(20).min()) if len(low.dropna()) >= 1 else None
    high_52w = _safe_float(high.max()) if len(high.dropna()) >= 1 else None
    low_52w = _safe_float(low.min()) if len(low.dropna()) >= 1 else None

    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_14 = (
        _safe_float(true_range.rolling(14).mean().iloc[-1])
        if len(true_range.dropna()) >= 14
        else None
    )

    technicals = TechnicalContext(
        sma_50=sma_50,
        sma_200=sma_200,
        price_vs_sma_50=_safe_ratio(
            current_price - sma_50 if current_price is not None and sma_50 is not None else None,
            sma_50,
        ),
        price_vs_sma_200=_safe_ratio(
            current_price - sma_200 if current_price is not None and sma_200 is not None else None,
            sma_200,
        ),
        high_20d=high_20d,
        low_20d=low_20d,
        high_52w=high_52w,
        low_52w=low_52w,
        atr_14=atr_14,
        atr_pct=_safe_ratio(atr_14, current_price),
        trend_regime=_trend_regime(current_price, sma_50, sma_200),
    )
    return current_price, technicals


def _empty_bundle(ticker: str, errors: list[str]) -> MarketDataBundle:
    return MarketDataBundle(
        ticker=ticker.upper(),
        as_of=datetime.now(timezone.utc),
        current_price=None,
        history_start=None,
        history_end=None,
        bars_count=0,
        technicals=None,
        fetch_success=False,
        fetch_errors=errors,
    )


def _bundle_from_frame(ticker: str, frame: pd.DataFrame, errors: list[str]) -> MarketDataBundle:
    if frame.empty:
        return _empty_bundle(ticker, errors or ["No market history returned"])

    current_price, technicals = _compute_technicals(frame)
    index = pd.to_datetime(frame.index)
    return MarketDataBundle(
        ticker=ticker.upper(),
        as_of=datetime.now(timezone.utc),
        current_price=current_price,
        history_start=index.min().date() if len(index) else None,
        history_end=index.max().date() if len(index) else None,
        bars_count=len(frame),
        technicals=technicals,
        fetch_success=current_price is not None and technicals is not None,
        fetch_errors=errors,
    )


def get_market_data(ticker: str, force_refresh: bool = False) -> MarketDataBundle:
    """
    Fetch ~1y daily OHLCV via yfinance and compute technical context.

    This function never raises. Provider failures return a failed bundle with
    diagnostics so callers can degrade gracefully.
    """

    normalized = ticker.upper().strip()
    errors: list[str] = []

    if not force_refresh:
        cached = cache_get("market_history", normalized, MARKET_HISTORY_TTL)
        if cached is not None:
            try:
                return _bundle_from_frame(
                    normalized,
                    _frame_from_rows(cached),
                    errors=[],
                )
            except Exception as exc:
                errors.append(f"cache parse failed: {exc}")

    try:
        history = yf.Ticker(normalized).history(period="1y", interval="1d")
    except Exception as exc:
        logger.warning("market history fetch failed for %s: %s", normalized, exc)
        return _empty_bundle(normalized, [f"{type(exc).__name__}: {exc}"])

    if history is None or history.empty:
        return _empty_bundle(normalized, ["No market history returned"])

    rows = _rows_from_frame(history)
    cache_set("market_history", normalized, rows)
    return _bundle_from_frame(normalized, _frame_from_rows(rows), errors)
