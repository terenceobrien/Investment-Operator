from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# --- Universes ---
SECTOR_ETFS: Dict[str, str] = {
    "XLB": "Materials",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLI": "Industrials",
    "XLK": "Technology",
    "XLP": "Staples",
    "XLU": "Utilities",
    "XLV": "Health Care",
    "XLY": "Discretionary",
    "XLC": "Comm Services",
    "XLRE": "Real Estate",
}

CROSS_ASSET: Dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "DIA": "Dow",
    "TLT": "10-20Y Treasuries",
    "HYG": "High Yield Credit",
    "GLD": "Gold",
    "USO": "Oil",
    "BTC-USD": "Bitcoin",
    "^VIX": "VIX",
    "RSP": "S&P Equal Weight"
    # Optional proxies you can add later:
    # "UUP": "US Dollar",
}


HORIZONS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
    "YTD": "YTD",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except Exception:
        return None


def _compute_return(series: pd.Series, horizon) -> Optional[float]:
    s = series.dropna()
    if len(s) < 2:
        return None

    if horizon == "YTD":
        year_start = pd.Timestamp(datetime.now().year, 1, 1)
        ytd = s[s.index >= year_start]
        if ytd.empty:
            return None
        start = ytd.iloc[0]
        end = ytd.iloc[-1]
        return _safe_float((end / start - 1.0) * 100.0)

    n = int(horizon)
    if len(s) <= n:
        return None
    start = s.iloc[-(n + 1)]
    end = s.iloc[-1]
    return _safe_float((end / start - 1.0) * 100.0)


def _close_location_value(high: float, low: float, close: float) -> Optional[float]:
    # CLV in [-1, 1], close near high => +1, near low => -1
    rng = high - low
    if rng <= 0:
        return None
    return _safe_float(((close - low) - (high - close)) / rng)


def _download_closes(tickers: List[str], period: str = "2y", auto_adjust: bool = True) -> pd.DataFrame:
    import yfinance as yf
    import time
    
    for attempt in range(3):
        try:
            data = yf.download(
                tickers,
                period=period,
                interval="1d",
                group_by="ticker",
                auto_adjust=auto_adjust,
                progress=False,
                threads=False,  # Change to False — threading causes issues on some servers
            )
            if data is None or len(data) == 0:
                time.sleep(2)
                continue
                
            if isinstance(data.columns, pd.MultiIndex):
                closes = pd.DataFrame({
                    t: data[t]["Close"] 
                    for t in tickers 
                    if t in data.columns.get_level_values(0)
                })
            else:
                closes = data[["Close"]].rename(columns={"Close": tickers[0]})
                
            closes = closes.dropna(how="all")
            
            # If we got less than half the tickers, retry
            if len(closes.columns) < len(tickers) / 2:
                time.sleep(2)
                continue
                
            return closes
            
        except Exception as e:
            print(f"yfinance download attempt {attempt + 1} failed: {e}")
            time.sleep(2)
    
    return pd.DataFrame()


def _download_ohlc(ticker: str, period: str = "10d", auto_adjust: bool = True) -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=auto_adjust,
        progress=False,
        threads=True,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    return df.dropna()

def _download_intraday(ticker: str, period: str = "1d", interval: str = "5m") -> pd.DataFrame:
    import yfinance as yf
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=False,  # VWAP should use raw prices/volume
        progress=False,
        threads=True,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    return df.dropna()

@dataclass
class MarketState:
    asof_utc: str
    horizon: str
    
    cross_asset_returns: Dict[str, float]         # ticker -> %
    sector_returns: Dict[str, float]              # ticker -> %

    leadership_top3: List[Tuple[str, float]]      # [(sector_name, return)]
    sectors_green: int                            # out of 11
    dispersion: Optional[float]                   # stddev of sector returns

    spy_clv: Optional[float]                      # close location value
    spy_range_pct: Optional[float]                # (high-low)/close * 100

    market_session_date: str | None = None

    spy_vol: Optional[float] = None               # Volume features (v1)
    spy_vol_vs_20d_pct: Optional[float] = None     # (Vol / Vol_MA20 - 1) * 100
    spy_vol_z_20d: Optional[float] = None
    
    vix_level: Optional[float] = None
    vix_z_20d: Optional[float] = None
    vix_change_pct_1d: Optional[float] = None
    rsp_minus_spy: Optional[float] = None           # (Vol - MA20) / STD20

        # --- Intraday structure (v2.5) ---
    spy_last_price: Optional[float] = None
    spy_prev_close: Optional[float] = None
    spy_above_prev_close: Optional[bool] = None

    spy_vwap: Optional[float] = None
    spy_above_vwap: Optional[bool] = None

    volume_confirmation: Optional[float] = None    # sign(SPY return) * vol_z

    confidence: Optional[float] = None

    # scoring outputs (filled by scorer)
    score_total: Optional[float] = None
    score_components: Optional[Dict[str, float]] = None
    environment: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict) -> "MarketState":
        return MarketState(**d)


