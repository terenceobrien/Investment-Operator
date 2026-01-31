from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Tuple

import pandas as pd
from fredapi import Fred
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class MacroSignal:
    name: str
    latest: float
    mom: float     # 1-month change (approx)
    yoy: float     # 12-month change (approx)
    trend: str     # "UP" / "DOWN" / "FLAT"

def _pct_change(series: pd.Series, periods: int) -> float:
    s = series.dropna()
    if len(s) <= periods:
        return float("nan")
    return float((s.iloc[-1] / s.iloc[-1 - periods] - 1.0) * 100.0)

def _level_change(series: pd.Series, periods: int) -> float:
    s = series.dropna()
    if len(s) <= periods:
        return float("nan")
    return float(s.iloc[-1] - s.iloc[-1 - periods])

def _trend_from_changes(short: float, long: float) -> str:
    # simple: agree -> direction; disagree -> flat
    if pd.isna(short) or pd.isna(long):
        return "FLAT"
    if short > 0 and long > 0:
        return "UP"
    if short < 0 and long < 0:
        return "DOWN"
    return "FLAT"

def fetch_regime_signals() -> Dict[str, MacroSignal]:
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("Missing FRED_API_KEY. Add it to your .env file.")

    fred = Fred(api_key=key)

    # Series choices (simple, robust):
    # Growth: Industrial Production (INDPRO)
    # Inflation: CPI (CPIAUCSL)
    # Liquidity proxy: Financial Conditions Index (NFCI) - higher = tighter (so invert interpretation)
    series_map: Dict[str, Tuple[str, str]] = {
        "Growth": ("INDPRO", "Industrial Production"),
        "Inflation": ("CPIAUCSL", "CPI (All Urban Consumers)"),
        "Liquidity": ("NFCI", "Chicago Fed NFCI (tighter ↑)"),
    }

    out: Dict[str, MacroSignal] = {}

    for bucket, (code, label) in series_map.items():
        s = fred.get_series(code)
        s = pd.Series(s)
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()

        latest = float(s.dropna().iloc[-1])

        # monthly-ish series; use 1 and 12 periods as MoM/YoY approximations
        if bucket in ("Growth", "Inflation"):
            mom = _pct_change(s, 1)
            yoy = _pct_change(s, 12)
            trend = _trend_from_changes(mom, yoy)
        else:
            # NFCI is an index; use level changes
            mom = _level_change(s, 4)   # ~4 weeks
            yoy = _level_change(s, 52)  # ~52 weeks
            trend = _trend_from_changes(mom, yoy)

        out[bucket] = MacroSignal(
            name=label,
            latest=latest,
            mom=mom,
            yoy=yoy,
            trend=trend,
        )

    return out
