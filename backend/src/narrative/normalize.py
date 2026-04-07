from __future__ import annotations
from typing import List
import pandas as pd


def rolling_zscore(series: pd.Series, window: int = 126, min_periods: int = 30) -> pd.Series:
    """
    Compute rolling z-score with given window; use min_periods for initial expanding behavior.
    """
    roll_mean = series.rolling(window=window, min_periods=min_periods).mean()
    roll_std = series.rolling(window=window, min_periods=min_periods).std(ddof=0)
    z = (series - roll_mean) / roll_std
    return z


def add_normalized_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add z-prefixed normalized columns for core numeric fields.
    Uses rolling_zscore; if insufficient data, normalized values will be NaN.
    Returns a new DataFrame with added columns appended in stable order.
    """
    df = df.copy()
    numeric_cols = ["tone", "uncertainty", "theme_ai", "theme_inflation", "theme_liquidity", "theme_credit", "theme_consumer", "narrative_dispersion", "theme_dispersion", "narrative_entropy"]
    for col in numeric_cols:
        zcol = f"z_{col}"
        try:
            df[zcol] = rolling_zscore(df[col])
        except Exception:
            # fallback: fill with NaN if column missing or non-numeric
            df[zcol] = pd.Series([float("nan")] * len(df))
    # ensure stable ordering: original cols then z_ cols
    orig = list(df.columns[: len(df.columns) - len(numeric_cols)])  # approximate, but we'll reorder explicitly
    cols_order = [
        "date",
        "tone",
        "uncertainty",
        "theme_ai",
        "theme_inflation",
        "theme_liquidity",
        "theme_credit",
        "theme_consumer",
        "conviction",
        "cohesion",
        "narrative_dispersion",
        "theme_dispersion",
        "narrative_entropy",
        "n_items",
        "n_chunks",
        "n_sources",
    ]
    zcols = [f"z_{c}" for c in numeric_cols]
    final_cols = [c for c in cols_order if c in df.columns] + zcols
    # append any other columns that might exist
    for c in df.columns:
        if c not in final_cols:
            final_cols.append(c)
    return df[final_cols]