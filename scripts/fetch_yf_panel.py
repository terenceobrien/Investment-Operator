#!/usr/bin/env python3
"""Download daily Yahoo OHLCV for a ticker list, with Parquet caching.

Dependencies: python3 -m pip install pandas yfinance pyarrow pandas_market_calendars
Example: python3 fetch_yf_panel.py --tickers AAPL MSFT SPY --start 2020-01-01
CLI end dates are inclusive. Omitted end dates use the last completed NYSE session.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import yfinance as yf


@dataclass(frozen=True)
class PricePanel:
    """Daily OHLCV: (ticker, field) columns and a DatetimeIndex."""
    df: pd.DataFrame

    def field(self, ticker: str, field: str) -> pd.Series:
        return self.df[(ticker, field)].dropna()

    def has(self, ticker: str, field: str) -> bool:
        return (ticker, field) in self.df.columns


def _cache_path(cache_dir, tickers, start, end, interval, auto_adjust=False):
    safe = "_".join(quote(t, safe="") for t in sorted(tickers))
    mode = "adjusted" if auto_adjust else "unadjusted"
    return Path(cache_dir) / f"yf_{interval}_{start}_{end}_{safe}_{mode}.parquet"


def fetch_yf_panel(tickers: list[str], start: str, end: str,
                   interval: str = "1d", auto_adjust: bool = False,
                   cache_dir: str | Path | None = None,
                   force: bool = False) -> PricePanel:
    """Download and cache OHLCV. Like yfinance, this function's end is exclusive."""
    cache_dir = Path(cache_dir or Path(__file__).resolve().parent / "price_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, tickers, start, end, interval, auto_adjust)
    if path.exists() and not force:
        df = pd.read_parquet(path)
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples(df.columns)
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        return PricePanel(df)
    df = yf.download(tickers=tickers, start=start, end=end, interval=interval,
                     auto_adjust=auto_adjust, group_by="ticker",
                     progress=False, threads=True)
    if df is None or df.empty:
        raise RuntimeError("yfinance returned no data. Check tickers/date range.")
    panel = df.copy() if isinstance(df.columns, pd.MultiIndex) else pd.concat({tickers[0]: df}, axis=1)
    panel.index = pd.to_datetime(panel.index)
    panel.sort_index(inplace=True)
    panel.to_parquet(path)
    return PricePanel(panel)


def csv_rows(panel: PricePanel) -> pd.DataFrame:
    """One row per date/ticker, omitting rows with no price data."""
    frames = []
    for ticker in panel.df.columns.get_level_values(0).unique():
        frame = panel.df[ticker].dropna(how="all").copy()
        frame.columns.name = None
        frame.insert(0, "Ticker", ticker)
        frames.append(frame.rename_axis("Date").reset_index())
    rows = pd.concat(frames, ignore_index=True)
    preferred = ["Date", "Ticker", "Open", "High", "Low", "Close", "Adj Close", "Volume"]
    columns = [col for col in preferred if col in rows.columns]
    columns += [col for col in rows.columns if col not in columns]
    return rows.loc[:, columns].sort_values(["Date", "Ticker"]).reset_index(drop=True)


def latest_close_day(now=None) -> date:
    import pandas_market_calendars as mcal
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.tz_convert("America/New_York").date()
    schedule = mcal.get_calendar("NYSE").schedule(
        start_date=today - timedelta(days=370), end_date=today)
    completed = schedule.loc[schedule["market_close"] <= now]
    if completed.empty:
        raise RuntimeError("No completed NYSE session found.")
    return completed.index[-1].date()


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD dates") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", required=True, help="Space- or comma-separated tickers")
    parser.add_argument("--start", type=parse_date, required=True, help="Inclusive start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=parse_date, help="Inclusive end date; default: latest completed NYSE session")
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).resolve().parent / "price_cache")
    parser.add_argument("--csv", type=Path, help="Export CSV with one row per date and ticker")
    parser.add_argument("--auto-adjust", action="store_true", help="Adjust OHLC prices (default: false)")
    parser.add_argument("--force", action="store_true", help="Download again even if cached")
    args = parser.parse_args(argv)
    tickers = list(dict.fromkeys(t.strip().upper() for group in args.tickers for t in group.split(",") if t.strip()))
    if not tickers:
        parser.error("Supply at least one ticker")
    try:
        end = args.end if args.end is not None else latest_close_day()
        if args.start > end:
            parser.error("--start must be on or before the end date")
        exclusive_end = (end + timedelta(days=1)).isoformat()
        panel = fetch_yf_panel(tickers, args.start.isoformat(), exclusive_end,
                               auto_adjust=args.auto_adjust, cache_dir=args.cache_dir, force=args.force)
        path = _cache_path(args.cache_dir, tickers, args.start.isoformat(), exclusive_end, "1d", args.auto_adjust)
        print(f"Requested: {args.start} through {end} (inclusive)")
        print(f"Parquet: {path.resolve()}")
        for ticker in tickers:
            if panel.has(ticker, "Close") and not panel.field(ticker, "Close").empty:
                close = panel.field(ticker, "Close")
                print(f"{ticker}: {len(close)} daily rows, {close.index.min().date()} through {close.index.max().date()}")
            else:
                print(f"WARNING: No close prices returned for {ticker}")
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            csv_rows(panel).to_csv(args.csv, index=False, date_format="%Y-%m-%d")
            print(f"CSV: {args.csv.resolve()}")
        return 0
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
