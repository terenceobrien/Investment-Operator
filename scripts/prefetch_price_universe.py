"""Prefetch price histories for theme baskets and core market proxies."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.services.theme_basket_pricer import ThemeBasketPricer


THEME_EXPOSURE_MATRIX_PATH = REPO_ROOT / "data" / "reference" / "theme_exposure_matrix.json"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "price_history"

TIER_2_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "RSP",
    "DIA",
    "XLI",
    "XLF",
    "XLK",
    "XLV",
    "XLE",
    "XLY",
    "XLP",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
    "SMH",
    "XBI",
    "KIE",
    "KRE",
    "KWEB",
    "ARKK",
    "GLD",
    "SLV",
    "USO",
    "UNG",
    "TLT",
    "IEF",
    "SHY",
    "HYG",
    "LQD",
    "EMB",
    "VXX",
]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _extract_theme_tickers(path: Path) -> list[str]:
    payload = _load_json(path)
    matrix = payload.get("themes") if isinstance(payload.get("themes"), dict) else payload
    tickers: set[str] = set()
    for key, basket in matrix.items():
        if key == "metadata":
            continue
        if not isinstance(basket, dict):
            continue
        tickers.update(str(ticker).strip().upper() for ticker in basket if str(ticker).strip())
    return sorted(tickers)


def _disk_usage_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


def main() -> int:
    tier_1 = _extract_theme_tickers(THEME_EXPOSURE_MATRIX_PATH)
    universe = sorted(set(tier_1) | set(TIER_2_TICKERS))
    pricer = ThemeBasketPricer(
        theme_exposure_matrix_path=str(THEME_EXPOSURE_MATRIX_PATH),
        cache_dir=str(CACHE_DIR),
    )

    print("Price universe prefetch")
    print(f"Tier 1 tickers: {len(tier_1)}")
    print(f"Tier 2 tickers: {len(TIER_2_TICKERS)}")
    print(f"Union tickers: {len(universe)}")
    print()

    fetched = 0
    cached = 0
    failed: list[str] = []
    for start in range(0, len(universe), 10):
        chunk = universe[start : start + 10]
        result = pricer.prefetch_universe(chunk)
        fetched += int(result.get("fetched") or 0)
        cached += int(result.get("cached") or 0)
        failed.extend(str(ticker) for ticker in result.get("failed") or [])
        processed = min(start + len(chunk), len(universe))
        print(f"Processed {processed}/{len(universe)} tickers...")

    disk_usage = _disk_usage_bytes(CACHE_DIR)
    print()
    print("PREFETCH SUMMARY")
    print(f"  Total tickers attempted: {len(universe)}")
    print(f"  Fetched successfully:    {fetched}")
    print(f"  Already cached:          {cached}")
    print(f"  Failed:                  {len(failed)}")
    if failed:
        print(f"  Failed tickers:          {', '.join(sorted(set(failed)))}")
    print(f"  Cache disk usage:        {_format_bytes(disk_usage)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
