"""Smoke test for the regime time-series DataFrame loader.

Confirms that data flows from the configured storage backend through the
loader into a usable DataFrame. Run after cron/backfill to verify.

Usage:
    python -m scripts.verify_regime_timeseries
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)


def main() -> int:
    from src.agent_system.regime.timeseries import (
        environment_runs,
        latest_state_summary,
        load_regime_timeseries,
        percentile_context,
    )

    df = load_regime_timeseries()
    print(f"\nLoaded {len(df)} regime state(s)")
    if df.empty:
        print("DataFrame is empty. Run the cron or backfill to populate.")
        return 0

    print(f"  Date range: {df.index.min().date()} -> {df.index.max().date()}")
    print(f"  Columns:    {len(df.columns)}")

    print("\nLast 5 days:")
    print(
        df.tail(5)[
            [
                "score_total",
                "environment",
                "layer_credit",
                "layer_volatility",
                "vix_level",
            ]
        ].to_string()
    )

    latest = latest_state_summary()
    if latest:
        print(
            f"\nLatest state: {latest['environment']} "
            f"composite={latest['score_total']}"
        )

    runs = environment_runs()
    if not runs.empty:
        print(f"\nEnvironment runs ({len(runs)} total):")
        print(runs.tail(10).to_string(index=False))

    pct = percentile_context("vix_level", lookback_days=90)
    if pct:
        print("\nVIX percentile context (90 day):")
        print(f"  Current:    {pct['current_value']:.2f}")
        print(f"  Percentile: {pct['percentile']:.0f}th")
        print(f"  Range:      [{pct['window_min']:.2f}, {pct['window_max']:.2f}]")

    print("\nRegime time-series loader verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
