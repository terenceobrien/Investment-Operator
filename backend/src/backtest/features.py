from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.backtest.data import (
    DEFAULT_CROSS_ASSET,
    DEFAULT_SECTOR_TICKERS,
    fetch_yf_panel,
)
from src.state.market_state import MarketState
from src.state.scoring import score_market_state

FEATURE_VERSION = "v1_02_22_2026"

# ---------- helpers ----------
def _pct_change(s: pd.Series, periods: int = 1) -> pd.Series:
    return s.pct_change(periods=periods)


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        if isinstance(x, (np.floating, float, int)):
            return float(x)
        return float(x)
    except Exception:
        return None


def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    ma = s.rolling(window).mean()
    sd = s.rolling(window).std(ddof=0)
    z = (s - ma) / sd.replace(0, np.nan)
    return z


def _leadership_top3(sector_rets: Dict[str, float]) -> List[Tuple[str, float]]:
    items = [(k, v) for k, v in sector_rets.items() if v is not None]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:3]


def _sectors_green(sector_rets: Dict[str, float]) -> int:
    return int(sum(1 for _, v in sector_rets.items() if v is not None and v > 0))


def _dispersion(sector_rets: Dict[str, float]) -> Optional[float]:
    vals = [v for v in sector_rets.values() if v is not None]
    if len(vals) < 3:
        return None
    return float(np.std(vals, ddof=0))


def _clv(high: float, low: float, close: float) -> Optional[float]:
    # Close Location Value: ( (Close-Low) - (High-Close) ) / (High-Low)
    denom = (high - low)
    if denom == 0:
        return None
    return float(((close - low) - (high - close)) / denom)


def _range_pct(high: float, low: float, close: float) -> Optional[float]:
    if close == 0:
        return None
    return float(((high - low) / close))


