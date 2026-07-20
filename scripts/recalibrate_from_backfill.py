"""Recalibrate scenario return CSVs from accumulated analogue backfill rows."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.services.calibration_utils import (
    HORIZON_DAYS,
    MARKET_COLUMNS,
    THEME_COLUMNS,
    calibrated_row,
    confirm_apply,
    load_csv_rows,
    old_market_values,
    old_theme_values,
    print_comparison,
    print_summary,
    single_ticker_distribution,
    theme_ids_from_matrix,
    write_csv,
)
from src.agent_system.services.theme_basket_pricer import ThemeBasketPricer


DEFAULT_BACKFILL_PATH = REPO_ROOT / "data" / "cache" / "backfilled_analogues.jsonl"
THEME_EXPOSURE_MATRIX_PATH = REPO_ROOT / "data" / "reference" / "theme_exposure_matrix.json"
THEME_RETURNS_PATH = REPO_ROOT / "data" / "reference" / "scenario_theme_returns.csv"
MARKET_RETURNS_PATH = REPO_ROOT / "data" / "reference" / "scenario_market_returns.csv"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "price_history"
SOURCE = "analogue_calibration_v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recalibrate scenario returns from backfilled analogue JSONL rows.")
    parser.add_argument("--input-path", default=str(DEFAULT_BACKFILL_PATH))
    return parser.parse_args()


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _load_backfill(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Backfilled analogue file not found: {path}")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no} of {path}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object on line {line_no} of {path}")
            rows.append(payload)
    if not rows:
        raise ValueError(f"Backfilled analogue file is empty: {path}")

    first = rows[0]
    if "mapped_scenario_id" not in first:
        available = ", ".join(sorted(first.keys())[:20])
        raise KeyError(
            "Expected first backfill row to contain 'mapped_scenario_id'. "
            f"Available fields include: {available}"
        )
    print("Confirmed backfill scenario field: mapped_scenario_id")
    return rows


def _group_dates_by_scenario(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        scenario_id = row.get("mapped_scenario_id")
        analogue_date = row.get("analogue_date") or row.get("date")
        if scenario_id and analogue_date:
            grouped[str(scenario_id)].append(str(analogue_date))
    return dict(sorted(grouped.items()))


def _print_sample_sizes(grouped_dates: dict[str, list[str]]) -> None:
    print()
    print("SCENARIO SAMPLE SIZES")
    for scenario_id, dates in grouped_dates.items():
        warning = "  WARNING: fewer than 20 observations" if len(dates) < 20 else ""
        print(f"  {scenario_id:<24} {len(dates):>5}{warning}")


def main() -> int:
    args = _parse_args()
    input_path = _resolve_path(args.input_path)
    rows = _load_backfill(input_path)
    grouped_dates = _group_dates_by_scenario(rows)
    if not grouped_dates:
        raise ValueError("No analogue dates grouped by mapped_scenario_id.")
    _print_sample_sizes(grouped_dates)

    pricer = ThemeBasketPricer(
        theme_exposure_matrix_path=str(THEME_EXPOSURE_MATRIX_PATH),
        cache_dir=str(CACHE_DIR),
    )
    themes = theme_ids_from_matrix(THEME_EXPOSURE_MATRIX_PATH)
    old_theme = old_theme_values(load_csv_rows(THEME_RETURNS_PATH))
    old_market = old_market_values(load_csv_rows(MARKET_RETURNS_PATH))

    theme_rows: list[dict[str, Any]] = []
    market_rows: list[dict[str, Any]] = []
    for scenario_id, dates in grouped_dates.items():
        notes = f"calibrated from {len(dates)} analogue matches"
        for theme_id in themes:
            stats = pricer.get_basket_distribution(theme_id, dates, horizon_days=HORIZON_DAYS)
            row = calibrated_row(
                scenario_id=scenario_id,
                item_key=theme_id,
                item_column="theme_id",
                stats=stats,
                source=SOURCE,
                notes=notes,
            )
            if row is not None:
                theme_rows.append(row)

        for ticker in ("SPY", "QQQ", "IWM"):
            stats = single_ticker_distribution(pricer, ticker, dates)
            row = calibrated_row(
                scenario_id=scenario_id,
                item_key=ticker,
                item_column="ticker",
                stats=stats,
                source=SOURCE,
                notes=notes,
            )
            if row is not None:
                market_rows.append(row)

    deltas = []
    deltas.extend(print_comparison("THEME CALIBRATION COMPARISON", theme_rows, old_theme, "theme_id"))
    deltas.extend(print_comparison("MARKET CALIBRATION COMPARISON", market_rows, old_market, "ticker"))

    print()
    if not confirm_apply():
        print("Calibration not applied.")
        return 0

    write_csv(THEME_RETURNS_PATH, THEME_COLUMNS, theme_rows)
    write_csv(MARKET_RETURNS_PATH, MARKET_COLUMNS, market_rows)
    print_summary(
        theme_rows=theme_rows,
        market_rows=market_rows,
        deltas=deltas,
        theme_path=THEME_RETURNS_PATH,
        market_path=MARKET_RETURNS_PATH,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
