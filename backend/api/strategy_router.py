"""
api/strategy_router.py

Custom strategy backtesting endpoints.
Mount in main.py with: app.include_router(strategy_router)

Endpoints:
  POST /api/strategy/backtest   — run backtest with custom params
  POST /api/strategy/config     — save a named config
  GET  /api/strategy/config/{name} — load a config
  GET  /api/strategy/configs    — list saved configs
  GET  /api/strategy/defaults   — return default weights + thresholds
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

strategy_router = APIRouter(prefix="/api/strategy", tags=["strategy"])

# ── Config ────────────────────────────────────────────────────────────────────

DATA_PATH = Path(os.environ.get(
    "RESEARCH_DATA_PATH",
    str(Path(__file__).resolve().parents[1] / "data" / "operator_research_v2.csv")
))

STRATEGY_DIR = Path(os.environ.get(
    "STRATEGY_DIR",
    str(Path(__file__).resolve().parents[1] / "data" / "strategies")
))

_df_cache: Optional[pd.DataFrame] = None


# ── Pydantic models ───────────────────────────────────────────────────────────

class LayerWeights(BaseModel):
    monetary:    float = Field(default=0.20, ge=0.0, le=1.0)
    credit:      float = Field(default=0.22, ge=0.0, le=1.0)
    volatility:  float = Field(default=0.22, ge=0.0, le=1.0)
    breadth:     float = Field(default=0.20, ge=0.0, le=1.0)
    positioning: float = Field(default=0.16, ge=0.0, le=1.0)


class LayerThresholds(BaseModel):
    # Credit
    hy_spread_tight:   float = Field(default=350.0, description="HY spread below this = tight (bps)")
    hy_spread_stressed: float = Field(default=600.0, description="HY spread above this = stressed (bps)")
    # Volatility
    vix_calm:          float = Field(default=15.0,  description="VIX below this = calm")
    vix_stressed:      float = Field(default=30.0,  description="VIX above this = stressed")
    vix_term_backwardation: float = Field(default=-2.0, description="VIX3M-VIX below this = backwardation")
    # Breadth
    breadth_strong:    float = Field(default=70.0,  description="% above 200d MA above this = strong")
    breadth_weak:      float = Field(default=40.0,  description="% above 200d MA below this = weak")
    sectors_strong:    int   = Field(default=7,     description="Sectors green above this = strong")
    sectors_weak:      int   = Field(default=3,     description="Sectors green below this = weak")
    # Monetary
    m2_growth_strong:  float = Field(default=8.0,   description="M2 YoY % above this = strong")
    m2_growth_weak:    float = Field(default=0.0,   description="M2 YoY % below this = weak")
    # Environment classification thresholds
    bull_score:        float = Field(default=70.0,  description="Composite score above this = bull regime")
    bear_score:        float = Field(default=38.0,  description="Composite score below this = bear regime")
    chop_agreement:    float = Field(default=0.4,   description="Layer agreement below this = chop")


class StrategyConfig(BaseModel):
    name:        str
    description: str = ""
    weights:     LayerWeights = LayerWeights()
    thresholds:  LayerThresholds = LayerThresholds()
    horizon:     str = "default"


class BacktestRequest(BaseModel):
    weights:    LayerWeights = LayerWeights()
    thresholds: LayerThresholds = LayerThresholds()
    horizon:    str = "default"
    start_date: Optional[str] = None
    end_date:   Optional[str] = None


# ── Data loading ──────────────────────────────────────────────────────────────

def _load_df() -> pd.DataFrame:
    global _df_cache
    if _df_cache is not None:
        return _df_cache
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Research data not found: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)
    df = df[df["signal_time"] == "close"].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["score_delta"] = df["score_total"].diff()
    _df_cache = df
    return df


# ── Custom scoring ────────────────────────────────────────────────────────────

def _scale(value: float, lo: float, hi: float, invert: bool = False) -> float:
    if hi == lo:
        return 5.0
    scaled = float(np.clip((value - lo) / (hi - lo) * 10.0, 0.0, 10.0))
    return 10.0 - scaled if invert else scaled


def _safe(x) -> Optional[float]:
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _score_row_custom(row: pd.Series, weights: LayerWeights, thresholds: LayerThresholds) -> Dict[str, Any]:
    """
    Score a single historical row using custom weights and thresholds.
    Returns layer scores, composite, and environment.
    """
    w = weights
    t = thresholds

    # ── Layer 1: Monetary ──
    monetary_parts = []
    net_liq_z = _safe(row.get("net_liquidity_z"))
    if net_liq_z is not None:
        monetary_parts.append(_scale(net_liq_z, -2.0, 2.0))
    m2 = _safe(row.get("m2_growth_yoy"))
    if m2 is not None:
        monetary_parts.append(_scale(m2, t.m2_growth_weak, t.m2_growth_strong))
    layer_monetary = float(np.mean(monetary_parts)) if monetary_parts else 5.0

    # ── Layer 2: Credit ──
    credit_parts = []
    hy = _safe(row.get("hy_spread_level"))
    if hy is not None:
        credit_parts.append(_scale(hy, t.hy_spread_tight, t.hy_spread_stressed, invert=True))
    hy_z = _safe(row.get("hy_spread_z"))
    if hy_z is not None:
        credit_parts.append(_scale(hy_z, -2.0, 3.0, invert=True))
    hy_chg = _safe(row.get("hy_spread_chg_4w"))
    if hy_chg is not None:
        credit_parts.append(_scale(hy_chg, -80.0, 150.0, invert=True))
    ig = _safe(row.get("ig_spread_level"))
    if ig is not None:
        credit_parts.append(_scale(ig, 60.0, 300.0, invert=True))
    hyg_tlt_z = _safe(row.get("hyg_tlt_ratio_z"))
    if hyg_tlt_z is not None:
        credit_parts.append(_scale(hyg_tlt_z, -2.5, 2.5))
    layer_credit = float(np.mean(credit_parts)) if credit_parts else 5.0

    # ── Layer 3: Volatility ──
    vol_parts = []
    vix = _safe(row.get("vix_level"))
    if vix is not None:
        vol_parts.append(_scale(vix, t.vix_calm, t.vix_stressed, invert=True))
    vix_z = _safe(row.get("vix_z_20d"))
    if vix_z is not None:
        vol_parts.append(_scale(vix_z, -1.5, 3.0, invert=True))
    vix_slope = _safe(row.get("vix_term_slope"))
    if vix_slope is not None:
        vol_parts.append(_scale(vix_slope, t.vix_term_backwardation, 8.0))
    vvix = _safe(row.get("vvix_level"))
    if vvix is not None:
        vol_parts.append(_scale(vvix, 70.0, 130.0, invert=True))
    layer_volatility = float(np.mean(vol_parts)) if vol_parts else 5.0

    # ── Layer 4: Breadth ──
    breadth_parts = []
    pct_200d = _safe(row.get("pct_above_200d"))
    if pct_200d is not None:
        breadth_parts.append(_scale(pct_200d, t.breadth_weak, t.breadth_strong))
    hl_z = _safe(row.get("new_highs_minus_lows_z"))
    if hl_z is not None:
        breadth_parts.append(_scale(hl_z, -2.5, 2.5))
    sec_green = _safe(row.get("sectors_green"))
    if sec_green is not None:
        breadth_parts.append(_scale(sec_green, t.sectors_weak, t.sectors_strong))
    rsp_z = _safe(row.get("rsp_vs_spy_z"))
    if rsp_z is not None:
        breadth_parts.append(_scale(rsp_z, -2.0, 2.0))
    layer_breadth = float(np.mean(breadth_parts)) if breadth_parts else 5.0

    # ── Layer 5: Positioning ──
    pos_parts = []
    pcr = _safe(row.get("put_call_ratio"))
    if pcr is not None:
        if pcr > 0.95:
            pos_parts.append(7.5)
        elif pcr < 0.60:
            pos_parts.append(2.5)
        else:
            pos_parts.append(5.0)
    layer_positioning = float(np.mean(pos_parts)) if pos_parts else 5.0

    # ── Composite ──
    total_weight = w.monetary + w.credit + w.volatility + w.breadth + w.positioning
    if total_weight == 0:
        total_weight = 1.0
    composite = (
        layer_monetary   * (w.monetary    / total_weight) +
        layer_credit     * (w.credit      / total_weight) +
        layer_volatility * (w.volatility  / total_weight) +
        layer_breadth    * (w.breadth     / total_weight) +
        layer_positioning * (w.positioning / total_weight)
    ) * 10.0

    # ── Layer agreement ──
    scores = [layer_monetary, layer_credit, layer_volatility, layer_breadth, layer_positioning]
    above   = sum(1 for s in scores if s >= 6.5)
    below   = sum(1 for s in scores if s <= 3.5)
    neutral = len(scores) - above - below
    majority = max(above, below, neutral)
    agreement = (majority / len(scores) - 1/3) / (2/3)

    # ── Environment ──
    if composite >= t.bull_score and above >= 3:
        if layer_breadth >= 7 and layer_volatility >= 6:
            env = "Trend Day — Broad Participation"
        elif layer_monetary >= 7 and layer_credit >= 7:
            env = "Risk-On — Liquidity Driven"
        else:
            env = "Risk-On Rotation Day"
    elif composite <= t.bear_score or (layer_credit <= 3.5 and layer_volatility <= 3.5):
        env = "Risk-Off / Headline Risk"
    elif agreement < t.chop_agreement:
        env = "Chop / Layer Divergence"
    elif layer_positioning >= 7 and composite <= 50:
        env = "Fear Exhaustion — Mean Reversion Setup"
    else:
        env = "Mixed / Neutral"

    return {
        "layer_monetary":    round(layer_monetary, 2),
        "layer_credit":      round(layer_credit, 2),
        "layer_volatility":  round(layer_volatility, 2),
        "layer_breadth":     round(layer_breadth, 2),
        "layer_positioning": round(layer_positioning, 2),
        "score_total":       round(composite, 2),
        "layer_agreement":   round(agreement, 3),
        "environment":       env,
    }


# ── Backtest runner ───────────────────────────────────────────────────────────

def _run_backtest(
    df: pd.DataFrame,
    weights: LayerWeights,
    thresholds: LayerThresholds,
) -> Dict[str, Any]:
    """
    Run custom scoring across all historical rows.
    Returns classified history + forward return stats by environment.
    """
    results = []
    for _, row in df.iterrows():
        scored = _score_row_custom(row, weights, thresholds)
        results.append({
            "date":        row["date"].strftime("%Y-%m-%d"),
            "score_total": scored["score_total"],
            "environment": scored["environment"],
            "layer_monetary":    scored["layer_monetary"],
            "layer_credit":      scored["layer_credit"],
            "layer_volatility":  scored["layer_volatility"],
            "layer_breadth":     scored["layer_breadth"],
            "layer_positioning": scored["layer_positioning"],
            "layer_agreement":   scored["layer_agreement"],
            "fwd_1d":  round(float(row["fwd_ret_cc_1d"])  * 100, 3) if pd.notna(row.get("fwd_ret_cc_1d"))  else None,
            "fwd_5d":  round(float(row["fwd_ret_cc_5d"])  * 100, 3) if pd.notna(row.get("fwd_ret_cc_5d"))  else None,
            "fwd_21d": round(float(row["fwd_ret_cc_21d"]) * 100, 3) if pd.notna(row.get("fwd_ret_cc_21d")) else None,
            "fwd_63d": round(float(row["fwd_ret_cc_63d"]) * 100, 3) if pd.notna(row.get("fwd_ret_cc_63d")) else None,
            "max_dd_5d": round(float(row["fwd_5d_max_drawdown_pct"]) * 100, 3) if pd.notna(row.get("fwd_5d_max_drawdown_pct")) else None,
            "max_up_5d": round(float(row["fwd_5d_max_upside_pct"])   * 100, 3) if pd.notna(row.get("fwd_5d_max_upside_pct"))   else None,
            "vix_level": round(float(row["vix_level"]), 1) if pd.notna(row.get("vix_level")) else None,
        })

    scored_df = pd.DataFrame(results)

    # ── Per-environment stats ──
    env_stats = {}
    for env, grp in scored_df.groupby("environment"):
        def _stats(col: str) -> Dict:
            s = grp[col].dropna()
            if len(s) < 3:
                return {"n": len(s)}
            return {
                "n":            int(len(s)),
                "median":       round(float(s.median()), 2),
                "pct_positive": round(float((s > 0).mean() * 100), 1),
                "p25":          round(float(s.quantile(0.25)), 2),
                "p75":          round(float(s.quantile(0.75)), 2),
                "worst":        round(float(s.min()), 2),
                "best":         round(float(s.max()), 2),
            }

        dd   = grp["max_dd_5d"].dropna()
        up   = grp["max_up_5d"].dropna()
        rr   = round(float(up.median() / abs(dd.median())), 2) if len(dd) > 0 and len(up) > 0 and dd.median() != 0 else None

        fwd_5d_vals = grp["fwd_5d"].dropna()
        win_rate    = round(float((fwd_5d_vals > 0).mean() * 100), 1) if len(fwd_5d_vals) > 0 else None
        ev_5d       = None
        if len(fwd_5d_vals) >= 5 and len(dd) >= 5 and len(up) >= 5:
            wr = (fwd_5d_vals > 0).mean()
            ev_5d = round(float(wr * float(up.median()) + (1 - wr) * float(dd.median())), 2)

        env_stats[str(env)] = {
            "count":    int(len(grp)),
            "pct_days": round(len(grp) / len(scored_df) * 100, 1),
            "fwd_1d":   _stats("fwd_1d"),
            "fwd_5d":   _stats("fwd_5d"),
            "fwd_21d":  _stats("fwd_21d"),
            "fwd_63d":  _stats("fwd_63d"),
            "reward_risk_5d": rr,
            "win_rate_5d":    win_rate,
            "ev_5d":          ev_5d,
        }

    # ── Score distribution ──
    score_dist = {
        "mean":   round(float(scored_df["score_total"].mean()), 1),
        "median": round(float(scored_df["score_total"].median()), 1),
        "p10":    round(float(scored_df["score_total"].quantile(0.10)), 1),
        "p90":    round(float(scored_df["score_total"].quantile(0.90)), 1),
        "pct_bull": round(float((scored_df["score_total"] >= thresholds.bull_score).mean() * 100), 1),
        "pct_bear": round(float((scored_df["score_total"] <= thresholds.bear_score).mean() * 100), 1),
    }

    # ── Score time series (sampled for charting — every 5th row) ──
    score_series = scored_df[["date", "score_total", "environment"]].iloc[::5].to_dict(orient="records")

    return {
        "n_days":        len(scored_df),
        "date_range":    {"start": scored_df["date"].iloc[0], "end": scored_df["date"].iloc[-1]},
        "env_stats":     env_stats,
        "score_dist":    score_dist,
        "score_series":  score_series,
        "env_counts":    scored_df["environment"].value_counts().to_dict(),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@strategy_router.get("/defaults")
async def get_defaults():
    """Return default weights and thresholds."""
    return {
        "weights":    LayerWeights().model_dump(),
        "thresholds": LayerThresholds().model_dump(),
        "descriptions": {
            "weights": {
                "monetary":    "Fed balance sheet + M2 growth. Slow-moving — set higher for macro-driven strategies",
                "credit":      "HY/IG spreads. Most predictive layer — default weight is highest",
                "volatility":  "VIX level + term structure + VVIX. Key for vol-regime strategies",
                "breadth":     "% stocks above 200d MA + new highs/lows. Important for confirming rallies",
                "positioning": "Put/call ratio + sentiment. Contrarian signals — weight lower for trend strategies",
            },
            "thresholds": {
                "hy_spread_tight":    "HY spreads below this level score maximum credit health (bps)",
                "hy_spread_stressed": "HY spreads above this level score maximum credit stress (bps)",
                "vix_calm":           "VIX below this scores maximum calm. Lower = tighter calm definition",
                "vix_stressed":       "VIX above this scores maximum stress. Lower = triggers stress sooner",
                "bull_score":         "Composite score above this triggers bull regime classification",
                "bear_score":         "Composite score below this triggers bear regime classification",
                "chop_agreement":     "Layer agreement below this triggers Chop classification (0-1)",
            }
        }
    }


@strategy_router.post("/backtest")
async def run_backtest(req: BacktestRequest):
    """
    Run backtest with custom weights and thresholds.
    Returns per-environment forward return statistics.
    """
    import asyncio
    df = _load_df()

    # Date filter
    if req.start_date:
        df = df[df["date"] >= pd.Timestamp(req.start_date)]
    if req.end_date:
        df = df[df["date"] <= pd.Timestamp(req.end_date)]

    if len(df) < 20:
        raise HTTPException(400, "Not enough data for the specified date range")

    # Run in thread — CPU bound
    result = await asyncio.to_thread(_run_backtest, df, req.weights, req.thresholds)

    # Echo back the config used
    result["config_used"] = {
        "weights":    req.weights.model_dump(),
        "thresholds": req.thresholds.model_dump(),
        "horizon":    req.horizon,
    }

    return result


@strategy_router.post("/config")
async def save_config(config: StrategyConfig):
    """Save a named strategy configuration."""
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in config.name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid strategy name")
    path = STRATEGY_DIR / f"{safe_name}.json"
    path.write_text(json.dumps(config.model_dump(), indent=2))
    return {"saved": safe_name, "path": str(path)}


@strategy_router.get("/configs")
async def list_configs():
    """List all saved strategy configurations."""
    STRATEGY_DIR.mkdir(parents=True, exist_ok=True)
    configs = []
    for f in sorted(STRATEGY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            configs.append({
                "name":        data.get("name", f.stem),
                "description": data.get("description", ""),
                "filename":    f.stem,
            })
        except Exception:
            pass
    return {"configs": configs}


@strategy_router.get("/config/{name}")
async def load_config(name: str):
    """Load a saved strategy configuration."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    path = STRATEGY_DIR / f"{safe_name}.json"
    if not path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    return json.loads(path.read_text())


