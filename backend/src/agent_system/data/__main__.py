"""CLI to fetch a single ticker's bundle and pretty-print key fields."""
from __future__ import annotations

import argparse

from src.agent_system.data import get_fundamental_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch fundamental data for a ticker.")
    parser.add_argument("ticker", help="Ticker symbol (e.g. AAPL)")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass cache")
    parser.add_argument("--full", action="store_true", help="Print full bundle as JSON")
    args = parser.parse_args()

    bundle = get_fundamental_data(args.ticker, force_refresh=args.force_refresh)

    if args.full:
        print(bundle.model_dump_json(indent=2))
        return

    print(f"Ticker: {bundle.ticker}")
    print(f"  is_etf: {bundle.is_etf}")
    print(f"  Company: {bundle.company_name or '(unknown)'}")
    print(
        f"  Fetch success: SEC={bundle.sec_fetch_success}, "
        f"Yahoo={bundle.yahoo_fetch_success}"
    )
    print(f"  Duration: {bundle.fetch_duration_ms}ms")
    print(f"  Price: ${bundle.current_price}")
    print(
        f"  Market cap: ${bundle.market_cap:,}"
        if bundle.market_cap
        else "  Market cap: None"
    )
    print(f"  Trailing P/E: {bundle.trailing_pe}")
    print(f"  Forward P/E: {bundle.forward_pe}")
    print(
        "  Analyst buy/hold/sell: "
        f"{bundle.analyst_count_buy}/{bundle.analyst_count_hold}/"
        f"{bundle.analyst_count_sell}"
    )
    if bundle.company_facts and bundle.company_facts.revenue_ttm is not None:
        print(f"  Revenue TTM: ${bundle.company_facts.revenue_ttm:,}")
    if bundle.most_recent_10k:
        text_length = len(bundle.most_recent_10k.extracted_text or "")
        print(
            f"  Most recent 10-K: {bundle.most_recent_10k.filing_date}, "
            f"text {text_length} chars"
        )
    if bundle.fetch_errors:
        print(f"  Errors: {bundle.fetch_errors}")


if __name__ == "__main__":
    main()
