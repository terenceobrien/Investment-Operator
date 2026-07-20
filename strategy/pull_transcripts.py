"""
Pull earnings-call transcripts for a universe of tickers from API Ninjas,
in ONE run, and cache everything to disk so the dataset survives cancelling
the subscription.

Design:
  - Loops tickers x quarters, hits /v1/earningstranscript once per (ticker, year, quarter).
  - Saves the RAW JSON response per call (transcript + date + timestamp +
    earnings_timing + transcript_split) to disk, so you never re-pull.
  - Separately writes a PREPARED-REMARKS-ONLY text per call, filtered via the
    per-turn is_qa flags (your extraction rule).
  - Ignores API Ninjas' own sentiment/summary/guidance fields entirely — you
    run YOUR frozen prompt over the raw prepared-remarks text later.
  - Records the exact call date + timestamp + timing per call into a manifest
    CSV, which is what your point-in-time forward-return window keys off.

Point-in-time note: earnings_timing (before_market/during_market/after_market)
plus the date tells you when the market could first react. after_market means
day-0 for forward returns is the NEXT session, not the call date. The manifest
captures this so the returns join can handle it correctly later.

Usage:
  export API_NINJAS_KEY=your_key_here
  python pull_transcripts.py

Adjust UNIVERSE and QUARTERS below.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
API_KEY = os.environ.get("API_NINJAS_KEY")
BASE = "https://api.api-ninjas.com/v1/earningstranscript"
CONSTITUENTS = HERE / "sp500_constituents.csv"

# (year, quarter) pairs to pull. Widened for the full-universe corpus build:
# more history gives every scored call a prior AND room for forward returns.
QUARTERS = [
    (2023, 1), (2023, 2), (2023, 3), (2023, 4),
    (2024, 1), (2024, 2), (2024, 3), (2024, 4),
    (2025, 1), (2025, 2), (2025, 3), (2025, 4),
    (2026, 1),
]

OUT_DIR = HERE / "transcripts"
RAW_DIR = OUT_DIR / "raw"          # raw JSON per call (source of truth)
PREP_DIR = OUT_DIR / "prepared"    # prepared-remarks-only .txt per call
MANIFEST = OUT_DIR / "manifest.csv"

REQUEST_PAUSE = 0.4  # seconds between calls; be polite / avoid rate limits


def load_universe(sectors: list[str] | None, only: list[str] | None) -> dict[str, dict]:
    """
    Returns {ticker: {'sector':..., 'name':...}} from the constituents CSV,
    filtered to `sectors` (GICS names) if given, or `only` (explicit tickers).
    """
    if not CONSTITUENTS.exists():
        raise SystemExit(f"{CONSTITUENTS} not found. Run: python3 -m strategy.fetch_sp500")
    uni = {}
    with CONSTITUENTS.open() as f:
        for row in csv.DictReader(f):
            uni[row["ticker"]] = {"sector": row["sector"], "name": row["name"]}
    if only:
        uni = {t: uni[t] for t in only if t in uni}
    elif sectors:
        want = {s.lower() for s in sectors}
        uni = {t: v for t, v in uni.items() if v["sector"].lower() in want}
    return uni


def _paths_for(ticker: str, year: int, quarter: int):
    stem = f"{ticker}_{year}Q{quarter}"
    return RAW_DIR / f"{stem}.json", PREP_DIR / f"{stem}.txt"


def fetch_one(ticker: str, year: int, quarter: int) -> dict | None:
    """Fetch a single transcript. Returns the parsed JSON dict, or None if
    unavailable (no transcript for that quarter is common and not an error)."""
    raw_path, _ = _paths_for(ticker, year, quarter)
    if raw_path.exists():
        # already pulled — load from cache, don't spend an API call
        return json.loads(raw_path.read_text())

    resp = requests.get(
        BASE,
        params={"ticker": ticker, "year": year, "quarter": quarter},
        headers={"X-Api-Key": API_KEY},
        timeout=30,
    )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        print(f"  ! {ticker} {year}Q{quarter}: HTTP {resp.status_code} {resp.text[:120]}")
        return None
    data = resp.json()
    # API returns {} or a list on 'not found' in some cases; normalize
    if not data or (isinstance(data, dict) and not data.get("transcript")):
        return None
    raw_path.write_text(json.dumps(data, indent=2))
    return data


# Phrases the OPERATOR uses to hand off from prepared remarks to analyst Q&A.
# These occur at the actual transition, not the boilerplate intro. We search
# for the LAST occurrence in the first ~70% of the text to avoid matching the
# opening "there will be a Q&A session" disclaimer.
QA_TRANSITION_PATTERNS = [
    r"\bwe(?:'ll| will) (?:now )?(?:open|take)\b[^.]{0,40}\b(?:the )?(?:line|call|floor|question)",
    r"\bopen (?:up )?the (?:line|call|floor)\b",
    r"\b(?:our )?first question\b",
    r"\bwe(?:'ll| will) now begin the question",
    r"\bthe question-and-answer session will (?:now )?begin",
    r"\bready (?:to|for) (?:begin|take) (?:the )?quest",
]


def prepared_remarks_only(data: dict, return_meta: bool = False):
    """
    Extract prepared remarks from the raw transcript string by locating the
    operator's hand-off to analyst Q&A and cutting everything after it.

    The Developer-tier `transcript_split` field is gated (returns an upgrade
    placeholder), so we work from the full `transcript` string instead.

    Heuristic: find the earliest Q&A-transition phrase that occurs AFTER the
    first 15% of the transcript (to skip the boilerplate "there will be a Q&A
    session" line in the intro). Cut there. If no marker is found, return the
    full transcript and flag it (via return_meta) for manual handling.
    """
    import re

    full = data.get("transcript", "")
    if not full:
        return ("", "empty") if return_meta else ""

    n = len(full)
    floor = int(n * 0.15)  # ignore matches in the intro boilerplate
    low = full.lower()

    best = None
    for pat in QA_TRANSITION_PATTERNS:
        for m in re.finditer(pat, low):
            if m.start() >= floor:
                if best is None or m.start() < best:
                    best = m.start()
                break  # earliest qualifying match for this pattern is enough

    if best is None:
        # no reliable cut point — keep full text, flag it
        return (full, "no_marker") if return_meta else full

    prepared = full[:best].rstrip()
    return (prepared, "ok") if return_meta else prepared


def _load_existing_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with MANIFEST.open() as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description="Pull earnings transcripts for S&P 500 by sector.")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--sector", nargs="+", help="GICS sector name(s), e.g. --sector 'Health Care'")
    grp.add_argument("--all", action="store_true", help="pull the entire S&P 500")
    grp.add_argument("--tickers", nargs="+", help="explicit ticker list")
    ap.add_argument("--list-sectors", action="store_true", help="print available sectors and exit")
    args = ap.parse_args()

    if not API_KEY:
        raise SystemExit("Set API_NINJAS_KEY in your environment first.")

    if args.list_sectors:
        uni = load_universe(None, None)
        from collections import Counter
        for s, n in sorted(Counter(v["sector"] for v in uni.values()).items()):
            print(f"  {s:<26} {n}")
        return

    if args.tickers:
        universe = load_universe(None, args.tickers)
    elif args.sector:
        universe = load_universe(args.sector, None)
    elif args.all:
        universe = load_universe(None, None)
    else:
        raise SystemExit("Specify --sector <name(s)>, --all, or --tickers <list>. "
                         "Use --list-sectors to see options.")

    print(f"Universe: {len(universe)} tickers"
          + (f" in sector(s) {args.sector}" if args.sector else "")
          + f"  x  {len(QUARTERS)} quarters = up to {len(universe)*len(QUARTERS)} calls\n")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PREP_DIR.mkdir(parents=True, exist_ok=True)

    # incremental manifest: keep prior rows, replace/add for this run's tickers
    existing = _load_existing_manifest()
    existing = [r for r in existing if r["ticker"] not in universe]  # drop rows we're re-pulling
    manifest_rows = list(existing)
    n_ok = n_missing = 0

    for ticker, meta in universe.items():
        for (year, quarter) in QUARTERS:
            data = fetch_one(ticker, year, quarter)
            if data is None:
                n_missing += 1
                time.sleep(REQUEST_PAUSE)
                continue

            _, prep_path = _paths_for(ticker, year, quarter)
            prep_text, split_status = prepared_remarks_only(data, return_meta=True)
            prep_path.write_text(prep_text)

            full_len = len(data.get("transcript", ""))
            manifest_rows.append({
                "ticker": ticker,
                "sector": meta["sector"],
                "name": meta["name"],
                "year": year,
                "quarter": quarter,
                "call_date": data.get("date", ""),
                "timestamp": data.get("timestamp", ""),
                "earnings_timing": data.get("earnings_timing", ""),
                "split_status": split_status,
                "prepared_chars": len(prep_text),
                "full_chars": full_len,
                "prepared_frac": round(len(prep_text) / full_len, 2) if full_len else 0,
                "raw_json": str(_paths_for(ticker, year, quarter)[0]),
                "prepared_txt": str(prep_path),
            })
            n_ok += 1
            print(f"  + {ticker} {year}Q{quarter}: {data.get('date','?')} "
                  f"({data.get('earnings_timing','?')}) split={split_status} "
                  f"{len(prep_text)}/{full_len}")
            time.sleep(REQUEST_PAUSE)
        # periodic manifest flush so a long run is crash-safe
        _write_manifest(manifest_rows)

    _write_manifest(manifest_rows)
    print(f"\nDone. {n_ok} transcripts this run, {n_missing} missing/unavailable.")
    print(f"Manifest ({len(manifest_rows)} total rows): {MANIFEST}")

    this_run = [r for r in manifest_rows if r["ticker"] in universe]
    no_marker = [r for r in this_run if r["split_status"] != "ok"]
    if no_marker:
        print(f"\n{len(no_marker)} calls had NO reliable Q&A-transition marker "
              f"(prepared text = full transcript). Sample:")
        for r in no_marker[:15]:
            print(f"    {r['ticker']} {r['year']}Q{r['quarter']} ({r['split_status']})")
        if len(no_marker) > 15:
            print(f"    ... and {len(no_marker)-15} more")


def _write_manifest(rows: list[dict]):
    if not rows:
        return
    # union of keys across rows (older rows may lack 'sector'/'name')
    fields = ["ticker", "sector", "name", "year", "quarter", "call_date", "timestamp",
              "earnings_timing", "split_status", "prepared_chars", "full_chars",
              "prepared_frac", "raw_json", "prepared_txt"]
    with MANIFEST.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


if __name__ == "__main__":
    main()