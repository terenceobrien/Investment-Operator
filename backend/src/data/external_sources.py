"""
External historical inputs for Helix backtests.

These helpers are defensive and cache their outputs so the backtest can degrade
gracefully when optional data sources are unavailable.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


CFTC_COT_URL = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
AAII_URL = "https://www.aaii.com/files/surveys/sentiment.xls"


def _empty_cot() -> pd.DataFrame:
    return pd.DataFrame(columns=["cot_net_large_spec", "cot_net_large_spec_z"])


def _empty_aaii() -> pd.DataFrame:
    return pd.DataFrame(columns=["aaii_bull_minus_bear"])


def _as_path(path: str | Path) -> Path:
    return Path(path)


def _is_cache_fresh(path: Path, max_age_days: int) -> bool:
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime <= timedelta(days=max_age_days)


def _daily_ffill(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    idx = pd.date_range(df.index.min(), pd.Timestamp.today().normalize(), freq="D")
    return df.reindex(df.index.union(idx)).sort_index().ffill().reindex(idx)


def _rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    ma = s.rolling(window, min_periods=max(20, window // 2)).mean()
    sd = s.rolling(window, min_periods=max(20, window // 2)).std(ddof=0)
    return (s - ma) / sd.replace(0, np.nan)


def fetch_cot_history(
    start_date: str = "2000-01-01",
    contract_code: str = "13874A",
    cache_path: str | Path = "backend/data/cache/cot_history.parquet",
) -> pd.DataFrame:
    """
    Fetch CFTC legacy COT large-spec net positioning for E-mini S&P 500.

    Returns daily-aligned columns:
      cot_net_large_spec     — noncommercial long minus short
      cot_net_large_spec_z   — rolling 104-week z-score, forward-filled daily
    """
    path = _as_path(cache_path)
    if _is_cache_fresh(path, max_age_days=7):
        try:
            cached = pd.read_parquet(path)
            cached.index = pd.to_datetime(cached.index)
            return cached
        except Exception as exc:
            print(f"  COT cache read failed, re-fetching: {exc}")

    try:
        import requests

        params = {
            "$where": f"cftc_contract_market_code='{contract_code}'",
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": "1000",
        }
        resp = requests.get(CFTC_COT_URL, params=params, timeout=30)
        resp.raise_for_status()
        records = resp.json()
        if not isinstance(records, list) or not records:
            print("  COT fetch returned no rows — positioning layer will degrade")
            return _empty_cot()

        rows = []
        for rec in records:
            try:
                dt = pd.to_datetime(rec.get("report_date_as_yyyy_mm_dd"))
                long_pos = float(rec.get("noncomm_positions_long_all"))
                short_pos = float(rec.get("noncomm_positions_short_all"))
                rows.append((dt, long_pos - short_pos))
            except Exception:
                continue

        if not rows:
            print("  COT fetch had no parseable rows — positioning layer will degrade")
            return _empty_cot()

        weekly = pd.DataFrame(rows, columns=["date", "cot_net_large_spec"]).dropna()
        weekly = weekly[weekly["date"] >= pd.to_datetime(start_date)]
        weekly = weekly.drop_duplicates("date").set_index("date").sort_index()
        if weekly.empty:
            print("  COT history empty after start-date filter — positioning layer will degrade")
            return _empty_cot()

        weekly["cot_net_large_spec_z"] = _rolling_zscore(weekly["cot_net_large_spec"], 104)
        daily = _daily_ffill(weekly)

        path.parent.mkdir(parents=True, exist_ok=True)
        daily.to_parquet(path)
        return daily
    except Exception as exc:
        print(f"  COT fetch failed: {exc}")
        if path.exists():
            try:
                cached = pd.read_parquet(path)
                cached.index = pd.to_datetime(cached.index)
                print("  Using stale COT cache after fetch failure")
                return cached
            except Exception:
                pass
        return _empty_cot()


def _read_excel_raw(file_path: Path) -> pd.DataFrame:
    errors = []
    for engine in ("xlrd", "openpyxl", None):
        try:
            kwargs = {"header": None}
            if engine:
                kwargs["engine"] = engine
            return pd.read_excel(file_path, **kwargs)
        except Exception as exc:
            errors.append(f"{engine or 'default'}: {exc}")
    raise RuntimeError("; ".join(errors))


def _find_aaii_start_row(raw: pd.DataFrame) -> int:
    for i in range(len(raw)):
        row = raw.iloc[i]
        text = " ".join(str(x).strip().lower() for x in row.dropna().tolist())
        if "date" in text and ("bull" in text or "bear" in text):
            return i
        first = row.iloc[0] if len(row) else None
        if pd.notna(first) and not pd.isna(pd.to_datetime(first, errors="coerce")):
            return i
    return 0


def _to_decimal(series: pd.Series) -> pd.Series:
    s = (
        series.astype(str)
        .str.replace("%", "", regex=False)
        .str.replace(",", "", regex=False)
        .replace({"nan": np.nan, "None": np.nan, "": np.nan})
    )
    vals = pd.to_numeric(s, errors="coerce")
    if vals.dropna().abs().median() > 1.5:
        vals = vals / 100.0
    return vals


def load_aaii_sentiment(
    file_path: str | Path = "backend/data/raw/aaii_sentiment.xls",
) -> pd.DataFrame:
    """
    Load manually downloaded AAII sentiment XLS and forward-fill to daily.

    Expected source: https://www.aaii.com/files/surveys/sentiment.xls
    Output column: aaii_bull_minus_bear in percentage-point form
    (15.0 = +15pp), matching regime_layers.py thresholds.
    """
    path = _as_path(file_path)
    if not path.exists():
        raise FileNotFoundError(
            f"AAII sentiment file missing at {path}. Download {AAII_URL} "
            "and place it at the expected path to enable AAII positioning history."
        )

    try:
        raw = _read_excel_raw(path)
        start_row = _find_aaii_start_row(raw)
        candidate = raw.iloc[start_row:].reset_index(drop=True)

        first_row = candidate.iloc[0].astype(str).str.lower().tolist()
        if any("date" in x for x in first_row):
            header = candidate.iloc[0].astype(str).str.strip().tolist()
            data = candidate.iloc[1:].copy()
            data.columns = header
        else:
            data = candidate.copy()
            data.columns = [f"col_{i}" for i in range(data.shape[1])]

        date_col = next((c for c in data.columns if "date" in str(c).lower()), data.columns[0])
        bull_col = next((c for c in data.columns if "bull" in str(c).lower()), None)
        bear_col = next((c for c in data.columns if "bear" in str(c).lower()), None)
        if bull_col is None or bear_col is None:
            if data.shape[1] < 4:
                raise ValueError("Could not identify AAII bullish/bearish columns")
            bull_col = data.columns[1]
            bear_col = data.columns[3]

        dates = pd.to_datetime(data[date_col], errors="coerce")
        bull = _to_decimal(data[bull_col])
        bear = _to_decimal(data[bear_col])
        weekly = pd.DataFrame({
            "date": dates,
            "aaii_bull_minus_bear": (bull - bear) * 100.0,
        }).dropna(subset=["date", "aaii_bull_minus_bear"])

        if weekly.empty:
            print("  AAII file parsed but produced no rows — positioning layer will degrade")
            return _empty_aaii()

        weekly = weekly.drop_duplicates("date").set_index("date").sort_index()
        return _daily_ffill(weekly)
    except FileNotFoundError:
        raise
    except Exception as exc:
        print(f"  AAII sentiment load failed: {exc}")
        return _empty_aaii()


if __name__ == "__main__":
    cot = fetch_cot_history()
    print("COT tail:")
    print(cot.tail(10))
    try:
        aaii = load_aaii_sentiment()
        print("AAII tail:")
        print(aaii.tail(10))
    except FileNotFoundError as exc:
        print(exc)
