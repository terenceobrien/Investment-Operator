"""Daily regime state cron job.

Run once per US trading day after market close to compute and persist the daily
regime snapshot.

Resolves the asof_date to the most recent US business day, runs the regime
classifier, and persists the result through the storage abstraction.

Designed to run on Railway as a scheduled service, but also runnable locally
for verification.

Usage:
    python -m scripts.run_daily_regime_cron
    python -m scripts.run_daily_regime_cron --asof 2026-06-17
    python -m scripts.run_daily_regime_cron --dry-run
    python -m scripts.run_daily_regime_cron --verbose

Exit codes:
    0 = success
    1 = computation failure
    2 = persistence failure
    3 = data quality below threshold (record not saved)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

logger = logging.getLogger(__name__)


def resolve_trading_date(asof: Optional[str] = None) -> str:
    """Resolve asof_date to the most recent US business day.

    US holidays are not handled in V1; the resolver only walks back across
    weekends. Holiday records can be overwritten later by rerunning --asof.
    """

    if asof:
        return asof

    from zoneinfo import ZoneInfo

    now_et = datetime.now(ZoneInfo("America/New_York"))
    cutoff = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    candidate = now_et.date() if now_et >= cutoff else now_et.date() - timedelta(days=1)

    while candidate.weekday() >= 5:
        candidate = candidate - timedelta(days=1)

    return candidate.strftime("%Y-%m-%d")


def assess_data_quality(state) -> tuple[float, list[str]]:
    """Compute overall data quality from layer data_quality scores."""

    qualities = list(state.layer_data_quality.values()) if state.layer_data_quality else []
    if not qualities:
        return 0.0, ["No layer data quality scores available"]

    avg = sum(qualities) / len(qualities)
    concerns: list[str] = []
    for layer_name, quality in state.layer_data_quality.items():
        if quality < 0.3:
            concerns.append(f"{layer_name} layer data quality very low ({quality:.0%})")
        elif quality < 0.5:
            concerns.append(f"{layer_name} layer data quality below 50% ({quality:.0%})")
    return avg, concerns


def _fmt_score(value: float | None) -> str:
    return " n/a " if value is None else f"{value:>5.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily regime state cron job.")
    parser.add_argument(
        "--asof",
        default=None,
        help="Override asof_date (YYYY-MM-DD). Defaults to most recent US business day.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute the regime state but do not save it.",
    )
    parser.add_argument(
        "--data-quality-floor",
        type=float,
        default=0.20,
        help="If overall data quality is below this threshold, do not save.",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asof_date = resolve_trading_date(args.asof)
    print("\n" + "=" * 70)
    print(f"DAILY REGIME CRON - {asof_date}")
    print(f"  current UTC: {datetime.now(timezone.utc).isoformat()}")
    print(f"  dry-run:     {args.dry_run}")
    print("=" * 70 + "\n")

    try:
        from src.state.regime_state import build_regime_state

        state = build_regime_state(save=False, asof_date=args.asof)
        if args.asof is None:
            state.asof_date = asof_date
    except Exception as exc:
        logger.exception("Regime computation failed")
        print(f"\nFAILED to compute regime state: {exc}")
        return 1

    avg_quality, concerns = assess_data_quality(state)

    print("\n" + "-" * 70)
    print("REGIME COMPUTED")
    print(f"  environment:    {state.environment}")
    print(f"  composite:      {state.score_total}/100")
    print(f"  confidence:     {state.confidence}/100")
    print("  layer scores:")
    for layer in ("monetary", "credit", "volatility", "breadth", "positioning"):
        score = getattr(state, f"layer_{layer}")
        quality = state.layer_data_quality.get(layer, 0.0)
        print(f"    {layer:<12} {_fmt_score(score)}/10  (data quality {quality:.0%})")
    print(f"  overall data quality: {avg_quality:.0%}")
    print("-" * 70)

    if concerns:
        print("\nDATA QUALITY CONCERNS:")
        for concern in concerns:
            print(f"  - {concern}")

    if avg_quality < args.data_quality_floor:
        print(
            f"\nData quality {avg_quality:.0%} below floor "
            f"{args.data_quality_floor:.0%}"
        )
        print("Record NOT saved. Investigate data dependencies and re-run.")
        return 3

    if args.dry_run:
        print(f"\n[dry-run] Would save regime state for {asof_date}")
        return 0

    try:
        from src.agent_system.storage.repository import save_regime_state

        record_id = save_regime_state(state.to_dict())
        print(f"\nRegime state saved (record_id={record_id})")
    except Exception as exc:
        logger.exception("Persistence failed")
        print(f"\nFAILED to save regime state: {exc}")
        return 2

    try:
        path = state.save_snapshot(save_via_backend=False)
        print(f"Local snapshot also saved: {path}")
    except Exception as exc:
        logger.warning("Local snapshot failed: %s (backend save succeeded)", exc)

    print(f"\nDone. Regime state for {asof_date} is available.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
