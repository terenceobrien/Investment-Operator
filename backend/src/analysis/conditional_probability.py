"""
conditional_probability.py

Drop this file into backend/src/analysis/
Exposes one public function: get_conditional_stats(state: MarketState) -> dict

Given today's MarketState, returns:
  - Historical return distributions for matching regimes
  - Risk metrics (drawdown, upside)
  - Comparable past dates
  - LLM-ready plain-English summary
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ── Config ────────────────────────────────────────────────────────────────────

DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "operator_research_v2.csv"

# Override at runtime if needed:
# import os; DATA_PATH = Path(os.getenv("RESEARCH_DATA_PATH", str(DATA_PATH)))

HORIZONS = {
    "1d":  "fwd_ret_cc_1d",
    "5d":  "fwd_ret_cc_5d",
    "10d": "fwd_ret_cc_10d",
    "21d": "fwd_ret_cc_21d",
    "63d": "fwd_ret_cc_63d",
    "126d": "fwd_ret_cc_126d",
    "252d": "fwd_ret_cc_252d",
}
TACTICAL_HORIZONS = ["1d", "5d", "10d"]
MACRO_HORIZONS = ["21d", "63d", "126d", "252d"]
MACRO_RISK_COLUMNS = {
    "21d": ("fwd_21d_max_drawdown_pct", "fwd_21d_max_upside_pct"),
    "63d": ("fwd_63d_max_drawdown_pct", "fwd_63d_max_upside_pct"),
    "126d": ("fwd_126d_max_drawdown_pct", "fwd_126d_max_upside_pct"),
    "252d": ("fwd_252d_max_drawdown_pct", "fwd_252d_max_upside_pct"),
}
MACRO_RISK_UNAVAILABLE_WARNING = (
    "Macro-horizon drawdown/upside columns unavailable; only return-distribution risk shown."
)

SCORE_BINS   = [0, 35, 45, 55, 65, 75, 101]
SCORE_LABELS = ["<35", "35-45", "45-55", "55-65", "65-75", ">75"]

VIX_BINS   = [0, 15, 20, 25, 35, 999]
VIX_LABELS = ["<15", "15-20", "20-25", "25-35", ">35"]


# ── Data loading (cached in module) ──────────────────────────────────────────

_df_cache: Optional[pd.DataFrame] = None


def _load_df() -> pd.DataFrame:
    global _df_cache
    if _df_cache is not None:
        return _df_cache

    df = pd.read_csv(DATA_PATH)
    df = df[df["signal_time"] == "close"].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["score_delta"] = df["score_total"].diff()

    # Bucket columns
    df["score_bucket"] = pd.cut(df["score_total"], bins=SCORE_BINS, labels=SCORE_LABELS, right=False)
    df["vix_bucket"]   = pd.cut(df["vix_level"],   bins=VIX_BINS,   labels=VIX_LABELS,  right=False)

    _df_cache = df
    return df


# ── Core stats helper ─────────────────────────────────────────────────────────

def _return_stats(series: pd.Series) -> Dict[str, Any]:
    """Return dict of stats for a forward return series (already in %)."""
    s = series.dropna()
    if len(s) < 3:
        return {
            "n": int(len(s)),
            "median": None,
            "mean": None,
            "pct_positive": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "worst": None,
            "best": None,
            "insufficient_data": True,
        }
    return {
        "n": int(len(s)),
        "median": round(float(s.median()), 2),
        "mean":   round(float(s.mean()),   2),
        "pct_positive": round(float((s > 0).mean() * 100), 1),
        "p10": round(float(s.quantile(0.10)), 2),
        "p25": round(float(s.quantile(0.25)), 2),
        "p75": round(float(s.quantile(0.75)), 2),
        "p90": round(float(s.quantile(0.90)), 2),
        "worst": round(float(s.min()), 2),
        "best":  round(float(s.max()), 2),
    }


def _build_return_table(
    subset: pd.DataFrame,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build return stats for all horizons for a given subset."""
    out = {}
    for label, col in HORIZONS.items():
        if col in subset.columns:
            out[label] = _return_stats(subset[col].dropna() * 100)
        elif warnings is not None:
            warning = f"Forward return column {col} unavailable; skipping {label} conditional stats."
            if warning not in warnings:
                warnings.append(warning)
    return out


def _comparable_dates(subset: pd.DataFrame, n: int = 5) -> List[str]:
    """Return the most recent n matching dates."""
    return subset["date"].sort_values(ascending=False).head(n).dt.strftime("%Y-%m-%d").tolist()


# ── Match logic ───────────────────────────────────────────────────────────────

def _get_environment_match(df: pd.DataFrame, environment: str) -> pd.DataFrame:
    return df[df["environment"] == environment]


