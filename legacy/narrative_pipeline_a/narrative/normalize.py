from __future__ import annotations
from typing import List
import logging
import pandas as pd

logger = logging.getLogger(__name__)


def rolling_zscore(series: pd.Series, window: int = 126, min_periods: int = 30) -> pd.Series:
    """
    Compute rolling z-score with given window; use min_periods for initial expanding behavior.
    """
    roll_mean = series.rolling(window=window, min_periods=min_periods).mean()
    roll_std = series.rolling(window=window, min_periods=min_periods).std(ddof=0)
    exp_mean = series.expanding(min_periods=1).mean()
    exp_std = series.expanding(min_periods=1).std(ddof=0)
    roll_z = (series - roll_mean) / roll_std
    exp_z = (series - exp_mean) / exp_std
    z = roll_z.where(series.expanding(min_periods=1).count() >= min_periods, exp_z)
    z = z.fillna(0.0)
    return z


def add_normalized_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add z-prefixed normalized columns for core numeric fields.
    Uses rolling_zscore; if insufficient data, normalized values will be NaN.
    Returns a new DataFrame with added columns appended in stable order.
    """
    df = df.copy()
    numeric_cols = ["tone", "uncertainty", "theme_ai", "theme_inflation", "theme_liquidity", "theme_credit", "theme_consumer", "narrative_dispersion", "theme_dispersion", "narrative_entropy"]
    df["z_is_expanding"] = pd.Series(range(1, len(df) + 1), index=df.index) < 30
    for col in numeric_cols:
        zcol = f"z_{col}"
        try:
            df[zcol] = rolling_zscore(df[col])
        except Exception:
            # fallback: fill with NaN if column missing or non-numeric
            df[zcol] = pd.Series([float("nan")] * len(df))
        if df[zcol].isna().all():
            logger.warning("normalize: %s is all NaN after z-score normalization", zcol)
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
    df = df[final_cols]
    for col in [c for c in df.columns if c.startswith("z_")]:
        if df[col].isna().all():
            logging.warning(
                "Column '%s' is all NaN after normalization: "
                "%d data points provided, at least 30 required.",
                col,
                len(df),
            )
    return df
