from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

import numpy as np
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

Trend = Literal["UP", "DOWN", "FLAT"]
Freq = Literal["ME", "W"]


# -----------------------------
# Data model
# -----------------------------
@dataclass(frozen=True)
class MacroComponent:
    name: str
    series_id: str
    transform: Literal["yoy_rate", "level", "net_liquidity_level"]
    freq: Freq
    invert: bool = False
    weight: float = 1.0


@dataclass(frozen=True)
class MacroSignal:
    name: str
    latest: float                # latest composite z-score (unitless)
    mom: float                   # 1-period change in composite (MoM if monthly, WoW if weekly)
    yoy: float                   # 12-period change in composite (12m if monthly, 52w if weekly)
    trend: Trend
    slope_n: float               # slope over last N periods (z-score units per period)
    history_12m: pd.Series       # last 12 months (monthly) or 52 weeks (weekly)
    components: Dict[str, float] # latest component z-scores


# -----------------------------
# Helpers
# -----------------------------
def _fred_client():
    from fredapi import Fred
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("Missing FRED_API_KEY. Add it to your .env file.")
    return Fred(api_key=key)


def _to_series(x) -> pd.Series:
    s = pd.Series(x).dropna()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _pct_change_series(level: pd.Series, periods: int) -> pd.Series:
    level = level.dropna().astype(float)
    return (level / level.shift(periods) - 1.0) * 100.0


def _resample_to_freq(s: pd.Series, freq: Freq) -> pd.Series:
    """
    Resample to monthly ('ME') or weekly ('W') last observation and forward-fill.
    """
    if freq == "ME":
        # month-end frequency
        out = s.resample("ME").last().ffill()
        return out
    if freq == "W":
        # week ending Friday
        out = s.resample("W").last().ffill()
        return out
    raise ValueError(f"Unsupported freq: {freq}")


