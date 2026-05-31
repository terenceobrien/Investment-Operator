"""
Build sector and industry percentile distributions for screen calibration.

This is a pure-data tool. It fetches FundamentalDataBundle objects for a
provided ticker universe, derives screen-relevant metrics, trims implausible
values per calibration_bounds.yaml, and writes a generated JSON asset for
future sector-aware threshold adoption.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src.agent_system.data import FundamentalDataBundle, get_fundamental_data

BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_UNIVERSE_PATH = (
    BACKEND_ROOT / "src/agent_system/config/calibration_universe.txt"
)
DEFAULT_BOUNDS_PATH = BACKEND_ROOT / "src/agent_system/config/calibration_bounds.yaml"
DEFAULT_OUTPUT_PATH = (
    BACKEND_ROOT / "data/agent_system/calibration/sector_distributions.json"
)

METRICS = [
    "debt_to_ebitda",
    "debt_to_assets",
    "fcf_margin",
    "operating_margin",
    "net_margin",
    "gross_margin",
    "revenue_yoy_growth",
    "revenue_3yr_cagr",
    "cash_runway_quarters",
]
SUMMARY_METRICS = ["debt_to_ebitda", "operating_margin", "revenue_3yr_cagr"]
YAHOO_TO_GICS_SECTOR = {
    "Basic Materials": "Materials",
    "Communication Services": "Communication Services",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Energy": "Energy",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Technology": "Information Technology",
    "Utilities": "Utilities",
}


def read_universe(path: Path, limit: int | None = None) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"Calibration universe not found: {path}. "
            "Provide --universe or add config/calibration_universe.txt."
        )
    tickers: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            ticker = line.strip().upper()
            if not ticker or ticker.startswith("#") or ticker in seen:
                continue
            seen.add(ticker)
            tickers.append(ticker)
            if limit is not None and len(tickers) >= limit:
                break
    return tickers


def load_calibration_bounds(path: Path = DEFAULT_BOUNDS_PATH) -> dict[str, dict]:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("calibration_bounds.yaml must contain a mapping")
    bounds: dict[str, dict] = {}
    for metric in METRICS:
        config = raw.get(metric)
        if not isinstance(config, dict):
            raise ValueError(f"Missing calibration bounds for {metric}")
        bounds[metric] = {
            "min": float(config["min"]),
            "max": float(config["max"]),
            "inclusion": config.get("inclusion", ""),
        }
    return bounds


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def normalize_sector(sector: str | None) -> str | None:
    if sector is None:
        return None
    stripped = sector.strip()
    if not stripped:
        return None
    return YAHOO_TO_GICS_SECTOR.get(stripped, stripped)


def _within_bounds(value: float, metric: str, bounds: dict[str, dict]) -> bool:
    return float(bounds[metric]["min"]) <= value <= float(bounds[metric]["max"])


def _bounded(value: float | None, metric: str, bounds: dict[str, dict]) -> dict:
    if value is None or not math.isfinite(value):
        return {"value": None, "dropped": False}
    if not _within_bounds(value, metric, bounds):
        return {"value": None, "dropped": True}
    return {"value": value, "dropped": False}


def derive_metric_values(
    bundle: FundamentalDataBundle,
    bounds: dict[str, dict],
) -> dict[str, dict]:
    facts = bundle.company_facts
    results = {metric: {"value": None, "dropped": False} for metric in METRICS}
    if facts is None:
        return results

    if facts.total_debt is not None and facts.ebitda_ttm is not None:
        if facts.ebitda_ttm <= 0 or facts.total_debt < 0:
            results["debt_to_ebitda"] = {"value": None, "dropped": True}
        else:
            results["debt_to_ebitda"] = _bounded(
                facts.total_debt / facts.ebitda_ttm,
                "debt_to_ebitda",
                bounds,
            )

    if facts.total_debt is not None and facts.total_assets is not None:
        if facts.total_assets <= 0:
            results["debt_to_assets"] = {"value": None, "dropped": True}
        else:
            results["debt_to_assets"] = _bounded(
                facts.total_debt / facts.total_assets,
                "debt_to_assets",
                bounds,
            )

    fcf_margin = _safe_ratio(facts.free_cash_flow_ttm, facts.revenue_ttm)
    if (
        facts.free_cash_flow_ttm is not None
        and facts.revenue_ttm is not None
        and facts.revenue_ttm <= 0
    ):
        results["fcf_margin"] = {"value": None, "dropped": True}
    else:
        results["fcf_margin"] = _bounded(fcf_margin, "fcf_margin", bounds)

    for metric, value in [
        ("operating_margin", facts.operating_margin),
        ("net_margin", facts.net_margin),
        ("gross_margin", facts.gross_margin),
        ("revenue_yoy_growth", facts.revenue_yoy_growth),
        ("revenue_3yr_cagr", facts.revenue_3yr_cagr),
    ]:
        results[metric] = _bounded(value, metric, bounds)

    if facts.operating_cash_flow_ttm is not None and facts.operating_cash_flow_ttm < 0:
        quarterly_burn = -facts.operating_cash_flow_ttm / 4
        results["cash_runway_quarters"] = _bounded(
            _safe_ratio(facts.cash_and_equivalents, quarterly_burn),
            "cash_runway_quarters",
            bounds,
        )

    return results


def compute_percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("Cannot compute percentiles for an empty sample")
    sorted_values = sorted(float(value) for value in values)
    n = len(sorted_values)

    def percentile(pct: float) -> float:
        position = (n - 1) * pct / 100
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return sorted_values[int(position)]
        lower_weight = upper - position
        upper_weight = position - lower
        return sorted_values[lower] * lower_weight + sorted_values[upper] * upper_weight

    return {
        "p10": percentile(10),
        "p25": percentile(25),
        "p50": percentile(50),
        "p75": percentile(75),
        "p90": percentile(90),
    }


def _empty_metric_accumulator() -> dict:
    return {metric: {"values": [], "dropped": 0} for metric in METRICS}


def _bucket_summary(metric_bucket: dict, min_n: int) -> dict | None:
    values = metric_bucket["values"]
    if len(values) < min_n:
        return None
    return {
        "n": len(values),
        "dropped": metric_bucket["dropped"],
        **compute_percentiles(values),
    }


def build_distributions(
    rows: list[dict],
    *,
    min_sector_n: int = 20,
    min_industry_n: int = 30,
    min_all_n: int = 20,
) -> dict:
    all_acc = _empty_metric_accumulator()
    sector_acc: dict[str, dict] = defaultdict(_empty_metric_accumulator)
    industry_acc: dict[str, dict] = defaultdict(_empty_metric_accumulator)

    for row in rows:
        sector = row.get("sector") or "Unknown"
        industry = row.get("industry")
        metrics = row["metrics"]

        for metric, outcome in metrics.items():
            value = outcome["value"]
            dropped = bool(outcome["dropped"])
            targets = [all_acc, sector_acc[sector]]
            if industry:
                targets.append(industry_acc[industry])
            for target in targets:
                if dropped:
                    target[metric]["dropped"] += 1
                elif value is not None:
                    target[metric]["values"].append(value)

    sector_output = {
        sector: {
            metric: summary
            for metric, bucket in metric_acc.items()
            if (summary := _bucket_summary(bucket, min_sector_n)) is not None
        }
        for sector, metric_acc in sorted(sector_acc.items())
    }
    industry_output = {
        industry: {
            metric: summary
            for metric, bucket in metric_acc.items()
            if (summary := _bucket_summary(bucket, min_industry_n)) is not None
        }
        for industry, metric_acc in sorted(industry_acc.items())
    }
    industry_output = {
        industry: metrics for industry, metrics in industry_output.items() if metrics
    }
    all_output = {
        metric: summary
        for metric, bucket in all_acc.items()
        if (summary := _bucket_summary(bucket, min_all_n)) is not None
    }

    return {
        "sector": sector_output,
        "industry": industry_output,
        "ALL": all_output,
    }


def _fetch_success(bundle: FundamentalDataBundle) -> bool:
    return bool(bundle.sec_fetch_success or bundle.yahoo_fetch_success)


def fetch_calibration_rows(
    tickers: list[str],
    *,
    bounds: dict[str, dict],
    force_refresh: bool = False,
    progress_every: int = 25,
) -> tuple[list[dict], int, int]:
    rows: list[dict] = []
    fetched = 0
    failed = 0
    total = len(tickers)
    for idx, ticker in enumerate(tickers, 1):
        try:
            bundle = get_fundamental_data(ticker, force_refresh=force_refresh)
        except Exception:
            failed += 1
            continue
        if _fetch_success(bundle):
            fetched += 1
        else:
            failed += 1
        rows.append(
            {
                "ticker": ticker,
                "sector": normalize_sector(bundle.sector),
                "industry": bundle.industry,
                "metrics": derive_metric_values(bundle, bounds),
                "fetch_success": _fetch_success(bundle),
            }
        )
        if progress_every > 0 and (idx % progress_every == 0 or idx == total):
            print(f"fetched {idx}/{total}")
    return rows, fetched, failed


def build_calibration_asset(
    *,
    tickers: list[str],
    rows: list[dict],
    universe_fetched: int,
    universe_failed: int,
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "universe_size": len(tickers),
        "universe_fetched": universe_fetched,
        "universe_failed": universe_failed,
        "buckets": build_distributions(rows),
    }


def _fmt_summary(summary: dict | None) -> str:
    if not summary:
        return "n/a"
    return f"{summary['p50']:.2f} (n={summary['n']})"


def print_sector_summary(asset: dict) -> None:
    print()
    print("Sector calibration summary (p50):")
    sectors = asset["buckets"].get("sector", {})
    for sector, metrics in sorted(sectors.items()):
        print(
            f"  {sector}: "
            f"debt/EBITDA={_fmt_summary(metrics.get('debt_to_ebitda'))}, "
            f"op_margin={_fmt_summary(metrics.get('operating_margin'))}, "
            f"rev_3yr_cagr={_fmt_summary(metrics.get('revenue_3yr_cagr'))}"
        )


def run_harness(
    *,
    universe_path: Path = DEFAULT_UNIVERSE_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    force_refresh: bool = False,
    limit: int | None = None,
) -> dict:
    bounds = load_calibration_bounds()
    tickers = read_universe(universe_path, limit=limit)
    rows, fetched, failed = fetch_calibration_rows(
        tickers,
        bounds=bounds,
        force_refresh=force_refresh,
    )
    asset = build_calibration_asset(
        tickers=tickers,
        rows=rows,
        universe_fetched=fetched,
        universe_failed=failed,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asset, indent=2, sort_keys=True), encoding="utf-8")
    print_sector_summary(asset)
    print()
    print(f"Wrote calibration asset to {output_path}")
    print(f"Universe fetched: {fetched}; failed: {failed}; total: {len(tickers)}")
    return asset


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build sector/industry distributions for screen calibration."
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=DEFAULT_UNIVERSE_PATH,
        help="Path to one-ticker-per-line calibration universe.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Output JSON asset path.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the data cache while fetching bundles.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Fetch only the first N tickers for quick smoke runs.",
    )
    return parser


def main() -> None:
    args = _build_argparser().parse_args()
    run_harness(
        universe_path=args.universe,
        output_path=args.out,
        force_refresh=args.force_refresh,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