def _get_score_bucket_match(df: pd.DataFrame, score: float) -> pd.DataFrame:
    bucket = pd.cut([score], bins=SCORE_BINS, labels=SCORE_LABELS, right=False)[0]
    return df[df["score_bucket"] == bucket], str(bucket)


def _get_vix_bucket(vix: Optional[float]) -> Optional[str]:
    if vix is None:
        return None
    bucket = pd.cut([vix], bins=VIX_BINS, labels=VIX_LABELS, right=False)[0]
    return str(bucket)


def _get_multi_factor_match(
    df: pd.DataFrame,
    environment: str,
    score: float,
    vix: Optional[float],
    score_delta: Optional[float],
    sectors_green: Optional[int],
) -> tuple[pd.DataFrame, str]:
    """
    Progressively layer conditions, falling back to fewer conditions
    if fewer than 15 matches found.
    """
    mask = pd.Series([True] * len(df), index=df.index)

    # Always filter by environment
    mask &= df["environment"] == environment

    # Score ± 10pts
    mask &= (df["score_total"] >= score - 12) & (df["score_total"] <= score + 12)

    conditions_used = ["environment", "score_range"]

    # Add VIX bucket if available
    if vix is not None:
        vix_bucket = _get_vix_bucket(vix)
        vix_mask = df["vix_bucket"] == vix_bucket
        if (mask & vix_mask).sum() >= 15:
            mask &= vix_mask
            conditions_used.append(f"vix_{vix_bucket}")

    # Add breadth direction if available
    if sectors_green is not None:
        broad_up = sectors_green >= 6
        breadth_mask = (df["sectors_green"] >= 6) if broad_up else (df["sectors_green"] < 6)
        if (mask & breadth_mask).sum() >= 15:
            mask &= breadth_mask
            conditions_used.append("breadth_direction")

    # Add score momentum direction if available
    if score_delta is not None:
        improving = score_delta > 3
        deteriorating = score_delta < -3
        if improving:
            delta_mask = df["score_delta"] > 3
            label = "score_improving"
        elif deteriorating:
            delta_mask = df["score_delta"] < -3
            label = "score_deteriorating"
        else:
            delta_mask = None
            label = None

        if delta_mask is not None and (mask & delta_mask).sum() >= 12:
            mask &= delta_mask
            conditions_used.append(label)

    matched = df[mask]
    condition_desc = " + ".join(conditions_used)
    return matched, condition_desc


# ── Risk profile ──────────────────────────────────────────────────────────────

def _risk_profile(subset: pd.DataFrame) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if "fwd_5d_max_drawdown_pct" in subset.columns:
        dd = subset["fwd_5d_max_drawdown_pct"].dropna() * 100
        if len(dd) >= 5:
            out["max_drawdown_5d"] = {
                "median": round(float(dd.median()), 2),
                "p25":    round(float(dd.quantile(0.25)), 2),
                "worst":  round(float(dd.min()), 2),
            }
    else:
        dd = pd.Series(dtype=float)

    if "fwd_5d_max_upside_pct" in subset.columns:
        up = subset["fwd_5d_max_upside_pct"].dropna() * 100
        if len(up) >= 5:
            out["max_upside_5d"] = {
                "median": round(float(up.median()), 2),
                "p75":    round(float(up.quantile(0.75)), 2),
                "best":   round(float(up.max()), 2),
            }
    else:
        up = pd.Series(dtype=float)

    if len(dd) >= 5 and len(up) >= 5:
        rr = abs(up.median() / dd.median()) if dd.median() != 0 else None
        out["reward_risk_ratio"] = round(rr, 2) if rr else None

    available_macro_risk_horizons: List[str] = []
    for horizon in MACRO_HORIZONS:
        col = HORIZONS[horizon]
        if col in subset.columns:
            values = (subset[col].dropna() * 100).tolist()
            out.update(_forward_return_risk(values, horizon))

        dd_col, up_col = MACRO_RISK_COLUMNS[horizon]
        if dd_col in subset.columns and up_col in subset.columns:
            dd_h = subset[dd_col].dropna() * 100
            up_h = subset[up_col].dropna() * 100
            if len(dd_h) >= 5 and len(up_h) >= 5:
                available_macro_risk_horizons.append(horizon)
                out[f"max_drawdown_{horizon}"] = {
                    "median": round(float(dd_h.median()), 2),
                    "p25": round(float(dd_h.quantile(0.25)), 2),
                    "worst": round(float(dd_h.min()), 2),
                }
                out[f"max_upside_{horizon}"] = {
                    "median": round(float(up_h.median()), 2),
                    "p75": round(float(up_h.quantile(0.75)), 2),
                    "best": round(float(up_h.max()), 2),
                }
    out["drawdown_upside_available_horizons"] = available_macro_risk_horizons

    return out


