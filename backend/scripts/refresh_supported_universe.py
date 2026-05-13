#!/usr/bin/env python3
"""
Refresh or validate the checked-in narrative supported universe files.

This intentionally uses free public tables only. It is not called by the app at
request time; the app reads the checked-in CSVs under backend/data/universe/.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_DIR = ROOT / "data" / "universe"
SP500_PATH = UNIVERSE_DIR / "sp500.csv"
NASDAQ100_PATH = UNIVERSE_DIR / "nasdaq100.csv"

HEADERS = ["ticker", "company_name", "index_memberships", "sector", "industry", "exchange"]


def _normalize_ticker(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().upper()).replace(".", "-")


def _read_html(url: str) -> List[pd.DataFrame]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 HelixUniverseRefresh/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read()
    return pd.read_html(io.BytesIO(html))


def _write_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = sorted(rows, key=lambda r: r["ticker"])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(clean)


def refresh_sp500() -> None:
    table = _read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")[0]
    rows = []
    for _, row in table.iterrows():
        ticker = _normalize_ticker(row.get("Symbol"))
        if not ticker:
            continue
        rows.append({
            "ticker": ticker,
            "company_name": str(row.get("Security") or "").strip(),
            "index_memberships": "S&P 500",
            "sector": str(row.get("GICS Sector") or "").strip(),
            "industry": str(row.get("GICS Sub-Industry") or "").strip(),
            "exchange": "",
        })
    _write_rows(SP500_PATH, rows)
    print(f"wrote {len(rows)} S&P 500 rows to {SP500_PATH}")


def refresh_nasdaq100() -> None:
    tables = _read_html("https://en.wikipedia.org/wiki/Nasdaq-100")
    table = next((t for t in tables if {"Ticker", "Company"}.issubset(set(map(str, t.columns)))), None)
    if table is None:
        raise RuntimeError("Could not find Nasdaq-100 constituents table")
    rows = []
    for _, row in table.iterrows():
        ticker = _normalize_ticker(row.get("Ticker"))
        if not ticker:
            continue
        rows.append({
            "ticker": ticker,
            "company_name": str(row.get("Company") or "").strip(),
            "index_memberships": "Nasdaq-100",
            "sector": str(row.get("GICS Sector") or row.get("Sector") or "").strip(),
            "industry": str(row.get("GICS Sub-Industry") or row.get("Industry") or "").strip(),
            "exchange": "NASDAQ",
        })
    _write_rows(NASDAQ100_PATH, rows)
    print(f"wrote {len(rows)} Nasdaq-100 rows to {NASDAQ100_PATH}")


def validate_file(path: Path) -> int:
    if not path.exists():
        print(f"missing {path}")
        return 0
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    missing = [h for h in HEADERS if h not in (rows[0].keys() if rows else [])]
    if missing:
        raise SystemExit(f"{path} missing columns: {missing}")
    tickers = {r["ticker"] for r in rows if r.get("ticker")}
    if len(tickers) != len(rows):
        raise SystemExit(f"{path} has duplicate or empty tickers")
    print(f"{path}: {len(rows)} rows OK")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Fetch public tables and rewrite CSVs")
    parser.add_argument("--validate", action="store_true", help="Validate checked-in CSVs")
    args = parser.parse_args()

    if args.refresh:
        refresh_sp500()
        refresh_nasdaq100()

    if args.validate or not args.refresh:
        validate_file(SP500_PATH)
        validate_file(NASDAQ100_PATH)


if __name__ == "__main__":
    main()
