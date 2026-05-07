"""
src/analysis/analogues.py

Historical analogue engine — finds the closest past market states
to today's conditions and returns enriched detail for each.

Drop into: backend/src/analysis/analogues.py
Data file: backend/data/backtest_master_file.csv
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

import os
DATA_PATH = Path(os.environ.get("RESEARCH_DATA_PATH", str(Path(__file__).resolve().parents[3] / "data" / "backtest_master_file.csv")))

SCORE_BINS   = [0, 35, 45, 55, 65, 75, 101]
SCORE_LABELS = ["<35", "35-45", "45-55", "55-65", "65-75", ">75"]

VIX_BINS   = [0, 15, 20, 25, 35, 999]
VIX_LABELS = ["<15", "15-20", "20-25", "25-35", ">35"]

SECTOR_MAP = {
    "ret_XLB_1d": "Materials",
    "ret_XLC_1d": "Comm Svcs",
    "ret_XLE_1d": "Energy",
    "ret_XLF_1d": "Financials",
    "ret_XLI_1d": "Industrials",
    "ret_XLK_1d": "Technology",
    "ret_XLP_1d": "Staples",
    "ret_XLRE_1d": "Real Estate",
    "ret_XLU_1d": "Utilities",
    "ret_XLV_1d": "Health Care",
    "ret_XLY_1d": "Discretionary",
}

_df_cache: Optional[pd.DataFrame] = None


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_df() -> pd.DataFrame:
    global _df_cache
    if _df_cache is not None:
        return _df_cache

    df = pd.read_csv(DATA_PATH)
    df = df[df["signal_time"] == "close"].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["score_delta"] = df["score_total"].diff()

    df["score_bucket"] = pd.cut(
        df["score_total"], bins=SCORE_BINS, labels=SCORE_LABELS, right=False
    )
    df["vix_bucket"] = pd.cut(
        df["vix_level"], bins=VIX_BINS, labels=VIX_LABELS, right=False
    )

    _df_cache = df
    return df


# ── Similarity scoring ────────────────────────────────────────────────────────

def _similarity_score(row: pd.Series, inputs: Dict[str, Any]) -> float:
    """
    Compute a 0-100 similarity score between a historical row and current inputs.
    Lower is more similar (like a distance metric).
    """
    penalties = 0.0

    # Score distance (most important — weight 40%)
    score_diff = abs(row["score_total"] - inputs["score_total"])
    penalties += score_diff * 0.4

    # VIX distance (weight 25%)
    if inputs.get("vix_level") and pd.notna(row.get("vix_level")):
        vix_diff = abs(row["vix_level"] - inputs["vix_level"])
        penalties += vix_diff * 0.25

    # Sectors green distance (weight 15%)
    if inputs.get("sectors_green") is not None and pd.notna(row.get("sectors_green")):
        breadth_diff = abs(row["sectors_green"] - inputs["sectors_green"])
        penalties += breadth_diff * 1.5  # scale: 0-11 range

    # Score delta direction match (weight 20%)
    if inputs.get("score_delta") is not None and pd.notna(row.get("score_delta")):
        # Penalize if delta direction mismatches
        same_direction = (
            (inputs["score_delta"] > 3 and row["score_delta"] > 3) or
            (inputs["score_delta"] < -3 and row["score_delta"] < -3) or
            (abs(inputs["score_delta"]) <= 3 and abs(row["score_delta"]) <= 3)
        )
        if not same_direction:
            penalties += 8.0

    return round(float(penalties), 2)


# ── Forward path builder ──────────────────────────────────────────────────────

def _forward_path(df: pd.DataFrame, date: pd.Timestamp, days: int = 21) -> List[Dict]:
    spy = df[["date", "spy_close"]].set_index("date")
    future = spy[spy.index > date].head(days)
    if future.empty:
        return []
    base_rows = spy[spy.index == date]
    if base_rows.empty:
        return []
    base = float(base_rows.iloc[0]["spy_close"])
    if base == 0:
        return []
    return [
        {
            "date": d.strftime("%Y-%m-%d"),
            "ret_pct": round((float(p) / base - 1) * 100, 3),
        }
        for d, p in zip(future.index, future["spy_close"])
    ]


# ── Per-date enrichment ───────────────────────────────────────────────────────

def _enrich_row(row: pd.Series, df: pd.DataFrame, similarity: float) -> Dict[str, Any]:
    date = row["date"]
    fwd_path = _forward_path(df, date, days=21)

    # Sector returns for this date
    sectors = {}
    for col, name in SECTOR_MAP.items():
        val = row.get(col)
        if pd.notna(val):
            sectors[name] = round(float(val) * 100, 2)

    # Score components
    components = {}
    for layer in ["monetary", "credit", "volatility", "breadth", "positioning"]:
        val = row.get(f"layer_{layer}")
        if pd.notna(val):
            components[layer] = round(float(val), 2)
    # Fallback to v1 components if v2 not present
    if not components:
        for comp in ["risk_on", "trend_strength", "vol_mood", "participation", "leadership_clarity"]:
            val = row.get(f"comp__{comp}")
            if pd.notna(val):
                components[comp] = round(float(val), 2)

    def _pct(val):
        return round(float(val) * 100, 2) if pd.notna(val) else None

    def _f(val, d=2):
        return round(float(val), d) if pd.notna(val) else None

    return {
        "date": date.strftime("%Y-%m-%d"),
        "similarity_score": similarity,
        "score_total": _f(row["score_total"], 1),
        "confidence": _f(row.get("confidence"), 1),
        "environment": str(row.get("environment", "")),
        "score_delta": _f(row.get("score_delta"), 1),
        "vix_level": _f(row.get("vix_level"), 1),
        "vix_z_20d": _f(row.get("vix_z_20d"), 2),
        "sectors_green": int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
        "dispersion": _f(row.get("dispersion"), 4),
        "spy_close": _f(row.get("spy_close"), 2),
        "score_components": components,
        "sector_returns": sectors,
        "forward_returns": {
            "1d":  _pct(row.get("fwd_ret_cc_1d")),
            "5d":  _pct(row.get("fwd_ret_cc_5d")),
            "10d": _pct(row.get("fwd_ret_cc_10d")),
            "21d": _pct(row.get("fwd_ret_cc_21d")),
        },
        "risk_profile": {
            "max_drawdown_5d": _pct(row.get("fwd_5d_max_drawdown_pct")),
            "max_upside_5d":   _pct(row.get("fwd_5d_max_upside_pct")),
        },
        "forward_path": fwd_path,
        "layer_agreement": _f(row.get("layer_agreement"), 2),
        "environment_drivers": [],  # not stored per-row in CSV
    }


# ── Aggregate stats ───────────────────────────────────────────────────────────

def _aggregate_stats(analogues: List[Dict]) -> Dict[str, Any]:
    def _horizon_stats(key: str) -> Dict:
        vals = [
            a["forward_returns"][key]
            for a in analogues
            if a["forward_returns"].get(key) is not None
        ]
        if len(vals) < 3:
            return {"n": len(vals)}
        arr = np.array(vals)
        return {
            "n": len(arr),
            "median": round(float(np.median(arr)), 2),
            "mean": round(float(arr.mean()), 2),
            "pct_positive": round(float((arr > 0).mean() * 100), 1),
            "p10": round(float(np.percentile(arr, 10)), 2),
            "p25": round(float(np.percentile(arr, 25)), 2),
            "p75": round(float(np.percentile(arr, 75)), 2),
            "p90": round(float(np.percentile(arr, 90)), 2),
            "worst": round(float(arr.min()), 2),
            "best":  round(float(arr.max()), 2),
            "distribution": [round(float(v), 2) for v in sorted(arr)],
        }

    drawdowns = [
        a["risk_profile"]["max_drawdown_5d"]
        for a in analogues
        if a["risk_profile"].get("max_drawdown_5d") is not None
    ]
    upsides = [
        a["risk_profile"]["max_upside_5d"]
        for a in analogues
        if a["risk_profile"].get("max_upside_5d") is not None
    ]

    risk = {}
    if drawdowns and upsides:
        med_dd = abs(np.median(drawdowns))
        med_up = np.median(upsides)

        # Raw reward/risk (unweighted, based on 5d max range)
        risk["reward_risk_ratio"] = round(float(med_up / med_dd), 2) if med_dd > 0 else None

        # Win rate from 21d forward returns
        fwd_21d_vals = [
            a["forward_returns"]["21d"]
            for a in analogues
            if a["forward_returns"].get("21d") is not None
        ]
        if fwd_21d_vals:
            win_rate = float(sum(1 for v in fwd_21d_vals if v > 0) / len(fwd_21d_vals))
            loss_rate = 1.0 - win_rate

            # Expected value using 21d forward return magnitude
            med_fwd_21d_up = float(np.median([v for v in fwd_21d_vals if v > 0])) if any(v > 0 for v in fwd_21d_vals) else 0.0
            med_fwd_21d_dn = float(np.median([v for v in fwd_21d_vals if v <= 0])) if any(v <= 0 for v in fwd_21d_vals) else 0.0

            ev = (win_rate * med_fwd_21d_up) + (loss_rate * med_fwd_21d_dn)
            risk["expected_value_21d"] = round(float(ev), 2)
            risk["win_rate_21d"] = round(win_rate * 100, 1)

            # Probability-weighted reward/risk using 21d realized returns
            if loss_rate > 0 and med_fwd_21d_dn != 0:
                weighted_rr = (win_rate * med_fwd_21d_up) / (loss_rate * abs(med_fwd_21d_dn))
                risk["weighted_reward_risk_21d"] = round(float(weighted_rr), 2)
            else:
                risk["weighted_reward_risk_21d"] = None
                
    # Environment transition counts
    env_counts = {}
    for a in analogues:
        e = a.get("environment", "Unknown")
        env_counts[e] = env_counts.get(e, 0) + 1

    return {
        "n_analogues": len(analogues),
        "forward_returns": {
            "1d":  _horizon_stats("1d"),
            "5d":  _horizon_stats("5d"),
            "10d": _horizon_stats("10d"),
            "21d": _horizon_stats("21d"),
        },
        "risk_profile": risk,
        "environment_distribution": env_counts,
    }


# ── Main public function ──────────────────────────────────────────────────────

def get_historical_analogues(
    environment: str,
    score_total: float,
    vix_level: Optional[float] = None,
    sectors_green: Optional[int] = None,
    score_delta: Optional[float] = None,
    confidence: Optional[float] = None,
    top_n: int = 15,
    min_score_window: float = 15.0,
) -> Dict[str, Any]:
    """
    Find the top_n most similar historical market states and return
    enriched detail for each plus aggregate statistics.

    Args:
        environment:      Current environment classification
        score_total:      0-100 composite score
        vix_level:        Current VIX level
        sectors_green:    Number of positive sectors (0-11)
        score_delta:      Today's score minus yesterday's
        confidence:       0-100 confidence reading
        top_n:            Number of analogues to return (default 15)
        min_score_window: Minimum score distance window (default ±15)

    Returns:
        {
          analogues: [...],          # enriched per-date details, ranked by similarity
          aggregate_stats: {...},    # distribution stats across all analogues
          inputs: {...},             # echo of inputs for reference
          conditions_matched: str,   # human-readable description
        }
    """
    df = _load_df()

    inputs = {
        "environment": environment,
        "score_total": score_total,
        "vix_level": vix_level,
        "sectors_green": sectors_green,
        "score_delta": score_delta,
        "confidence": confidence,
    }

    # ── Filter to same environment first ──
    pool = df[df["environment"] == environment].copy()

    # ── Score window filter ──
    pool = pool[
        (pool["score_total"] >= score_total - min_score_window) &
        (pool["score_total"] <= score_total + min_score_window)
    ]

    # ── Compute similarity for every candidate ──
    if pool.empty:
        # Fallback: relax to any environment if no matches
        pool = df[
            (df["score_total"] >= score_total - min_score_window) &
            (df["score_total"] <= score_total + min_score_window)
        ].copy()

    pool = pool.copy()
    pool["_similarity"] = pool.apply(
        lambda row: _similarity_score(row, inputs), axis=1
    )

    # ── Select top N most similar ──
    top = pool.nsmallest(top_n, "_similarity")

    # ── Enrich each row ──
    analogues = [
        _enrich_row(row, df, float(row["_similarity"]))
        for _, row in top.iterrows()
    ]

    # ── Sort by date descending (most recent first) for display ──
    analogues.sort(key=lambda x: x["date"], reverse=True)

    # ── Aggregate stats ──
    agg = _aggregate_stats(analogues)

    # ── Conditions description ──
    conditions = [f"environment={environment}", f"score≈{score_total:.0f}"]
    if vix_level is not None:
        vb = pd.cut([vix_level], bins=VIX_BINS, labels=VIX_LABELS, right=False)[0]
        conditions.append(f"vix={vb}")
    if sectors_green is not None:
        conditions.append(f"breadth={'strong' if sectors_green >= 6 else 'weak'}")
    if score_delta is not None:
        if score_delta < -3:
            conditions.append("score_deteriorating")
        elif score_delta > 3:
            conditions.append("score_improving")

    return {
        "analogues": analogues,
        "aggregate_stats": agg,
        "inputs": inputs,
        "conditions_matched": " · ".join(conditions),
    }


# ── Quick test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    result = get_historical_analogues(
        environment="Mixed / Neutral",
        score_total=54.2,
        vix_level=25.8,
        sectors_green=5,
        score_delta=-8.0,
        top_n=10,
    )

    print(f"Found {result['aggregate_stats']['n_analogues']} analogues")
    print(f"Conditions: {result['conditions_matched']}")
    print()
    print("Top 5 most recent:")
    for a in result["analogues"][:5]:
        fwd = a["forward_returns"]
        print(
            f"  {a['date']}  score={a['score_total']:.0f}  "
            f"vix={a['vix_level']}  "
            f"1d={fwd['1d']:+.2f}%  5d={fwd['5d']:+.2f}%  "
            f"21d={fwd['21d']:+.2f}%  "
            f"similarity={a['similarity_score']}"
        )
    print()
    print("Aggregate 5d stats:")
    s5 = result["aggregate_stats"]["forward_returns"]["5d"]
    print(f"  median={s5['median']:+.2f}%  %pos={s5['pct_positive']:.0f}%  "
          f"p25={s5['p25']:+.2f}%  p75={s5['p75']:+.2f}%")

# Note: set RESEARCH_DATA_PATH env var if running outside the backend folder:
# export RESEARCH_DATA_PATH=/path/to/backend/data/backtest_master_file.csv