from __future__ import annotations

from typing import Dict, Any, List
import pandas as pd

def compute_portfolio_snapshot(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Returns dict with:
      - summary: dict metrics
      - top_positions: df
      - theme_exposure: df
      - flags: list[str]
    """
    d = df.copy()
    d["ticker"] = d["ticker"].astype(str).str.upper().str.strip()

    # Identify cash-like
    cash_mask = d["ticker"].isin(["CASH", "USD", "CASHX"])
    cash_w = float(d.loc[cash_mask, "weight"].sum())
    invested = d.loc[~cash_mask].copy()
    invested_w = float(invested["weight"].sum())

    # Normalize invested weights to 1 for concentration analysis
    if invested_w > 0:
        invested["w_norm"] = invested["weight"] / invested_w
    else:
        invested["w_norm"] = 0.0

    # Top positions
    top_positions = invested.sort_values("weight", ascending=False).head(10)
    top_positions = top_positions[["ticker", "weight", "theme", "w_norm"]].reset_index(drop=True)

    # Theme exposure
    theme_exposure = invested.copy()
    theme_exposure["theme"] = theme_exposure["theme"].replace("", "Unspecified")
    theme_exposure = (
        theme_exposure.groupby("theme", as_index=False)["weight"]
        .sum()
        .sort_values("weight", ascending=False)
        .reset_index(drop=True)
    )

    # Concentration stats
    weights_sorted = invested["w_norm"].sort_values(ascending=False).tolist()
    top1 = float(weights_sorted[0]) if len(weights_sorted) >= 1 else 0.0
    top3 = float(sum(weights_sorted[:3])) if len(weights_sorted) >= 3 else float(sum(weights_sorted))
    top5 = float(sum(weights_sorted[:5])) if len(weights_sorted) >= 5 else float(sum(weights_sorted))

    # Simple flags (V1)
    flags: List[str] = []
    if cash_w > 0.05:
        flags.append(f"Cash is {cash_w:.1%} (target was ≤ 5% per your preference).")
    if top1 > 0.25:
        flags.append(f"Single-name concentration: top position is {top1:.1%} of invested capital.")
    if top3 > 0.55:
        flags.append(f"Top-3 concentration is {top3:.1%} of invested capital.")
    if top5 > 0.70:
        flags.append(f"Top-5 concentration is {top5:.1%} of invested capital.")
    if invested_w < 0.90 and cash_w < 0.05:
        flags.append("Weights may not sum cleanly—double-check your CSV (or normalization).")

    summary = {
        "n_positions": int(len(invested)),
        "cash_weight": cash_w,
        "invested_weight": invested_w,
        "top1_invested": top1,
        "top3_invested": top3,
        "top5_invested": top5,
    }

    return {
        "summary": summary,
        "top_positions": top_positions,
        "theme_exposure": theme_exposure,
        "flags": flags,
    }

from typing import Optional

def add_regime_aware_flags(
    base_flags: list[str],
    macro_signals: Optional[dict],
    summary: dict,
    theme_exposure: pd.DataFrame,
    top_positions: pd.DataFrame,
) -> list[str]:
    """
    Adds macro-regime-aware warnings (V1 heuristics).
    This is intentionally simple + explainable.
    """
    flags = list(base_flags)

    if not macro_signals:
        return flags

    growth = macro_signals.get("Growth")
    inflation = macro_signals.get("Inflation")
    liquidity = macro_signals.get("Liquidity")

    # Safety checks
    if not (growth and inflation and liquidity):
        return flags

    g, i, l = growth.trend, inflation.trend, liquidity.trend

    cash = float(summary.get("cash_weight", 0.0))
    top1 = float(summary.get("top1_invested", 0.0))
    top3 = float(summary.get("top3_invested", 0.0))

    # Theme exposure helper
    te = theme_exposure.copy()
    if "theme" in te.columns:
        te["theme"] = te["theme"].astype(str).str.lower()
    def theme_weight_contains(substr: str) -> float:
        if te.empty:
            return 0.0
        mask = te["theme"].str.contains(substr, na=False)
        return float(te.loc[mask, "weight"].sum())

    # --- Regime-aware heuristics ---
    # Liquidity DOWN: reduce fragility / concentration
    if l == "DOWN":
        if cash < 0.03:
            flags.append("Regime: Liquidity is DOWN — consider keeping a bit more dry powder (cash < 3%).")
        if top1 > 0.20:
            flags.append("Regime: Liquidity is DOWN — single-position concentration is elevated (top 1 > 20% of invested).")
        if top3 > 0.55:
            flags.append("Regime: Liquidity is DOWN — portfolio is concentrated (top 3 > 55% of invested).")

    # Inflation UP + Liquidity DOWN: avoid long-duration / “tightening pain”
    if i == "UP" and l == "DOWN":
        # crude theme-based flags if user tags themes
        durationish = theme_weight_contains("tech") + theme_weight_contains("growth") + theme_weight_contains("duration")
        if durationish > 0.35:
            flags.append("Regime: Inflation UP + Liquidity DOWN — sizable duration/growth exposure by theme tags (≥ ~35%).")

    # Growth DOWN: cyclicals / high beta caution (theme tags)
    if g == "DOWN":
        cyclicals = (
            theme_weight_contains("small cap") +
            theme_weight_contains("cyc") +
            theme_weight_contains("industrial") +
            theme_weight_contains("consumer") +
            theme_weight_contains("financial")
        )
        if cyclicals > 0.35:
            flags.append("Regime: Growth is DOWN — cyclical exposure looks large by theme tags (≥ ~35%).")

    # Growth UP + Liquidity UP: risk-on is supported (positive note as info)
    if g == "UP" and l == "UP":
        flags.append("Regime: Growth UP + Liquidity UP — backdrop is generally supportive for risk assets (still watch concentration).")

    return flags


