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

from src.state.config_loader import (
    ENV_PARAMS,
    REGIME_PARAMS,
    WEIGHTS as CONFIG_WEIGHTS,
)


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


# ── Shared helpers ────────────────────────────────────────────────────────────

def _get_weights(horizon: str) -> dict[str, float]:
    """Build per-layer composite weights for a scoring horizon from config."""
    if horizon not in ("default", "swing", "investor"):
        horizon = "default"
    return {
        "monetary": CONFIG_WEIGHTS[f"weights.{horizon}.monetary"],
        "credit": CONFIG_WEIGHTS[f"weights.{horizon}.credit"],
        "volatility": CONFIG_WEIGHTS[f"weights.{horizon}.volatility"],
        "breadth": CONFIG_WEIGHTS[f"weights.{horizon}.breadth"],
        "positioning": CONFIG_WEIGHTS[f"weights.{horizon}.positioning"],
    }


# Compatibility view for adapters that rehydrate older dataclass snapshots.
# Values are sourced from AGENT_SYSTEM_INPUTS.xlsx, not hardcoded here.
WEIGHTS = {
    horizon: _get_weights(horizon)
    for horizon in ("default", "swing", "investor")
}


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
    bullish = REGIME_PARAMS["status.bullish_cutoff"]
    bearish = REGIME_PARAMS["status.bearish_cutoff"]
    if score >= bullish:
        return "bullish"
    if score <= bearish:
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
    P = REGIME_PARAMS
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
        s = _scale(
            inputs["net_liquidity_z"],
            P["monetary.net_liquidity_z.scale_lo"],
            P["monetary.net_liquidity_z.scale_hi"],
        )
        components.append(s)
        if inputs["net_liquidity_z"] > P["monetary.net_liquidity_z.expanding_signal_threshold"]:
            signals.append("Net liquidity expanding — structural tailwind")
        elif inputs["net_liquidity_z"] < P["monetary.net_liquidity_z.contracting_signal_threshold"]:
            signals.append("Net liquidity contracting — structural headwind")

    # NFCI inverted: higher = easier financial conditions
    if inputs["nfci_inverted"] is not None:
        s = _scale(
            inputs["nfci_inverted"],
            P["monetary.nfci_inverted.scale_lo"],
            P["monetary.nfci_inverted.scale_hi"],
        )
        components.append(s)
        if inputs["nfci_inverted"] < P["monetary.nfci_inverted.tightening_signal_threshold"]:
            signals.append("Financial conditions tightening (NFCI elevated)")

    # M2 growth: above 5% YoY historically supportive
    if inputs["m2_growth_yoy"] is not None:
        s = _scale(
            inputs["m2_growth_yoy"],
            P["monetary.m2_growth_yoy.scale_lo"],
            P["monetary.m2_growth_yoy.scale_hi"],
        )
        components.append(s)
        if inputs["m2_growth_yoy"] < P["monetary.m2_growth_yoy.contracting_signal_threshold"]:
            signals.append(f"M2 contracting YoY ({inputs['m2_growth_yoy']:.1f}%) — rare tightening signal")
        elif inputs["m2_growth_yoy"] > P["monetary.m2_growth_yoy.accelerating_signal_threshold"]:
            signals.append(f"M2 accelerating ({inputs['m2_growth_yoy']:.1f}% YoY) — liquidity abundant")

    # FCI z-score inverted: higher = easier
    if inputs["fci_z"] is not None:
        s = _scale(
            inputs["fci_z"],
            P["monetary.fci_z.scale_lo"],
            P["monetary.fci_z.scale_hi"],
        )
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
    P = REGIME_PARAMS
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

    if inputs["hy_spread_level"] is not None:
        s = _scale(
            inputs["hy_spread_level"],
            P["credit.hy_spread_level.scale_lo"],
            P["credit.hy_spread_level.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["hy_spread_level"] > P["credit.hy_spread_level.stress_signal_threshold"]:
            signals.append(f"HY spreads at stress levels ({inputs['hy_spread_level']:.0f}bps) — credit deteriorating")
        elif inputs["hy_spread_level"] < P["credit.hy_spread_level.tight_signal_threshold"]:
            signals.append(f"HY spreads tight ({inputs['hy_spread_level']:.0f}bps) — credit healthy")

    # HY z-score — relative to recent history
    if inputs["hy_spread_z"] is not None:
        s = _scale(
            inputs["hy_spread_z"],
            P["credit.hy_spread_z.scale_lo"],
            P["credit.hy_spread_z.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["hy_spread_z"] > P["credit.hy_spread_z.elevated_signal_threshold"]:
            signals.append("HY spreads elevated relative to 2yr history")

    # HY 4-week change — momentum matters as much as level
    if inputs["hy_spread_chg_4w"] is not None:
        s = _scale(
            inputs["hy_spread_chg_4w"],
            P["credit.hy_spread_chg_4w.scale_lo"],
            P["credit.hy_spread_chg_4w.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["hy_spread_chg_4w"] > P["credit.hy_spread_chg_4w.widening_signal_threshold"]:
            signals.append(f"HY spreads widening rapidly (+{inputs['hy_spread_chg_4w']:.0f}bps/4wk) — stress accelerating")
        elif inputs["hy_spread_chg_4w"] < P["credit.hy_spread_chg_4w.tightening_signal_threshold"]:
            signals.append(f"HY spreads tightening ({inputs['hy_spread_chg_4w']:.0f}bps/4wk) — credit improving")

    # IG spread level — IG widening is systemic, not idiosyncratic
    if inputs["ig_spread_level"] is not None:
        s = _scale(
            inputs["ig_spread_level"],
            P["credit.ig_spread_level.scale_lo"],
            P["credit.ig_spread_level.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["ig_spread_level"] > P["credit.ig_spread_level.elevated_signal_threshold"]:
            signals.append(f"IG spreads elevated ({inputs['ig_spread_level']:.0f}bps) — systemic stress signal")

    # HYG/TLT ratio z-score — risk appetite in credit
    if inputs["hyg_tlt_ratio_z"] is not None:
        s = _scale(
            inputs["hyg_tlt_ratio_z"],
            P["credit.hyg_tlt_ratio_z.scale_lo"],
            P["credit.hyg_tlt_ratio_z.scale_hi"],
        )
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
    P = REGIME_PARAMS
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
        s = _scale(
            inputs["vix_level"],
            P["volatility.vix_level.scale_lo"],
            P["volatility.vix_level.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["vix_level"] > P["volatility.vix_level.elevated_signal_threshold"]:
            signals.append(f"VIX elevated at {inputs['vix_level']:.1f} — fear regime")
        elif inputs["vix_level"] < P["volatility.vix_level.suppressed_signal_threshold"]:
            signals.append(f"VIX suppressed at {inputs['vix_level']:.1f} — complacency risk")

    # VIX z-score
    if inputs["vix_z_20d"] is not None:
        s = _scale(
            inputs["vix_z_20d"],
            P["volatility.vix_z_20d.scale_lo"],
            P["volatility.vix_z_20d.scale_hi"],
            invert=True,
        )
        components.append(s)

    # VIX term slope: VIX3M - VIX
    # Positive (contango) = normal, calm
    # Negative (backwardation) = crisis, acute fear
    if inputs["vix_term_slope"] is not None:
        s = _scale(
            inputs["vix_term_slope"],
            P["volatility.vix_term_slope.scale_lo"],
            P["volatility.vix_term_slope.scale_hi"],
        )
        components.append(s)
        if inputs["vix_term_slope"] < P["volatility.vix_term_slope.inverted_signal_threshold"]:
            signals.append(f"VIX term structure inverted ({inputs['vix_term_slope']:+.1f}) — acute near-term fear")
        elif inputs["vix_term_slope"] > P["volatility.vix_term_slope.contango_signal_threshold"]:
            signals.append("VIX term structure steep contango — market pricing calm ahead")

    # VVIX — uncertainty about uncertainty
    if inputs["vvix_level"] is not None:
        s = _scale(
            inputs["vvix_level"],
            P["volatility.vvix_level.scale_lo"],
            P["volatility.vvix_level.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["vvix_level"] > P["volatility.vvix_level.elevated_signal_threshold"]:
            signals.append(f"VVIX elevated ({inputs['vvix_level']:.0f}) — VIX itself unstable, regime calls less reliable")

    # Put/call ratio — 5d MA
    # ~0.85 neutral; >1.1 = fear (contrarian bullish); <0.65 = greed (contrarian bearish)
    if inputs["put_call_ratio"] is not None:
        # High P/C (fear) = contrarian bullish = higher vol score
        # Low P/C (greed) = contrarian bearish = lower vol score
        if inputs["put_call_ratio"] > P["volatility.put_call_ratio.fear_threshold"]:
            s = P["volatility.put_call_ratio.fear_score"]
            signals.append(f"Put/call ratio elevated ({inputs['put_call_ratio']:.2f}) — fear-driven hedging, contrarian bullish")
        elif inputs["put_call_ratio"] < P["volatility.put_call_ratio.complacency_threshold"]:
            s = P["volatility.put_call_ratio.complacency_score"]
            signals.append(f"Put/call ratio low ({inputs['put_call_ratio']:.2f}) — complacency, limited upside protection")
        else:
            s = _scale(
                inputs["put_call_ratio"],
                P["volatility.put_call_ratio.complacency_threshold"],
                P["volatility.put_call_ratio.fear_threshold"],
            )
        components.append(s)

    # SKEW index
    if inputs["skew_index"] is not None:
        # High skew = institutions paying up for tail protection = bearish
        s = _scale(
            inputs["skew_index"],
            P["volatility.skew_index.scale_lo"],
            P["volatility.skew_index.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["skew_index"] > P["volatility.skew_index.elevated_signal_threshold"]:
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
    pct_above_200d: Optional[float] = None,       # diagnostic only; not scored
    avg_dist_from_200d: Optional[float] = None,   # avg % distance from 200d MA
    sectors_green: Optional[int] = None,           # raw count out of 11
    rsp_vs_spy_z: Optional[float] = None,          # equal vs cap weight z-score
    adl_slope: Optional[float] = None,             # normalized constituent ADL 20d slope
) -> LayerScore:
    """
    Breadth & Participation layer.
    High score = broad participation, healthy internals.
    Low score  = narrow leadership, diverging breadth.

    Inputs (with weights for the weighted average):
        avg_dist_from_200d (35%) — continuous distance from 200d MA
        rsp_vs_spy_z       (30%) — equal vs cap-weight z-score
        adl_slope          (20%) — normalized constituent ADL trend direction
        sectors_green      (15%) — noisy daily snapshot

    pct_above_200d is retained for diagnostic display but not scored.
    """
    P = REGIME_PARAMS
    component_weight_pairs: list[tuple[float, float]] = []
    signals = []
    inputs = {
        "pct_above_200d":      _safe(pct_above_200d),
        "avg_dist_from_200d":  _safe(avg_dist_from_200d),
        "sectors_green":       float(sectors_green) if sectors_green is not None else None,
        "rsp_vs_spy_z":        _safe(rsp_vs_spy_z),
        "adl_slope":           _safe(adl_slope),
    }

    if inputs["avg_dist_from_200d"] is not None:
        d = inputs["avg_dist_from_200d"]
        s = _scale(
            d,
            P["breadth.avg_dist_from_200d.scale_lo"],
            P["breadth.avg_dist_from_200d.scale_hi"],
        )
        component_weight_pairs.append((s, P["breadth.avg_dist_from_200d.weight"]))
        if d < P["breadth.avg_dist_from_200d.below_signal_threshold"]:
            signals.append(f"Constituent avg {d:+.1f}% below 200d MA — broad downtrend")
        elif d > P["breadth.avg_dist_from_200d.above_signal_threshold"]:
            signals.append(f"Constituent avg {d:+.1f}% above 200d MA — broad uptrend")
        elif (
            P["breadth.avg_dist_from_200d.transition_zone_lo"]
            <= d
            <= P["breadth.avg_dist_from_200d.transition_zone_hi"]
        ):
            signals.append(f"Constituent avg near 200d MA ({d:+.1f}%) — transition zone")

    if inputs["rsp_vs_spy_z"] is not None:
        s = _scale(
            inputs["rsp_vs_spy_z"],
            P["breadth.rsp_vs_spy_z.scale_lo"],
            P["breadth.rsp_vs_spy_z.scale_hi"],
        )
        component_weight_pairs.append((s, P["breadth.rsp_vs_spy_z.weight"]))
        if inputs["rsp_vs_spy_z"] < P["breadth.rsp_vs_spy_z.lagging_signal_threshold"]:
            signals.append("Equal weight (RSP) lagging cap weight (SPY) — mega-cap concentration, breadth narrowing")
        elif inputs["rsp_vs_spy_z"] > P["breadth.rsp_vs_spy_z.outperforming_signal_threshold"]:
            signals.append("Equal weight outperforming — broad rally, not just mega-cap driven")

    if inputs["adl_slope"] is not None:
        s = _scale(
            inputs["adl_slope"],
            P["breadth.adl_slope.scale_lo"],
            P["breadth.adl_slope.scale_hi"],
        )
        component_weight_pairs.append((s, P["breadth.adl_slope.weight"]))
        if inputs["adl_slope"] < P["breadth.adl_slope.deteriorating_signal_threshold"]:
            signals.append("Constituent ADL slope sharply negative — participation deteriorating")
        elif inputs["adl_slope"] > P["breadth.adl_slope.broadening_signal_threshold"]:
            signals.append("Constituent ADL slope rising — participation broadening")

    if inputs["sectors_green"] is not None:
        s = _scale(
            inputs["sectors_green"],
            P["breadth.sectors_green.scale_lo"],
            P["breadth.sectors_green.scale_hi"],
        )
        component_weight_pairs.append((s, P["breadth.sectors_green.weight"]))

    if component_weight_pairs:
        total_weight = sum(w for _, w in component_weight_pairs)
        score = sum(s * w for s, w in component_weight_pairs) / total_weight
    else:
        score = 5.0
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
    P = REGIME_PARAMS
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
        s = _scale(
            inputs["dealer_gamma_z"],
            P["positioning.dealer_gamma_z.scale_lo"],
            P["positioning.dealer_gamma_z.scale_hi"],
        )
        components.append(s)
        if inputs["dealer_gamma_z"] < P["positioning.dealer_gamma_z.negative_signal_threshold"]:
            signals.append("Dealers net short gamma — mechanical vol amplification likely, moves will overshoot")
        elif inputs["dealer_gamma_z"] > P["positioning.dealer_gamma_z.positive_signal_threshold"]:
            signals.append("Dealers net long gamma — suppressing volatility, orderly tape")

    # Put/call ratio (equity) — contrarian
    if inputs["put_call_5d_ma"] is not None:
        if inputs["put_call_5d_ma"] > P["positioning.put_call_5d_ma.fear_threshold"]:
            s = P["positioning.put_call_5d_ma.fear_score"]
            signals.append(f"Equity put/call elevated ({inputs['put_call_5d_ma']:.2f}) — retail fear, contrarian bullish setup")
        elif inputs["put_call_5d_ma"] < P["positioning.put_call_5d_ma.complacency_threshold"]:
            s = P["positioning.put_call_5d_ma.complacency_score"]
            signals.append(f"Equity put/call suppressed ({inputs['put_call_5d_ma']:.2f}) — complacency, limited protection bought")
        else:
            s = P["positioning.put_call_5d_ma.neutral_score"]
        components.append(s)

    # AAII sentiment — contrarian. Tightened thresholds:
    #   < -28pp -> genuine panic (12th percentile historically) -> strong contrarian bullish
    #   > +37pp -> genuine euphoria (88th percentile historically) -> strong contrarian bearish
    # Old thresholds of -20/+30 fired on too many normal-range readings.
    if inputs["aaii_bull_minus_bear"] is not None:
        if inputs["aaii_bull_minus_bear"] < P["positioning.aaii_bull_minus_bear.panic_threshold"]:
            s = P["positioning.aaii_bull_minus_bear.panic_score"]
            signals.append(
                f"AAII sentiment in panic territory ({inputs['aaii_bull_minus_bear']:+.0f}pp) "
                "— rare contrarian bullish signal"
            )
        elif inputs["aaii_bull_minus_bear"] > P["positioning.aaii_bull_minus_bear.euphoria_threshold"]:
            s = P["positioning.aaii_bull_minus_bear.euphoria_score"]
            signals.append(
                f"AAII sentiment euphoric ({inputs['aaii_bull_minus_bear']:+.0f}pp) "
                "— extreme positioning, contrarian bearish"
            )
        else:
            # Scale linearly within the normal -28 to +37 band, inverted (contrarian)
            s = _scale(
                inputs["aaii_bull_minus_bear"],
                P["positioning.aaii_bull_minus_bear.scale_lo"],
                P["positioning.aaii_bull_minus_bear.scale_hi"],
                invert=True,
            )
        components.append(s)

    # COT large speculator net positioning — contrarian at extremes
    if inputs["cot_net_large_spec_z"] is not None:
        # Extreme long (z > 2) = crowded = contrarian bearish
        # Extreme short (z < -2) = washed out = contrarian bullish
        s = _scale(
            inputs["cot_net_large_spec_z"],
            P["positioning.cot_net_large_spec_z.scale_lo"],
            P["positioning.cot_net_large_spec_z.scale_hi"],
            invert=True,
        )
        components.append(s)
        if inputs["cot_net_large_spec_z"] > P["positioning.cot_net_large_spec_z.extreme_long_signal_threshold"]:
            signals.append("COT large speculators near extreme net long — historically mean-reverts")
        elif inputs["cot_net_large_spec_z"] < P["positioning.cot_net_large_spec_z.extreme_short_signal_threshold"]:
            signals.append("COT large speculators near extreme net short — historically bullish setup")

    # ETF flows z-score — contrarian at extremes
    if inputs["equity_etf_flow_z"] is not None:
        # Large inflows = crowded = mild bearish
        # Large outflows = capitulation = mild bullish
        s = _scale(
            inputs["equity_etf_flow_z"],
            P["positioning.equity_etf_flow_z.scale_lo"],
            P["positioning.equity_etf_flow_z.scale_hi"],
            invert=True,
        )
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

    E = ENV_PARAMS
    drivers = []

    if (
        composite >= E["env.trend_day.composite_threshold"]
        and agreement >= E["env.trend_day.agreement_threshold"]
        and b >= E["env.trend_day.breadth_threshold"]
        and v >= E["env.trend_day.volatility_threshold"]
        and c >= E["env.trend_day.credit_threshold"]
    ):
        drivers = ["Strong breadth", "Healthy credit", "Calm vol structure"]
        return "Trend Day — Broad Participation", drivers

    if (
        composite >= E["env.risk_on_liquidity.composite_threshold"]
        and agreement >= E["env.risk_on_liquidity.agreement_threshold"]
        and m >= E["env.risk_on_liquidity.monetary_threshold"]
        and c >= E["env.risk_on_liquidity.credit_threshold"]
        and b >= E["env.risk_on_liquidity.breadth_threshold"]
    ):
        drivers = ["Liquidity supportive", "Credit healthy", "Breadth expanding"]
        return "Risk-On — Liquidity Driven", drivers

    if (
        composite >= E["env.risk_on_rotation.composite_threshold"]
        and b >= E["env.risk_on_rotation.breadth_threshold"]
        and c >= E["env.risk_on_rotation.credit_threshold"]
    ):
        if v < E["env.risk_on_rotation.vol_caution_threshold"]:
            drivers = ["Good breadth/credit", "Vol structure elevated"]
            return "Risk-On Rotation — Vol Caution", drivers
        drivers = ["Breadth expanding", "Credit supportive"]
        return "Risk-On Rotation Day", drivers

    if (
        v >= E["env.complacency.volatility_threshold"]
        and p <= E["env.complacency.positioning_threshold"]
        and b <= E["env.complacency.breadth_threshold"]
    ):
        drivers = ["Vol suppressed", "Crowded positioning", "Breadth deteriorating"]
        return "Complacency Warning", drivers

    dgz = scores.positioning.inputs.get("dealer_gamma_z")
    if (
        dgz is not None
        and dgz < E["env.negative_gamma.dealer_gamma_z_threshold"]
        and v <= E["env.negative_gamma.volatility_threshold"]
    ):
        drivers = ["Negative dealer gamma", "Elevated vol"]
        return "Negative Gamma — Volatile", drivers

    risk_off_triggered = (
        c <= E["env.risk_off_headline.credit_threshold"]
        or (
            composite <= E["env.risk_off_headline.composite_threshold"]
            and v <= E["env.risk_off_headline.volatility_threshold"]
        )
    )
    if risk_off_triggered:
        if (
            c <= E["env.risk_off_credit_stress.credit_threshold"]
            and v <= E["env.risk_off_credit_stress.volatility_threshold"]
        ):
            drivers = ["Credit stress", "Vol elevated"]
            return "Risk-Off — Credit Stress", drivers
        drivers = ["Low composite score", "Stress signals present"]
        return "Risk-Off / Headline Risk", drivers

    if (
        p >= E["env.fear_exhaustion.positioning_threshold"]
        and v <= E["env.fear_exhaustion.volatility_threshold"]
        and composite <= E["env.fear_exhaustion.composite_threshold"]
    ):
        drivers = ["Positioning washed out", "Contrarian setup"]
        return "Fear Exhaustion — Mean Reversion Setup", drivers

    chop_band_lo = E["env.chop.composite_band_lo"]
    chop_band_hi = E["env.chop.composite_band_hi"]
    if (
        agreement < E["env.chop.agreement_threshold_strict"]
        or (
            chop_band_lo <= composite <= chop_band_hi
            and agreement < E["env.chop.agreement_threshold_band"]
        )
    ):
        layer_statuses = {
            "monetary":    m, "credit": c,
            "volatility":  v, "breadth": b, "positioning": p,
        }
        bullish = REGIME_PARAMS["status.bullish_cutoff"]
        bearish = REGIME_PARAMS["status.bearish_cutoff"]
        bullish_layers = [k for k, s in layer_statuses.items() if s >= bullish]
        bearish_layers = [k for k, s in layer_statuses.items() if s <= bearish]
        if bullish_layers and bearish_layers:
            drivers = [
                f"Bullish: {', '.join(bullish_layers)}",
                f"Bearish: {', '.join(bearish_layers)}",
            ]
        else:
            drivers = ["Low layer agreement", "Mixed signals"]
        return "Chop / Layer Divergence", drivers

    drivers = ["No dominant regime signal"]
    return "Mixed / Neutral", drivers


# ── Layer agreement calculation ───────────────────────────────────────────────

def _layer_agreement(scores: List[float]) -> float:
    """
    0 = completely split (half bullish, half bearish)
    1 = all layers pointing same direction
    """
    bullish = REGIME_PARAMS["status.bullish_cutoff"]
    bearish = REGIME_PARAMS["status.bearish_cutoff"]
    above = sum(1 for s in scores if s >= bullish)
    below = sum(1 for s in scores if s <= bearish)
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
    avg_dist_from_200d: Optional[float] = None,
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
    breadth    = score_breadth(pct_above_200d, avg_dist_from_200d, sectors_green, rsp_vs_spy_z, adl_slope)
    positioning = score_positioning(dealer_gamma_z, put_call_5d_ma, aaii_bull_minus_bear, cot_net_large_spec_z, equity_etf_flow_z)

    weights = _get_weights(horizon)

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
        avg_dist_from_200d=-4.5,
        sectors_green=5,
        rsp_vs_spy_z=-0.5,
        adl_slope=-0.2,
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