# ---------- core: build historical features and score ----------
def build_daily_feature_frame(
    start: str,
    end: str,
    cross_assets: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    vix_window: int = 20,
    vol_window: int = 20,
    cache_dir: str = "data/cache/backtest",
    force_download: bool = False,
) -> pd.DataFrame:
    """
    Creates a daily feature frame with everything needed to score MarketState historically.
    Uses daily bars (1d) for robustness.

    Returns a DataFrame indexed by date with columns:
      - raw features (returns, vix z, rsp-spy, clv, range, volume z, etc.)
      - plus forward returns (for later backtests)
    """
    cross_assets = cross_assets or DEFAULT_CROSS_ASSET
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

    # Core daily series
    spy_close = panel.field("SPY", "Close")
    spy_open = panel.field("SPY", "Open")
    spy_high = panel.field("SPY", "High")
    spy_low = panel.field("SPY", "Low")
    spy_vol = panel.field("SPY", "Volume")

    # Cross-asset returns (1D)
    cross_ret_1d = {}
    for t in cross_assets:
        if panel.has(t, "Close"):
            cross_ret_1d[t] = _pct_change(panel.field(t, "Close"), 1)
    cross_ret_5d = {}
    cross_ret_21d = {}
    for t in cross_assets:
        if panel.has(t, "Close"):
            close = panel.field(t, "Close")
            cross_ret_5d[t] = _pct_change(close, 5)
            cross_ret_21d[t] = _pct_change(close, 21)
    # Sector returns (1D)
    sector_ret_1d = {t: _pct_change(panel.field(t, "Close"), 1) for t in sectors if panel.has(t, "Close")}

    # VIX z-score (20D) if ^VIX present
    vix_level = panel.field("^VIX", "Close") if panel.has("^VIX", "Close") else pd.Series(dtype=float)
    vix_z_20d = _rolling_zscore(vix_level, vix_window) if not vix_level.empty else pd.Series(dtype=float)
    vix_change_pct_1d = _pct_change(vix_level, 1) if not vix_level.empty else pd.Series(dtype=float)

    # RSP - SPY breadth proxy
    rsp_minus_spy = None
    if panel.has("RSP", "Close"):
        rsp_close = panel.field("RSP", "Close")
        rsp_minus_spy = (_pct_change(rsp_close, 1) - _pct_change(spy_close, 1))

    # Volume features
    spy_vol_z = _rolling_zscore(spy_vol.astype(float), vol_window)
    spy_vol_ma = spy_vol.rolling(vol_window).mean()
    spy_vol_vs_20d_pct = (spy_vol / spy_vol_ma - 1.0)

    # Tape features
    clv = pd.Series(index=spy_close.index, dtype=float)
    rng = pd.Series(index=spy_close.index, dtype=float)
    for idx in spy_close.index:
        try:
            clv.loc[idx] = _clv(float(spy_high.loc[idx]), float(spy_low.loc[idx]), float(spy_close.loc[idx]))
            rng.loc[idx] = _range_pct(float(spy_high.loc[idx]), float(spy_low.loc[idx]), float(spy_close.loc[idx]))
        except Exception:
            continue

    # Sector breadth/dispersion
    sec_df = pd.DataFrame({k: v for k, v in sector_ret_1d.items()})
    dispersion = sec_df.std(axis=1, ddof=0)
    sectors_green = (sec_df > 0).sum(axis=1)

    # Build feature frame
    out = pd.DataFrame(index=spy_close.index)
    out["spy_ret_1d"] = _pct_change(spy_close, 1)
    out["spy_open"] = spy_open
    out["spy_close"] = spy_close
    out["spy_prev_close"] = spy_close.shift(1)
    out["spy_high"] = spy_high
    out["spy_low"] = spy_low

    out["spy_clv"] = clv
    out["spy_range_pct"] = rng

    out["spy_vol"] = spy_vol
    out["spy_vol_vs_20d_pct"] = spy_vol_vs_20d_pct
    out["spy_vol_z_20d"] = spy_vol_z

    if not vix_level.empty:
        out["vix_level"] = vix_level
        out["vix_z_20d"] = vix_z_20d
        out["vix_change_pct_1d"] = vix_change_pct_1d

    if rsp_minus_spy is not None:
        out["rsp_minus_spy"] = rsp_minus_spy

    # Add cross-asset returns columns
    for t, s in cross_ret_1d.items():
        out[f"ret_{t}_1d"] = s
    for t, s in cross_ret_5d.items():
        out[f"ret_{t}_5d"] = s
    for t, s in cross_ret_21d.items():
        out[f"ret_{t}_21d"] = s

    # Add sector return columns
    for t, s in sector_ret_1d.items():
        out[f"ret_{t}_1d"] = s

    out["dispersion"] = dispersion
    out["sectors_green"] = sectors_green

    # Forward returns for evaluation
    out["fwd_ret_oc_1d"] = (spy_close / spy_open - 1.0)  # open->close same day
    out["fwd_ret_cc_1d"] = (spy_close.shift(-1) / spy_close - 1.0)  # close->next close

    for n in (3, 5, 10, 21, 63, 126, 252):
        out[f"fwd_ret_cc_{n}d"] = (spy_close.shift(-n) / spy_close - 1.0)

    h_next5 = spy_high.shift(-1).rolling(5).max()
    l_next5 = spy_low.shift(-1).rolling(5).min()

    out["fwd_5d_max_upside_pct"] = (h_next5 / spy_close - 1.0)
    out["fwd_5d_max_drawdown_pct"] = (l_next5 / spy_close - 1.0)

    out["tail_loss_3d_1p5"] = (out["fwd_ret_cc_3d"] < -.015).astype("Int64")
    out["tail_loss_5d_2p5"] = (out["fwd_ret_cc_5d"] < -.025).astype("Int64")
    out["big_win_3d_1p5"] = (out["fwd_ret_cc_3d"] > .015).astype("Int64")
    out["fwd_ret_cc_1m"] = out["fwd_ret_cc_21d"]
    out["fwd_ret_cc_3m"] = out["fwd_ret_cc_63d"]
    out["fwd_ret_cc_6m"] = out["fwd_ret_cc_126d"]
    out["fwd_ret_cc_1y"] = out["fwd_ret_cc_252d"]

    out["feature_version"] = FEATURE_VERSION
    
    # Clean
    out.sort_index(inplace=True)
    return out


