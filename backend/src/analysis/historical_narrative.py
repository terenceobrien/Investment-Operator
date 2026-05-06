"""
src/analysis/historical_narrative.py

Generates a retrospective market narrative for any historical date
using only quantitative market structure data (no news required).

Drop into: backend/src/analysis/historical_narrative.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
import pandas as pd

DATA_PATH = Path(os.environ.get(
    "RESEARCH_DATA_PATH",
    str(Path(__file__).resolve().parents[3] / "data" / "operator_research_v2.csv")
))

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
_narrative_cache: Dict[str, Any] = {}


def _load_df() -> pd.DataFrame:
    global _df_cache
    if _df_cache is not None:
        return _df_cache
    df = pd.read_csv(DATA_PATH)
    df = df[df["signal_time"] == "close"].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df["score_delta"] = df["score_total"].diff()
    _df_cache = df
    return df


def _build_context(date_str: str) -> Optional[Dict[str, Any]]:
    df = _load_df()
    rows = df[df["date"].dt.strftime("%Y-%m-%d") == date_str]
    if rows.empty:
        return None
    row = rows.iloc[0]

    def pct(v, d=2):
        if pd.isna(v): return None
        return round(float(v) * 100, d)

    def f(v, d=2):
        if pd.isna(v): return None
        return round(float(v), d)

    sectors = {}
    for col, name in SECTOR_MAP.items():
        val = row.get(col)
        if pd.notna(val):
            sectors[name] = pct(val)
    sectors_sorted = dict(sorted(sectors.items(), key=lambda x: x[1] or 0, reverse=True))

    return {
        "date": date_str,
        "environment": str(row.get("environment", "")),
        "score_total": f(row.get("score_total"), 1),
        "score_delta": f(row.get("score_delta"), 1),
        "confidence": f(row.get("confidence"), 1),
        "components": {
            "risk_on":           f(row.get("comp__risk_on"), 1),
            "trend_strength":    f(row.get("comp__trend_strength"), 1),
            "vol_mood":          f(row.get("comp__vol_mood"), 1),
            "participation":     f(row.get("comp__participation"), 1),
            "leadership_clarity": f(row.get("comp__leadership_clarity"), 1),
        },
        "vix": {
            "level":      f(row.get("vix_level"), 1),
            "z_20d":      f(row.get("vix_z_20d"), 2),
            "change_pct": pct(row.get("vix_change_pct_1d"), 1),
        },
        "spy": {
            "close":         f(row.get("spy_close"), 2),
            "clv":           f(row.get("spy_clv"), 3),
            "range_pct":     pct(row.get("spy_range_pct"), 2),
            "vol_vs_20d_pct": f(row.get("spy_vol_vs_20d_pct"), 1),
        },
        "breadth": {
            "sectors_green": int(row["sectors_green"]) if pd.notna(row.get("sectors_green")) else None,
            "dispersion":    f(row.get("dispersion"), 4),
        },
        "cross_asset": {
            "SPY": pct(row.get("ret_SPY_1d")),
            "QQQ": pct(row.get("ret_QQQ_1d")),
            "TLT": pct(row.get("ret_TLT_1d")),
            "HYG": pct(row.get("ret_HYG_1d")),
        },
        "sector_returns": sectors_sorted,
        "forward_returns": {
            "1d":  pct(row.get("fwd_ret_cc_1d")),
            "5d":  pct(row.get("fwd_ret_cc_5d")),
            "21d": pct(row.get("fwd_ret_cc_21d")),
        },
        "risk": {
            "max_drawdown_5d": pct(row.get("fwd_5d_max_drawdown_pct")),
            "max_upside_5d":   pct(row.get("fwd_5d_max_upside_pct")),
        },
    }


def _build_prompt(ctx: Dict[str, Any]) -> str:
    date = ctx["date"]
    return f"""You are a senior market analyst writing a retrospective end-of-day note.
Given ONLY the quantitative market structure data below from {date}, write a concise narrative \
interpretation of what the tape was telling traders that day.

Rules:
- Do NOT invent news events, company names, or specific external catalysts
- DO interpret what the structure implies: regime character, risk appetite, positioning signals, \
sector rotation themes
- Write in past tense as a retrospective
- Be specific about the numbers — reference actual values from the data
- Be direct and concise. No filler. No generic statements.

Market structure data for {date}:
{json.dumps(ctx, indent=2)}

Respond ONLY with valid JSON in this exact structure (no markdown, no backticks):
{{
  "summary": "3-4 sentence narrative of what the tape was saying",
  "key_signals": ["signal 1", "signal 2", "signal 3"],
  "risks_and_uncertainties": ["risk or unknown 1", "risk or unknown 2"],
  "regime_verdict": "one crisp sentence characterizing the day",
  "outcome_note": "one sentence noting how this played out given the actual forward returns in the data"
}}"""


def generate_historical_narrative(date_str: str) -> Dict[str, Any]:
    """
    Generate a retrospective market narrative for a historical date.
    Results are cached in memory — same date won't call the LLM twice.

    Args:
        date_str: Date in YYYY-MM-DD format

    Returns:
        dict with: summary, key_signals, risks_and_uncertainties,
                   regime_verdict, outcome_note, market_context, date
    """
    # Return cached result if available
    if date_str in _narrative_cache:
        return _narrative_cache[date_str]

    # Build context from CSV
    ctx = _build_context(date_str)
    if ctx is None:
        raise ValueError(f"No data found for date {date_str}")

    # Call OpenAI — historical retrospective summary uses preprocessing tier
    from src.narrative.runtime_config import assert_llm_calls_allowed
    assert_llm_calls_allowed("historical narrative synthesis")
    from openai import OpenAI
    from src.narrative.config import PREPROCESSING_MODEL
    client = OpenAI()

    prompt = _build_prompt(ctx)

    resp = client.chat.completions.create(
        model=PREPROCESSING_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=600,
    )

    raw = resp.choices[0].message.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "summary": raw,
            "key_signals": [],
            "risks_and_uncertainties": [],
            "regime_verdict": "",
            "outcome_note": "",
        }

    result = {
        "date": date_str,
        "narrative": parsed,
        "market_context": ctx,
        "generated": True,
        "model": PREPROCESSING_MODEL,
    }

    # Cache result
    _narrative_cache[date_str] = result
    return result
