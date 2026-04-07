# src/state/delta.py
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import pandas as pd

from .market_state import MarketState, load_snapshot


def _to_date_str(d: datetime | str | None) -> str:
    if d is None:
        return datetime.now().strftime("%Y-%m-%d")
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


def find_previous_snapshot(
    base_dir: str | Path,
    today_date_str: Optional[str] = None,
    max_lookback_business_days: int = 7,
) -> Tuple[Optional[str], Optional[MarketState]]:
    """
    Attempts to find the most recent prior snapshot by stepping back business days.
    Returns (date_str, MarketState) or (None, None) if not found.
    """
    today = pd.Timestamp(_to_date_str(today_date_str))

    # Step back 1 business day, then keep stepping up to max_lookback_business_days
    for i in range(1, max_lookback_business_days + 1):
        d = (today - pd.tseries.offsets.BDay(i)).strftime("%Y-%m-%d")
        s = load_snapshot(base_dir, d)
        if s is not None:
            return d, s

    return None, None


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return float(a - b)


def _fmt(x: Optional[float], decimals: int = 2, signed: bool = True) -> str:
    if x is None:
        return "—"
    if signed:
        return f"{x:+.{decimals}f}"
    return f"{x:.{decimals}f}"


def diff_states(today: MarketState, prior: MarketState) -> Dict:
    """
    Returns a machine-friendly diff dict.
    """
    t = today
    p = prior

    # Score & components
    t_score = getattr(t, "score_total", None)
    p_score = getattr(p, "score_total", None)

    t_comp = getattr(t, "score_components", None) or {}
    p_comp = getattr(p, "score_components", None) or {}

    comp_keys = sorted(set(t_comp.keys()) | set(p_comp.keys()))
    comp_delta = {k: _delta(t_comp.get(k), p_comp.get(k)) for k in comp_keys}

    # Leadership (names only)
    t_lead = [x[0] for x in (t.leadership_top3 or [])]
    p_lead = [x[0] for x in (p.leadership_top3 or [])]
    leadership_changed = t_lead != p_lead

    # Vol / breadth / volume / tape features you added
    keys = [
        "vix_level",
        "vix_change_pct_1d",
        "vix_vs_20d_pct",
        "vix_z_20d",
        "rsp_minus_spy",
        "spy_range_pct",
        "spy_clv",
        "spy_vol_vs_20d_pct",
        "spy_vol_z_20d",
        "volume_confirmation",
        "dispersion",
        "sectors_green",
    ]
    feature_delta = {}
    for k in keys:
        feature_delta[k] = _delta(getattr(t, k, None), getattr(p, k, None))

    # Cross-asset deltas (tickers that exist in both)
    ca_t = t.cross_asset_returns or {}
    ca_p = p.cross_asset_returns or {}
    ca_keys = sorted(set(ca_t.keys()) | set(ca_p.keys()))
    cross_asset_delta = {k: _delta(ca_t.get(k), ca_p.get(k)) for k in ca_keys}

    # Sector deltas
    sr_t = t.sector_returns or {}
    sr_p = p.sector_returns or {}
    sec_keys = sorted(set(sr_t.keys()) | set(sr_p.keys()))
    sector_delta = {k: _delta(sr_t.get(k), sr_p.get(k)) for k in sec_keys}

    return {
        "score": {
            "today": t_score,
            "prior": p_score,
            "delta": _delta(t_score, p_score),
        },
        "components_delta": comp_delta,
        "environment": {"today": t.environment, "prior": p.environment},
        "leadership": {
            "today": t_lead,
            "prior": p_lead,
            "changed": leadership_changed,
        },
        "feature_delta": feature_delta,
        "cross_asset_delta": cross_asset_delta,
        "sector_delta": sector_delta,
    }


def diff_to_bullets(d: Dict) -> List[str]:
    """
    Turns diff dict into short human-readable bullets for the dashboard.
    """
    bullets: List[str] = []

    # Score / environment
    score_delta = d.get("score", {}).get("delta")
    env_t = d.get("environment", {}).get("today")
    env_p = d.get("environment", {}).get("prior")
    if score_delta is not None:
        bullets.append(f"Sentiment score change: {_fmt(score_delta, 2)} (env: {env_p} → {env_t})")
    else:
        bullets.append(f"Environment: {env_p} → {env_t}")

    # Vol regime (if present)
    fd = d.get("feature_delta", {})
    if fd.get("vix_z_20d") is not None:
        bullets.append(f"VIX z-score (20D) change: {_fmt(fd.get('vix_z_20d'), 2)}")
    if fd.get("vix_change_pct_1d") is not None:
        bullets.append(f"VIX 1D % change shift: {_fmt(fd.get('vix_change_pct_1d'), 2)}pp")

    # Breadth
    if fd.get("rsp_minus_spy") is not None:
        bullets.append(f"Breadth (RSP−SPY) change: {_fmt(fd.get('rsp_minus_spy'), 2)}pp")
    if fd.get("sectors_green") is not None:
        bullets.append(f"Sectors green change: {_fmt(fd.get('sectors_green'), 0)}")

    # Volume confirmation
    if fd.get("volume_confirmation") is not None:
        bullets.append(f"Volume confirmation change: {_fmt(fd.get('volume_confirmation'), 2)}")

    # Leadership
    lead = d.get("leadership", {})
    if lead.get("changed"):
        bullets.append(f"Leadership shifted: {', '.join(lead.get('prior', []))} → {', '.join(lead.get('today', []))}")

    return bullets


def top_movers_from_delta(delta_map: Dict[str, Optional[float]], n: int = 3) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
    """
    Returns (top_positive, top_negative) movers from a {key: delta} map.
    """
    clean = [(k, v) for k, v in delta_map.items() if v is not None]
    clean.sort(key=lambda x: x[1], reverse=True)
    top_pos = clean[:n]
    top_neg = list(reversed(clean[-n:])) if len(clean) >= n else []
    return top_pos, top_neg
