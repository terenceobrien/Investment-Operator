from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import pandas as pd

REQUIRED_COLS = {"ticker", "weight"}

@dataclass(frozen=True)
class PortfolioRow:
    ticker: str
    weight: float
    theme: Optional[str] = None

def load_portfolio_csv(file) -> pd.DataFrame:
    """
    Expects columns:
      - ticker (str)
      - weight (float): either decimals (0.10) or percents (10)
      - theme (optional str)
    Returns standardized DataFrame with columns: ticker, weight, theme
    """
    df = pd.read_csv(file)

    cols = set(c.lower() for c in df.columns)
    if not REQUIRED_COLS.issubset(cols):
        raise ValueError("CSV must include columns: ticker, weight")

    # Normalize column names
    df.columns = [c.lower().strip() for c in df.columns]

    # Clean
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df["weight"] = pd.to_numeric(df["weight"], errors="coerce")

    if "theme" not in df.columns:
        df["theme"] = ""

    df["theme"] = df["theme"].fillna("").astype(str).str.strip()

    df = df.dropna(subset=["weight"])
    df = df[df["weight"] != 0]

    # Convert percent-style weights if it looks like 0–100
    w_sum = df["weight"].sum()
    if w_sum > 1.5:  # heuristic: user probably used percent weights
        df["weight"] = df["weight"] / 100.0

    # Normalize to sum to 1.0 (excluding CASH if user includes it)
    df = df.reset_index(drop=True)
    return df
