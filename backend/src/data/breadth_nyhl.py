"""
S&P 500 new-highs/new-lows breadth builder.

This module computes an S&P 500 new highs minus new lows series from current
S&P 500 membership and historical adjusted close prices. It intentionally uses
static current membership for v1, so historical backtests carry survivorship
bias. This is a practical substitute for the broken FRED HIGHNEW/LOWNEW series;
point-in-time membership can be added later if results warrant it.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List

import numpy as np
import pandas as pd


SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _as_path(path: str | Path) -> Path:
    return Path(path)


def _yf_symbol(symbol: str) -> str:
    # Wikipedia uses dots for share classes; yfinance uses hyphens.
    return symbol.strip().upper().replace(".", "-")


def get_sp500_membership(
    cache_path: str | Path = "backend/data/cache/sp500_membership.txt",
) -> List[str]:
    """
    Return current S&P 500 membership as yfinance-compatible tickers.

    The first successful scrape is cached as one ticker per line. Subsequent
    calls load the cache instantly unless the file is removed.
    """
    path = _as_path(cache_path)
    if path.exists():
        tickers = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        return [t for t in tickers if t]

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        tables = pd.read_html(SP500_WIKI_URL)
        if not tables:
            raise RuntimeError("Wikipedia returned no tables")
        table = tables[0]
        symbol_col = "Symbol" if "Symbol" in table.columns else table.columns[0]
        tickers = sorted({_yf_symbol(str(x)) for x in table[symbol_col].dropna() if str(x).strip()})
        if not tickers:
            raise RuntimeError("No tickers parsed from S&P 500 Wikipedia table")
        path.write_text("\n".join(tickers) + "\n", encoding="utf-8")
        return tickers
    except Exception as exc:
        print(f"  S&P 500 membership scrape failed: {exc}")
        return []


def _batch(items: Iterable[str], batch_size: int) -> Iterable[List[str]]:
    buf: List[str] = []
    for item in items:
        buf.append(item)
        if len(buf) >= batch_size:
            yield buf
            buf = []
    if buf:
        yield buf


def bulk_fetch_sp500_history(
    tickers: List[str],
    start: str,
    end: str,
    cache_path: str | Path = "backend/data/cache/sp500_prices.parquet",
    force_download: bool = False,
    batch_size: int = 75,
    retries: int = 3,
) -> pd.DataFrame:
    """
    Batched yfinance adjusted-close downloader for S&P 500 members.

    Returns a wide daily DataFrame indexed by date with one column per ticker.
    Cached parquet loads immediately unless force_download=True.
    """
    path = _as_path(cache_path)
    if path.exists() and not force_download:
        try:
            df = pd.read_parquet(path)
            df.index = pd.to_datetime(df.index)
            df.sort_index(inplace=True)
            start_ts = pd.to_datetime(start)
            end_ts = pd.to_datetime(end)
            if df.index.min() <= start_ts and df.index.max() >= end_ts - pd.Timedelta(days=5):
                return df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
            print("  S&P 500 price cache does not cover requested range, re-downloading")
        except Exception as exc:
            print(f"  S&P 500 price cache read failed, re-downloading: {exc}")

    clean_tickers = sorted({_yf_symbol(t) for t in tickers if str(t).strip()})
    if not clean_tickers:
        return pd.DataFrame()

    path.parent.mkdir(parents=True, exist_ok=True)
    frames: List[pd.DataFrame] = []

    try:
        import yfinance as yf
    except Exception as exc:
        print(f"  yfinance unavailable for S&P 500 NYHL: {exc}")
        return pd.DataFrame()

    for batch in _batch(clean_tickers, batch_size):
        batch_df = pd.DataFrame()
        for attempt in range(1, retries + 1):
            try:
                raw = yf.download(
                    tickers=batch,
                    start=start,
                    end=end,
                    interval="1d",
                    auto_adjust=True,
                    group_by="ticker",
                    progress=False,
                    threads=True,
                )
                if raw is None or raw.empty:
                    raise RuntimeError("empty yfinance response")

                if isinstance(raw.columns, pd.MultiIndex):
                    cols = {}
                    for ticker in batch:
                        if (ticker, "Close") in raw.columns:
                            cols[ticker] = raw[(ticker, "Close")]
                    batch_df = pd.DataFrame(cols)
                else:
                    ticker = batch[0]
                    batch_df = pd.DataFrame({ticker: raw["Close"]}) if "Close" in raw else pd.DataFrame()

                if not batch_df.empty:
                    break
            except Exception as exc:
                if attempt == retries:
                    print(f"  S&P 500 price batch failed ({batch[:3]}...): {exc}")
                else:
                    time.sleep(1.0 * attempt)

        if not batch_df.empty:
            frames.append(batch_df)

    if not frames:
        return pd.DataFrame()

    prices = pd.concat(frames, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices.sort_index(inplace=True)
    prices.to_parquet(path)
    return prices


def compute_sp500_nyhl(prices_df: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """
    Compute daily S&P 500 new highs, new lows, and net highs-lows.

    NaN prices do not contribute to either count, which keeps inactive or
    missing tickers from polluting the breadth count.
    """
    if prices_df is None or prices_df.empty:
        return pd.DataFrame(columns=["new_highs", "new_lows", "net_highs_lows"])

    prices = prices_df.sort_index().astype(float)
    rolling_high = prices.rolling(window, min_periods=window).max()
    rolling_low = prices.rolling(window, min_periods=window).min()
    valid = prices.notna()

    new_highs = (valid & prices.ge(rolling_high)).sum(axis=1)
    new_lows = (valid & prices.le(rolling_low)).sum(axis=1)
    out = pd.DataFrame({
        "new_highs": new_highs.astype(float),
        "new_lows": new_lows.astype(float),
    }, index=prices.index)
    out["net_highs_lows"] = out["new_highs"] - out["new_lows"]
    return out


def compute_nyhl_zscore(net_series: pd.Series, window: int = 252) -> pd.Series:
    """Rolling z-score of net highs-lows."""
    if net_series is None or net_series.empty:
        return pd.Series(dtype=float)
    s = pd.to_numeric(net_series, errors="coerce")
    ma = s.rolling(window, min_periods=max(20, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(20, window // 2)).std(ddof=0)
    return (s - ma) / sd.replace(0, np.nan)


if __name__ == "__main__":
    end_dt = datetime.utcnow().date()
    start_dt = end_dt - timedelta(days=365)
    members = get_sp500_membership()
    print(f"members={len(members)}")
    sample = members[:75]
    prices = bulk_fetch_sp500_history(sample, str(start_dt), str(end_dt), force_download=False)
    nyhl = compute_sp500_nyhl(prices)
    z = compute_nyhl_zscore(nyhl["net_highs_lows"] if not nyhl.empty else pd.Series(dtype=float))
    print(nyhl.tail())
    print("z_tail:")
    print(z.dropna().tail())
