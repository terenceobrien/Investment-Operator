# src/backtest/data.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf


DEFAULT_SECTOR_TICKERS = [
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"
]

# Cross-asset “macro tape” set (edit as you like)
DEFAULT_CROSS_ASSET = [
    "SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "USO", "BTC-USD", "RSP", "^VIX"
]


@dataclass(frozen=True)
class PricePanel:
    """Daily OHLCV panel: columns are MultiIndex (ticker, field). index is DatetimeIndex."""
    df: pd.DataFrame

    def field(self, ticker: str, field: str) -> pd.Series:
        return self.df[(ticker, field)].dropna()

    def has(self, ticker: str, field: str) -> bool:
        return (ticker, field) in self.df.columns


def _cache_path(cache_dir: Path, tickers: List[str], start: str, end: str, interval: str) -> Path:
    safe = "_".join(sorted(tickers)).replace("^", "IDX")
    return cache_dir / f"yf_{interval}_{start}_{end}_{safe}.parquet"


def fetch_yf_panel(
    tickers: List[str],
    start: str,
    end: str,
    interval: str = "1d",
    auto_adjust: bool = False,
    cache_dir: str | Path = "data/cache/backtest",
    force: bool = False,
) -> PricePanel:
    """
    Downloads an OHLCV panel from yfinance and caches to parquet.
    interval: '1d' (recommended first). Intraday intervals are possible but yfinance history is limited.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, tickers, start, end, interval)

    if path.exists() and not force:
        df = pd.read_parquet(path)
        # parquet may lose column MultiIndex typing; rehydrate if needed
        if not isinstance(df.columns, pd.MultiIndex):
            df.columns = pd.MultiIndex.from_tuples(df.columns)
        df.index = pd.to_datetime(df.index)
        df.sort_index(inplace=True)
        return PricePanel(df=df)

    df = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=auto_adjust,
        group_by="ticker",
        progress=False,
        threads=True,
    )

    if df is None or df.empty:
        raise RuntimeError("yfinance returned no data. Check tickers/date range.")

    # Ensure columns are MultiIndex: (ticker, field)
    if isinstance(df.columns, pd.MultiIndex):
        panel = df.copy()
    else:
        # Single ticker case returns flat columns
        t = tickers[0]
        panel = pd.concat({t: df}, axis=1)

    panel.index = pd.to_datetime(panel.index)
    panel.sort_index(inplace=True)

    panel.to_parquet(path)
    return PricePanel(df=panel)
