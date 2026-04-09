from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

import csv

import numpy as np

from .market_state import MarketState


DEFAULT_WEIGHTS: Dict[str, float] = {
    "risk_on": 0.20,
    "trend_strength": 0.20,
    "vol_mood": 0.20,
    "participation": 0.20,
    "leadership_clarity": 0.20,
}

DEFAULT_THRESHOLDS: Dict[str, Tuple[float, float]] = {
    "risk_on_raw": (-0.06, 0.06),
    "trend_clv_abs": (0.0, 1.0),
    "trend_range_pct": (0.005, 0.02),
    "vol_mood_vix": (0.0, 3.0),
    "vol_spike_pct": (0.0, 12.0),
    "vol_mood_fallback": (0.3, 2.2),
    "participation_green": (2.0, 10.0),
    "leadership_dispersion": (0.2, 1.2),
}


@lru_cache(maxsize=1)
def _load_thresholds(path: str | Path = "data/scoring_thresholds.csv") -> Dict[str, Tuple[float, float]]:
    """
    Load scoring thresholds from a CSV file.
    Expected columns: name, lo, hi
    Any missing/invalid entries fall back to DEFAULT_THRESHOLDS.
    """
    out = dict(DEFAULT_THRESHOLDS)
    p = Path(path)
    if not p.exists():
        return out

    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                try:
                    lo = float(row.get("lo", "").strip())
                    hi = float(row.get("hi", "").strip())
                except Exception:
                    continue
                out[name] = (lo, hi)
    except Exception:
        # If the file is unreadable, fall back to defaults
        return dict(DEFAULT_THRESHOLDS)

    return out


@lru_cache(maxsize=1)
def _load_weights(path: str | Path = "data/scoring_weights.csv") -> Dict[str, float]:
    """
    Load component weights from CSV.
    Expected columns: name, weight
    Weights are normalized to sum to 1.0. Missing/invalid => DEFAULT_WEIGHTS.
    """
    out = dict(DEFAULT_WEIGHTS)
    p = Path(path)
    if not p.exists():
        return out

    raw: Dict[str, float] = {}
    try:
        with p.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                if not name:
                    continue
                try:
                    w = float(row.get("weight", "").strip())
                except Exception:
                    continue
                raw[name] = w
    except Exception:
        return dict(DEFAULT_WEIGHTS)

    if not raw:
        return dict(DEFAULT_WEIGHTS)

    total = float(sum(max(0.0, v) for v in raw.values()))
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)

    # Normalize and keep only known components
    norm = {k: max(0.0, v) / total for k, v in raw.items() if k in DEFAULT_WEIGHTS}
    if not norm:
        return dict(DEFAULT_WEIGHTS)

    # Fill missing components with 0
    for k in DEFAULT_WEIGHTS:
        norm.setdefault(k, 0.0)
    return norm


