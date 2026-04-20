"""
src/state/regime_layers.py

Five-layer regime scoring system.
Each layer scores 0-10 independently, then combines into a 0-100 composite.

Layers:
  1. Monetary & Liquidity   — the tide
  2. Credit & Stress        — the canary
  3. Volatility Structure   — the shape of fear
  4. Breadth & Participation — the internals
  5. Positioning & Sentiment — the crowding signal

Usage:
    from src.state.regime_layers import score_all_layers, LayerScores
    scores = score_all_layers(raw_data)
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple
import numpy as np


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class LayerScore:
    score: float                    # 0-10
    inputs: Dict[str, Optional[float]]   # raw inputs used
    signals: List[str]              # plain-english signals fired
    status: str                     # "bullish" | "neutral" | "bearish"
    data_quality: float             # 0-1, how complete the inputs were


@dataclass
class LayerScores:
    monetary:   LayerScore
    credit:     LayerScore
    volatility: LayerScore
    breadth:    LayerScore
    positioning: LayerScore

    # Derived
    composite: float = 0.0          # weighted 0-100
    layer_agreement: float = 0.0    # 0-1, how aligned the layers are
    confidence: float = 0.0         # 0-100, based on data quality + agreement
    environment: str = ""
    environment_drivers: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "monetary":    asdict(self.monetary),
            "credit":      asdict(self.credit),
            "volatility":  asdict(self.volatility),
            "breadth":     asdict(self.breadth),
            "positioning": asdict(self.positioning),
            "composite":   round(self.composite, 2),
            "layer_agreement": round(self.layer_agreement, 3),
            "confidence":  round(self.confidence, 1),
            "environment": self.environment,
            "environment_drivers": self.environment_drivers,
        }


# ── Weights by horizon ────────────────────────────────────────────────────────

WEIGHTS = {
    "swing":    {"monetary": 0.15, "credit": 0.25, "volatility": 0.25, "breadth": 0.20, "positioning": 0.15},
    "investor": {"monetary": 0.30, "credit": 0.25, "volatility": 0.15, "breadth": 0.20, "positioning": 0.10},
    "default":  {"monetary": 0.20, "credit": 0.22, "volatility": 0.22, "breadth": 0.20, "positioning": 0.16},
}


# ── Shared helpers ────────────────────────────────────────────────────────────

def _safe(x) -> Optional[float]:
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _scale(value: float, lo: float, hi: float, invert: bool = False) -> float:
    """Linear scale value from [lo,hi] to [0,10], clipped."""
    if hi == lo:
        return 5.0
    scaled = (value - lo) / (hi - lo) * 10.0
    scaled = float(np.clip(scaled, 0.0, 10.0))
    return 10.0 - scaled if invert else scaled


def _status(score: float) -> str:
    if score >= 6.5:
        return "bullish"
    if score <= 3.5:
        return "bearish"
    return "neutral"


def _data_quality(values: List[Optional[float]]) -> float:
    available = sum(1 for v in values if v is not None)
    return round(available / len(values), 2) if values else 0.0


# ── Layer 1: Monetary & Liquidity ─────────────────────────────────────────────

def score_monetary(
    net_liquidity_z: Optional[float] = None,      # z-score of WALCL-TGA-RRP
    nfci_inverted: Optional[float] = None,         # NFCI inverted (higher = easier)
    m2_growth_yoy: Optional[float] = None,         # M2 YoY % growth
    fci_z: Optional[float] = None,                 # Financial conditions z-score inverted
) -> LayerScore:
    """
    Monetary & Liquidity layer.
    High score = abundant liquidity, easy conditions.
    Low score  = tightening, draining liquidity.
    """
    components = []
    signals = []
    inputs = {
        "net_liquidity_z": _safe(net_liquidity_z),
        "nfci_inverted":   _safe(nfci_inverted),
        "m2_growth_yoy":   _safe(m2_growth_yoy),
        "fci_z":           _safe(fci_z),
    }

    # Net liquidity z-score: positive = expanding (bullish), negative = contracting
    if inputs["net_liquidity_z"] is not None:
        # z-score range: -2 to +2 typical
        s = _scale(inputs["net_liquidity_z"], -2.0, 2.0)
        components.append(s)
        if inputs["net_liquidity_z"] > 0.5:
            signals.append("Net liquidity expanding — structural tailwind")
        elif inputs["net_liquidity_z"] < -0.5:
            signals.append("Net liquidity contracting — structural headwind")

    # NFCI inverted: higher = easier financial conditions
    if inputs["nfci_inverted"] is not None:
        # NFCI inverted z-score: -2 to +2
        s = _scale(inputs["nfci_inverted"], -2.0, 2.0)
        components.append(s)
        if inputs["nfci_inverted"] < -0.5:
            signals.append("Financial conditions tightening (NFCI elevated)")

    # M2 growth: above 5% YoY historically supportive
    if inputs["m2_growth_yoy"] is not None:
        s = _scale(inputs["m2_growth_yoy"], -2.0, 10.0)
        components.append(s)
        if inputs["m2_growth_yoy"] < 0:
            signals.append(f"M2 contracting YoY ({inputs['m2_growth_yoy']:.1f}%) — rare tightening signal")
        elif inputs["m2_growth_yoy"] > 8:
            signals.append(f"M2 accelerating ({inputs['m2_growth_yoy']:.1f}% YoY) — liquidity abundant")

    # FCI z-score inverted: higher = easier
    if inputs["fci_z"] is not None:
        s = _scale(inputs["fci_z"], -2.0, 2.0)
        components.append(s)

    score = float(np.mean(components)) if components else 5.0
    dq = _data_quality(list(inputs.values()))

    return LayerScore(
        score=round(score, 2),
        inputs=inputs,
        signals=signals,
        status=_status(score),
        data_quality=dq,
    )


# ── Layer 2: Credit & Stress ──────────────────────────────────────────────────

def score_credit(
    hy_spread_level: Optional[float] = None,       # HY OAS in bps (e.g. 350)
    hy_spread_z: Optional[float] = None,           # z-score vs 2yr rolling
    hy_spread_chg_4w: Optional[float] = None,      # 4-week change in bps
    ig_spread_level: Optional[float] = None,       # IG OAS in bps (e.g. 100)
    ig_spread_z: Optional[float] = None,
    hyg_tlt_ratio_z: Optional[float] = None,       # z-score of HYG/TLT ratio
) -> LayerScore:
    """
    Credit & Stress layer.
    High score = credit healthy, spreads tight, no stress.
    Low score  = spreads widening, credit stress, systemic risk rising.
    """
    components = []
    signals = []
    inputs = {
        "hy_spread_level":  _safe(hy_spread_level),
        "hy_spread_z":      _safe(hy_spread_z),
        "hy_spread_chg_4w": _safe(hy_spread_chg_4w),
        "ig_spread_level":  _safe(ig_spread_level),
        "ig_spread_z":      _safe(ig_spread_z),
        "hyg_tlt_ratio_z":  _safe(hyg_tlt_ratio_z),
    }

    # HY spread level — tight is good, wide is bad
    # Historical range: ~250 (tight/bull) to ~900 (crisis)
    if inputs["hy_spread_level"] is not None:
        s = _scale(inputs["hy_spread_level"], 250.0, 900.0, invert=True)
        components.append(s)
        if inputs["hy_spread_level"] > 600:
            signals.append(f"HY spreads at stress levels ({inputs['hy_spread_level']:.0f}bps) — credit deteriorating")
        elif inputs["hy_spread_level"] < 350:
            signals.append(f"HY spreads tight ({inputs['hy_spread_level']:.0f}bps) — credit healthy")

    # HY z-score — relative to recent history
    if inputs["hy_spread_z"] is not None:
        s = _scale(inputs["hy_spread_z"], -2.0, 3.0, invert=True)
        components.append(s)
        if inputs["hy_spread_z"] > 1.5:
            signals.append("HY spreads elevated relative to 2yr history")

    # HY 4-week change — momentum matters as much as level
    if inputs["hy_spread_chg_4w"] is not None:
        # Widening (positive) is bad, tightening (negative) is good
        s = _scale(inputs["hy_spread_chg_4w"], -80.0, 150.0, invert=True)
        components.append(s)
        if inputs["hy_spread_chg_4w"] > 50:
            signals.append(f"HY spreads widening rapidly (+{inputs['hy_spread_chg_4w']:.0f}bps/4wk) — stress accelerating")
        elif inputs["hy_spread_chg_4w"] < -30:
            signals.append(f"HY spreads tightening ({inputs['hy_spread_chg_4w']:.0f}bps/4wk) — credit improving")

    # IG spread level — IG widening is systemic, not idiosyncratic
    if inputs["ig_spread_level"] is not None:
        s = _scale(inputs["ig_spread_level"], 60.0, 300.0, invert=True)
        components.append(s)
        if inputs["ig_spread_level"] > 180:
            signals.append(f"IG spreads elevated ({inputs['ig_spread_level']:.0f}bps) — systemic stress signal")

    # HYG/TLT ratio z-score — risk appetite in credit
    if inputs["hyg_tlt_ratio_z"] is not None:
        s = _scale(inputs["hyg_tlt_ratio_z"], -2.5, 2.5)
        components.append(s)

    score = float(np.mean(components)) if components else 5.0
    dq = _data_quality(list(inputs.values()))

    return LayerScore(
        score=round(score, 2),
        inputs=inputs,
        signals=signals,
        status=_status(score),
        data_quality=dq,
    )


# ── Layer 3: Volatility Structure ─────────────────────────────────────────────

def score_volatility(
    vix_level: Optional[float] = None,
    vix_z_20d: Optional[float] = None,
    vix_term_slope: Optional[float] = None,    # VIX3M - VIX (positive = contango = calm)
    vvix_level: Optional[float] = None,        # vol of vol, ~80 normal, >110 stressed
    vvix_z: Optional[float] = None,
    put_call_ratio: Optional[float] = None,    # 5d MA, ~0.85 neutral, >1.1 fearful
    skew_index: Optional[float] = None,        # SKEW index, ~125 normal, >145 elevated
) -> LayerScore:
    """
    Volatility Structure layer.
    High score = calm, normal term structure, no hedging surge.
    Low score  = acute fear, inverted term structure, VVIX elevated.
    """
    components = []
    signals = []
    inputs = {
        "vix_level":      _safe(vix_level),
        "vix_z_20d":      _safe(vix_z_20d),
        "vix_term_slope": _safe(vix_term_slope),
        "vvix_level":     _safe(vvix_level),
        "vvix_z":         _safe(vvix_z),
        "put_call_ratio": _safe(put_call_ratio),
        "skew_index":     _safe(skew_index),
    }

    # VIX level — lower is calmer
    if inputs["vix_level"] is not None:
        s = _scale(inputs["vix_level"], 10.0, 45.0, invert=True)
        components.append(s)
        if inputs["vix_level"] > 30:
            signals.append(f"VIX elevated at {inputs['vix_level']:.1f} — fear regime")
        elif inputs["vix_level"] < 15:
            signals.append(f"VIX suppressed at {inputs['vix_level']:.1f} — complacency risk")

    # VIX z-score
    if inputs["vix_z_20d"] is not None:
        s = _scale(inputs["vix_z_20d"], -1.5, 3.0, invert=True)
        components.append(s)

    # VIX term slope: VIX3M - VIX
    # Positive (contango) = normal, calm
    # Negative (backwardation) = crisis, acute fear
    if inputs["vix_term_slope"] is not None:
        s = _scale(inputs["vix_term_slope"], -8.0, 8.0)
        components.append(s)
        if inputs["vix_term_slope"] < -2:
            signals.append(f"VIX term structure inverted ({inputs['vix_term_slope']:+.1f}) — acute near-term fear")
        elif inputs["vix_term_slope"] > 4:
            signals.append("VIX term structure steep contango — market pricing calm ahead")

    # VVIX — uncertainty about uncertainty
    if inputs["vvix_level"] is not None:
        s = _scale(inputs["vvix_level"], 70.0, 130.0, invert=True)
        components.append(s)
        if inputs["vvix_level"] > 110:
            signals.append(f"VVIX elevated ({inputs['vvix_level']:.0f}) — VIX itself unstable, regime calls less reliable")

    # Put/call ratio — 5d MA
    # ~0.85 neutral; >1.1 = fear (contrarian bullish); <0.65 = greed (contrarian bearish)
    if inputs["put_call_ratio"] is not None:
        # High P/C (fear) = contrarian bullish = higher vol score
        # Low P/C (greed) = contrarian bearish = lower vol score
        if inputs["put_call_ratio"] > 1.1:
            s = 7.5  # fear = tradeable bounce setup
            signals.append(f"Put/call ratio elevated ({inputs['put_call_ratio']:.2f}) — fear-driven hedging, contrarian bullish")
        elif inputs["put_call_ratio"] < 0.65:
            s = 2.5  # complacency
            signals.append(f"Put/call ratio low ({inputs['put_call_ratio']:.2f}) — complacency, limited upside protection")
        else:
            s = _scale(inputs["put_call_ratio"], 0.65, 1.1)
        components.append(s)

    # SKEW index
    if inputs["skew_index"] is not None:
        # High skew = institutions paying up for tail protection = bearish
        s = _scale(inputs["skew_index"], 110.0, 155.0, invert=True)
        components.append(s)
        if inputs["skew_index"] > 145:
            signals.append(f"SKEW index elevated ({inputs['skew_index']:.0f}) — institutional tail hedging surge")

    score = float(np.mean(components)) if components else 5.0
    dq = _data_quality(list(inputs.values()))

    return LayerScore(
        score=round(score, 2),
        inputs=inputs,
        signals=signals,
        status=_status(score),
        data_quality=dq,
    )


# ── Layer 4: Breadth & Participation ──────────────────────────────────────────

def score_breadth(
    pct_above_200d: Optional[float] = None,     # % of S&P stocks above 200-day MA
    new_highs_minus_lows_z: Optional[float] = None,  # z-score of (HIGHNEW - LOWNEW)
    sectors_green: Optional[int] = None,         # your existing 0-11
    rsp_vs_spy_z: Optional[float] = None,        # z-score of RSP/SPY ratio (equal vs cap weight)
    adl_slope: Optional[float] = None,           # advance/decline line 20d slope
) -> LayerScore:
    """
    Breadth & Participation layer.
    High score = broad participation, healthy internals.
    Low score  = narrow leadership, diverging breadth.
    """
    components = []
    signals = []
    inputs = {
        "pct_above_200d":        _safe(pct_above_200d),
        "new_highs_minus_lows_z": _safe(new_highs_minus_lows_z),
        "sectors_green":          float(sectors_green) if sectors_green is not None else None,
        "rsp_vs_spy_z":          _safe(rsp_vs_spy_z),
        "adl_slope":             _safe(adl_slope),
    }

    # % above 200-day MA — most important breadth signal
    if inputs["pct_above_200d"] is not None:
        s = _scale(inputs["pct_above_200d"], 45.0, 100.0)
        components.append(s)
        if inputs["pct_above_200d"] >= 100:
            signals.append(f"{inputs['pct_above_200d']:.0f}% of stocks above 200d MA — broad participation")
        elif inputs["pct_above_200d"] < 50:
            signals.append(f"Only {inputs['pct_above_200d']:.0f}% above 200d MA — narrow market, deteriorating internals")

    # New highs minus new lows z-score
    if inputs["new_highs_minus_lows_z"] is not None:
        s = _scale(inputs["new_highs_minus_lows_z"], -2.5, 2.5)
        components.append(s)
        if inputs["new_highs_minus_lows_z"] < -1.5:
            signals.append("New lows expanding rapidly — internal deterioration despite possible index strength")
        elif inputs["new_highs_minus_lows_z"] > 1.5:
            signals.append("New highs expanding — broad underlying strength confirmed")

    # Sectors green — your existing signal
    if inputs["sectors_green"] is not None:
        s = _scale(inputs["sectors_green"], 1.0, 10.0)
        components.append(s)

    # RSP vs SPY z-score — equal weight vs cap weight
    # Positive = equal weight outperforming = broad rally (good)
    # Negative = cap weight outperforming = narrow/mega-cap led rally (caution)
    if inputs["rsp_vs_spy_z"] is not None:
        s = _scale(inputs["rsp_vs_spy_z"], -2.0, 2.0)
        components.append(s)
        if inputs["rsp_vs_spy_z"] < -1.0:
            signals.append("Equal weight (RSP) lagging cap weight (SPY) — mega-cap concentration, breadth narrowing")
        elif inputs["rsp_vs_spy_z"] > 1.0:
            signals.append("Equal weight outperforming — broad rally, not just mega-cap driven")

    # ADL slope
    if inputs["adl_slope"] is not None:
        s = _scale(inputs["adl_slope"], -50.0, 50.0)
        components.append(s)

    score = float(np.mean(components)) if components else 5.0
    dq = _data_quality(list(inputs.values()))

    return LayerScore(
        score=round(score, 2),
        inputs=inputs,
        signals=signals,
        status=_status(score),
        data_quality=dq,
    )


# ── Layer 5: Positioning & Sentiment ──────────────────────────────────────────

def score_positioning(
    dealer_gamma_z: Optional[float] = None,     # z-score of net dealer gamma (positive = long gamma = dampening)
    put_call_5d_ma: Optional[float] = None,     # 5d MA put/call equity ratio
    aaii_bull_minus_bear: Optional[float] = None, # AAII bull% - bear% (contrarian)
    cot_net_large_spec_z: Optional[float] = None, # z-score COT large spec net longs in S&P futures
    equity_etf_flow_z: Optional[float] = None,  # z-score of weekly equity ETF flows
) -> LayerScore:
    """
    Positioning & Sentiment layer.
    Largely CONTRARIAN — extreme readings in either direction are signals.

    High score = positioning neutral or contrarian-bullish
                 (room to run, dealers dampening vol, sentiment washed out)
    Low score  = crowded long, extreme complacency, or negative gamma territory
                 (fragile, mechanical amplification, limited upside)
    """
    components = []
    signals = []
    inputs = {
        "dealer_gamma_z":       _safe(dealer_gamma_z),
        "put_call_5d_ma":       _safe(put_call_5d_ma),
        "aaii_bull_minus_bear": _safe(aaii_bull_minus_bear),
        "cot_net_large_spec_z": _safe(cot_net_large_spec_z),
        "equity_etf_flow_z":    _safe(equity_etf_flow_z),
    }

    # Dealer gamma — mechanical vol suppressor or amplifier
    if inputs["dealer_gamma_z"] is not None:
        # Positive gamma = dealers suppress vol = more orderly = higher score
        # Negative gamma = dealers amplify = dangerous = lower score
        s = _scale(inputs["dealer_gamma_z"], -2.5, 2.5)
        components.append(s)
        if inputs["dealer_gamma_z"] < -1.0:
            signals.append("Dealers net short gamma — mechanical vol amplification likely, moves will overshoot")
        elif inputs["dealer_gamma_z"] > 1.0:
            signals.append("Dealers net long gamma — suppressing volatility, orderly tape")

    # Put/call ratio (equity) — contrarian
    if inputs["put_call_5d_ma"] is not None:
        if inputs["put_call_5d_ma"] > 0.95:
            # Extreme fear = contrarian bullish
            s = 7.5
            signals.append(f"Equity put/call elevated ({inputs['put_call_5d_ma']:.2f}) — retail fear, contrarian bullish setup")
        elif inputs["put_call_5d_ma"] < 0.60:
            # Extreme complacency = contrarian bearish
            s = 2.5
            signals.append(f"Equity put/call suppressed ({inputs['put_call_5d_ma']:.2f}) — complacency, limited protection bought")
        else:
            s = 5.0
        components.append(s)

    # AAII sentiment — contrarian
    if inputs["aaii_bull_minus_bear"] is not None:
        # Extreme bearish (< -20) = contrarian bullish
        # Extreme bullish (> +30) = contrarian bearish
        if inputs["aaii_bull_minus_bear"] < -20:
            s = 8.0
            signals.append(f"AAII sentiment deeply bearish ({inputs['aaii_bull_minus_bear']:+.0f}pp) — historically bullish contrarian signal")
        elif inputs["aaii_bull_minus_bear"] > 30:
            s = 2.5
            signals.append(f"AAII sentiment euphoric ({inputs['aaii_bull_minus_bear']:+.0f}pp) — crowded bullish positioning")
        else:
            # Neutral zone: scale normally
            s = _scale(inputs["aaii_bull_minus_bear"], -20.0, 30.0, invert=True)
        components.append(s)

    # COT large speculator net positioning — contrarian at extremes
    if inputs["cot_net_large_spec_z"] is not None:
        # Extreme long (z > 2) = crowded = contrarian bearish
        # Extreme short (z < -2) = washed out = contrarian bullish
        s = _scale(inputs["cot_net_large_spec_z"], -2.5, 2.5, invert=True)
        components.append(s)
        if inputs["cot_net_large_spec_z"] > 2.0:
            signals.append("COT large speculators near extreme net long — historically mean-reverts")
        elif inputs["cot_net_large_spec_z"] < -2.0:
            signals.append("COT large speculators near extreme net short — historically bullish setup")

    # ETF flows z-score — contrarian at extremes
    if inputs["equity_etf_flow_z"] is not None:
        # Large inflows = crowded = mild bearish
        # Large outflows = capitulation = mild bullish
        s = _scale(inputs["equity_etf_flow_z"], -2.5, 2.5, invert=True)
        components.append(s)

    score = float(np.mean(components)) if components else 5.0
    dq = _data_quality(list(inputs.values()))

    return LayerScore(
        score=round(score, 2),
        inputs=inputs,
        signals=signals,
        status=_status(score),
        data_quality=dq,
    )


# ── Environment classification ────────────────────────────────────────────────

def classify_environment(scores: LayerScores) -> Tuple[str, List[str]]:
    """
    Classify market environment from layer scores.
    Returns (environment_label, driver_list).
    """
    m = scores.monetary.score
    c = scores.credit.score
    v = scores.volatility.score
    b = scores.breadth.score
    p = scores.positioning.score
    composite = scores.composite
    agreement = scores.layer_agreement

    drivers = []

    # ── High conviction bullish regimes ──
    if composite >= 70 and agreement >= 0.7:
        if b >= 7 and v >= 6 and c >= 6:
            drivers = ["Strong breadth", "Healthy credit", "Calm vol structure"]
            return "Trend Day — Broad Participation", drivers
        if m >= 7 and c >= 7 and b >= 6:
            drivers = ["Liquidity supportive", "Credit healthy", "Breadth expanding"]
            return "Risk-On — Liquidity Driven", drivers

    # ── Risk-on with caveats ──
    if composite >= 62 and b >= 6 and c >= 6:
        if v < 5:
            drivers = ["Good breadth/credit", "Vol structure elevated"]
            return "Risk-On Rotation — Vol Caution", drivers
        drivers = ["Breadth expanding", "Credit supportive"]
        return "Risk-On Rotation Day", drivers

    # ── Complacency warning — calm surface, fragile underneath ──
    if v >= 7 and p <= 3.5 and b <= 5:
        drivers = ["Vol suppressed", "Crowded positioning", "Breadth deteriorating"]
        return "Complacency Warning", drivers

    # ── Gamma squeeze / technical environment ──
    if scores.positioning.inputs.get("dealer_gamma_z") is not None:
        dgz = scores.positioning.inputs["dealer_gamma_z"]
        if dgz is not None and dgz < -1.5 and v <= 4:
            drivers = ["Negative dealer gamma", "Elevated vol"]
            return "Negative Gamma — Volatile", drivers

    # ── Stress / risk-off ──
    if c <= 3.5 or (composite <= 38 and v <= 4):
        if c <= 3 and v <= 3:
            drivers = ["Credit stress", "Vol elevated"]
            return "Risk-Off — Credit Stress", drivers
        drivers = ["Low composite score", "Stress signals present"]
        return "Risk-Off / Headline Risk", drivers

    # ── Mean reversion / fear exhaustion ──
    if p >= 7 and v <= 4 and composite <= 50:
        drivers = ["Positioning washed out", "Contrarian setup"]
        return "Fear Exhaustion — Mean Reversion Setup", drivers

    # ── Chop / divergence ──
    if agreement < 0.4 or (40 <= composite <= 60 and agreement < 0.55):
        # Find which layers are diverging
        layer_statuses = {
            "monetary":    m, "credit": c,
            "volatility":  v, "breadth": b, "positioning": p,
        }
        bullish_layers = [k for k, s in layer_statuses.items() if s >= 6.5]
        bearish_layers = [k for k, s in layer_statuses.items() if s <= 3.5]
        if bullish_layers and bearish_layers:
            drivers = [
                f"Bullish: {', '.join(bullish_layers)}",
                f"Bearish: {', '.join(bearish_layers)}",
            ]
        else:
            drivers = ["Low layer agreement", "Mixed signals"]
        return "Chop / Layer Divergence", drivers

    # ── Mixed neutral ──
    drivers = ["No dominant regime signal"]
    return "Mixed / Neutral", drivers


# ── Layer agreement calculation ───────────────────────────────────────────────

def _layer_agreement(scores: List[float]) -> float:
    """
    0 = completely split (half bullish, half bearish)
    1 = all layers pointing same direction
    """
    above = sum(1 for s in scores if s >= 6.5)
    below = sum(1 for s in scores if s <= 3.5)
    neutral = len(scores) - above - below
    total = len(scores)
    if total == 0:
        return 0.5
    majority = max(above, below, neutral)
    # Perfect agreement = 1.0, perfect split = 0.0
    return round((majority / total - 1/3) / (2/3), 3)


# ── Composite confidence ──────────────────────────────────────────────────────

def _composite_confidence(scores: LayerScores) -> float:
    """
    Confidence is a function of:
    - Data quality (how many inputs were available)
    - Layer agreement (how much consensus exists)
    """
    avg_dq = np.mean([
        scores.monetary.data_quality,
        scores.credit.data_quality,
        scores.volatility.data_quality,
        scores.breadth.data_quality,
        scores.positioning.data_quality,
    ])
    agreement_boost = scores.layer_agreement * 30.0
    base = avg_dq * 70.0
    return round(float(np.clip(base + agreement_boost, 0.0, 100.0)), 1)


# ── Main entry point ──────────────────────────────────────────────────────────

def score_all_layers(
    # Monetary
    net_liquidity_z: Optional[float] = None,
    nfci_inverted: Optional[float] = None,
    m2_growth_yoy: Optional[float] = None,
    fci_z: Optional[float] = None,
    # Credit
    hy_spread_level: Optional[float] = None,
    hy_spread_z: Optional[float] = None,
    hy_spread_chg_4w: Optional[float] = None,
    ig_spread_level: Optional[float] = None,
    ig_spread_z: Optional[float] = None,
    hyg_tlt_ratio_z: Optional[float] = None,
    # Volatility
    vix_level: Optional[float] = None,
    vix_z_20d: Optional[float] = None,
    vix_term_slope: Optional[float] = None,
    vvix_level: Optional[float] = None,
    vvix_z: Optional[float] = None,
    put_call_ratio: Optional[float] = None,
    skew_index: Optional[float] = None,
    # Breadth
    pct_above_200d: Optional[float] = None,
    new_highs_minus_lows_z: Optional[float] = None,
    sectors_green: Optional[int] = None,
    rsp_vs_spy_z: Optional[float] = None,
    adl_slope: Optional[float] = None,
    # Positioning
    dealer_gamma_z: Optional[float] = None,
    put_call_5d_ma: Optional[float] = None,
    aaii_bull_minus_bear: Optional[float] = None,
    cot_net_large_spec_z: Optional[float] = None,
    equity_etf_flow_z: Optional[float] = None,
    # Config
    horizon: str = "default",
) -> LayerScores:
    """
    Main scoring function. Pass whatever inputs you have — missing inputs
    fall back gracefully, reducing data_quality score accordingly.
    """
    monetary   = score_monetary(net_liquidity_z, nfci_inverted, m2_growth_yoy, fci_z)
    credit     = score_credit(hy_spread_level, hy_spread_z, hy_spread_chg_4w, ig_spread_level, ig_spread_z, hyg_tlt_ratio_z)
    volatility = score_volatility(vix_level, vix_z_20d, vix_term_slope, vvix_level, vvix_z, put_call_ratio, skew_index)
    breadth    = score_breadth(pct_above_200d, new_highs_minus_lows_z, sectors_green, rsp_vs_spy_z, adl_slope)
    positioning = score_positioning(dealer_gamma_z, put_call_5d_ma, aaii_bull_minus_bear, cot_net_large_spec_z, equity_etf_flow_z)

    weights = WEIGHTS.get(horizon, WEIGHTS["default"])

    raw_scores = [monetary.score, credit.score, volatility.score, breadth.score, positioning.score]
    layer_names = ["monetary", "credit", "volatility", "breadth", "positioning"]

    composite = sum(
        s * weights[n]
        for s, n in zip(raw_scores, layer_names)
    ) * 10.0

    agreement = _layer_agreement(raw_scores)

    result = LayerScores(
        monetary=monetary,
        credit=credit,
        volatility=volatility,
        breadth=breadth,
        positioning=positioning,
        composite=round(composite, 2),
        layer_agreement=round(agreement, 3),
    )

    result.confidence = _composite_confidence(result)
    result.environment, result.environment_drivers = classify_environment(result)

    return result


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    # Simulate today's market: mixed conditions, VIX elevated, credit ok
    result = score_all_layers(
        # Monetary — neutral
        net_liquidity_z=0.2,
        nfci_inverted=-0.3,
        m2_growth_yoy=3.5,
        # Credit — mildly stressed
        hy_spread_level=420,
        hy_spread_z=0.8,
        hy_spread_chg_4w=35,
        ig_spread_level=110,
        # Volatility — stressed
        vix_level=25.8,
        vix_z_20d=0.4,
        vix_term_slope=-1.5,
        vvix_level=95,
        put_call_ratio=1.05,
        # Breadth — weak
        pct_above_200d=42,
        new_highs_minus_lows_z=-0.8,
        sectors_green=5,
        rsp_vs_spy_z=-0.5,
        # Positioning — fear / contrarian bullish
        put_call_5d_ma=1.02,
        aaii_bull_minus_bear=-18,
        cot_net_large_spec_z=-0.8,
    )

    print(f"Environment: {result.environment}")
    print(f"Composite:   {result.composite:.1f}/100")
    print(f"Confidence:  {result.confidence:.1f}/100")
    print(f"Agreement:   {result.layer_agreement:.2f}")
    print()
    print("Layer scores:")
    for name in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        layer = getattr(result, name)
        print(f"  {name:12} {layer.score:4.1f}/10  [{layer.status}]  dq={layer.data_quality:.0%}")
        for sig in layer.signals:
            print(f"    → {sig}")
    print()
    print("Drivers:", result.environment_drivers)