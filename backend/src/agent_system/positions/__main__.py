"""CLI for inspecting the latest Fidelity positions snapshot."""
from __future__ import annotations

import argparse
from datetime import timezone

from src.agent_system.positions.loader import (
    load_latest_positions,
    positions_drop_dir,
    positions_freshness_warning,
)
from src.agent_system.storage.repository import save_schema


def _money(value: float | None) -> str:
    if value is None:
        return ""
    return f"${value:,.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.1%}"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _cmd_show(_args: argparse.Namespace) -> int:
    snapshot = load_latest_positions()
    if snapshot is None:
        print(
            f"No positions file found in {positions_drop_dir()}. "
            "Drop a Fidelity CSV export there to begin tracking positions."
        )
        return 1

    warning = positions_freshness_warning(snapshot)
    save_id = save_schema(snapshot, schema_type="PositionsSnapshot")
    mtime = snapshot.file_mtime.astimezone(timezone.utc).isoformat()
    print(f"Source: {snapshot.source_file}")
    print(f"File mtime: {mtime}")
    if warning:
        print(f"Warning: {warning}")
    print(f"Account: {snapshot.account_number or '(unknown)'} {snapshot.account_name or ''}".rstrip())
    print(f"Total NAV: {_money(snapshot.total_nav_usd)}")
    print(f"Cash: {_money(snapshot.cash_usd)} ({_pct(snapshot.cash_pct)})")
    print(f"Long equity: {_money(snapshot.long_equity_usd)}")
    print(f"Margin used: {_money(snapshot.margin_positions_usd)}")
    print(f"Persisted snapshot id: {save_id}")
    print()
    print(f"{'Symbol':<12} {'Description':<34} {'Qty':>12} {'Last':>12} {'Value':>14} {'%Acct':>8} Type")
    print("-" * 112)
    for position in sorted(
        snapshot.positions,
        key=lambda item: item.current_value_usd,
        reverse=True,
    ):
        qty = "" if position.quantity_shares is None else f"{position.quantity_shares:,.4f}".rstrip("0").rstrip(".")
        print(
            f"{position.symbol:<12} "
            f"{_truncate(position.description, 34):<34} "
            f"{qty:>12} "
            f"{_money(position.last_price_usd):>12} "
            f"{_money(position.current_value_usd):>14} "
            f"{_pct(position.percent_of_account):>8} "
            f"{position.position_type}"
        )
    return 0


def _build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Fidelity positions CSV exports.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    show = subparsers.add_parser("show", help="Show latest positions snapshot.")
    show.set_defaults(func=_cmd_show)
    return parser


def main() -> None:
    args = _build_argparser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