def _forward_return_risk(values: List[float], horizon: str) -> Dict[str, Any]:
    if not values:
        return {
            f"win_rate_{horizon}": None,
            f"median_up_{horizon}": None,
            f"median_down_{horizon}": None,
            f"expected_value_{horizon}": None,
            f"worst_forward_return_{horizon}": None,
            f"p10_forward_return_{horizon}": None,
            f"p90_forward_return_{horizon}": None,
        }
    arr = np.array(values, dtype=float)
    up = arr[arr > 0]
    down = arr[arr <= 0]
    win_rate = float((arr > 0).mean())
    median_up = float(np.median(up)) if len(up) else 0.0
    median_down = float(np.median(down)) if len(down) else 0.0
    return {
        f"win_rate_{horizon}": round(win_rate * 100.0, 1),
        f"median_up_{horizon}": round(median_up, 2),
        f"median_down_{horizon}": round(median_down, 2),
        f"expected_value_{horizon}": round(float(win_rate * median_up + (1.0 - win_rate) * median_down), 2),
        f"worst_forward_return_{horizon}": round(float(arr.min()), 2),
        f"p10_forward_return_{horizon}": round(float(np.percentile(arr, 10)), 2),
        f"p90_forward_return_{horizon}": round(float(np.percentile(arr, 90)), 2),
        f"worst_drawdown_{horizon}": round(float(arr.min()), 2),
    }


# ── Plain-English summary ─────────────────────────────────────────────────────

def _plain_english_summary(
    environment: str,
    score: float,
    multi_stats: Dict[str, Any],
    risk: Dict[str, Any],
    condition_desc: str,
    n_matches: int,
    vix: Optional[float],
    score_delta: Optional[float],
) -> str:
    lines = []

    # Regime description
    lines.append(f"Current environment: {environment} (score {score:.0f}/100).")

    # Data confidence
    if n_matches < 15:
        lines.append(f"Limited historical precedent — only {n_matches} comparable days found. Treat with caution.")
    else:
        lines.append(f"Based on {n_matches} comparable historical days ({condition_desc}).")

    # Forward return narrative
    fwd_5d = multi_stats.get("5d", {})
    fwd_21d = multi_stats.get("21d", {})

    if fwd_5d and not fwd_5d.get("insufficient_data"):
        direction = "positive" if fwd_5d["pct_positive"] >= 55 else "negative" if fwd_5d["pct_positive"] < 45 else "mixed"
        lines.append(
            f"5-day forward returns: median {fwd_5d['median']:+.2f}%, "
            f"positive {fwd_5d['pct_positive']:.0f}% of the time "
            f"(range: {fwd_5d['p25']:+.2f}% to {fwd_5d['p75']:+.2f}%)."
        )

    if fwd_21d and not fwd_21d.get("insufficient_data"):
        lines.append(
            f"21-day forward returns: median {fwd_21d['median']:+.2f}%, "
            f"positive {fwd_21d['pct_positive']:.0f}% of the time."
        )

    # Risk asymmetry
    dd = risk.get("max_drawdown_5d", {})
    up = risk.get("max_upside_5d", {})
    rr = risk.get("reward_risk_ratio")

    if dd and up:
        lines.append(
            f"5-day risk profile: typical drawdown {dd['median']:.2f}% / "
            f"typical upside {up['median']:+.2f}% "
            f"(reward/risk: {rr:.1f}x)." if rr else
            f"5-day risk profile: typical drawdown {dd['median']:.2f}% / "
            f"typical upside {up['median']:+.2f}%."
        )

    # VIX context
    if vix is not None:
        if vix > 30:
            lines.append(f"VIX at {vix:.1f} — elevated fear. Historically, this environment has seen mean-reversion bounces.")
        elif vix < 15:
            lines.append(f"VIX at {vix:.1f} — complacency risk. Low vol environments can reverse sharply.")

    # Score momentum context
    if score_delta is not None:
        if score_delta < -10:
            lines.append(f"Score deteriorated {score_delta:.0f}pts today — sharp regime shifts tend to overshoot short-term.")
        elif score_delta > 10:
            lines.append(f"Score improved {score_delta:.0f}pts today — regime improvement often has follow-through over 3-5 days.")

    return " ".join(lines)


# ── Main public function ──────────────────────────────────────────────────────

