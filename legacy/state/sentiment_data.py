"""AAII Investor Sentiment Survey data loader.

Reads the locally-saved sentiment.xls file at data/agent_system/sentiment.xls
and exposes a clean time series of bull-minus-bear spread readings.

The file is published weekly by AAII. To refresh, manually download from
https://www.aaii.com/sentimentsurvey and replace the file.

Public API:
    get_aaii_history() -> pd.Series
        Returns Series indexed by date with bull-minus-bear spread values in
        percentage points.

    get_aaii_asof(asof_date: str | None) -> Optional[float]
        Returns the most recent bull-minus-bear reading on or before asof_date.
        If asof_date is None, returns the latest reading.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from src.agent_system.paths import agent_system_data_root


logger = logging.getLogger(__name__)


AAII_FILE_PATH = agent_system_data_root(create=False) / "sentiment.xls"


def _parse_aaii_file(path: Path = AAII_FILE_PATH) -> pd.Series:
    """Parse the AAII sentiment XLS into a clean Series.

    Returns a Series indexed by weekly reading date with bull-minus-bear spread
    values in percentage points. The parser is defensive because the AAII file
    has historically used multiple header rows and minor column-name changes.
    """
    if not path.exists():
        raise FileNotFoundError(f"AAII file not found at {path}")

    xls = pd.ExcelFile(path)

    sheet_candidates = ["Sentiment", "SENTIMENT", "Data", "DATA"]
    sheet = next((s for s in sheet_candidates if s in xls.sheet_names), xls.sheet_names[0])

    raw = pd.read_excel(xls, sheet_name=sheet, header=None)

    header_row = None
    for i in range(min(25, len(raw))):
        row_text = " ".join(str(v) for v in raw.iloc[i].values).lower()
        if "date" in row_text and ("bull" in row_text or "bearish" in row_text):
            header_row = i
            break

    if header_row is None:
        raise ValueError(
            f"Could not find header row in {path}; first 10 rows:\n{raw.head(10)}"
        )

    df = pd.read_excel(xls, sheet_name=sheet, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    date_col = next(
        (
            c
            for c in df.columns
            if c.lower().startswith("date") or c.lower() == "reported date"
        ),
        None,
    )
    if date_col is None:
        raise ValueError(f"No Date column found; columns: {list(df.columns)}")

    df = df.rename(columns={date_col: "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    spread_col = next(
        (
            c
            for c in df.columns
            if c.lower() == "spread"
            or ("bull" in c.lower() and "bear" in c.lower() and "spread" in c.lower())
        ),
        None,
    )

    if spread_col is not None:
        spread = pd.to_numeric(df[spread_col], errors="coerce")
    else:
        bull_col = next(
            (
                c
                for c in df.columns
                if c.lower().startswith("bull")
                and "ma" not in c.lower()
                and "mov" not in c.lower()
                and "spread" not in c.lower()
            ),
            None,
        )
        bear_col = next(
            (
                c
                for c in df.columns
                if c.lower().startswith("bear")
                and "ma" not in c.lower()
                and "mov" not in c.lower()
            ),
            None,
        )
        if bull_col is None or bear_col is None:
            raise ValueError(
                f"Could not find Bull and Bear columns; available: {list(df.columns)}"
            )
        bull = pd.to_numeric(df[bull_col], errors="coerce")
        bear = pd.to_numeric(df[bear_col], errors="coerce")
        spread = bull - bear

    max_abs = spread.abs().max(skipna=True)
    if pd.notna(max_abs) and max_abs < 1.5:
        spread = spread * 100

    result = pd.Series(
        spread.to_numpy(),
        index=pd.DatetimeIndex(df["date"]),
        name="bull_minus_bear",
    )
    result = result.dropna().sort_index()
    result = result[~result.index.duplicated(keep="last")]

    if result.empty:
        raise ValueError("AAII parse produced empty series; check file structure")

    logger.info(
        "Parsed AAII file: %d readings from %s to %s",
        len(result),
        result.index[0].date(),
        result.index[-1].date(),
    )
    return result


@lru_cache(maxsize=1)
def get_aaii_history() -> pd.Series:
    """Get the full AAII bull-minus-bear history. Cached per process."""
    return _parse_aaii_file()


def get_aaii_asof(asof_date: Optional[str] = None) -> Optional[float]:
    """Get the most recent AAII reading on or before asof_date."""
    try:
        history = get_aaii_history()
    except (FileNotFoundError, ValueError) as exc:
        logger.warning("AAII history unavailable: %s", exc)
        return None

    if asof_date is None:
        return float(history.iloc[-1])

    cutoff = pd.Timestamp(asof_date)
    eligible = history[history.index <= cutoff]
    if eligible.empty:
        return None
    return float(eligible.iloc[-1])
