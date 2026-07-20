"""
Fetch current S&P 500 constituents with GICS sector tags, write to a CSV the
pull script consumes. Sourced from Wikipedia's maintained list, which carries
ticker + GICS sector + sub-industry in a clean table.

Usage:
  python3 -m strategy.fetch_sp500
  -> writes strategy/sp500_constituents.csv  (columns: ticker, name, sector, sub_industry)

Note: this is the CURRENT membership snapshot. For a rigorous historical
backtest you'd eventually want point-in-time membership (to avoid survivorship
bias from names that were added/dropped), but for building the transcript
corpus the current list is the right starting universe.
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).parent
OUT = HERE / "sp500_constituents.csv"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _from_wikipedia() -> pd.DataFrame:
    resp = requests.get(
        WIKI_URL,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/122.0 Safari/537.36"},
        timeout=30,
    )
    resp.raise_for_status()
    # prefer lxml parser; fall back to html5lib; either must be installed
    try:
        tables = pd.read_html(io.StringIO(resp.text), flavor="lxml")
    except ImportError:
        tables = pd.read_html(io.StringIO(resp.text), flavor="html5lib")
    return tables[0]


def _from_github() -> pd.DataFrame:
    """Fallback: a maintained GitHub CSV mirror of S&P 500 constituents."""
    url = ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
           "main/data/constituents.csv")
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    # this mirror uses columns: Symbol, Security, GICS Sector, GICS Sub-Industry
    return df


def fetch() -> pd.DataFrame:
    # Try Wikipedia first (freshest); fall back to the GitHub mirror on any failure.
    try:
        df = _from_wikipedia()
        source = "wikipedia"
    except Exception as e:
        print(f"Wikipedia fetch failed ({e}); falling back to GitHub mirror.")
        df = _from_github()
        source = "github"
    print(f"Source: {source}")
    # Column names on the page: 'Symbol', 'Security', 'GICS Sector',
    # 'GICS Sub-Industry'. Normalize defensively in case of minor header drift.
    cols = {c.lower().strip(): c for c in df.columns}
    def pick(*cands):
        for c in cands:
            if c in cols:
                return cols[c]
        raise KeyError(f"none of {cands} found in {list(df.columns)}")

    sym = pick("symbol", "ticker symbol")
    sec = pick("security", "company")
    gics = pick("gics sector")
    sub = pick("gics sub-industry", "gics sub industry")

    out = pd.DataFrame({
        "ticker": df[sym].astype(str).str.strip(),
        "name": df[sec].astype(str).str.strip(),
        "sector": df[gics].astype(str).str.strip(),
        "sub_industry": df[sub].astype(str).str.strip(),
    })
    # yfinance/API-Ninjas use '-' for share classes; Wikipedia uses '.'
    out["ticker"] = out["ticker"].str.replace(".", "-", regex=False)
    return out.sort_values(["sector", "ticker"]).reset_index(drop=True)


def main():
    df = fetch()
    df.to_csv(OUT, index=False)
    print(f"Wrote {len(df)} constituents -> {OUT}")
    print("\nBy sector:")
    for sector, n in df["sector"].value_counts().sort_index().items():
        print(f"  {sector:<26} {n}")


if __name__ == "__main__":
    main()