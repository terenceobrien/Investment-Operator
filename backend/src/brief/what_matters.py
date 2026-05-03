from __future__ import annotations

import os
import json
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

def _df_to_compact_records(df: pd.DataFrame, n: int = 8) -> List[dict]:
    if df is None or df.empty:
        return []
    keep_cols = [c for c in ["ticker", "chg_pct_1d", "zscore_1d", "last"] if c in df.columns]
    d = df.copy()
    if keep_cols:
        d = d[keep_cols]
    return d.head(n).to_dict(orient="records")

def generate_what_matters_today(
    macro_signals: Dict,
    market_moves_df: pd.DataFrame,
    portfolio_flags: Optional[List[str]] = None,
    model: Optional[str] = None,
) -> str:
    """
    Returns a short bullet brief (3–5 bullets) grounded in:
      - Macro regime (Growth/Inflation/Liquidity)
      - Market movers
      - Portfolio flags (optional)

    This is a preprocessing-tier brief, not the final narrative synthesis,
    so it defaults to PREPROCESSING_MODEL.
    """
    from openai import OpenAI
    from src.narrative.config import PREPROCESSING_MODEL
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY in your environment/.env")

    if not model:
        model = PREPROCESSING_MODEL

    client = OpenAI(api_key=api_key)

    macro = {}
    for k in ["Growth", "Inflation", "Liquidity"]:
        sig = macro_signals.get(k)
        if sig is None:
            continue
        macro[k] = {
            "trend": getattr(sig, "trend", None),
            "mom": getattr(sig, "mom", None),
            "yoy": getattr(sig, "yoy", None),
            "name": getattr(sig, "name", None),
        }

    payload = {
        "macro": macro,
        "top_movers": _df_to_compact_records(market_moves_df, n=8),
        "portfolio_flags": portfolio_flags or [],
        "constraints": {
            "max_bullets": 5,
            "tone": "crisp, PM-style",
            "no_external_news": True,
            "grounding": "Only use the provided data. If uncertain, say so explicitly.",
        },
    }

    prompt = f"""
You are an investment operator writing the "What matters today" section.
Use ONLY the JSON data provided. Do NOT add external facts or news.

Output requirements:
- 3–5 bullets max.
- Each bullet should cite which input it is based on (Macro, Movers, Portfolio Flags).
- If a bullet is speculative, label it as "Hypothesis:".
- Keep it tight and actionable.

DATA (JSON):
{json.dumps(payload, indent=2)}
""".strip()

    # Responses API (recommended)
    resp = client.responses.create(
        model=model,
        input=prompt,
    )

    # SDK exposes convenient output_text
    return resp.output_text.strip()


def heuristic_what_matters(
    macro_signals: Dict,
    market_moves_df: pd.DataFrame,
    portfolio_flags: Optional[List[str]] = None,
) -> str:
    bullets = []

    # Macro
    g = macro_signals["Growth"].trend
    i = macro_signals["Inflation"].trend
    l = macro_signals["Liquidity"].trend
    bullets.append(
        f"- **Macro:** Growth {g}, Inflation {i}, Liquidity {l}. (Macro)"
    )

    # Market movers
    if (
        market_moves_df is not None
        and not market_moves_df.empty
        and "chg_pct_1d" in market_moves_df.columns
    ):
        d = market_moves_df.copy()
        d["abs"] = d["chg_pct_1d"].abs()
        top = d.sort_values("abs", ascending=False).head(3)
        movers = ", ".join(
            [f"{r['ticker']} {r['chg_pct_1d']:+.2f}%" for _, r in top.iterrows()]
        )
        bullets.append(f"- **Largest moves:** {movers}. (Movers)")

    # Portfolio flags
    pf = portfolio_flags or []
    for f in pf[:2]:
        bullets.append(f"- **Portfolio:** {f} (Portfolio)")

    return "\n".join(bullets[:5])