def get_conditional_stats(
    environment: str,
    score_total: float,
    vix_level: Optional[float] = None,
    sectors_green: Optional[int] = None,
    score_delta: Optional[float] = None,
    confidence: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Main entry point. Pass in today's market state values,
    get back conditional probability analysis.

    Args:
        environment:   e.g. "Risk-On Rotation Day"
        score_total:   0-100 composite score
        vix_level:     current VIX level (optional but recommended)
        sectors_green: number of sectors with positive returns (0-11)
        score_delta:   today's score minus yesterday's score
        confidence:    0-100 confidence reading

    Returns:
        dict with:
          - by_environment: stats for all days in this environment
          - by_score_bucket: stats for this score range
          - multi_factor: stats for closest historical matches
          - risk_profile: drawdown/upside asymmetry
          - comparable_dates: recent similar days
          - plain_english: human-readable summary
          - condition_description: what conditions were matched
    """
    df = _load_df()
    warnings: List[str] = []

    # ── By environment ──
    env_subset = _get_environment_match(df, environment)
    by_environment = _build_return_table(env_subset, warnings)
    by_environment["n"] = len(env_subset)

    # ── By score bucket ──
    score_subset, score_bucket_label = _get_score_bucket_match(df, score_total)
    by_score_bucket = _build_return_table(score_subset, warnings)
    by_score_bucket["n"] = len(score_subset)
    by_score_bucket["bucket"] = score_bucket_label

    # ── Multi-factor match ──
    multi_subset, condition_desc = _get_multi_factor_match(
        df,
        environment=environment,
        score=score_total,
        vix=vix_level,
        score_delta=score_delta,
        sectors_green=sectors_green,
    )
    multi_factor = _build_return_table(multi_subset, warnings)
    multi_factor["n"] = len(multi_subset)
    multi_factor["condition_description"] = condition_desc

    # ── Risk profile ──
    risk = _risk_profile(multi_subset if len(multi_subset) >= 15 else env_subset)
    if not risk.get("drawdown_upside_available_horizons") and MACRO_RISK_UNAVAILABLE_WARNING not in warnings:
        warnings.append(MACRO_RISK_UNAVAILABLE_WARNING)

    # ── Comparable dates ──
    comparable_dates = _comparable_dates(multi_subset)

    # ── Plain English ──
    summary = _plain_english_summary(
        environment=environment,
        score=score_total,
        multi_stats=multi_factor,
        risk=risk,
        condition_desc=condition_desc,
        n_matches=len(multi_subset),
        vix=vix_level,
        score_delta=score_delta,
    )

    return {
        "by_environment": by_environment,
        "by_score_bucket": by_score_bucket,
        "multi_factor": multi_factor,
        "risk_profile": risk,
        "comparable_dates": comparable_dates,
        "plain_english_summary": summary,
        "inputs": {
            "environment": environment,
            "score_total": score_total,
            "vix_level": vix_level,
            "sectors_green": sectors_green,
            "score_delta": score_delta,
            "confidence": confidence,
        },
        "available_horizons": [
            label
            for label, column in HORIZONS.items()
            if column in df.columns
        ],
        "missing_horizons": [
            label
            for label, column in HORIZONS.items()
            if column not in df.columns
        ],
        "warnings": warnings,
    }


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = get_conditional_stats(
        environment="Mixed / Neutral",
        score_total=54.2,
        vix_level=25.8,
        sectors_green=5,
        score_delta=-8.0,
        confidence=70.0,
    )
    print(json.dumps({
        k: v for k, v in result.items()
        if k in ["plain_english_summary", "condition_description", "comparable_dates"]
    }, indent=2))
    print()
    print("Multi-factor returns:")
    for horizon, stats in result["multi_factor"].items():
        if isinstance(stats, dict) and "median" in stats:
            print(f"  {horizon}: median={stats['median']:+.2f}%  %pos={stats['pct_positive']:.0f}%  n={stats['n']}")

# ── FastAPI endpoint helper ───────────────────────────────────────────────────

def get_conditional_stats_from_market_state(state_dict: dict) -> dict:
    """
    Convenience wrapper that accepts a MarketState.to_dict() output directly.
    Use this in your FastAPI endpoint:

        from src.analysis.conditional_probability import get_conditional_stats_from_market_state
        result = get_conditional_stats_from_market_state(state.to_dict())
    """
    # Extract score delta from snapshot history if available
    # For now we pass None — the endpoint can compute it from prior snapshot
    return get_conditional_stats(
        environment   = state_dict.get("environment", "Mixed / Neutral"),
        score_total   = state_dict.get("score_total", 50.0),
        vix_level     = state_dict.get("vix_level"),
        sectors_green = state_dict.get("sectors_green"),
        score_delta   = state_dict.get("score_delta"),  # not on MarketState yet, add below
        confidence    = state_dict.get("confidence"),
    )
