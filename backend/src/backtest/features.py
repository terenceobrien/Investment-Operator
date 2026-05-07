"""
src/backtest/features.py  — v2

Builds historical research frames using the new five-layer regime scoring system.

Key changes from v1:
  - Replaces score_market_state() with score_all_layers() from regime_layers.py
  - Augments yfinance data with FRED series for credit and breadth layers
  - Adds ^VIX3M and ^VVIX to cross-asset panel for vol term structure
  - Derives rsp_vs_spy_z and hyg_tlt_ratio_z from price data
  - Gracefully handles missing inputs — layers score at neutral when data unavailable
  - Output schema is backward-compatible: same long format, same fwd return cols
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.src.backtest.data import (
    DEFAULT_CROSS_ASSET,
    DEFAULT_SECTOR_TICKERS,
    fetch_yf_panel,
)
from backend.src.data.breadth_nyhl import (
    bulk_fetch_sp500_history,
    compute_nyhl_zscore,
    compute_sp500_nyhl,
    get_sp500_membership,
)
from backend.src.data.external_sources import fetch_cot_history, load_aaii_sentiment
from backend.src.state.regime_layers import score_all_layers

FEATURE_VERSION = "v2_layers_2026"

# ── Extended cross-asset set (adds VIX term structure + VVIX) ─────────────────

EXTENDED_CROSS_ASSET = sorted(set(DEFAULT_CROSS_ASSET + ["^VIX3M", "^VVIX", "^SKEW"]))

# ── FRED series needed for credit + breadth layers ────────────────────────────

FRED_SERIES = {
    "hy_spread":  "BAMLH0A0HYM2",   # HY OAS (%) — multiply by 100 for bps
    "ig_spread":  "BAMLC0A0CM",     # IG OAS (%)
    "new_highs":  "HIGHNEW",        # NYSE new 52-week highs
    "new_lows":   "LOWNEW",         # NYSE new 52-week lows
    "walcl":      "WALCL",          # Fed balance sheet (millions)
    "tga":        "WTREGEN",        # Treasury General Account (billions)
    "rrp":        "RRPONTSYD",      # Overnight reverse repo (billions)
    "nfci":       "NFCI",           # Chicago Fed National Financial Conditions Index
    "m2":         "M2SL",           # M2 money stock
    "baa10y":     "BAA10Y",         # Moody's BAA minus 10Y Treasury (%)
    "aaa10y":     "AAA10Y",         # Moody's AAA minus 10Y Treasury (%)
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pct_change(s: pd.Series, periods: int = 1) -> pd.Series:
    return s.pct_change(periods=periods)


def _safe_float(x) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    ma = s.rolling(window, min_periods=max(5, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(5, window // 2)).std(ddof=0)
    return (s - ma) / sd.replace(0, np.nan)


def _leadership_top3(sector_rets: Dict[str, float]) -> List[Tuple[str, float]]:
    items = [(k, v) for k, v in sector_rets.items() if v is not None]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:3]


def _clv(high: float, low: float, close: float) -> Optional[float]:
    denom = high - low
    if denom == 0:
        return None
    return float(((close - low) - (high - close)) / denom)


def _range_pct(high: float, low: float, close: float) -> Optional[float]:
    if close == 0:
        return None
    return float((high - low) / close)


# ── FRED fetch (reuses fredapi if available, skips gracefully if not) ─────────

def _fetch_fred_series(series_id: str, start: str, end: str) -> pd.Series:
    try:
        from fredapi import Fred
        fred = Fred(api_key=os.environ.get("FRED_API_KEY", ""))
        data = fred.get_series(series_id, observation_start=start, observation_end=end)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        data.index = pd.to_datetime(data.index)
        return data.dropna()
    except Exception as e:
        print(f"  FRED fetch skipped ({series_id}): {e}")
        return pd.Series(dtype=float)


def _fetch_fred_data(start: str, end: str) -> Dict[str, pd.Series]:
    """Fetch all FRED series needed for regime scoring."""
    print("  Fetching FRED data for credit + breadth layers...")
    out = {}
    for name, series_id in FRED_SERIES.items():
        s = _fetch_fred_series(series_id, start, end)
        if not s.empty:
            print(f"    {name} ({series_id}): {len(s)} obs, {s.index.min().date()} → {s.index.max().date()}")
        else:
            print(f"    {name} ({series_id}): NO DATA — layer will degrade gracefully")
        out[name] = s
    return out


def _align_fred_to_daily(fred_series: pd.Series, daily_index: pd.DatetimeIndex) -> pd.Series:
    """Forward-fill FRED data (weekly/monthly) to daily index."""
    if fred_series.empty:
        return pd.Series(np.nan, index=daily_index)
    combined = fred_series.reindex(fred_series.index.union(daily_index))
    combined = combined.ffill()
    return combined.reindex(daily_index)


# ── Main feature builder ──────────────────────────────────────────────────────

def build_daily_feature_frame(
    start: str,
    end: str,
    cross_assets: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    vix_window: int = 20,
    vol_window: int = 20,
    zscore_window: int = 252,        # for credit/breadth z-scores
    use_fred: bool = True,           # set False to skip FRED (faster, less accurate)
    cache_dir: str = "data/cache/backtest",
    force_download: bool = False,
) -> pd.DataFrame:
    """
    Builds daily feature frame with all inputs needed for five-layer regime scoring.
    Augments yfinance data with FRED credit + breadth series.

    New columns vs v1:
      vix_term_slope     — VIX3M minus VIX (contango = positive = calm)
      vvix_level         — CBOE VVIX
      vvix_z             — VVIX 252-day z-score
      hy_spread_level    — HY OAS in bps (FRED)
      hy_spread_z        — rolling z-score of HY spreads
      hy_spread_chg_4w   — 4-week change in HY spread level
      ig_spread_level    — IG OAS in bps (FRED)
      ig_spread_z        — rolling z-score of IG spreads
      hyg_tlt_ratio_z    — z-score of HYG/TLT price ratio
      rsp_vs_spy_z       — z-score of RSP/SPY price ratio
      new_highs_minus_lows_z — z-score of S&P 500 new highs minus new lows
    """
    cross_assets = cross_assets or EXTENDED_CROSS_ASSET
    sectors = sectors or DEFAULT_SECTOR_TICKERS

    tickers = sorted(set(cross_assets + sectors + ["^VIX"]))
    panel = fetch_yf_panel(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        auto_adjust=False,
        cache_dir=cache_dir,
        force=force_download,
    )

    # ── Core SPY series ──
    spy_close = panel.field("SPY", "Close")
    spy_open  = panel.field("SPY", "Open")
    spy_high  = panel.field("SPY", "High")
    spy_low   = panel.field("SPY", "Low")
    spy_vol   = panel.field("SPY", "Volume")

    # ── Cross-asset returns ──
    cross_ret_1d, cross_ret_5d, cross_ret_21d = {}, {}, {}
    for t in cross_assets:
        if panel.has(t, "Close"):
            c = panel.field(t, "Close")
            cross_ret_1d[t]  = _pct_change(c, 1)
            cross_ret_5d[t]  = _pct_change(c, 5)
            cross_ret_21d[t] = _pct_change(c, 21)

    # ── Sector returns ──
    sector_ret_1d = {
        t: _pct_change(panel.field(t, "Close"), 1)
        for t in sectors if panel.has(t, "Close")
    }

    # ── VIX signals ──
    vix_level = panel.field("^VIX", "Close") if panel.has("^VIX", "Close") else pd.Series(dtype=float)
    vix_z_20d = _rolling_zscore(vix_level, vix_window) if not vix_level.empty else pd.Series(dtype=float)
    vix_change_pct_1d = _pct_change(vix_level, 1) if not vix_level.empty else pd.Series(dtype=float)

    # ── VIX term structure: VIX3M - VIX ──
    vix_term_slope = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("^VIX3M", "Close") and not vix_level.empty:
        vix3m = panel.field("^VIX3M", "Close")
        aligned = pd.concat([vix3m, vix_level], axis=1).dropna()
        aligned.columns = ["vix3m", "vix"]
        slope = aligned["vix3m"] - aligned["vix"]
        vix_term_slope = slope.reindex(spy_close.index)

    # ── VVIX ──
    vvix_level = pd.Series(dtype=float, index=spy_close.index)
    vvix_z     = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("^VVIX", "Close"):
        vv = panel.field("^VVIX", "Close")
        vvix_level = vv.reindex(spy_close.index)
        vvix_z     = _rolling_zscore(vv, zscore_window).reindex(spy_close.index)

    # ── SKEW ──
    skew_level = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("^SKEW", "Close"):
        skew_level = panel.field("^SKEW", "Close").reindex(spy_close.index)

    # ── RSP/SPY ratio z-score ──
    rsp_vs_spy_z = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("RSP", "Close"):
        rsp = panel.field("RSP", "Close")
        ratio = (rsp / spy_close).dropna()
        rsp_vs_spy_z = _rolling_zscore(ratio, zscore_window).reindex(spy_close.index)

    # ── RSP minus SPY 1d ret (kept for backward compat) ──
    rsp_minus_spy = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("RSP", "Close"):
        rsp = panel.field("RSP", "Close")
        rsp_minus_spy = (_pct_change(rsp, 1) - _pct_change(spy_close, 1)).reindex(spy_close.index)

    # ── HYG/TLT ratio z-score ──
    hyg_tlt_ratio_z = pd.Series(dtype=float, index=spy_close.index)
    if panel.has("HYG", "Close") and panel.has("TLT", "Close"):
        hyg = panel.field("HYG", "Close")
        tlt = panel.field("TLT", "Close")
        ratio = (hyg / tlt).dropna()
        hyg_tlt_ratio_z = _rolling_zscore(ratio, zscore_window).reindex(spy_close.index)

    # ── Volume ──
    spy_vol_z       = _rolling_zscore(spy_vol.astype(float), vol_window)
    spy_vol_ma      = spy_vol.rolling(vol_window).mean()
    spy_vol_vs_20d  = (spy_vol / spy_vol_ma - 1.0)

    # ── Tape features ──
    clv = pd.Series(index=spy_close.index, dtype=float)
    rng = pd.Series(index=spy_close.index, dtype=float)
    for idx in spy_close.index:
        try:
            clv.loc[idx] = _clv(float(spy_high.loc[idx]), float(spy_low.loc[idx]), float(spy_close.loc[idx]))
            rng.loc[idx] = _range_pct(float(spy_high.loc[idx]), float(spy_low.loc[idx]), float(spy_close.loc[idx]))
        except Exception:
            continue

    # ── Sector breadth ──
    sec_df     = pd.DataFrame({k: v for k, v in sector_ret_1d.items()})
    dispersion = sec_df.std(axis=1, ddof=0)
    sectors_green = (sec_df > 0).sum(axis=1)

    # Time-aware sector proxy for % above 200d MA. Handles newer ETFs such as
    # XLRE/XLC by dividing only by sectors that have valid data on each date.
    pct_above_200d = pd.Series(dtype=float, index=spy_close.index)
    try:
        above_cols = {}
        valid_cols = {}
        sector_proxy = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
        for t in sector_proxy:
            if not panel.has(t, "Close"):
                continue
            c = panel.field(t, "Close").reindex(spy_close.index)
            ma200 = c.rolling(200, min_periods=200).mean()
            valid = c.notna() & ma200.notna()
            above_cols[t] = (c > ma200).where(valid, False)
            valid_cols[t] = valid
        if above_cols:
            above_df = pd.DataFrame(above_cols)
            valid_df = pd.DataFrame(valid_cols)
            denom = valid_df.sum(axis=1).replace(0, np.nan)
            pct_above_200d = (above_df.sum(axis=1) / denom * 100.0).reindex(spy_close.index)
    except Exception as e:
        print(f"  pct_above_200d sector proxy failed: {e}")

    # ── FRED data ──
    fred_data = {}
    if use_fred:
        fred_data = _fetch_fred_data(start, end)

    # Monetary + credit + breadth defaults
    net_liquidity_z = pd.Series(dtype=float, index=spy_close.index)
    nfci_inverted = pd.Series(dtype=float, index=spy_close.index)
    m2_growth_yoy = pd.Series(dtype=float, index=spy_close.index)
    hy_spread_level    = pd.Series(dtype=float, index=spy_close.index)
    hy_spread_z        = pd.Series(dtype=float, index=spy_close.index)
    hy_spread_chg_4w   = pd.Series(dtype=float, index=spy_close.index)
    ig_spread_level    = pd.Series(dtype=float, index=spy_close.index)
    ig_spread_z        = pd.Series(dtype=float, index=spy_close.index)
    baa_spread_level   = pd.Series(dtype=float, index=spy_close.index)
    baa_spread_z       = pd.Series(dtype=float, index=spy_close.index)
    baa_spread_chg_4w  = pd.Series(dtype=float, index=spy_close.index)
    aaa_spread_level   = pd.Series(dtype=float, index=spy_close.index)
    aaa_spread_z       = pd.Series(dtype=float, index=spy_close.index)
    new_highs_minus_lows_z = pd.Series(dtype=float, index=spy_close.index)

    # Monetary: net liquidity, NFCI, M2
    if all(k in fred_data and not fred_data[k].empty for k in ("walcl", "tga", "rrp")):
        try:
            walcl_b = _align_fred_to_daily(fred_data["walcl"] / 1000.0, spy_close.index)
            tga = _align_fred_to_daily(fred_data["tga"], spy_close.index)
            rrp = _align_fred_to_daily(fred_data["rrp"], spy_close.index)
            net_liq = (walcl_b - tga - rrp).dropna()
            net_liquidity_z = _rolling_zscore(net_liq, zscore_window).reindex(spy_close.index)
        except Exception as e:
            print(f"  net_liquidity calc failed: {e}")

    if "nfci" in fred_data and not fred_data["nfci"].empty:
        try:
            nfci_daily = _align_fred_to_daily(fred_data["nfci"], spy_close.index)
            nfci_inverted = (-1.0 * _rolling_zscore(nfci_daily.dropna(), zscore_window)).reindex(spy_close.index)
        except Exception as e:
            print(f"  NFCI calc failed: {e}")

    if "m2" in fred_data and not fred_data["m2"].empty:
        try:
            m2_daily = _align_fred_to_daily(fred_data["m2"], spy_close.index)
            m2_growth_yoy = ((m2_daily / m2_daily.shift(252) - 1.0) * 100.0).reindex(spy_close.index)
        except Exception as e:
            print(f"  M2 growth calc failed: {e}")

    if "hy_spread" in fred_data and not fred_data["hy_spread"].empty:
        hy_bps = fred_data["hy_spread"] * 100  # % -> bps
        hy_daily = _align_fred_to_daily(hy_bps, spy_close.index)
        hy_spread_level = hy_daily
        hy_spread_z = _rolling_zscore(hy_daily.dropna(), zscore_window).reindex(spy_close.index)
        # 4-week change (~20 trading days)
        hy_spread_chg_4w = (hy_daily - hy_daily.shift(20))

    if "ig_spread" in fred_data and not fred_data["ig_spread"].empty:
        ig_bps = fred_data["ig_spread"] * 100
        ig_daily = _align_fred_to_daily(ig_bps, spy_close.index)
        ig_spread_level = ig_daily
        ig_spread_z = _rolling_zscore(ig_daily.dropna(), zscore_window).reindex(spy_close.index)

    if "baa10y" in fred_data and not fred_data["baa10y"].empty:
        baa_bps = fred_data["baa10y"] * 100
        baa_daily = _align_fred_to_daily(baa_bps, spy_close.index)
        baa_spread_level = baa_daily
        baa_spread_z = _rolling_zscore(baa_daily.dropna(), zscore_window).reindex(spy_close.index)
        baa_spread_chg_4w = baa_daily - baa_daily.shift(20)

    if "aaa10y" in fred_data and not fred_data["aaa10y"].empty:
        aaa_bps = fred_data["aaa10y"] * 100
        aaa_daily = _align_fred_to_daily(aaa_bps, spy_close.index)
        aaa_spread_level = aaa_daily
        aaa_spread_z = _rolling_zscore(aaa_daily.dropna(), zscore_window).reindex(spy_close.index)

    if "new_highs" in fred_data and "new_lows" in fred_data:
        nh = fred_data["new_highs"]
        nl = fred_data["new_lows"]
        if not nh.empty and not nl.empty:
            hl = (nh - nl).dropna()
            hl_z = _rolling_zscore(hl, zscore_window)
            new_highs_minus_lows_z = _align_fred_to_daily(hl_z, spy_close.index)

    # Self-computed S&P 500 NYHL substitute for broken FRED HIGHNEW/LOWNEW.
    try:
        members = get_sp500_membership()
        if members:
            sp500_prices = bulk_fetch_sp500_history(
                members,
                start=start,
                end=end,
                force_download=force_download,
            )
            if not sp500_prices.empty:
                nyhl = compute_sp500_nyhl(sp500_prices, window=252)
                nyhl_z = compute_nyhl_zscore(nyhl["net_highs_lows"], window=252)
                if not nyhl_z.empty:
                    new_highs_minus_lows_z = nyhl_z.reindex(spy_close.index)
    except Exception as e:
        print(f"  S&P 500 NYHL build failed: {e}")

    cot_net_large_spec_z = pd.Series(dtype=float, index=spy_close.index)
    try:
        cot = fetch_cot_history(start_date=start)
        if not cot.empty and "cot_net_large_spec_z" in cot:
            cot_net_large_spec_z = cot["cot_net_large_spec_z"].reindex(
                cot.index.union(spy_close.index)
            ).sort_index().ffill().reindex(spy_close.index)
    except Exception as e:
        print(f"  COT history skipped: {e}")

    aaii_bull_minus_bear = pd.Series(dtype=float, index=spy_close.index)
    try:
        aaii = load_aaii_sentiment()
        if not aaii.empty and "aaii_bull_minus_bear" in aaii:
            aaii_bull_minus_bear = aaii["aaii_bull_minus_bear"].reindex(
                aaii.index.union(spy_close.index)
            ).sort_index().ffill().reindex(spy_close.index)
    except FileNotFoundError as e:
        print(f"  AAII sentiment skipped: {e}")
    except Exception as e:
        print(f"  AAII sentiment skipped: {e}")

    # ── Build output frame ──
    out = pd.DataFrame(index=spy_close.index)

    # SPY
    out["spy_ret_1d"]       = _pct_change(spy_close, 1)
    out["spy_open"]         = spy_open
    out["spy_close"]        = spy_close
    out["spy_prev_close"]   = spy_close.shift(1)
    out["spy_high"]         = spy_high
    out["spy_low"]          = spy_low
    out["spy_clv"]          = clv
    out["spy_range_pct"]    = rng * 100   # express as % for v2 (was decimal in v1)
    out["spy_vol"]          = spy_vol
    out["spy_vol_vs_20d_pct"] = spy_vol_vs_20d
    out["spy_vol_z_20d"]    = spy_vol_z

    # VIX
    if not vix_level.empty:
        out["vix_level"]          = vix_level
        out["vix_z_20d"]          = vix_z_20d
        out["vix_change_pct_1d"]  = vix_change_pct_1d
        out["vix_term_slope"]     = vix_term_slope

    # VVIX
    out["vvix_level"] = vvix_level
    out["vvix_z"]     = vvix_z
    out["skew_level"] = skew_level

    # Monetary
    out["net_liquidity_z"] = net_liquidity_z
    out["nfci_inverted"] = nfci_inverted
    out["m2_growth_yoy"] = m2_growth_yoy

    # Credit
    out["hy_spread_level"]  = hy_spread_level
    out["hy_spread_z"]      = hy_spread_z
    out["hy_spread_chg_4w"] = hy_spread_chg_4w
    out["ig_spread_level"]  = ig_spread_level
    out["ig_spread_z"]      = ig_spread_z
    out["baa_spread_level"] = baa_spread_level
    out["baa_spread_z"] = baa_spread_z
    out["baa_spread_chg_4w"] = baa_spread_chg_4w
    out["aaa_spread_level"] = aaa_spread_level
    out["aaa_spread_z"] = aaa_spread_z
    out["hyg_tlt_ratio_z"]  = hyg_tlt_ratio_z

    # Breadth
    out["pct_above_200d"]           = pct_above_200d
    out["rsp_minus_spy"]            = rsp_minus_spy
    out["rsp_vs_spy_z"]             = rsp_vs_spy_z
    out["new_highs_minus_lows_z"]   = new_highs_minus_lows_z
    out["dispersion"]               = dispersion
    out["sectors_green"]            = sectors_green

    # Positioning
    out["cot_net_large_spec_z"] = cot_net_large_spec_z
    out["aaii_bull_minus_bear"] = aaii_bull_minus_bear

    # Cross-asset returns
    for t, s in cross_ret_1d.items():
        out[f"ret_{t}_1d"] = s
    for t, s in cross_ret_5d.items():
        out[f"ret_{t}_5d"] = s
    for t, s in cross_ret_21d.items():
        out[f"ret_{t}_21d"] = s

    # Sector returns
    for t, s in sector_ret_1d.items():
        out[f"ret_{t}_1d"] = s

    # Forward returns — identical to v1
    out["fwd_ret_oc_1d"] = (spy_close / spy_open - 1.0)
    out["fwd_ret_cc_1d"] = (spy_close.shift(-1) / spy_close - 1.0)
    for n in (3, 5, 10, 21, 63, 126, 252):
        out[f"fwd_ret_cc_{n}d"] = (spy_close.shift(-n) / spy_close - 1.0)

    h_next5 = spy_high.shift(-1).rolling(5).max()
    l_next5 = spy_low.shift(-1).rolling(5).min()
    out["fwd_5d_max_upside_pct"]    = (h_next5 / spy_close - 1.0)
    out["fwd_5d_max_drawdown_pct"]  = (l_next5 / spy_close - 1.0)

    out["tail_loss_3d_1p5"] = (out["fwd_ret_cc_3d"] < -.015).astype("Int64")
    out["tail_loss_5d_2p5"] = (out["fwd_ret_cc_5d"] < -.025).astype("Int64")
    out["big_win_3d_1p5"]   = (out["fwd_ret_cc_3d"] > .015).astype("Int64")
    out["fwd_ret_cc_1m"]    = out["fwd_ret_cc_21d"]
    out["fwd_ret_cc_3m"]    = out["fwd_ret_cc_63d"]
    out["fwd_ret_cc_6m"]    = out["fwd_ret_cc_126d"]
    out["fwd_ret_cc_1y"]    = out["fwd_ret_cc_252d"]

    out["feature_version"] = FEATURE_VERSION
    out.sort_index(inplace=True)
    return out


# ── Scoring: replace score_market_state with score_all_layers ────────────────

def _row_to_layer_inputs(row: pd.Series) -> dict:
    """
    Maps a feature frame row to keyword arguments for score_all_layers().
    Returns only fields that are non-null.
    """
    def g(col):
        v = row.get(col)
        return _safe_float(v)

    def first_available(*cols):
        for col in cols:
            v = g(col)
            if v is not None:
                return v
        return None

    return dict(
        # Monetary
        net_liquidity_z=g("net_liquidity_z"),
        nfci_inverted=g("nfci_inverted"),
        m2_growth_yoy=g("m2_growth_yoy"),
        fci_z=None,

        # Credit. Use BAA/AAA Treasury-relative series as substitutes when
        # the preferred HY/IG OAS series are unavailable.
        hy_spread_level=first_available("hy_spread_level", "baa_spread_level"),
        hy_spread_z=first_available("hy_spread_z", "baa_spread_z"),
        hy_spread_chg_4w=first_available("hy_spread_chg_4w", "baa_spread_chg_4w"),
        ig_spread_level=first_available("ig_spread_level", "aaa_spread_level"),
        ig_spread_z=first_available("ig_spread_z", "aaa_spread_z"),
        hyg_tlt_ratio_z=g("hyg_tlt_ratio_z"),

        # Volatility
        vix_level=g("vix_level"),
        vix_z_20d=g("vix_z_20d"),
        vix_term_slope=g("vix_term_slope"),
        vvix_level=g("vvix_level"),
        vvix_z=g("vvix_z"),
        put_call_ratio=None,    # not in daily data
        skew_index=g("skew_level"),

        # Breadth
        pct_above_200d=g("pct_above_200d"),
        new_highs_minus_lows_z=g("new_highs_minus_lows_z"),
        sectors_green=int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
        rsp_vs_spy_z=g("rsp_vs_spy_z"),
        adl_slope=None,

        # Positioning
        dealer_gamma_z=None,
        put_call_5d_ma=None,
        aaii_bull_minus_bear=g("aaii_bull_minus_bear"),
        cot_net_large_spec_z=g("cot_net_large_spec_z"),
        equity_etf_flow_z=None,
    )


def score_history_both_signal_times(
    features: pd.DataFrame,
    sector_tickers: Optional[List[str]] = None,
    horizon: str = "default",
) -> pd.DataFrame:
    """
    Scores features using the five-layer regime scoring system for both
    signal_time='open' and signal_time='close'.

    Output: wide DataFrame with MultiIndex columns (signal_time, field).
    Same structure as v1 — drop-in replacement.
    """
    sector_tickers = sector_tickers or DEFAULT_SECTOR_TICKERS

    def score_for_index(frame: pd.DataFrame, ix: pd.DatetimeIndex) -> pd.DataFrame:
        rows = []
        total = len(ix)
        for i, dt in enumerate(ix):
            if i % 100 == 0:
                print(f"    Scoring {i}/{total} ({dt.date()})...")
            row = frame.loc[dt]
            try:
                kwargs = _row_to_layer_inputs(row)
                kwargs["horizon"] = horizon
                result = score_all_layers(**kwargs)

                rec = {
                    "score_total":    round(result.composite, 2),
                    "confidence":     round(result.confidence, 2),
                    "environment":    result.environment,
                    "layer_agreement": round(result.layer_agreement, 3),

                    # Layer scores (0-10 each)
                    "layer_monetary":    round(result.monetary.score, 2),
                    "layer_credit":      round(result.credit.score, 2),
                    "layer_volatility":  round(result.volatility.score, 2),
                    "layer_breadth":     round(result.breadth.score, 2),
                    "layer_positioning": round(result.positioning.score, 2),

                    # Data quality per layer
                    "dq_monetary":    result.monetary.data_quality,
                    "dq_credit":      result.credit.data_quality,
                    "dq_volatility":  result.volatility.data_quality,
                    "dq_breadth":     result.breadth.data_quality,
                    "dq_positioning": result.positioning.data_quality,

                    # Layer statuses
                    "status_monetary":    result.monetary.status,
                    "status_credit":      result.credit.status,
                    "status_volatility":  result.volatility.status,
                    "status_breadth":     result.breadth.status,
                    "status_positioning": result.positioning.status,

                    # Volume confirmation (kept from v1)
                    "volume_confirmation": (
                        (1.0 if _safe_float(row.get("spy_ret_1d")) > 0 else -1.0) *
                        (_safe_float(row.get("spy_vol_z_20d")) or 0.0)
                        if _safe_float(row.get("spy_ret_1d")) is not None
                        and _safe_float(row.get("spy_vol_z_20d")) is not None
                        else None
                    ),
                }
            except Exception as e:
                print(f"  Scoring error at {dt}: {e}")
                rec = {
                    "score_total": None, "confidence": None,
                    "environment": "Error", "layer_agreement": None,
                    "layer_monetary": None, "layer_credit": None,
                    "layer_volatility": None, "layer_breadth": None,
                    "layer_positioning": None,
                    "dq_monetary": 0, "dq_credit": 0, "dq_volatility": 0,
                    "dq_breadth": 0, "dq_positioning": 0,
                    "status_monetary": "neutral", "status_credit": "neutral",
                    "status_volatility": "neutral", "status_breadth": "neutral",
                    "status_positioning": "neutral",
                    "volume_confirmation": None,
                }
            rows.append(rec)

        return pd.DataFrame(rows, index=ix)

    def add_fwd(scored_df: pd.DataFrame, label: str, feature_frame: pd.DataFrame) -> pd.DataFrame:
        out = scored_df.copy()
        fwd_cols = [c for c in feature_frame.columns
                    if c.startswith("fwd_") or c.startswith("tail_") or c.startswith("big_")]
        for c in fwd_cols:
            out[c] = feature_frame[c]
        out.columns = pd.MultiIndex.from_product([[label], out.columns])
        return out

    # signal_time=open: use prior day's features (shift by 1)
    feat_open   = features.shift(1)
    scored_open = score_for_index(feat_open, feat_open.index)
    scored_open = scored_open.reindex(features.index)
    scored_open["signal_time"] = "open"

    # signal_time=close: use current day's features
    scored_close = score_for_index(features, features.index)
    scored_close = scored_close.reindex(features.index)
    scored_close["signal_time"] = "close"

    wide = pd.concat([
        add_fwd(scored_open,  "open",  features),
        add_fwd(scored_close, "close", features),
    ], axis=1)

    return wide


# ── Main entry point (matches v1 interface) ───────────────────────────────────

def build_research_frame(
    start: str,
    end: str,
    cross_assets: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    vix_window: int = 20,
    vol_window: int = 20,
    zscore_window: int = 252,
    use_fred: bool = True,
    cache_dir: str = "data/cache/backtest",
    force_download: bool = False,
    horizon: str = "default",
) -> pd.DataFrame:
    """
    Builds the full research dataset with five-layer regime scores.
    Output is long format: one row per date per signal_time.

    New columns vs v1:
      layer_monetary, layer_credit, layer_volatility,
      layer_breadth, layer_positioning  — each 0-10
      layer_agreement                   — 0-1
      dq_*                              — data quality per layer
      status_*                          — bullish/neutral/bearish per layer
      net_liquidity_z, nfci_inverted, m2_growth_yoy
      vix_term_slope, vvix_level, vvix_z, skew_level
      hy/ig spreads plus BAA/AAA substitutes
      hyg_tlt_ratio_z, rsp_vs_spy_z, pct_above_200d
      new_highs_minus_lows_z, cot_net_large_spec_z, aaii_bull_minus_bear
    """
    print(f"Building feature frame: {start} → {end}")
    feats = build_daily_feature_frame(
        start=start,
        end=end,
        cross_assets=cross_assets or EXTENDED_CROSS_ASSET,
        sectors=sectors,
        vix_window=vix_window,
        vol_window=vol_window,
        zscore_window=zscore_window,
        use_fred=use_fred,
        cache_dir=cache_dir,
        force_download=force_download,
    )
    print(f"  Features: {len(feats)} rows, {feats.index.min().date()} → {feats.index.max().date()}")

    print("Scoring history (both signal times)...")
    scored_wide = score_history_both_signal_times(feats, sectors, horizon=horizon)

    # Wide -> long
    parts = []
    for signal_time in ["open", "close"]:
        s = scored_wide[signal_time].copy()
        s["signal_time"] = signal_time
        parts.append(s)

    scored_long = pd.concat(parts, axis=0)
    scored_long.index.name = "date"
    scored_long = scored_long.reset_index()

    # Merge raw features (drop fwd cols to avoid duplication)
    feats2 = feats.copy()
    feats2.index.name = "date"
    feats2 = feats2.reset_index()
    label_cols = [c for c in feats2.columns
                  if c.startswith("fwd_") or c.startswith("tail_") or c.startswith("big_")]
    feats2 = feats2.drop(columns=label_cols)

    df = scored_long.merge(feats2, on="date", how="left")
    df.sort_values(["date", "signal_time"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    print(f"Done. {len(df)} rows, {df['date'].min()} → {df['date'].max()}")
    return df
