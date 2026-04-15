"""
src/state/regime_data.py

Fetches all raw inputs needed for the five-layer regime scoring system.
Runs ONCE at market close — not intraday.

Returns a RegimeInputs dataclass with every field the scoring system needs.
Missing data is None — the scoring system handles this gracefully.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional
import numpy as np
import pandas as pd


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class RegimeInputs:
    asof_date: str = ""

    # Layer 1 — Monetary
    net_liquidity:      Optional[float] = None   # WALCL - TGA - RRP (billions)
    net_liquidity_z:    Optional[float] = None   # z-score vs 1yr
    nfci:               Optional[float] = None   # Chicago Fed NFCI
    nfci_inverted:      Optional[float] = None   # -NFCI z-score
    m2_growth_yoy:      Optional[float] = None   # M2 YoY %
    fci_z:              Optional[float] = None   # FCI z-score inverted

    # Layer 2 — Credit
    hy_spread_level:    Optional[float] = None   # bps
    hy_spread_z:        Optional[float] = None
    hy_spread_chg_4w:   Optional[float] = None   # bps
    ig_spread_level:    Optional[float] = None   # bps
    ig_spread_z:        Optional[float] = None
    hyg_tlt_ratio_z:    Optional[float] = None

    # Layer 3 — Volatility
    vix_level:          Optional[float] = None
    vix_z_20d:          Optional[float] = None
    vix_term_slope:     Optional[float] = None   # VIX3M - VIX
    vvix_level:         Optional[float] = None
    vvix_z:             Optional[float] = None
    put_call_ratio:     Optional[float] = None   # 5d MA equity P/C
    skew_index:         Optional[float] = None

    # Layer 4 — Breadth
    pct_above_200d:         Optional[float] = None
    new_highs_minus_lows_z: Optional[float] = None
    sectors_green:           Optional[int]   = None
    rsp_vs_spy_z:           Optional[float] = None
    adl_slope:              Optional[float] = None

    # Layer 5 — Positioning
    dealer_gamma_z:       Optional[float] = None
    put_call_5d_ma:       Optional[float] = None
    aaii_bull_minus_bear: Optional[float] = None
    cot_net_large_spec_z: Optional[float] = None
    equity_etf_flow_z:    Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_last(series: pd.Series) -> Optional[float]:
    try:
        v = series.dropna().iloc[-1]
        return float(v) if np.isfinite(float(v)) else None
    except Exception:
        return None


def _z_score(series: pd.Series, window: int = 252) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 20:
            return None
        rolling = s.rolling(window, min_periods=20)
        mu = rolling.mean().iloc[-1]
        sd = rolling.std().iloc[-1]
        if sd == 0 or not np.isfinite(sd):
            return None
        return float((s.iloc[-1] - mu) / sd)
    except Exception:
        return None


def _pct_change_yoy(series: pd.Series) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 252:
            return None
        latest = s.iloc[-1]
        year_ago = s.iloc[-252]
        if year_ago == 0:
            return None
        return float((latest / year_ago - 1) * 100)
    except Exception:
        return None


# ── FRED fetcher ──────────────────────────────────────────────────────────────

def _fred(series_id: str, periods: int = 520) -> pd.Series:
    """Fetch a FRED series. Returns empty Series on failure."""
    try:
        def _lazy_fred():
            from fredapi import Fred
            api_key = os.environ.get("FRED_API_KEY", "")
            return Fred(api_key=api_key)

        fred = _lazy_fred()
        data = fred.get_series(series_id)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        return data.dropna().tail(periods)
    except Exception as e:
        print(f"FRED fetch failed for {series_id}: {e}")
        return pd.Series(dtype=float)


# ── yfinance fetcher ──────────────────────────────────────────────────────────

def _yf_close(ticker: str, period: str = "2y") -> pd.Series:
    """Fetch closing prices via yfinance."""
    try:
        import yfinance as yf
        data = yf.download(ticker, period=period, progress=False,
                           auto_adjust=True, threads=False)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        closes = data["Close"].squeeze().dropna()
        return closes
    except Exception as e:
        print(f"yfinance fetch failed for {ticker}: {e}")
        return pd.Series(dtype=float)


# ── Layer 1: Monetary ─────────────────────────────────────────────────────────

def _fetch_monetary(inputs: RegimeInputs) -> None:
    print("  Fetching monetary & liquidity data...")

    # Net liquidity = Fed balance sheet - TGA - RRP
    walcl = _fred("WALCL")      # Fed balance sheet (millions)
    tga   = _fred("WTREGEN")    # Treasury General Account (billions)
    rrp   = _fred("RRPONTSYD")  # Overnight reverse repo (billions)

    if not walcl.empty and not tga.empty and not rrp.empty:
        try:
            walcl_b = walcl / 1000  # millions -> billions
            # Align to weekly frequency
            combined = pd.concat([walcl_b, tga, rrp], axis=1).ffill().dropna()
            combined.columns = ["walcl", "tga", "rrp"]
            net_liq = combined["walcl"] - combined["tga"] - combined["rrp"]
            inputs.net_liquidity = _safe_last(net_liq)
            z = _z_score(net_liq, window=52)
            inputs.net_liquidity_z = z
            print(f"    net_liquidity=${inputs.net_liquidity:.0f}B  z={z}")
        except Exception as e:
            print(f"    net_liquidity calc failed: {e}")

    # NFCI — Chicago Fed National Financial Conditions Index
    nfci = _fred("NFCI")
    if not nfci.empty:
        inputs.nfci = _safe_last(nfci)
        # Inverted z-score: negative NFCI (easy) = positive score
        z = _z_score(nfci)
        inputs.nfci_inverted = -z if z is not None else None
        print(f"    nfci={inputs.nfci}  inverted_z={inputs.nfci_inverted}")

    # M2 growth YoY
    m2 = _fred("M2SL")
    if not m2.empty:
        inputs.m2_growth_yoy = _pct_change_yoy(m2)
        print(f"    m2_growth_yoy={inputs.m2_growth_yoy}")


# ── Layer 2: Credit ───────────────────────────────────────────────────────────

def _fetch_credit(inputs: RegimeInputs) -> None:
    print("  Fetching credit & stress data...")

    # HY spreads (BAMLH0A0HYM2 = ICE BofA HY OAS in %)
    hy = _fred("BAMLH0A0HYM2")
    if not hy.empty:
        hy_bps = hy * 100  # convert % to bps
        inputs.hy_spread_level = _safe_last(hy_bps)
        inputs.hy_spread_z = _z_score(hy_bps, window=504)  # 2yr

        # 4-week change
        try:
            s = hy_bps.dropna()
            if len(s) >= 20:
                inputs.hy_spread_chg_4w = float(s.iloc[-1] - s.iloc[-20])
        except Exception:
            pass
        print(f"    hy_spread={inputs.hy_spread_level}bps  z={inputs.hy_spread_z}  chg4w={inputs.hy_spread_chg_4w}")

    # IG spreads (BAMLC0A0CM = ICE BofA IG OAS in %)
    ig = _fred("BAMLC0A0CM")
    if not ig.empty:
        ig_bps = ig * 100
        inputs.ig_spread_level = _safe_last(ig_bps)
        inputs.ig_spread_z = _z_score(ig_bps, window=504)
        print(f"    ig_spread={inputs.ig_spread_level}bps  z={inputs.ig_spread_z}")

    # HYG/TLT ratio z-score via yfinance
    hyg = _yf_close("HYG")
    tlt = _yf_close("TLT")
    if not hyg.empty and not tlt.empty:
        try:
            ratio = (hyg / tlt).dropna()
            inputs.hyg_tlt_ratio_z = _z_score(ratio, window=252)
            print(f"    hyg_tlt_ratio_z={inputs.hyg_tlt_ratio_z}")
        except Exception:
            pass


# ── Layer 3: Volatility ───────────────────────────────────────────────────────

def _fetch_volatility(inputs: RegimeInputs) -> None:
    print("  Fetching volatility structure data...")

    vix   = _yf_close("^VIX",  period="1y")
    vix3m = _yf_close("^VIX3M", period="1y")
    vvix  = _yf_close("^VVIX", period="1y")
    skew  = _yf_close("^SKEW", period="1y")

    if not vix.empty:
        inputs.vix_level = _safe_last(vix)
        inputs.vix_z_20d = _z_score(vix, window=20)
        print(f"    vix={inputs.vix_level}  z={inputs.vix_z_20d}")

    if not vix.empty and not vix3m.empty:
        try:
            aligned = pd.concat([vix, vix3m], axis=1).dropna()
            aligned.columns = ["vix", "vix3m"]
            slope = aligned["vix3m"] - aligned["vix"]
            inputs.vix_term_slope = _safe_last(slope)
            print(f"    vix_term_slope={inputs.vix_term_slope} (VIX3M-VIX)")
        except Exception:
            pass

    if not vvix.empty:
        inputs.vvix_level = _safe_last(vvix)
        inputs.vvix_z = _z_score(vvix, window=252)
        print(f"    vvix={inputs.vvix_level}  z={inputs.vvix_z}")

    if not skew.empty:
        inputs.skew_index = _safe_last(skew)
        print(f"    skew={inputs.skew_index}")

    # CBOE equity put/call ratio
    pcr = _yf_close("^PCCE", period="6mo")
    if not pcr.empty:
        s = pcr.dropna()
        if len(s) >= 5:
            inputs.put_call_ratio = float(s.rolling(5).mean().iloc[-1])
            inputs.put_call_5d_ma = inputs.put_call_ratio
        print(f"    put_call_ratio_5dma={inputs.put_call_ratio}")


# ── Layer 4: Breadth ──────────────────────────────────────────────────────────

def _fetch_breadth(inputs: RegimeInputs, sectors_green: Optional[int] = None) -> None:
    print("  Fetching breadth & participation data...")

    inputs.sectors_green = sectors_green

    # New highs / new lows from FRED
    highs = _fred("HIGHNEW", periods=520)
    lows  = _fred("LOWNEW",  periods=520)
    if not highs.empty and not lows.empty:
        try:
            hl = (highs - lows).dropna()
            inputs.new_highs_minus_lows_z = _z_score(hl, window=252)
            print(f"    new_highs_minus_lows_z={inputs.new_highs_minus_lows_z}")
        except Exception:
            pass

    # RSP vs SPY ratio z-score
    rsp = _yf_close("RSP")
    spy = _yf_close("SPY")
    if not rsp.empty and not spy.empty:
        try:
            ratio = (rsp / spy).dropna()
            inputs.rsp_vs_spy_z = _z_score(ratio, window=252)
            print(f"    rsp_vs_spy_z={inputs.rsp_vs_spy_z}")
        except Exception:
            pass

    # % stocks above 200d MA — use S&P 500 members via NYSE composite proxy
    # Best proxy available without expensive data: use ^NYA breadth or estimate
    # from sector ETFs vs their 200d MAs
    try:
        sector_etfs = ["XLK", "XLF", "XLV", "XLY", "XLP",
                        "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        above_200d = []
        for etf in sector_etfs:
            closes = _yf_close(etf, period="2y")
            if closes.empty or len(closes) < 200:
                continue
            above = closes.iloc[-1] > closes.rolling(200).mean().iloc[-1]
            above_200d.append(float(above))
        if above_200d:
            inputs.pct_above_200d = round(np.mean(above_200d) * 100, 1)
            print(f"    pct_above_200d (sector proxy)={inputs.pct_above_200d}%")
    except Exception as e:
        print(f"    pct_above_200d failed: {e}")


# ── Layer 5: Positioning ──────────────────────────────────────────────────────

def _fetch_positioning(inputs: RegimeInputs) -> None:
    print("  Fetching positioning & sentiment data...")

    # Put/call 5d MA already fetched in volatility section
    # inputs.put_call_5d_ma is set there

    # AAII sentiment — not available via free API directly
    # COT data via FRED (CFTC Large Speculator Net Positions)
    # Series: DCOILWTICO for oil COT, for equity futures use manual fetch
    # For now: placeholder — integrate SpotGamma or CFTC download separately
    # These are set to None and will degrade gracefully in scoring

    print("    dealer_gamma: requires SpotGamma API — skipping")
    print("    aaii_sentiment: requires AAII feed — skipping")
    print("    cot_data: requires CFTC download — skipping")
    print("    Note: positioning layer will use available put/call data only")


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_regime_inputs(
    sectors_green: Optional[int] = None,
    asof_date: Optional[str] = None,
) -> RegimeInputs:
    """
    Fetch all regime inputs from FRED and yfinance.
    Call this ONCE at market close.

    Args:
        sectors_green: Pass from your existing market_state build
        asof_date: Override date string (defaults to today)

    Returns:
        RegimeInputs with all available data populated
    """
    inputs = RegimeInputs(
        asof_date=asof_date or datetime.utcnow().strftime("%Y-%m-%d")
    )

    print(f"\nFetching regime inputs for {inputs.asof_date}...")

    try:
        _fetch_monetary(inputs)
    except Exception as e:
        print(f"  Monetary fetch error: {e}")

    try:
        _fetch_credit(inputs)
    except Exception as e:
        print(f"  Credit fetch error: {e}")

    try:
        _fetch_volatility(inputs)
    except Exception as e:
        print(f"  Volatility fetch error: {e}")

    try:
        _fetch_breadth(inputs, sectors_green=sectors_green)
    except Exception as e:
        print(f"  Breadth fetch error: {e}")

    try:
        _fetch_positioning(inputs)
    except Exception as e:
        print(f"  Positioning fetch error: {e}")

    print(f"Done. Fields populated: {sum(1 for v in asdict(inputs).values() if v is not None)}/{len(asdict(inputs))}")
    return inputs