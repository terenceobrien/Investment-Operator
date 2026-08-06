"""
Run the deterministic financial-health screen against arbitrary tickers.

Usage from repo root:
    python -m src.agent_system.evals.run_screen_harness --tickers AAPL

    python -m src.agent_system.evals.run_screen_harness \
      --tickers POWL,ETN,GEV,PWR,CEG,HUBB,VRT,FIX,D,NRG,MOD,VST \
      --out data/agent_system/screen_evals/ai_power_screen.jsonl

This is a pure-data, no-LLM eval harness. It fetches FundamentalDataBundle
objects, applies the deterministic financial-health screen, prints compact
verdict summaries, and writes self-contained JSONL output for threshold review.
It does not invoke the research cycle and does not write to production storage.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.agent_system.data import FundamentalDataBundle, get_fundamental_data
from src.agent_system.rules.fundamental_screen import screen_candidate
from src.agent_system.schemas.fundamental_screen import FundamentalScreen
from src.agent_system.paths import screen_evals_dir

DEFAULT_OUTPUT_DIR = screen_evals_dir(create=False)


def _default_output_path() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"screen_{timestamp}.jsonl"


def _parse_tickers(raw: str) -> list[str]:
    tickers = [ticker.strip().upper() for ticker in raw.split(",") if ticker.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        deduped.append(ticker)
    return deduped


def _extract_key_metrics(bundle: FundamentalDataBundle) -> dict:
    facts = bundle.company_facts
    return {
        "revenue_ttm": facts.revenue_ttm if facts else None,
        "free_cash_flow_ttm": facts.free_cash_flow_ttm if facts else None,
        "operating_cash_flow_ttm": facts.operating_cash_flow_ttm if facts else None,
        "total_debt": facts.total_debt if facts else None,
        "cash_and_equivalents": facts.cash_and_equivalents if facts else None,
        "total_assets": facts.total_assets if facts else None,
        "stockholders_equity": facts.stockholders_equity if facts else None,
        "operating_income_ttm": facts.operating_income_ttm if facts else None,
        "depreciation_amortization_ttm": (
            facts.depreciation_amortization_ttm if facts else None
        ),
        "ebitda_ttm": facts.ebitda_ttm if facts else None,
        "ebitda_proxy_operating_income_ttm": facts.operating_income_ttm if facts else None,
        "revenue_yoy_growth": facts.revenue_yoy_growth if facts else None,
        "revenue_3yr_cagr": facts.revenue_3yr_cagr if facts else None,
        "gross_margin": facts.gross_margin if facts else None,
        "operating_margin": facts.operating_margin if facts else None,
        "net_margin": facts.net_margin if facts else None,
        "current_price": bundle.current_price,
        "mean_price_target": bundle.mean_price_target,
        "analyst_count_buy": bundle.analyst_count_buy,
        "analyst_count_hold": bundle.analyst_count_hold,
        "analyst_count_sell": bundle.analyst_count_sell,
    }


def _bundle_diagnostics(bundle: FundamentalDataBundle) -> dict:
    return {
        "sec_fetch_success": bundle.sec_fetch_success,
        "yahoo_fetch_success": bundle.yahoo_fetch_success,
        "fetch_errors": bundle.fetch_errors,
    }


def _output_record(
    *,
    ticker: str,
    bundle: FundamentalDataBundle,
    screen: FundamentalScreen,
) -> dict:
    return {
        "ticker": ticker,
        "screen": screen.model_dump(mode="json"),
        "key_metrics": _extract_key_metrics(bundle),
        "bundle_diagnostics": _bundle_diagnostics(bundle),
    }


def _print_summary(ticker: str, screen: FundamentalScreen) -> None:
    line = (
        f"{ticker}: {screen.archetype.value} / {screen.verdict.value} "
        f"— {screen.reason}"
    )
    if screen.crowding_flag:
        line += f"  [CROWDED: {screen.crowding_detail}]"
    print(line)


def run_harness(
    *,
    tickers: list[str],
    output_path: Path,
    force_refresh: bool = False,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records_written = 0
    with output_path.open("w", encoding="utf-8") as fh:
        for ticker in tickers:
            bundle = get_fundamental_data(ticker, force_refresh=force_refresh)
            screen = screen_candidate(bundle)
            _print_summary(ticker, screen)
            record = _output_record(ticker=ticker, bundle=bundle, screen=screen)
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            records_written += 1

    print()
    print(f"Wrote {records_written} screen records to {output_path}")
    return {
        "output_path": str(output_path),
        "ticker_count": len(tickers),
        "records_written": records_written,
    }


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the financial-health screen against a ticker list."
    )
    parser.add_argument(
        "--tickers",
        required=True,
        help='Comma-separated ticker list, e.g. "ETN,GEV,PWR".',
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Output JSONL path. Default: "
            "data/agent_system/screen_evals/screen_<timestamp>.jsonl"
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass the data cache when fetching provider data.",
    )
    return parser


def main() -> None:
    parser = _build_argparser()
    args = parser.parse_args()
    tickers = _parse_tickers(args.tickers)
    if not tickers:
        parser.error("--tickers must include at least one ticker")

    run_harness(
        tickers=tickers,
        output_path=args.out or _default_output_path(),
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    main()
