"""Backfill historical regime states for the last N years.

Runs build_regime_state() for each approximate US trading day in the target
window using point-in-time-correct data fetches. Saves each result through the
storage abstraction.

Usage:
    python -m scripts.backfill_regime_states
    python -m scripts.backfill_regime_states --years 2
    python -m scripts.backfill_regime_states --start 2024-01-01
    python -m scripts.backfill_regime_states --start 2024-01-01 --end 2024-06-30
    python -m scripts.backfill_regime_states --skip-existing
    python -m scripts.backfill_regime_states --dry-run
    python -m scripts.backfill_regime_states --verbose
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay


logger = logging.getLogger(__name__)


def generate_trading_dates(start_date: str, end_date: str) -> list[str]:
    """Generate approximate US trading dates between start and end."""

    calendar = USFederalHolidayCalendar()
    business_day = CustomBusinessDay(calendar=calendar)
    dates = pd.date_range(start=start_date, end=end_date, freq=business_day)
    return [date.strftime("%Y-%m-%d") for date in dates]


def load_existing_dates() -> set[str]:
    """Load asof_dates already present in the regime database."""

    from src.agent_system.regime.timeseries import load_regime_timeseries

    df = load_regime_timeseries()
    if df.empty:
        return set()
    return {date.strftime("%Y-%m-%d") for date in df.index}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical regime states.")
    parser.add_argument(
        "--years",
        type=float,
        default=2.0,
        help="How many years of history to backfill.",
    )
    parser.add_argument("--start", default=None, help="Override start date YYYY-MM-DD.")
    parser.add_argument(
        "--end",
        default=None,
        help="Override end date YYYY-MM-DD. Defaults to yesterday.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip dates already in the database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List dates that would be processed without computing.",
    )
    parser.add_argument(
        "--rate-limit-ms",
        type=int,
        default=500,
        help="Sleep this many milliseconds between iterations.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    end_date = args.end or (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    if args.start:
        start_date = args.start
    else:
        start_date = (
            datetime.strptime(end_date, "%Y-%m-%d")
            - timedelta(days=int(args.years * 365.25))
        ).strftime("%Y-%m-%d")

    trading_dates = generate_trading_dates(start_date, end_date)
    print("\n" + "=" * 70)
    print("REGIME STATE BACKFILL")
    print("=" * 70)
    print(f"  range:        {start_date} -> {end_date}")
    print(f"  trading days: {len(trading_dates)}")

    if args.skip_existing:
        existing = load_existing_dates()
        original_count = len(trading_dates)
        trading_dates = [date for date in trading_dates if date not in existing]
        print(f"  skipped:      {original_count - len(trading_dates)} (already in DB)")
        print(f"  to process:   {len(trading_dates)}")

    if not trading_dates:
        print("\nNothing to do.")
        return 0

    if args.dry_run:
        print(f"\n[dry-run] Would process {len(trading_dates)} dates:")
        for date in trading_dates[:10]:
            print(f"  {date}")
        if len(trading_dates) > 10:
            print(f"  ... and {len(trading_dates) - 10} more")
        return 0

    estimated_seconds = len(trading_dates) * (5 + args.rate_limit_ms / 1000)
    print(f"  estimated:    ~{estimated_seconds / 60:.1f} minutes")
    print()

    from src.agent_system.storage.repository import save_regime_state
    from src.state.regime_state import build_regime_state

    succeeded = 0
    failed: list[tuple[str, str]] = []
    low_quality: list[tuple[str, float]] = []

    for index, asof in enumerate(trading_dates, 1):
        try:
            print(f"\n[{index}/{len(trading_dates)}] Processing {asof}...")
            state = build_regime_state(save=False, asof_date=asof)

            dq_values = (
                list(state.layer_data_quality.values())
                if state.layer_data_quality
                else []
            )
            avg_dq = sum(dq_values) / len(dq_values) if dq_values else 0.0
            if avg_dq < 0.20:
                print(f"  Low data quality ({avg_dq:.0%}) - saving anyway")
                low_quality.append((asof, avg_dq))

            save_regime_state(state.to_dict())
            succeeded += 1
            score = state.score_total if state.score_total is not None else float("nan")
            print(f"  {state.environment} | composite={score:.1f} | dq={avg_dq:.0%}")

            if args.rate_limit_ms > 0 and index < len(trading_dates):
                time.sleep(args.rate_limit_ms / 1000)

        except Exception as exc:
            print(f"  FAILED: {exc}")
            failed.append((asof, str(exc)))
            logger.exception("Failed to process %s", asof)
            continue

    print("\n" + "=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    print(f"  succeeded:     {succeeded}")
    print(f"  failed:        {len(failed)}")
    print(f"  low quality:   {len(low_quality)} (saved with warning)")

    if failed:
        print("\nFailed dates (first 10):")
        for asof, err in failed[:10]:
            print(f"  {asof}: {err}")

    if low_quality:
        print("\nLow quality dates (data_quality < 20%):")
        for asof, dq in low_quality[:10]:
            print(f"  {asof}: {dq:.0%}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
