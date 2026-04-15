"""
src/state/regime_state.py

Two public functions replacing the old monolithic build_market_state():

  1. build_regime_state()   — runs once at close, saves snapshot
  2. build_intraday_tape()  — runs every 5min, real-time only, never changes score

The regime score is stable all day. The intraday tape shows live conditions.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


SNAPSHOT_DIR = Path(os.environ.get("SNAPSHOT_DIR", "data/snapshots"))


# ── Regime State dataclass ────────────────────────────────────────────────────

@dataclass
class RegimeState:
    """
    Stable daily regime reading. Computed once at close.
    Never changes intraday.
    """
    asof_date: str = ""
    asof_utc: str = ""
    signal_time: str = "close"

    # Five-layer scores
    layer_monetary:    Optional[float] = None
    layer_credit:      Optional[float] = None
    layer_volatility:  Optional[float] = None
    layer_breadth:     Optional[float] = None
    layer_positioning: Optional[float] = None

    # Layer details
    layer_signals: Dict[str, List[str]] = field(default_factory=dict)
    layer_statuses: Dict[str, str] = field(default_factory=dict)
    layer_data_quality: Dict[str, float] = field(default_factory=dict)

    # Composite
    score_total: Optional[float] = None
    score_prior: Optional[float] = None
    score_delta: Optional[float] = None
    environment: str = ""
    environment_drivers: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    layer_agreement: Optional[float] = None
    horizon: str = "default"

    # Key raw inputs (for display)
    vix_level: Optional[float] = None
    vix_term_slope: Optional[float] = None
    hy_spread_level: Optional[float] = None
    net_liquidity_z: Optional[float] = None
    pct_above_200d: Optional[float] = None
    new_highs_minus_lows_z: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def save_snapshot(self, directory: Path = SNAPSHOT_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"regime_state_{self.asof_date}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    @classmethod
    def load_snapshot(cls, date_str: str, directory: Path = SNAPSHOT_DIR) -> Optional["RegimeState"]:
        path = directory / f"regime_state_{date_str}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Intraday Tape dataclass ───────────────────────────────────────────────────

@dataclass
class IntradayTape:
    """
    Live intraday readings. Updates every 5 minutes.
    Never affects the regime score.
    """
    asof_utc: str = ""
    market_open: bool = False

    # SPY tape
    spy_last: Optional[float] = None
    spy_vwap: Optional[float] = None
    spy_above_vwap: Optional[bool] = None
    spy_vs_open_pct: Optional[float] = None
    spy_range_pct_intraday: Optional[float] = None
    spy_clv_intraday: Optional[float] = None

    # Real-time breadth
    sectors_green_now: Optional[int] = None
    sectors_leading: List[str] = field(default_factory=list)
    sectors_lagging: List[str] = field(default_factory=list)

    # Vol snapshot
    vix_now: Optional[float] = None
    vix_vs_close: Optional[float] = None  # % change from yesterday's close

    # Cross-asset pulse
    cross_asset_now: Dict[str, float] = field(default_factory=dict)

    # Tape character (rule-based, not scored)
    tape_character: str = ""   # "trending_up" | "trending_down" | "choppy" | "range_bound"
    tape_notes: List[str] = field(default_factory=list)

    # Consistency with regime
    consistent_with_regime: Optional[bool] = None
    consistency_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ── Build regime state (close only) ──────────────────────────────────────────

def build_regime_state(
    horizon: str = "default",
    save: bool = True,
) -> RegimeState:
    """
    Build and optionally save the daily regime state.
    Call this once after market close (4:30pm ET or later).

    Uses the new five-layer scoring system from regime_layers.py
    and fetches inputs from regime_data.py.
    """
    from src.state.regime_data import fetch_regime_inputs
    from src.state.regime_layers import score_all_layers

    # First: get current market state to extract sectors_green
    # (reuses your existing market_state.py build for price data)
    sectors_green = None
    try:
        from src.state.market_state import build_market_state
        ms = build_market_state()
        sectors_green = ms.sectors_green
    except Exception as e:
        print(f"Could not get sectors_green from market_state: {e}")

    # Fetch all regime inputs
    raw = fetch_regime_inputs(sectors_green=sectors_green)

    # Score all five layers
    scores = score_all_layers(
        # Monetary
        net_liquidity_z=raw.net_liquidity_z,
        nfci_inverted=raw.nfci_inverted,
        m2_growth_yoy=raw.m2_growth_yoy,
        fci_z=raw.fci_z,
        # Credit
        hy_spread_level=raw.hy_spread_level,
        hy_spread_z=raw.hy_spread_z,
        hy_spread_chg_4w=raw.hy_spread_chg_4w,
        ig_spread_level=raw.ig_spread_level,
        ig_spread_z=raw.ig_spread_z,
        hyg_tlt_ratio_z=raw.hyg_tlt_ratio_z,
        # Volatility
        vix_level=raw.vix_level,
        vix_z_20d=raw.vix_z_20d,
        vix_term_slope=raw.vix_term_slope,
        vvix_level=raw.vvix_level,
        vvix_z=raw.vvix_z,
        put_call_ratio=raw.put_call_ratio,
        skew_index=raw.skew_index,
        # Breadth
        pct_above_200d=raw.pct_above_200d,
        new_highs_minus_lows_z=raw.new_highs_minus_lows_z,
        sectors_green=raw.sectors_green,
        rsp_vs_spy_z=raw.rsp_vs_spy_z,
        adl_slope=raw.adl_slope,
        # Positioning
        dealer_gamma_z=raw.dealer_gamma_z,
        put_call_5d_ma=raw.put_call_5d_ma,
        aaii_bull_minus_bear=raw.aaii_bull_minus_bear,
        cot_net_large_spec_z=raw.cot_net_large_spec_z,
        equity_etf_flow_z=raw.equity_etf_flow_z,
        horizon=horizon,
    )

    now = datetime.utcnow()
    asof_date = raw.asof_date or now.strftime("%Y-%m-%d")

    # Load prior snapshot for score delta
    prior_score = None
    try:
        from datetime import date, timedelta
        yesterday = (date.fromisoformat(asof_date) - timedelta(days=1)).isoformat()
        prior = RegimeState.load_snapshot(yesterday)
        if prior is None:
            # Try going back further (weekends)
            for days_back in range(2, 6):
                d = (date.fromisoformat(asof_date) - timedelta(days=days_back)).isoformat()
                prior = RegimeState.load_snapshot(d)
                if prior:
                    break
        if prior and prior.score_total:
            prior_score = prior.score_total
    except Exception:
        pass

    state = RegimeState(
        asof_date=asof_date,
        asof_utc=now.isoformat(),
        signal_time="close",
        horizon=horizon,

        # Layer scores
        layer_monetary=scores.monetary.score,
        layer_credit=scores.credit.score,
        layer_volatility=scores.volatility.score,
        layer_breadth=scores.breadth.score,
        layer_positioning=scores.positioning.score,

        # Layer details
        layer_signals={
            "monetary":    scores.monetary.signals,
            "credit":      scores.credit.signals,
            "volatility":  scores.volatility.signals,
            "breadth":     scores.breadth.signals,
            "positioning": scores.positioning.signals,
        },
        layer_statuses={
            "monetary":    scores.monetary.status,
            "credit":      scores.credit.status,
            "volatility":  scores.volatility.status,
            "breadth":     scores.breadth.status,
            "positioning": scores.positioning.status,
        },
        layer_data_quality={
            "monetary":    scores.monetary.data_quality,
            "credit":      scores.credit.data_quality,
            "volatility":  scores.volatility.data_quality,
            "breadth":     scores.breadth.data_quality,
            "positioning": scores.positioning.data_quality,
        },

        # Composite
        score_total=scores.composite,
        score_prior=prior_score,
        score_delta=round(scores.composite - prior_score, 2) if prior_score else None,
        environment=scores.environment,
        environment_drivers=scores.environment_drivers,
        confidence=scores.confidence,
        layer_agreement=scores.layer_agreement,

        # Key raw inputs for display
        vix_level=raw.vix_level,
        vix_term_slope=raw.vix_term_slope,
        hy_spread_level=raw.hy_spread_level,
        net_liquidity_z=raw.net_liquidity_z,
        pct_above_200d=raw.pct_above_200d,
        new_highs_minus_lows_z=raw.new_highs_minus_lows_z,
    )

    if save:
        path = state.save_snapshot()
        print(f"Regime state saved: {path}")

    return state


# ── Build intraday tape (live, no scoring) ────────────────────────────────────

def build_intraday_tape(regime_state: Optional[RegimeState] = None) -> IntradayTape:
    """
    Build real-time intraday tape reading.
    Updates every 5 minutes during market hours.
    NEVER modifies the regime score.

    Args:
        regime_state: Pass today's regime state for consistency check
    """
    import yfinance as yf

    tape = IntradayTape(asof_utc=datetime.utcnow().isoformat())

    SECTOR_TICKERS = {
        "XLK": "Technology", "XLF": "Financials", "XLV": "Health Care",
        "XLY": "Discretionary", "XLP": "Staples", "XLE": "Energy",
        "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities",
        "XLRE": "Real Estate", "XLC": "Comm Svcs",
    }

    CROSS_ASSET = ["SPY", "QQQ", "IWM", "TLT", "HYG", "GLD", "^VIX"]

    try:
        # ── SPY intraday ──
        spy_data = yf.download("SPY", period="1d", interval="5m",
                               progress=False, auto_adjust=True, threads=False)
        if not spy_data.empty:
            tape.market_open = True
            closes = spy_data["Close"].squeeze().dropna()
            highs  = spy_data["High"].squeeze().dropna()
            lows   = spy_data["Low"].squeeze().dropna()
            vols   = spy_data["Volume"].squeeze().dropna()

            tape.spy_last = float(closes.iloc[-1])

            # VWAP = sum(price * vol) / sum(vol)
            if not vols.empty:
                typical = ((highs + lows + closes) / 3).values
                v = vols.values
                tape.spy_vwap = float(np.cumsum(typical * v)[-1] / np.cumsum(v)[-1])
                tape.spy_above_vwap = tape.spy_last > tape.spy_vwap

            # Day open
            if len(closes) > 0:
                open_price = float(spy_data["Open"].squeeze().dropna().iloc[0])
                tape.spy_vs_open_pct = round((tape.spy_last / open_price - 1) * 100, 3)

            # Intraday range
            day_high = float(highs.max())
            day_low  = float(lows.min())
            if day_low > 0:
                tape.spy_range_pct_intraday = round((day_high - day_low) / day_low * 100, 3)

            # CLV (close location value)
            if day_high != day_low:
                tape.spy_clv_intraday = round(
                    (2 * tape.spy_last - day_low - day_high) / (day_high - day_low), 3
                )

        # ── Sector breadth ──
        sector_data = yf.download(
            list(SECTOR_TICKERS.keys()), period="2d", interval="1d",
            progress=False, auto_adjust=True, threads=False,
            group_by="ticker"
        )
        green = 0
        leaders = []
        laggards = []
        sector_rets = {}

        for ticker, name in SECTOR_TICKERS.items():
            try:
                if isinstance(sector_data.columns, pd.MultiIndex):
                    closes = sector_data[ticker]["Close"].dropna()
                else:
                    closes = sector_data["Close"].dropna()
                if len(closes) >= 2:
                    ret = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
                    sector_rets[name] = round(float(ret), 3)
                    if ret > 0:
                        green += 1
            except Exception:
                pass

        tape.sectors_green_now = green
        sorted_sectors = sorted(sector_rets.items(), key=lambda x: x[1], reverse=True)
        tape.sectors_leading = [f"{n} {r:+.2f}%" for n, r in sorted_sectors[:3]]
        tape.sectors_lagging = [f"{n} {r:+.2f}%" for n, r in sorted_sectors[-3:]]

        # ── Cross-asset pulse ──
        ca_data = yf.download(
            CROSS_ASSET, period="2d", interval="1d",
            progress=False, auto_adjust=True, threads=False,
            group_by="ticker"
        )
        for ticker in CROSS_ASSET:
            try:
                if isinstance(ca_data.columns, pd.MultiIndex):
                    closes = ca_data[ticker]["Close"].dropna()
                else:
                    closes = ca_data["Close"].dropna()
                if len(closes) >= 2:
                    ret = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
                    tape.cross_asset_now[ticker] = round(float(ret), 3)
            except Exception:
                pass

        # VIX now
        vix_now = tape.cross_asset_now.get("^VIX")
        if vix_now is not None and regime_state and regime_state.vix_level:
            tape.vix_now = regime_state.vix_level * (1 + vix_now / 100)
            tape.vix_vs_close = round(vix_now, 2)

        # ── Tape character ──
        _classify_tape_character(tape)

        # ── Consistency with regime ──
        if regime_state:
            _check_consistency(tape, regime_state)

    except Exception as e:
        print(f"Intraday tape error: {e}")
        tape.market_open = False

    return tape


# ── Tape character classification ─────────────────────────────────────────────

def _classify_tape_character(tape: IntradayTape) -> None:
    notes = []

    if tape.spy_clv_intraday is not None:
        clv = tape.spy_clv_intraday
        if clv > 0.5 and tape.spy_above_vwap:
            tape.tape_character = "trending_up"
            notes.append("SPY closing near highs, above VWAP")
        elif clv < -0.5 and not tape.spy_above_vwap:
            tape.tape_character = "trending_down"
            notes.append("SPY closing near lows, below VWAP")
        elif tape.spy_range_pct_intraday and tape.spy_range_pct_intraday > 1.5:
            tape.tape_character = "choppy"
            notes.append(f"Wide intraday range ({tape.spy_range_pct_intraday:.2f}%) with no directional close")
        else:
            tape.tape_character = "range_bound"
            notes.append("Tight range, no directional conviction")

    if tape.sectors_green_now is not None:
        if tape.sectors_green_now >= 9:
            notes.append(f"Breadth strong: {tape.sectors_green_now}/11 sectors green")
        elif tape.sectors_green_now <= 2:
            notes.append(f"Breadth weak: only {tape.sectors_green_now}/11 sectors green")

    tape.tape_notes = notes


# ── Consistency check ─────────────────────────────────────────────────────────

def _check_consistency(tape: IntradayTape, regime: RegimeState) -> None:
    """
    Does today's intraday action confirm or conflict with the regime reading?
    """
    env = regime.environment or ""
    char = tape.tape_character

    if "Risk-On" in env or "Trend Day" in env:
        if char == "trending_up":
            tape.consistent_with_regime = True
            tape.consistency_note = "Intraday tape confirming risk-on regime"
        elif char == "trending_down":
            tape.consistent_with_regime = False
            tape.consistency_note = "Warning: intraday tape diverging from risk-on regime"
        else:
            tape.consistent_with_regime = None
            tape.consistency_note = "Inconclusive intraday action vs regime"

    elif "Risk-Off" in env:
        if char == "trending_down":
            tape.consistent_with_regime = True
            tape.consistency_note = "Intraday weakness consistent with risk-off regime"
        elif char == "trending_up":
            tape.consistent_with_regime = False
            tape.consistency_note = "Intraday rally contradicts risk-off regime — watch for reversal"
        else:
            tape.consistent_with_regime = None
            tape.consistency_note = "Mixed intraday action in risk-off environment"

    else:
        tape.consistent_with_regime = None
        tape.consistency_note = f"Mixed/neutral regime — intraday: {char}"