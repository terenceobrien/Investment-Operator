"""
Polygon / Massive intraday bar fetcher for the trend-pullback backtest.

- Pulls aggregate bars (default 1-minute) for one or more tickers.
- Caches each (ticker, multiplier, timespan, from, to) pull to Parquet so you
  download once and re-run backtests offline.
- Returns a DataFrame in the EXACT shape the backtest expects: capitalized
  OHLCV columns, tz-aware America/New_York DatetimeIndex, sorted, RTH-filtered.

Auth: set your key in the env var  MASSIVE_API_KEY  (or POLYGON_API_KEY),
or pass api_key= explicitly. NEVER hard-code the key in a committed file.

Client import: post-rebrand the SDK is `massive` (`from massive import RESTClient`).
The legacy `from polygon import RESTClient` still works IF you installed
`polygon-api-client`. This module tries both so it works either way.

    pip install massive pandas pyarrow
    export MASSIVE_API_KEY=sk_...
    python massive_data.py            # fetches SPY/QQQ/IWM, prints summary

Note on Starter tier: unlimited calls, 1-min aggregates available, data is
15-min delayed — irrelevant for historical backtesting (only the most recent
15 min of *today* is withheld). Tick trades/quotes are NOT on Starter; this
module only uses aggregate bars, which are.
"""

from __future__ import annotations
import os
import time
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

# --- client import shim (massive preferred, polygon legacy fallback) ---------
try:
    from massive import RESTClient  # post-rebrand SDK
except ImportError:  # pragma: no cover
    try:
        from polygon import RESTClient  # legacy package
    except ImportError as e:
        raise ImportError(
            "No Massive/Polygon client found. Install with: pip install massive"
        ) from e

MARKET_TZ = "America/New_York"
RTH_START = "09:30"
RTH_END = "16:00"
CACHE_DIR = Path(os.environ.get("POLY_CACHE_DIR", "./data_cache"))
DEFAULT_TICKERS = ["SPY", "QQQ", "IWM"]


def _api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key. Set MASSIVE_API_KEY (or POLYGON_API_KEY) env var, "
            "or pass api_key= to fetch_bars()."
        )
    return key


def _cache_path(ticker: str, multiplier: int, timespan: str,
                start: str, end: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{ticker}_{multiplier}{timespan}_{start}_{end}.parquet"
    return CACHE_DIR / fname


def _aggs_to_df(aggs: list) -> pd.DataFrame:
    """Convert a list of Agg objects into a clean, RTH-filtered, tz-aware frame."""
    if not aggs:
        raise ValueError("No aggregates returned — check ticker/date range/entitlements.")

    # Agg objects expose .open/.high/.low/.close/.volume/.timestamp (epoch ms, UTC)
    rows = [{
        "ts": a.timestamp,
        "Open": a.open, "High": a.high, "Low": a.low,
        "Close": a.close, "Volume": a.volume,
        "VWAP": getattr(a, "vwap", None),
        "Transactions": getattr(a, "transactions", None),
    } for a in aggs]

    df = pd.DataFrame(rows)
    # epoch-ms UTC -> tz-aware NY
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_convert(MARKET_TZ)
    df = df.set_index("ts").sort_index()

    # de-dupe any repeated timestamps (rare but happens on merged feeds)
    df = df[~df.index.duplicated(keep="last")]

    # regular session only
    df = df.between_time(RTH_START, RTH_END)

    core = ["Open", "High", "Low", "Close", "Volume"]
    df = df.dropna(subset=core)
    if df.empty:
        raise ValueError("Frame empty after RTH filter — check the date range.")
    return df


def fetch_bars(ticker: str,
               start: str,
               end: str,
               multiplier: int = 1,
               timespan: str = "minute",
               api_key: str | None = None,
               use_cache: bool = True,
               adjusted: bool = True) -> pd.DataFrame:
    """
    Fetch aggregate bars for one ticker.

    start / end : 'YYYY-MM-DD' (inclusive).
    timespan    : 'minute' | 'hour' | 'day' (etc.); multiplier scales it
                  (multiplier=5, timespan='minute' -> 5-min bars).
    Returns a backtest-ready DataFrame (see module docstring).
    """
    cache = _cache_path(ticker, multiplier, timespan, start, end)
    if use_cache and cache.exists():
        return pd.read_parquet(cache)

    client = RESTClient(_api_key(api_key))

    aggs = []
    # list_aggs paginates internally (handles next_url); limit is PAGE size.
    for a in client.list_aggs(
        ticker=ticker,
        multiplier=multiplier,
        timespan=timespan,
        from_=start,
        to=end,
        adjusted=adjusted,
        limit=50000,
    ):
        aggs.append(a)

    df = _aggs_to_df(aggs)

    if use_cache:
        df.to_parquet(cache)
    return df


def fetch_universe(tickers: list[str] | None = None,
                   start: str | None = None,
                   end: str | None = None,
                   lookback_days: int = 30,
                   multiplier: int = 1,
                   timespan: str = "minute",
                   api_key: str | None = None,
                   use_cache: bool = True,
                   pause_s: float = 0.0) -> dict[str, pd.DataFrame]:
    """
    Fetch bars for several tickers. Returns {ticker: DataFrame}.
    If start/end omitted, uses the last `lookback_days` ending today.
    pause_s: optional sleep between tickers (Starter has unlimited calls, so 0
             is fine; bump it if you ever hit throttling on a lower tier).
    """
    tickers = tickers or DEFAULT_TICKERS
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    if start is None:
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_bars(t, start, end, multiplier, timespan,
                        api_key=api_key, use_cache=use_cache)
        out[t] = df
        if pause_s:
            time.sleep(pause_s)
    return out


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Fetch Polygon/Massive intraday bars.")
    p.add_argument("--tickers", nargs="+", default=DEFAULT_TICKERS)
    p.add_argument("--start", help="YYYY-MM-DD (default: lookback-days ago)")
    p.add_argument("--end", help="YYYY-MM-DD (default: today)")
    p.add_argument("--lookback-days", type=int, default=30)
    p.add_argument("--multiplier", type=int, default=1)
    p.add_argument("--timespan", default="minute",
                   choices=["minute", "hour", "day"])
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    data = fetch_universe(
        tickers=args.tickers,
        start=args.start,
        end=args.end,
        lookback_days=args.lookback_days,
        multiplier=args.multiplier,
        timespan=args.timespan,
        use_cache=not args.no_cache,
    )

    print(f"\nFetched {len(data)} tickers "
          f"({args.multiplier}{args.timespan} bars, cached in {CACHE_DIR}):\n")
    for t, df in data.items():
        print(f"  {t:5s}  {len(df):>7,} bars   "
              f"{df.index[0]}  ->  {df.index[-1]}")
    print("\nEach frame is backtest-ready. To run the strategy on one:")
    print("  from trend_pullback_strategy import run")
    print("  bt, stats = run(data['SPY']); print(stats)")