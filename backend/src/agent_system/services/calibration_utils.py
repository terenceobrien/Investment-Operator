"""Shared helpers for scenario return calibration scripts."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from src.agent_system.services.theme_basket_pricer import ThemeBasketPricer


HORIZON_DAYS = 63
ANSI_RED = "\033[91m"
ANSI_RESET = "\033[0m"

THEME_COLUMNS = [
    "scenario_id",
    "theme_id",
    "expected_return",
    "volatility",
    "p10",
    "p25",
    "p75",
    "p90",
    "n_observations",
    "horizon_days",
    "source",
    "last_updated",
    "notes",
]
MARKET_COLUMNS = [
    "scenario_id",
    "ticker",
    "expected_return",
    "volatility",
    "p10",
    "p25",
    "p75",
    "p90",
    "n_observations",
    "horizon_days",
    "source",
    "last_updated",
    "notes",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        print(f"Warning: {path} not found; using empty prior values for comparison.")
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def theme_ids_from_matrix(path: Path) -> list[str]:
    payload = load_json(path)
    matrix = payload.get("themes") if isinstance(payload.get("themes"), dict) else payload
    return sorted(str(key) for key in matrix if key != "metadata")


def theme_baskets_from_matrix(path: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(path)
    matrix = payload.get("themes") if isinstance(payload.get("themes"), dict) else payload
    baskets: dict[str, dict[str, Any]] = {}
    for key, value in matrix.items():
        if key == "metadata":
            continue
        if isinstance(value, dict) and value:
            baskets[str(key)] = value
    return baskets


def old_theme_values(rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    return old_values(rows, item_column="theme_id", aliases=("theme",))


def old_market_values(rows: list[dict[str, str]]) -> dict[tuple[str, str], float]:
    return old_values(rows, item_column="ticker", aliases=("market",))


def old_values(
    rows: list[dict[str, str]],
    *,
    item_column: str,
    aliases: tuple[str, ...] = (),
) -> dict[tuple[str, str], float]:
    out: dict[tuple[str, str], float] = {}
    for row in rows:
        scenario = row.get("scenario_id")
        item = row.get(item_column)
        if item is None:
            for alias in aliases:
                item = row.get(alias)
                if item is not None:
                    break
        if scenario and item:
            value = safe_float(row.get("expected_return"))
            if value is not None:
                out[(scenario, item)] = value
    return out


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "mean": None,
            "volatility": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "n_dates_with_data": 0,
        }
    arr = np.array(values, dtype=float)
    return {
        "mean": float(np.mean(arr)),
        "volatility": float(np.std(arr)),
        "p10": float(np.percentile(arr, 10)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "p90": float(np.percentile(arr, 90)),
        "n_dates_with_data": len(values),
    }


def single_ticker_distribution(
    pricer: ThemeBasketPricer,
    ticker: str,
    dates: list[str],
    *,
    horizon_days: int = HORIZON_DAYS,
) -> dict[str, Any]:
    theme_id = f"__single_{ticker.lower()}"
    matrix = pricer.theme_exposure_matrix
    if isinstance(matrix.get("themes"), dict):
        matrix["themes"][theme_id] = {ticker: 1.0}
    else:
        matrix[theme_id] = {ticker: 1.0}

    values: list[float] = []
    for asof_date in dates:
        result = pricer.get_basket_return(theme_id, asof_date, horizon_days=horizon_days)
        value = result.get("basket_return")
        if value is not None:
            values.append(float(value))
    return distribution(values)


def calibrated_row(
    *,
    scenario_id: str,
    item_key: str,
    item_column: str,
    stats: dict[str, Any],
    source: str,
    notes: str,
    horizon_days: int = HORIZON_DAYS,
) -> dict[str, Any] | None:
    if int(stats.get("n_dates_with_data") or 0) <= 0:
        return None
    return {
        "scenario_id": scenario_id,
        item_column: item_key,
        "expected_return": stats.get("mean"),
        "volatility": stats.get("volatility"),
        "p10": stats.get("p10"),
        "p25": stats.get("p25"),
        "p75": stats.get("p75"),
        "p90": stats.get("p90"),
        "n_observations": stats.get("n_dates_with_data"),
        "horizon_days": horizon_days,
        "source": source,
        "last_updated": date.today().isoformat(),
        "notes": notes,
    }


def format_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:+.1f}%"


def print_comparison(
    label: str,
    rows: list[dict[str, Any]],
    old_value_map: dict[tuple[str, str], float],
    item_column: str,
) -> list[tuple[str, float]]:
    deltas: list[tuple[str, float]] = []
    print()
    print(label)
    print(f"{'Scenario':<24} {'Cell':<42} {'Old':>10} {'New':>10} {'Delta':>10} {'N':>4}  Flag")
    print("-" * 112)
    for row in rows:
        scenario = str(row["scenario_id"])
        item = str(row[item_column])
        item_display = f"{item} [OVERRIDE]" if row.get("source") == "manual_override" else item
        old = old_value_map.get((scenario, item))
        new = float(row["expected_return"])
        delta = None if old is None else new - old
        flag = ""
        if delta is not None:
            deltas.append((f"{scenario}/{item}", delta))
            if abs(delta) > 0.05:
                flag = f"{ANSI_RED}>5pp{ANSI_RESET}"
        print(
            f"{scenario:<24} {item_display:<42} {format_pct(old):>10} "
            f"{format_pct(new):>10} {format_pct(delta):>10} "
            f"{int(row['n_observations']):>4}  {flag}"
        )
    return deltas


def confirm_apply(prompt: str = "Apply these calibrations? (y/n): ") -> bool:
    return input(prompt).strip() in {"y", "Y"}


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def print_summary(
    *,
    theme_rows: list[dict[str, Any]],
    market_rows: list[dict[str, Any]],
    deltas: list[tuple[str, float]],
    theme_path: Path,
    market_path: Path,
) -> None:
    total_cells = len(theme_rows) + len(market_rows)
    comparable = [abs(delta) for _, delta in deltas]
    average_abs_delta = float(np.mean(comparable)) if comparable else 0.0
    largest_cell, largest_delta = ("n/a", 0.0)
    if deltas:
        largest_cell, largest_delta = max(deltas, key=lambda item: abs(item[1]))

    print()
    print("CALIBRATION SUMMARY")
    print(f"  Total cells updated:      {total_cells}")
    print(f"  Average absolute delta:   {average_abs_delta * 100:.1f}pp")
    print(f"  Largest delta:            {largest_cell} ({largest_delta * 100:+.1f}pp)")
    print(f"  Theme CSV written to:     {theme_path}")
    print(f"  Market CSV written to:    {market_path}")