def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    """
    Rolling z-score; requires enough history to stabilize.
    """
    s = s.astype(float)
    minp = max(12, window // 4)  # conservative
    mu = s.rolling(window, min_periods=minp).mean()
    sd = s.rolling(window, min_periods=minp).std()
    z = (s - mu) / sd
    return z.replace([np.inf, -np.inf], np.nan)


def _slope_last_n(s: pd.Series, n: int) -> float:
    s = s.dropna()
    if len(s) < 2:
        return 0.0
    if len(s) < n:
        n = len(s)
    y = s.iloc[-n:].values.astype(float)
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _trend_from_slope(slope: float, threshold: float) -> Trend:
    if slope > threshold:
        return "UP"
    if slope < -threshold:
        return "DOWN"
    return "FLAT"


def _compute_component_series(
    fred,
    comp: MacroComponent,
    *,
    net_liq_inputs: Optional[Dict[str, pd.Series]] = None,
) -> pd.Series:
    """
    Build the transformed "signal series" at native date index (pre-resample).
    """
    sid = comp.series_id.strip().upper()

    if comp.transform == "yoy_rate":
        try:
            level = _to_series(fred.get_series(sid))
        except Exception as e:
            raise ValueError(f"FRED failed for series '{sid}': {e}")
        # YoY % rate series (this is the meaningful inflation/growth signal)
        sig = _pct_change_series(level, 12).dropna()
        return sig

    if comp.transform == "level":
        return _to_series(fred.get_series(sid))

    if comp.transform == "net_liquidity_level":
        if net_liq_inputs is None:
            raise RuntimeError("net_liq_inputs required for net_liquidity_level.")
        walcl = net_liq_inputs["WALCL"]
        tga = net_liq_inputs["WTREGEN"]
        rrp = net_liq_inputs["RRPONTSYD"]
        df = pd.concat([walcl, tga, rrp], axis=1).dropna()
        df.columns = ["WALCL", "WTREGEN", "RRPONTSYD"]
        net = df["WALCL"] - df["WTREGEN"] - df["RRPONTSYD"]
        net.name = "NET_LIQ"
        return net

    raise ValueError(f"Unknown transform: {comp.transform}")


def _composite_bucket(
    fred,
    bucket_name: str,
    comps: List[MacroComponent],
    *,
    freq: Freq,
    z_window: int,
    slope_n: int,
    slope_threshold: float,
) -> MacroSignal:
    """
    Pipeline:
      1) transform each component into a "signal series"
      2) resample to target freq (ME or W)
      3) invert if needed
      4) rolling z-score (window depends on freq)
      5) weighted average across components => composite z-score series
      6) compute latest stats + trend + 12m history
    """
    # Pre-fetch inputs for net liquidity if needed
    need_net_liq = any(c.transform == "net_liquidity_level" for c in comps)
    net_liq_inputs = None
    if need_net_liq:
        net_liq_inputs = {
            "WALCL": _to_series(fred.get_series("WALCL")),
            "WTREGEN": _to_series(fred.get_series("WTREGEN")),
            "RRPONTSYD": _to_series(fred.get_series("RRPONTSYD")),
        }

    # Build each component's z-score series
    comp_z: Dict[str, pd.Series] = {}
    for c in comps:
        sig = _compute_component_series(fred, c, net_liq_inputs=net_liq_inputs)
        sig_rs = _resample_to_freq(sig, freq=c.freq)  # resample at component's declared freq

        # If bucket freq differs from component freq, align by resampling again
        # Example: liquidity components all weekly; growth/inflation all monthly (in this version)
        sig_rs = _resample_to_freq(sig_rs, freq=freq)

        if c.invert:
            sig_rs = -1.0 * sig_rs

        z = _rolling_zscore(sig_rs, window=z_window)
        comp_z[c.name] = z

    # Align components
    zdf = pd.concat(comp_z.values(), axis=1)
    zdf.columns = list(comp_z.keys())
    zdf = zdf.ffill().dropna(how="all")

    # Weighted composite
    cols = [c.name for c in comps]
    zdf = zdf[cols]

    weights = np.array([c.weight for c in comps], dtype=float)
    wsum = float(weights.sum()) if float(weights.sum()) != 0.0 else 1.0
    wnorm = weights / wsum

    composite_vals = zdf.values @ wnorm
    composite = pd.Series(composite_vals, index=zdf.index, name=bucket_name).dropna()

    latest = float(composite.iloc[-1])
    mom = float(composite.iloc[-1] - composite.iloc[-2]) if len(composite) >= 2 else float("nan")

    if freq == "ME":
        yoy = float(composite.iloc[-1] - composite.iloc[-12]) if len(composite) >= 13 else float("nan")
        hist = composite.iloc[-12:] if len(composite) >= 12 else composite
    else:
        yoy = float(composite.iloc[-1] - composite.iloc[-52]) if len(composite) >= 53 else float("nan")
        hist = composite.iloc[-52:] if len(composite) >= 52 else composite

    slope_val = _slope_last_n(composite, slope_n)
    trend = _trend_from_slope(slope_val, slope_threshold)

    latest_components = {col: float(zdf[col].iloc[-1]) for col in zdf.columns}

    return MacroSignal(
        name=bucket_name,
        latest=latest,
        mom=mom,
        yoy=yoy,
        trend=trend,
        slope_n=slope_val,
        history_12m=hist,
        components=latest_components,
    )


# -----------------------------
# Public API
# -----------------------------
def fetch_regime_signals() -> Dict[str, MacroSignal]:
    fred = _fred_client()

    # --- Growth: monthly composite of YoY rates ---
    growth_components = [
        MacroComponent(
            name="Industrial Production YoY",
            series_id="INDPRO",
            transform="yoy_rate",
            freq="ME",
            weight=1.0,
        ),
        MacroComponent(
            name="Payrolls (PAYEMS) YoY",
            series_id="PAYEMS",
            transform="yoy_rate",
            freq="ME",
            weight=1.0,
        ),
        # GDP later (quarterly) after pipeline calibration
    ]

    # --- Inflation: monthly composite of YoY rates ---
    inflation_components = [
        MacroComponent(name="CPI YoY", series_id="CPIAUCSL", transform="yoy_rate", freq="ME", weight=1.0),
        MacroComponent(name="Core PCE YoY", series_id="PCEPILFE", transform="yoy_rate", freq="ME", weight=1.0),
        MacroComponent(name="PPI YoY", series_id="PPIACO", transform="yoy_rate", freq="ME", weight=1.0),
    ]

    # --- Liquidity: weekly composite (net liquidity + financial conditions overlay) ---
    liquidity_components = [
        MacroComponent(
            name="Net Liquidity (WALCL-TGA-RRP)",
            series_id="NET_LIQ",
            transform="net_liquidity_level",
            freq="W",
            weight=1.0,
        ),
        MacroComponent(
            name="NFCI (inverted)",
            series_id="NFCI",
            transform="level",
            freq="W",
            invert=True,     # higher NFCI = tighter, so invert so higher = easier
            weight=0.75,
        ),
    ]

    out: Dict[str, MacroSignal] = {}
    out["Growth"] = _composite_bucket(
        fred,
        "Growth",
        growth_components,
        freq="ME",
        z_window=36,         # 36 months
        slope_n=6,           # 6 months slope
        slope_threshold=0.10 # z-score units per month
    )
    out["Inflation"] = _composite_bucket(
        fred,
        "Inflation",
        inflation_components,
        freq="ME",
        z_window=36,
        slope_n=6,
        slope_threshold=0.10
    )
    out["Liquidity"] = _composite_bucket(
        fred,
        "Liquidity",
        liquidity_components,
        freq="W",
        z_window=156,        # 156 weeks (~3 years)
        slope_n=13,          # 13 weeks slope
        slope_threshold=0.03 # z-score units per week
    )

    return out