@strategy_router.delete("/config/{name}")
async def delete_config(name: str):
    """Delete a saved strategy configuration."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    path = STRATEGY_DIR / f"{safe_name}.json"
    if not path.exists():
        raise HTTPException(404, f"Config '{name}' not found")
    path.unlink()
    return {"deleted": safe_name}


# ── Score Analysis endpoints ───────────────────────────────────────────────────

_score_history_cache: Optional[List[Dict]] = None


@strategy_router.get("/score-history")
async def get_score_history():
    """Return full close-only score history for charting."""
    global _score_history_cache
    if _score_history_cache is not None:
        return {"series": _score_history_cache}

    def _build():
        df = _load_df()
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "date": r["date"].strftime("%Y-%m-%d"),
                "score": round(float(r["score_total"]), 2) if pd.notna(r["score_total"]) else None,
                "environment": r["environment"] if pd.notna(r.get("environment", None)) else "Unknown",
            })
        return rows

    _score_history_cache = await asyncio.to_thread(_build)
    return {"series": _score_history_cache}


class SecondaryCondition(BaseModel):
    field: str = Field(..., description="CSV column name: vix_level | hy_spread_level | layer_credit | layer_volatility | layer_breadth")
    operator: str = Field(..., description="gt | lt | gte | lte")
    value: float


class ThresholdRequest(BaseModel):
    score_threshold: float = Field(..., ge=0.0, le=100.0)
    direction: str = Field(..., description="above | below")
    secondary_condition: Optional[SecondaryCondition] = None
    ticker: str = "SPY"


_SECONDARY_FIELD_MAP = {
    "vix_level": "vix_level",
    "hy_spread_level": "hy_spread_level",
    "layer_credit": "layer_credit",
    "layer_volatility": "layer_volatility",
    "layer_breadth": "layer_breadth",
}

_OP_MAP = {
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
}


@strategy_router.post("/threshold-instances")
async def get_threshold_instances(req: ThresholdRequest):
    """
    Find all historical instances matching score threshold + optional secondary condition.
    Returns each instance with 5d/21d/63d forward returns, a 21-day forward path,
    and aggregate summary statistics.
    """

    def _compute():
        df = _load_df()

        # Primary filter
        if req.direction == "above":
            mask = df["score_total"] >= req.score_threshold
        else:
            mask = df["score_total"] <= req.score_threshold

        # Secondary filter
        if req.secondary_condition is not None:
            col = _SECONDARY_FIELD_MAP.get(req.secondary_condition.field)
            if col is None or col not in df.columns:
                raise HTTPException(400, f"Unknown secondary field: {req.secondary_condition.field}")
            op_fn = _OP_MAP.get(req.secondary_condition.operator)
            if op_fn is None:
                raise HTTPException(400, f"Unknown operator: {req.secondary_condition.operator}")
            sec_mask = df[col].apply(lambda v: bool(op_fn(v, req.secondary_condition.value)) if pd.notna(v) else False)
            mask = mask & sec_mask

        matched = df[mask].copy()

        instances = []
        fwd_5d_vals, fwd_21d_vals, fwd_63d_vals = [], [], []

        for idx in matched.index:
            row = df.loc[idx]

            fwd_5  = _safe(row.get("fwd_ret_cc_5d"))
            fwd_21 = _safe(row.get("fwd_ret_cc_21d"))
            fwd_63 = _safe(row.get("fwd_ret_cc_63d"))

            if fwd_5  is not None: fwd_5d_vals.append(fwd_5)
            if fwd_21 is not None: fwd_21d_vals.append(fwd_21)
            if fwd_63 is not None: fwd_63d_vals.append(fwd_63)

            # Build 21-day forward path from subsequent rows' spy_close prices
            path_rows = df.iloc[idx + 1: idx + 22]
            if len(path_rows) > 0 and pd.notna(row.get("spy_close")) and float(row["spy_close"]) > 0:
                base = float(row["spy_close"])
                forward_path = [
                    round((float(r["spy_close"]) / base - 1.0) * 100.0, 4)
                    for _, r in path_rows.iterrows()
                    if pd.notna(r.get("spy_close"))
                ]
            else:
                forward_path = []

            instances.append({
                "date": row["date"].strftime("%Y-%m-%d"),
                "score": round(float(row["score_total"]), 1) if pd.notna(row["score_total"]) else None,
                "environment": str(row.get("environment", "")) if pd.notna(row.get("environment")) else "",
                "vix": round(float(row["vix_level"]), 1) if pd.notna(row.get("vix_level")) else None,
                "fwd_5d": round(fwd_5 * 100.0, 2) if fwd_5 is not None else None,
                "fwd_21d": round(fwd_21 * 100.0, 2) if fwd_21 is not None else None,
                "fwd_63d": round(fwd_63 * 100.0, 2) if fwd_63 is not None else None,
                "forward_path": forward_path,
            })

        # Sort newest first
        instances.sort(key=lambda x: x["date"], reverse=True)

        def _stats(vals):
            if not vals:
                return {"median": None, "pct_positive": None, "p25": None, "p75": None}
            arr = np.array(vals) * 100.0
            return {
                "median": round(float(np.median(arr)), 2),
                "pct_positive": round(float(np.mean(arr > 0)) * 100.0, 1),
                "p25": round(float(np.percentile(arr, 25)), 2),
                "p75": round(float(np.percentile(arr, 75)), 2),
            }

        summary = {
            "n": len(instances),
            "fwd_5d":  _stats(fwd_5d_vals),
            "fwd_21d": _stats(fwd_21d_vals),
            "fwd_63d": _stats(fwd_63d_vals),
        }

        return {"instances": instances, "summary": summary}

    return await asyncio.to_thread(_compute)