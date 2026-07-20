"""Backfill rolling-composite analogue matches across historical as-of dates."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.forecasting.historical_calibration import map_analogue_to_scenario
from src.analysis.analogues import _load_df
from src.analysis.rolling_composite import get_rolling_composite


DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "cache" / "backfilled_analogues.jsonl"
SCENARIO_IDS = [
    "sticky_late_cycle_ai",
    "reopening_soft_landing",
    "oil_inflation_tail",
    "late_cycle_risk_off",
    "ai_capex_rollover",
]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historical rolling-composite analogue rows.")
    parser.add_argument("--start-date", default="2010-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--interval-days", type=int, default=30)
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    return parser.parse_args()


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _date_grid(
    start_date: str,
    end_date: str,
    interval_days: int,
    trading_dates: list[pd.Timestamp],
) -> list[str]:
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()
    interval = max(1, int(interval_days))
    dates: list[str] = []
    seen: set[str] = set()
    cursor = start
    while cursor <= end:
        resolved = _next_trading_day(cursor, trading_dates)
        if resolved is not None and resolved.date() <= end:
            text = resolved.strftime("%Y-%m-%d")
            if text not in seen:
                seen.add(text)
                dates.append(text)
        cursor += timedelta(days=interval)
    return dates


def _next_trading_day(target: date, trading_dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    target_ts = pd.Timestamp(target)
    for trading_date in trading_dates:
        if trading_date >= target_ts:
            return trading_date
    return None


def _forward_return(match: dict[str, Any], horizon: str) -> Any:
    flat = match.get(f"forward_return_{horizon}")
    if flat is not None:
        return flat
    forward_returns = match.get("forward_returns")
    if isinstance(forward_returns, dict):
        return forward_returns.get(horizon)
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _backfill_row(asof_date: str, match: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    scenario_id, confidence, rationale = map_analogue_to_scenario(
        dict(match),
        SCENARIO_IDS,
        scenario_mapping_horizon="63d",
        warnings=warnings,
    )
    row = dict(match)
    analogue_date = str(match.get("date") or "")
    row.update(
        {
            "asof_date": asof_date,
            "analogue_date": analogue_date,
            "mapped_scenario_id": scenario_id,
            "mapped_scenario_confidence": confidence,
            "mapping_rationale": rationale,
            "mapping_warnings": warnings,
            "similarity_score": match.get("similarity_score"),
            "vix_level": match.get("vix_level"),
            "score_total": match.get("score_total"),
            "forward_return_63d": _forward_return(match, "63d"),
            "forward_return_126d": _forward_return(match, "126d"),
            "environment": match.get("environment"),
        }
    )
    return _jsonable(row)


def main() -> int:
    args = _parse_args()
    output_path = _resolve_path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    df = _load_df()
    trading_dates = [pd.Timestamp(item) for item in sorted(df["date"].dropna().unique())]
    dates = _date_grid(args.start_date, args.end_date, args.interval_days, trading_dates)
    if not dates:
        raise ValueError("No trading dates resolved for requested backfill range.")

    print("Backfilling rolling-composite analogues")
    print(f"Dates: {dates[0]} to {dates[-1]} ({len(dates)} resolved trading dates)")
    print(f"Output: {output_path}")

    total_matches = 0
    scenario_counts: Counter[str] = Counter()
    with output_path.open("w", encoding="utf-8") as fh:
        for idx, asof_date in enumerate(dates, start=1):
            result = get_rolling_composite(asof_date=asof_date)
            result_asof = str(result.get("asof_date") or asof_date)
            matches = [item for item in (result.get("analogues") or []) if isinstance(item, dict)]
            for match in matches:
                row = _backfill_row(result_asof, match)
                scenario_counts[str(row.get("mapped_scenario_id") or "unmapped")] += 1
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                total_matches += 1
            if idx % 12 == 0 or idx == len(dates):
                print(f"Processed {idx}/{len(dates)} dates; collected {total_matches} analogue matches.")

    print()
    print("BACKFILL SUMMARY")
    print(f"  Total dates processed:          {len(dates)}")
    print(f"  Total analogue matches:         {total_matches}")
    print("  Matches by mapped_scenario_id:")
    for scenario_id, count in sorted(scenario_counts.items()):
        print(f"    {scenario_id:<24} {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