def score_history_both_signal_times(
    features: pd.DataFrame,
    sector_tickers: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Produces scored history for BOTH:
      - signal_time='open': signal for date t uses info up to t-1 close
      - signal_time='close': signal for date t uses info up to t close (trade next open)
    Returns a single DataFrame with MultiIndex columns: (signal_time, field)
    """
    sector_tickers = sector_tickers or DEFAULT_SECTOR_TICKERS

    # We will create MarketState objects per date and reuse your existing score_market_state().
    # Keep required fields consistent; fill what you have; others as None.

    def build_state_from_row(dt: pd.Timestamp, row: pd.Series) -> MarketState:
        # Cross-asset returns dict (using 1D)
        cross_asset_returns: Dict[str, float] = {}
        for col in row.index:
            if col.startswith("ret_") and (col.endswith("_1d") or col.endswith("_5d") or col.endswith("_21d")):
                base = col[len("ret_"):]
                ticker, horizon = base.rsplit("_", 1)  # "HYG", "5d"
                v = row.get(col)
                if pd.notna(v):
                    cross_asset_returns[f"{ticker}_{horizon}"] = float(v)

        # Sector returns dict (just the sector ETF subset)
        sector_returns: Dict[str, float] = {}
        for t in sector_tickers:
            c = f"ret_{t}_1d"
            if c in row.index:
                v = row.get(c)
                if pd.notna(v):
                    sector_returns[t] = float(v)

        leadership_top3 = _leadership_top3(sector_returns)
        sectors_green = int(row.get("sectors_green")) if pd.notna(row.get("sectors_green")) else 0
        dispersion = _safe_float(row.get("dispersion"))
        spy_clv = _safe_float(row.get("spy_clv"))
        spy_range_pct = _safe_float(row.get("spy_range_pct"))

        # Volume confirmation: sign(SPY ret) * vol_z
        spy_ret = _safe_float(row.get("spy_ret_1d"))
        vol_z = _safe_float(row.get("spy_vol_z_20d"))
        volume_confirmation = None
        if spy_ret is not None and vol_z is not None:
            sign = 1.0 if spy_ret > 0 else (-1.0 if spy_ret < 0 else 0.0)
            volume_confirmation = sign * vol_z

        # VWAP and intraday fields not available in daily history v1 (set None)
        # VIX fields if available
        vix_level = _safe_float(row.get("vix_level")) if "vix_level" in row.index else None
        vix_z_20d = _safe_float(row.get("vix_z_20d")) if "vix_z_20d" in row.index else None
        vix_change_pct_1d = _safe_float(row.get("vix_change_pct_1d")) if "vix_change_pct_1d" in row.index else None

        rsp_minus_spy = _safe_float(row.get("rsp_minus_spy")) if "rsp_minus_spy" in row.index else None

        # Required fields: depends on your MarketState dataclass ordering.
        # Adjust names if yours differ.
        state = MarketState(
            asof_utc=str(dt),
            horizon="1D",
            cross_asset_returns=cross_asset_returns,
            sector_returns=sector_returns,
            leadership_top3=leadership_top3,
            sectors_green=sectors_green,
            dispersion=dispersion,
            spy_clv=spy_clv,
            spy_range_pct=spy_range_pct,
        )

        # Attach optional attributes (only if your MarketState supports these; otherwise remove)
        # If your dataclass already has these fields, replace(...) will work.
        try:
            state = replace(
                state,
                vix_level=vix_level,
                vix_z_20d=vix_z_20d,
                vix_change_pct_1d=vix_change_pct_1d,
                rsp_minus_spy=rsp_minus_spy,
                spy_vol=_safe_float(row.get("spy_vol")),
                spy_vol_vs_20d_pct=_safe_float(row.get("spy_vol_vs_20d_pct")),
                spy_vol_z_20d=vol_z,
                volume_confirmation=volume_confirmation,
                spy_last_price=_safe_float(row.get("spy_close")),
                spy_prev_close=_safe_float(row.get("spy_prev_close")),
                spy_above_prev_close=(
                    bool(row.get("spy_close") > row.get("spy_prev_close"))
                    if pd.notna(row.get("spy_close")) and pd.notna(row.get("spy_prev_close")) 
                    else None),
                spy_vwap=None,
                spy_above_vwap=None,
                market_session_date=dt.strftime("%Y-%m-%d"),
            )
        except TypeError:
            # Your MarketState may not have these fields yet; that’s fine for v1 scoring.
            pass

        return state

    def score_for_index(frame: pd.DataFrame, ix: pd.DatetimeIndex) -> pd.DataFrame:
        rows = []
        for dt in ix:
            row = frame.loc[dt]
            st = build_state_from_row(dt, row)
            st_scored = score_market_state(st)
            base = {
                "score_total": getattr(st_scored, "score_total", None),
                "confidence": getattr(st_scored, "confidence", None),
                "environment": getattr(st_scored, "environment", None),
                "volume_confirmation": getattr(st_scored, "volume_confirmation", None),
            }

            components = getattr(st_scored, "score_components", None)
            if isinstance(components, dict):
                for k, v in components.items():
                    base[f"comp__{k}"] = v

            rows.append(base)

        return pd.DataFrame(rows, index=ix)

    # --- signal_time = open ---
    # Signal for date t uses info up to t-1 close -> use shifted feature rows
    
    feat_open = features.shift(1)
    scored_open = score_for_index(feat_open, feat_open.index)
    scored_open = scored_open.reindex(features.index)
    scored_open["signal_time"] = "open"

    scored_close = score_for_index(features, features.index)
    scored_close = scored_close.reindex(features.index)
    scored_close["signal_time"] = "close"

    def add_fwd(scored_df: pd.DataFrame, label: str, feature_frame: pd.DataFrame) -> pd.DataFrame:
        out = scored_df.copy()
        fwd_cols = [
            c
            for c in feature_frame.columns
            if c.startswith("fwd_") or c.startswith("tail_") or c.startswith("big_")
        ]
        for c in fwd_cols:
            out[c] = feature_frame[c]

        out.columns = pd.MultiIndex.from_product([[label], out.columns])
        return out

    wide = pd.concat(
        [
            add_fwd(scored_open, "open", features), 
            add_fwd(scored_close, "close", features),
        ], 
        axis=1,
    )
    return wide

def build_research_frame(
    start: str,
    end: str,
    cross_assets: Optional[List[str]] = None,
    sectors: Optional[List[str]] = None,
    vix_window: int = 20,
    vol_window: int = 20,
    cache_dir: str = "data/cache/backtest",
    force_download: bool = False,
) -> pd.DataFrame:
    """
    Builds the research dataset:
      - raw features (one row per date)
      - scoring outputs for open + close (two rows per date, via signal_time)
      - forward returns + tail metrics
    Returns LONG format (one row per date per signal_time).
    """

    feats = build_daily_feature_frame(
        start=start,
        end=end,
        cross_assets=cross_assets,
        sectors=sectors,
        vix_window=vix_window,
        vol_window=vol_window,
        cache_dir=cache_dir,
        force_download=force_download,
    )

    print("DEBUG feats date range:", feats.index.min(), "→", feats.index.max(), "rows:", len(feats))

    scored_wide = score_history_both_signal_times(
        feats,
        sector_tickers=sectors,
    )
    print("DEBUG scored_wide index range:", scored_wide.index.min(), "→", scored_wide.index.max(), "rows:", len(scored_wide))

    # wide (MultiIndex cols: open/close) -> long rows
    parts = []
    for signal_time in ["open", "close"]:
        s = scored_wide[signal_time].copy()
        s["signal_time"] = signal_time
        parts.append(s)

    scored_long = pd.concat(parts, axis=0)
    scored_long.index.name = "date"
    scored_long = scored_long.reset_index()

    # raw features (same for open/close); merge on date
    feats2 = feats.copy()
    feats2.index.name = "date"
    feats2 = feats2.reset_index()

    label_cols = [c for c in feats2.columns if c.startswith("fwd_") or c.startswith("tail_") or c.startswith("big_")]
    feats2 = feats2.drop(columns=label_cols)

    df = scored_long.merge(feats2, on="date", how="left")
    df.sort_values(["date", "signal_time"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    print("DEBUG final df date range:", df["date"].min(), "→", df["date"].max(), "rows:", len(df))

    return df