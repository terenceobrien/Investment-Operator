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

    if not tickers:
        return pd.DataFrame(columns=["ticker", "last", "chg_pct_1d"])

    data = yf.download(
        tickers,
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=False,
        threads=True,
        group_by="ticker",
    )

    rows = []
    is_multi = isinstance(getattr(data, "columns", None), pd.MultiIndex)

    for t in tickers:
        try:
            if is_multi:
                hist = data[t]
            else:
                hist = data

            if hist is None or hist.empty or "Close" not in hist:
                continue

            closes = hist["Close"].dropna()
            if len(closes) < 2:
                continue

            last = float(closes.iloc[-1])
            prev = float(closes.iloc[-2])
            chg_pct = (last / prev - 1.0) * 100.0
            rows.append({"ticker": t, "last": last, "chg_pct_1d": chg_pct})
        except Exception:
            continue

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("chg_pct_1d", ascending=False).reset_index(drop=True)
    return df
