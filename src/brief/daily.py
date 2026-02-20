from __future__ import annotations

from typing import List, Dict, Any
import pandas as pd

from src.data.market import fetch_market_moves
from src.data.macro import fetch_regime_signals
from src.data.releases import fetch_today_releases, fetch_latest_updates

DEFAULT_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "USO", "BTC-USD"]

INDICATOR_MAP: Dict[str, str] = {
    "Initial Jobless Claims": "ICSA",
    "Nonfarm Payrolls": "PAYEMS",
    "Unemployment Rate": "UNRATE",
    "GDP": "GDPC1",
    "Consumer Confidence": "UMCSENT",
    "CPI": "CPIAUCSL",
    "Core CPI": "CPILFESL",
    "PCE": "PCEPI",
    "Core PCE": "PCEPILFE",
    "PPI": "PPIACO",
    "Avg Hourly Earnings": "CES0500000003",
}

# --- Your liquidity trackers (not "prints" in the same sense) ---
LIQUIDITY_SERIES: Dict[str, str] = {
    "Fed Balance Sheet": "WALCL",
    "Reverse Repo": "RRPONTSYD",
    "Treasury General Account": "WTREGEN",
    "Bank Reserves": "WRESBAL",
}

def build_daily_brief(tickers: List[str]) -> Dict[str, Any]:
    """
    Returns a dict with:
      - "macro": dict of MacroSignal
      - "sections": dict[str, DataFrame]
    """
    macro = fetch_regime_signals()
    today_releases = fetch_today_releases(INDICATOR_MAP)
    liquidity_updates = fetch_latest_updates(LIQUIDITY_SERIES)

    sections: Dict[str, pd.DataFrame] = {
        "Today’s Economic Releases": today_releases,
        "Liquidity Updates": liquidity_updates,
    }
    
    return {
        "macro": macro,
        "sections": {},
    }
