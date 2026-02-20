from __future__ import annotations

from dataclasses import replace
from typing import Dict, Optional

import numpy as np

from .market_state import MarketState


def _clip(x: float, lo: float, hi: float) -> float:
    return float(max(lo, min(hi, x)))


def _scale_to_0_20(value: float, lo: float, hi: float) -> float:
    """
    Linear map value in [lo,hi] to [0,20], clipped.
    """
    if hi == lo:
        return 10.0
    return _clip((value - lo) / (hi - lo) * 20.0, 0.0, 20.0)


def score_market_state(state: MarketState) -> MarketState:
    """
    Price-implied "sentiment" score (0-100) using only market data.
    Components (0-20 each):
      1) risk_on
      2) trend_strength
      3) vol_mood (proxy via range% as a stand-in until VIX is added)
      4) participation
      5) leadership_clarity
    """
    ca = state.cross_asset_returns
    sr = state.sector_returns

    # --- Component 1: Risk-on vs Risk-off ---
    spy = ca.get("SPY")
    iwm = ca.get("IWM")
    hyg = ca.get("HYG")
    tlt = ca.get("TLT")

    # Build a simple composite:
    # - SPY return (centered around 0)
    # - IWM-SPY (beta leadership)
    # - HYG-TLT (credit vs duration)
    risk_terms = []
    if spy is not None:
        risk_terms.append(_scale_to_0_20(spy, -1.5, 1.5))
    if spy is not None and iwm is not None:
        risk_terms.append(_scale_to_0_20(iwm - spy, -1.0, 1.0))
    if hyg is not None and tlt is not None:
        risk_terms.append(_scale_to_0_20(hyg - tlt, -1.0, 1.0))
    risk_on = float(np.mean(risk_terms)) if risk_terms else 10.0

    # --- Component 2: Trend strength ---
    # Using CLV and range% as tape proxies.
    # CLV near +1 and larger range% => trend day risk.
    clv = state.spy_clv
    rng = state.spy_range_pct

    trend_terms = []
    if clv is not None:
        # map [-1,1] to [0,20]
        trend_terms.append(_scale_to_0_20(clv, -1.0, 1.0))
    if rng is not None:
        # typical SPY daily range maybe ~0.8%–2.2% depending on regime
        trend_terms.append(_scale_to_0_20(rng, 0.6, 2.5))
    trend_strength = float(np.mean(trend_terms)) if trend_terms else 10.0

    # --- Component 3: Vol mood (placeholder proxy) ---
    # Until you add VIX, use "range%" inversely:
    # very high range implies more headline/whipsaw risk.
    if rng is None:
        vol_mood = 10.0
    else:
        # If range is low/moderate => higher vol mood score
        # Map range 0.6% -> 20, range 2.8% -> 0 (clipped)
        vol_mood = _scale_to_0_20(2.8 - rng, 0.3, 2.2)

    # --- Component 4: Participation (breadth proxy) ---
    # Use sector breadth (# green out of 11) and SPY as anchor.
    green = state.sectors_green
    participation = _scale_to_0_20(green, 2, 10)

    # --- Component 5: Leadership clarity ---
    # Low dispersion + consistent leaders => clearer tape.
    disp = state.dispersion
    if disp is None:
        leadership_clarity = 10.0
    else:
        # dispersion low (~0.2-0.6) => clear
        # dispersion high (~1.2+) => messy
        leadership_clarity = _scale_to_0_20(1.4 - disp, 0.2, 1.2)

    components: Dict[str, float] = {
        "risk_on": round(risk_on, 2),
        "trend_strength": round(trend_strength, 2),
        "vol_mood": round(vol_mood, 2),
        "participation": round(participation, 2),
        "leadership_clarity": round(leadership_clarity, 2),
    }

    total = round(sum(components.values()), 2)  # 0-100

    # -------------------------
    # Confidence (0–100)
    # "How tradable/reliable is the tape?"
    # -------------------------
    vol = components.get("vol_mood", 10.0)
    part = components.get("participation", 10.0)
    lead = components.get("leadership_clarity", 10.0)

    # Optional boosters/penalties
    vol_conf = getattr(state, "volume_confirmation", None)
    vwap_ok = getattr(state, "spy_above_vwap", None)

    base_conf_0_20 = float(np.mean([vol, part, lead]))  # 0–20
    conf = base_conf_0_20 * 5.0                         # 0–100

    # If volume is strongly confirming direction (abs > ~1 z), boost slightly
    if vol_conf is not None:
        conf += _clip(abs(float(vol_conf)) * 3.0, 0.0, 8.0)  # max +8

    # If SPY is above VWAP (trend-friendly), small boost; below VWAP small penalty
    if vwap_ok is True:
        conf += 2.0
    elif vwap_ok is False:
        conf -= 2.0

    confidence = round(_clip(conf, 0.0, 100.0), 2)


    environment = classify_environment(total, components)

    return replace(
        state,
        score_total=total,
        score_components=components,
        environment=environment,
        confidence=confidence,
    )


def classify_environment(total_score: float, components: Dict[str, float]) -> str:
    trend = components.get("trend_strength", 10.0)
    vol = components.get("vol_mood", 10.0)
    part = components.get("participation", 10.0)
    lead = components.get("leadership_clarity", 10.0)

    # Simple rules (you’ll refine after a few weeks of snapshots)
    if total_score >= 70 and trend >= 14 and vol >= 10:
        return "Trend Day (Directional)"
    if 60 <= total_score < 75 and part >= 12 and lead >= 10:
        return "Risk-On Rotation Day"
    if total_score <= 35 or vol <= 6:
        return "Risk-Off / Headline Risk"
    if 40 <= total_score <= 60 and (lead <= 9 or vol <= 9):
        return "Chop / Mean Reversion"
    return "Mixed / Neutral"