def build_market_state(
    horizon: str = "1D",
    auto_adjust: bool = True,
    period: str = "2y",
) -> MarketState:
    if horizon not in HORIZONS:
        raise ValueError(f"Unsupported horizon: {horizon}. Choose from {list(HORIZONS.keys())}")

    h = HORIZONS[horizon]
    asof = _utc_now_iso()

    cross_tickers = list(CROSS_ASSET.keys())
    sector_tickers = list(SECTOR_ETFS.keys())

    cross_prices = _download_closes(cross_tickers, period=period, auto_adjust=auto_adjust)
    market_session_date = None
    if "SPY" in cross_prices.columns and not cross_prices["SPY"].dropna().empty:
        market_session_date = cross_prices["SPY"].dropna().index[-1].strftime("%Y-%m-%d")

    sector_prices = _download_closes(sector_tickers, period=period, auto_adjust=auto_adjust)

    cross_rets: Dict[str, float] = {}
    for t in cross_tickers:
        if t in cross_prices.columns:
            r = _compute_return(cross_prices[t], h)
            if r is not None:
                cross_rets[t] = r

    sector_rets: Dict[str, float] = {}
    for t in sector_tickers:
        if t in sector_prices.columns:
            r = _compute_return(sector_prices[t], h)
            if r is not None:
                sector_rets[t] = r

        # --- VIX metrics ---
    vix_level = None
    vix_z_20d = None
    vix_change_pct_1d = None

    if "^VIX" in cross_prices.columns:
        vix_series = cross_prices["^VIX"].dropna()
        if len(vix_series) >= 21:
            vix_level = _safe_float(float(vix_series.iloc[-1]))
            vix_prev = _safe_float(float(vix_series.iloc[-2]))

            # 1D % change
            if vix_level is not None and vix_prev is not None and vix_prev != 0:
                vix_change_pct_1d = _safe_float((vix_level / vix_prev - 1.0) * 100.0)

            # 20D z-score
            vix_ma20 = float(vix_series.rolling(20).mean().iloc[-1])
            vix_sd20 = float(vix_series.rolling(20).std(ddof=0).iloc[-1])
            if vix_sd20 > 0:
                vix_z_20d = _safe_float((float(vix_series.iloc[-1]) - vix_ma20) / vix_sd20)

                    # --- SPY prev close (from daily series) ---
    spy_prev_close = None
    if "SPY" in cross_prices.columns:
        spy_daily = cross_prices["SPY"].dropna()
        if len(spy_daily) >= 2:
            spy_prev_close = _safe_float(float(spy_daily.iloc[-2]))

    # --- Intraday bars for VWAP + last price ---
    spy_last_price = None
    spy_vwap = None
    spy_above_prev_close = None
    spy_above_vwap = None

    spy_intraday = _download_intraday("SPY", period="1d", interval="5m")

    if not spy_intraday.empty and "Volume" in spy_intraday.columns:
        # last traded price proxy = last bar close
        close_col = spy_intraday["Close"]
        if isinstance(close_col, pd.DataFrame):
            close_col = close_col.iloc[:, 0]
        spy_last_price = _safe_float(float(close_col.iloc[-1]))
        
        # VWAP (cumulative, intraday): sum(price*vol)/sum(vol)
        vol_col = spy_intraday["Volume"]
        if isinstance(vol_col, pd.DataFrame):
            vol_col = vol_col.iloc[:, 0]
        vol = vol_col.astype(float)

        px_col = spy_intraday["Close"]
        if isinstance(px_col, pd.DataFrame):
            px_col = px_col.iloc[:, 0]
        px = px_col.astype(float)

        vol_sum = float(vol.sum())
        if vol_sum > 0:
            spy_vwap = _safe_float(float((px * vol).sum() / vol_sum))

        if spy_last_price is not None and spy_prev_close is not None:
            spy_above_prev_close = bool(spy_last_price > spy_prev_close)

        if spy_last_price is not None and spy_vwap is not None:
            spy_above_vwap = bool(spy_last_price > spy_vwap)


    # Leadership + breadth + dispersion
    sector_name_rets = [(SECTOR_ETFS[t], sector_rets.get(t, np.nan)) for t in sector_tickers]
    sector_name_rets_clean = [(n, v) for (n, v) in sector_name_rets if v is not None and not np.isnan(v)]
    sector_name_rets_clean.sort(key=lambda x: x[1], reverse=True)
    leadership_top3 = sector_name_rets_clean[:3]

    sectors_green = sum(1 for _, v in sector_name_rets_clean if v > 0)

    dispersion = None
    if len(sector_name_rets_clean) >= 5:
        dispersion = _safe_float(float(np.std([v for _, v in sector_name_rets_clean], ddof=0)))

    # SPY tape metrics (simple, daily)
    spy_ohlc = _download_ohlc("SPY", period="6mo", auto_adjust=auto_adjust)
    spy_clv = None
    spy_range_pct = None
    spy_vol = None
    spy_vol_vs_20d_pct = None
    spy_vol_z_20d = None
    volume_confirmation = None

    if (spy_ohlc is not None) and (not spy_ohlc.empty) and ("Volume" in spy_ohlc.columns):
        vol_raw = spy_ohlc["Volume"]

        # If Volume comes back as a DataFrame (rare but possible), take first column
        if isinstance(vol_raw, pd.DataFrame):
            vol = vol_raw.iloc[:, 0].dropna()
        else:
            vol = vol_raw.dropna()

        if len(vol) >= 25:
            spy_vol = _safe_float(float(vol.iloc[-1]))

            ma20 = vol.rolling(20).mean()
            sd20 = vol.rolling(20).std(ddof=0)

            ma_last = float(ma20.iloc[-1])
            sd_last = float(sd20.iloc[-1])
            last = float(vol.iloc[-1])

            if ma_last != 0:
                spy_vol_vs_20d_pct = _safe_float(((last / ma_last) - 1.0) * 100.0)

            if sd_last != 0:
                spy_vol_z_20d = _safe_float((last - ma_last) / sd_last)

            # confirmation uses SPY move (your selected horizon return)
            spy_ret = cross_rets.get("SPY")
            if spy_ret is not None and spy_vol_z_20d is not None:
                sign = 1.0 if spy_ret > 0 else (-1.0 if spy_ret < 0 else 0.0)
                volume_confirmation = _safe_float(sign * float(spy_vol_z_20d))

    if not spy_ohlc.empty:
        last = spy_ohlc.iloc[-1]
        high = float(last["High"]) if not isinstance(last["High"], pd.Series) else float(last["High"].iloc[0])
        low = float(last["Low"]) if not isinstance(last["Low"], pd.Series) else float(last["Low"].iloc[0])
        close = float(last["Close"]) if not isinstance(last["Close"], pd.Series) else float(last["Close"].iloc[0])
        spy_clv = _close_location_value(high, low, close)
        if close != 0:
            spy_range_pct = _safe_float(((high - low) / close) * 100.0)

    return MarketState(
        asof_utc=asof,
        horizon=horizon,
        cross_asset_returns=cross_rets,
        sector_returns=sector_rets,
        leadership_top3=leadership_top3,
        sectors_green=sectors_green,
        dispersion=dispersion,
        spy_clv=spy_clv,
        spy_range_pct=spy_range_pct,
        spy_vol=spy_vol,
        spy_vol_vs_20d_pct=spy_vol_vs_20d_pct,
        spy_vol_z_20d=spy_vol_z_20d,
        volume_confirmation=volume_confirmation,
        spy_last_price=spy_last_price,
        spy_prev_close=spy_prev_close,
        spy_above_prev_close=spy_above_prev_close,
        spy_vwap=spy_vwap,
        spy_above_vwap=spy_above_vwap,
        market_session_date=market_session_date,
        vix_level=vix_level,
        vix_z_20d=vix_z_20d,
        vix_change_pct_1d=vix_change_pct_1d,
    )


def snapshot_path(base_dir: str | Path, date_str: str) -> Path:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    return base / f"market_state_{date_str}.json"


def save_snapshot(state: MarketState, base_dir: str | Path, date_str: Optional[str] = None) -> Path:
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    path = snapshot_path(base_dir, date_str)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    return path


def load_snapshot(base_dir: str | Path, date_str: str) -> Optional[MarketState]:
    path = snapshot_path(base_dir, date_str)
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    return MarketState.from_dict(d)

def summarize_state(state: MarketState) -> dict:
    return {
        "score": state.score_total,
        "environment": state.environment,
        "risk_on": state.score_components.get("risk_on"),
        "trend_strength": state.score_components.get("trend_strength"),
        "vol_mood": state.score_components.get("vol_mood"),
        "participation": state.score_components.get("participation"),
        "leadership_clarity": state.score_components.get("leadership_clarity"),
        "volume_confirmation": state.volume_confirmation,
    }