def _clip(x: float, lo: float, hi: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 10.0  # neutral fallback

    if not np.isfinite(x):
        return 10.0  # neutral fallback for NaN/inf

    return float(max(lo, min(hi, x)))

def _scale_to_0_10(value: float, lo: float, hi: float) -> float:
    """
    Linear map value in [lo,hi] to [0,10], clipped.
    """
    if hi == lo:
        return 5.0
    return _clip((value - lo) / (hi - lo) * 10.0, 0.0, 10.0)


def score_market_state(state: MarketState) -> MarketState:
    """
    Price-implied "sentiment" score (0-100) using only market data.
    Components (0-10 each), combined using weights from CSV.
      1) risk_on
      2) trend_strength
      3) vol_mood
      4) participation
      5) leadership_clarity
    """
    ca = state.cross_asset_returns or {}
    sr = state.sector_returns

    thresholds = _load_thresholds()
    weights = _load_weights()

    # --- Component 1: Risk-on vs Risk-off ---
    hyg = ca.get("HYG")
    tlt = ca.get("TLT")

    # Build a simple composite:

    if hyg is not None and tlt is not None and np.isfinite(float(hyg)) and np.isfinite(float(tlt)):
        raw = float(hyg - tlt)  # positive = risk-on, negative = risk-off
        # bounds for blended 5d/21d relative performance (in % points)
        # tune later using quantiles
        lo, hi = thresholds["risk_on_raw"]
        risk_on = _scale_to_0_10(raw, lo, hi)
    else:
        risk_on = 5.0

    # --- Component 2: Trend strength ---
    clv = state.spy_clv
    rng = state.spy_range_pct

    trend_terms = []
    if clv is not None and np.isfinite(float(clv)):
        # Strength should be symmetric: strong up OR strong down is "trend"
        lo, hi = thresholds["trend_clv_abs"]
        trend_terms.append(_scale_to_0_10(abs(float(clv)), lo, hi))

    if rng is not None and np.isfinite(float(rng)):
        # tighten range bounds (SPY typically spends most days below 2%)
        lo, hi = thresholds["trend_range_pct"]
        trend_terms.append(_scale_to_0_10(float(rng), lo, hi))

    trend_strength = float(np.mean(trend_terms)) if trend_terms else 5.0

    # --- Component 3: Vol mood (uses VIX) ---
    # Goal: low/normal vol => high score (more tradable),
    #       high/stressed vol => low score (headline / whipsaw risk).
    vix_z = getattr(state, "vix_z_20d", None)
    vix_chg = getattr(state, "vix_change_pct_1d", None)

    if vix_z is not None and np.isfinite(float(vix_z)):
        # Map vix_z: -1 -> ~20, +2 -> ~0
        # Use (2 - vix_z) in [0,3] -> [0,20]
        lo, hi = thresholds["vol_mood_vix"]
        vol_mood = _scale_to_0_10(2.0 - float(vix_z), lo, hi)

        # Optional: penalize sharp VIX spikes (keeps “headline risk” honest)
        # Example: +12% VIX day should reduce tradability even if z-score isn’t extreme
        if vix_chg is not None and np.isfinite(float(vix_chg)):
            lo, hi = thresholds["vol_spike_pct"]
            spike_penalty = _scale_to_0_10(float(vix_chg), lo, hi)  # 0..10
            vol_mood = _clip(vol_mood - 0.35 * spike_penalty, 0.0, 10.0)

    else:
        # Fallback: if VIX unavailable, revert to inverse range% heuristic
        if rng is None or (not np.isfinite(float(rng))):
            vol_mood = 5.0
        else:
            lo, hi = thresholds["vol_mood_fallback"]
            vol_mood = _scale_to_0_10(2.8 - float(rng), lo, hi)

    # --- Component 4: Participation (breadth proxy) ---
    # Use sector breadth (# green out of 11) and SPY as anchor.
    green = state.sectors_green
    lo, hi = thresholds["participation_green"]
    participation = _scale_to_0_10(green, lo, hi)

    # --- Component 5: Leadership clarity ---
    # Low dispersion + consistent leaders => clearer tape.
    disp = state.dispersion
    if disp is None:
        leadership_clarity = 5.0
    else:
        # dispersion low (~0.2-0.6) => clear
        # dispersion high (~1.2+) => messy
        lo, hi = thresholds["leadership_dispersion"]
        leadership_clarity = _scale_to_0_10(1.4 - disp, lo, hi)

    components: Dict[str, float] = {
        "risk_on": round(risk_on, 2),
        "trend_strength": round(trend_strength, 2),
        "vol_mood": round(vol_mood, 2),
        "participation": round(participation, 2),
        "leadership_clarity": round(leadership_clarity, 2),
    }

    # Weighted total (0-100): sum(component_0_10 * weight) * 10
    total = round(
        10.0 * sum(components[k] * weights.get(k, 0.0) for k in components.keys()),
        2,
    )

    # -------------------------
    # Confidence (0–100)
    # "How tradable/reliable is the tape?"
    # -------------------------
    vol = components.get("vol_mood", 5.0)
    part = components.get("participation", 5.0)
    lead = components.get("leadership_clarity", 5.0)

    # Optional boosters/penalties
    vol_conf = getattr(state, "volume_confirmation", None)
    vwap_ok = getattr(state, "spy_above_vwap", None)

    base_conf_0_10 = float(np.mean([vol, part, lead]))  # 0–10
    conf = base_conf_0_10 * 10.0                        # 0–100

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
    if total_score >= 70 and trend >= 7 and vol >= 5:
        return "Trend Day (Directional)"
    if 60 <= total_score < 70 and part >= 6 and lead >= 5:
        return "Risk-On Rotation Day"
    if total_score <= 35 or vol <= 3:
        return "Risk-Off / Headline Risk"
    if 40 <= total_score <= 60 and (lead <= 4.5 or vol <= 4.5):
        return "Chop / Mean Reversion"
    return "Mixed / Neutral"
