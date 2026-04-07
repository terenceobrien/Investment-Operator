from __future__ import annotations

from dataclasses import dataclass
from typing import List
import pandas as pd

@dataclass(frozen=True)
class MarketMove:
    ticker: str
    last: float
    chg_pct_1d: float

def fetch_market_moves(tickers: List[str]) -> pd.DataFrame:
    """
    Returns a DataFrame with columns:
    ticker, last, chg_pct_1d
    """
    import yfinance as yf
    rows = []
    for t in tickers:
        tk = yf.Ticker(t)
        hist = tk.history(period="5d", interval="1d")
        if hist is None or hist.empty or len(hist) < 2:
            continue
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        chg_pct = (last / prev - 1.0) * 100.0
        rows.append({"ticker": t, "last": last, "chg_pct_1d": chg_pct})

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("chg_pct_1d", ascending=False).reset_index(drop=True)
    return df
