from __future__ import annotations

from typing import List, Dict, Any
import pandas as pd

from src.data.market import fetch_market_moves
from src.data.macro import fetch_regime_signals

DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "USO", "BTC-USD"]

def build_daily_brief(tickers: List[str]) -> Dict[str, Any]:
    """
    Returns a dict with:
      - "macro": dict of MacroSignal
      - "sections": dict[str, DataFrame]
    """
    macro = fetch_regime_signals()
    moves = fetch_market_moves(tickers)
    return {
        "macro": macro,
        "sections": {"Market Moves (1D)": moves},
    }
