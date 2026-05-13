#!/usr/bin/env python3
"""
Add realized price outcomes to narrative memory records.

Examples:
    python backend/scripts/label_narrative_outcomes.py --ticker SPY
    python backend/scripts/label_narrative_outcomes.py --all

This first pass only labels price returns. Natural-language falsifier
evaluation remains pending for a later calibration pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pandas as pd
import yfinance as yf

_repo_root = Path(__file__).resolve().parents[2]
_backend_dir = _repo_root / "backend"
_backend_src_dir = _backend_dir / "src"
for _p in (_backend_src_dir, _backend_dir):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

from src.narrative.memory import MEMORY_DIR  # noqa: E402
from src.narrative.ticker_profiles import get_ticker_profile, normalize_ticker  # noqa: E402

HORIZONS = {"1d": 1, "5d": 5, "20d": 20}


def _memory_files(ticker: Optional[str]) -> Iterable[Path]:
    if ticker:
        yield from sorted((MEMORY_DIR / normalize_ticker(ticker)).glob("*.json"))
    else:
        yield from sorted(MEMORY_DIR.glob("*/*.json"))


def _download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    data = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True, group_by="ticker")
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        close = pd.DataFrame({t: data[t]["Close"] for t in tickers if t in data.columns.get_level_values(0)})
    else:
        close = pd.DataFrame({tickers[0]: data["Close"]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all")


def _forward_return(close: pd.Series, asof: pd.Timestamp, days: int) -> Optional[float]:
    series = close.dropna()
    if series.empty:
        return None
    future = series[series.index >= asof]
    if len(future) <= days:
        return None
    start_px = float(future.iloc[0])
    end_px = float(future.iloc[days])
    if start_px == 0:
        return None
    return round((end_px / start_px - 1.0) * 100.0, 3)


def _max_drawdown(close: pd.Series, asof: pd.Timestamp, days: int) -> Optional[float]:
    series = close.dropna()
    future = series[series.index >= asof]
    if len(future) <= 1:
        return None
    window = future.iloc[: days + 1]
    start_px = float(window.iloc[0])
    if start_px == 0:
        return None
    return round((float(window.min()) / start_px - 1.0) * 100.0, 3)


def _label_file(path: Path) -> bool:
    record = json.loads(path.read_text(encoding="utf-8"))
    ticker = normalize_ticker(record.get("ticker"))
    asof = pd.to_datetime(record.get("asof_date")).tz_localize(None)
    profile = get_ticker_profile(ticker) or {}
    benchmark = normalize_ticker(profile.get("benchmark") or "SPY")
    sector_etf = normalize_ticker(profile.get("sector_etf") or "")
    tickers = [t for t in dict.fromkeys([ticker, benchmark, sector_etf]) if t]

    start = (asof - timedelta(days=5)).date().isoformat()
    end = (asof + timedelta(days=45)).date().isoformat()
    closes = _download_prices(tickers, start, end)
    if closes.empty or ticker not in closes:
        return False

    outcomes: Dict[str, Any] = record.get("outcomes") if isinstance(record.get("outcomes"), dict) else {}
    for key, days in HORIZONS.items():
        primary = _forward_return(closes[ticker], asof, days)
        benchmark_ret = _forward_return(closes[benchmark], asof, days) if benchmark in closes else None
        sector_ret = _forward_return(closes[sector_etf], asof, days) if sector_etf and sector_etf in closes else None
        if primary is None:
            continue
        outcomes[key] = {
            "ticker_return_pct": primary,
            "benchmark": benchmark,
            "benchmark_return_pct": benchmark_ret,
            "relative_vs_benchmark_pct": round(primary - benchmark_ret, 3) if benchmark_ret is not None else None,
            "sector_etf": sector_etf or None,
            "sector_return_pct": sector_ret,
            "relative_vs_sector_pct": round(primary - sector_ret, 3) if sector_ret is not None else None,
            "max_drawdown_pct": _max_drawdown(closes[ticker], asof, days),
            "labeled_at": datetime.utcnow().isoformat() + "Z",
        }

    record["outcomes"] = outcomes
    record.setdefault("falsifier_status", "pending")
    record.setdefault("resolution_type", None)
    path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticker")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()

    files = list(_memory_files(None if args.all else args.ticker))
    updated = 0
    for path in files:
        try:
            if _label_file(path):
                updated += 1
        except Exception as exc:
            print(f"skip {path}: {type(exc).__name__}: {exc}")
    print(f"Updated {updated} of {len(files)} memory records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
