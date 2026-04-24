"""
scripts/validate_trends_live.py

Manual one-off validation script for fetch_term_history.
NOT for CI use and must never be imported by application code.  # noqa

Usage:
    python scripts/validate_trends_live.py [--term TERM] [--days DAYS]

    --term   Search term to validate (default: "recession")
    --days   How many days back to fetch (default: 90)
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make src/ importable when run from the backend root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate fetch_term_history against live Google Trends"
    )
    parser.add_argument("--term", default="recession", help="Search term to fetch")
    parser.add_argument("--days", type=int, default=90, help="Days of history to fetch")
    args = parser.parse_args()

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=args.days)
    start = start_dt.strftime("%Y-%m-%d")
    end = end_dt.strftime("%Y-%m-%d")

    print(f"Term     : {args.term}")
    print(f"Range    : {start} → {end}")
    print("Fetching ...")

    try:
        from src.narrative.trends_history import fetch_term_history

        series = fetch_term_history(
            args.term,
            start=start,
            end=end,
            delay_range=(2.0, 4.0),
        )

        if series.empty:
            print("Result   : empty series returned (no data from Google Trends)")
            return 1

        print(f"Length   : {len(series)}")
        print(f"Min      : {series.min():.2f}")
        print(f"Max      : {series.max():.2f}")
        print(f"Mean     : {series.mean():.2f}")
        print(f"First 3  : {series.iloc[:3].tolist()}")
        print(f"Last 3   : {series.iloc[-3:].tolist()}")
        return 0

    except ImportError as exc:
        try:
            from pytrends.exceptions import ResponseError
        except ImportError:
            ResponseError = None

        if ResponseError and isinstance(exc, ResponseError):
            print("Rate limited by Google — wait a few minutes and retry")
            return 1
        print(str(exc))
        return 1

    except Exception as exc:
        # Catch pytrends ResponseError by name in case import succeeded
        if exc.__class__.__name__ == "ResponseError":
            print("Rate limited by Google — wait a few minutes and retry")
            return 1
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
