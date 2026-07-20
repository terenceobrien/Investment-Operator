"""Daily price update batch for tracked trade outcomes.

Suggested cron schedule:
    # Run at 4:30 PM ET on weekdays after market close
    30 16 * * 1-5 cd /path/to/AI_Financial_Operator && python -m scripts.update_trade_prices

Manual invocation:
    python -m scripts.update_trade_prices              # today
    python -m scripts.update_trade_prices --asof 2026-06-15  # specific date
    python -m scripts.update_trade_prices --ticker EME --verbose

The batch is idempotent within a date — re-running for the same asof_date
overwrites the existing PricePoint for that date rather than appending duplicates.
Use load_price_points and check for existing asof_date before appending.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.schemas.trade_outcome import PricePoint, TradeOutcome
from src.agent_system.services.option_pricing import (
    fetch_option_chain_price,
    parse_option_from_description,
)
from src.agent_system.storage.repository import (
    load_open_trade_outcomes,
    load_price_points,
    load_trade_outcomes,
    save_price_point,
    save_trade_outcome,
)


@dataclass
class PriceFetch:
    price: float | None
    close_date: str | None = None
    error: str | None = None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


def _asof_date(value: str | None) -> str:
    return (_parse_date(value) if value else date.today()).isoformat()


def _days_between(start: str | None, end: str) -> int:
    if not start:
        return 0
    return max(0, (_parse_date(end) - _parse_date(start)).days)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1%}"


def _history_close(ticker: str, asof: str) -> PriceFetch:
    import yfinance as yf

    asof_dt = _parse_date(asof)
    start = asof_dt - timedelta(days=14)
    end = asof_dt + timedelta(days=1)
    history = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=end.isoformat(),
        auto_adjust=False,
    )
    if history is None or history.empty or "Close" not in history:
        return PriceFetch(price=None, error="no close history")
    closes = history["Close"].dropna()
    if closes.empty:
        return PriceFetch(price=None, error="no close prices")
    last = closes.iloc[-1]
    close_date = closes.index[-1].date().isoformat()
    return PriceFetch(price=float(last), close_date=close_date)


def fetch_underlying_close(ticker: str, asof: str) -> PriceFetch:
    for attempt in range(2):
        try:
            return _history_close(ticker, asof)
        except Exception as exc:
            if attempt == 0:
                time.sleep(1.0)
                continue
            return PriceFetch(price=None, error=str(exc))
    return PriceFetch(price=None, error="unknown fetch failure")


def _pnl_pct(
    outcome: TradeOutcome,
    *,
    underlying_price: float,
    instrument_price: float | None,
) -> float | None:
    if outcome.entry_underlying_price is None:
        return None
    if instrument_price is not None and outcome.entry_instrument_price is not None:
        entry = outcome.entry_instrument_price
        current = instrument_price
    else:
        entry = outcome.entry_underlying_price
        current = underlying_price
    if entry == 0:
        return None
    sign = -1.0 if outcome.direction == "short" else 1.0
    return sign * ((current - entry) / entry)


def _fetch_instrument_price(outcome: TradeOutcome) -> tuple[float | None, str | None]:
    if outcome.instrument_type not in {"option_underlying", "spread"}:
        return None, None
    parsed = parse_option_from_description(outcome.instrument_description)
    if parsed is None:
        return None, "option parse failed"
    price = fetch_option_chain_price(
        outcome.underlying,
        parsed["expiry"],
        parsed["strikes"],
        parsed["option_type"],
    )
    if price is None:
        return None, "option chain unavailable"
    return price, None


def _prior_point(outcome: TradeOutcome, asof: str) -> PricePoint | None:
    prior = [
        point for point in load_price_points(outcome.trade_id)
        if point.asof_date < asof
    ]
    return prior[-1] if prior else None


def _recompute_cached_metrics(
    outcome: TradeOutcome,
    *,
    asof: str,
    underlying_price: float,
    instrument_price: float | None,
) -> TradeOutcome:
    points = load_price_points(outcome.trade_id)
    pnls = [
        point.unrealized_pnl_pct
        for point in points
        if point.unrealized_pnl_pct is not None
    ]
    days_held = (
        _days_between(outcome.entry_date, asof)
        if outcome.status in {"open", "shadow_rejected"}
        else outcome.days_held
    )
    updated_at = datetime.now(timezone.utc)
    price_update_at = datetime.combine(
        _parse_date(asof),
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return outcome.model_copy_validate(
        {
            "current_underlying_price": underlying_price,
            "current_instrument_price": instrument_price,
            "days_held": days_held,
            "days_since_proposed": _days_between(outcome.cycle_date, asof),
            "last_price_update": price_update_at,
            "max_drawdown_pct": min(pnls) if pnls else None,
            "max_runup_pct": max(pnls) if pnls else None,
            "updated_at": updated_at,
        }
    )


def _entry_trigger_status(
    outcome: TradeOutcome,
    *,
    current_price: float,
) -> tuple[bool, str] | None:
    if outcome.status != "watching" or outcome.entry_target_price is None:
        return None
    target = outcome.entry_target_price
    if outcome.direction == "short":
        triggered = current_price <= target
    else:
        triggered = current_price >= target
    label = "TRIGGERED" if triggered else "not triggered"
    detail = (
        f"{outcome.underlying}  watching, current ${current_price:.2f} "
        f"vs target ${target:.2f} - {label}"
    )
    return triggered, detail


def _update_one(
    outcome: TradeOutcome,
    *,
    asof: str,
    verbose: bool,
) -> tuple[str, dict]:
    fetch = fetch_underlying_close(outcome.underlying, asof)
    if fetch.price is None:
        return "failed", {"outcome": outcome, "error": fetch.error or "fetch failed"}

    notes: list[str] = []
    if fetch.close_date and fetch.close_date != asof:
        notes.append(f"last close date {fetch.close_date}")
    instrument_price, option_note = _fetch_instrument_price(outcome)
    if option_note:
        notes.append(option_note)
        print(
            f"Warning: {outcome.underlying} {option_note}; "
            "using underlying-only tracking."
        )
    unrealized = _pnl_pct(
        outcome,
        underlying_price=fetch.price,
        instrument_price=instrument_price,
    )
    days_held = (
        _days_between(outcome.entry_date, asof)
        if outcome.status == "open"
        else 0
    )
    prior = _prior_point(outcome, asof)
    point = PricePoint(
        trade_id=outcome.trade_id,
        asof_date=asof,
        underlying_price=fetch.price,
        instrument_price=instrument_price,
        unrealized_pnl_pct=unrealized,
        days_held=days_held,
        source="yfinance",
        notes="; ".join(notes) if notes else None,
    )
    save_price_point(point, replace_same_date=True)

    updated = _recompute_cached_metrics(
        outcome,
        asof=asof,
        underlying_price=fetch.price,
        instrument_price=instrument_price,
    )
    trigger = _entry_trigger_status(updated, current_price=fetch.price)
    if trigger and trigger[0] and not updated.entry_triggered:
        updated = updated.model_copy_validate(
            {
                "entry_triggered": True,
                "updated_at": datetime.now(timezone.utc),
            }
        )
    save_trade_outcome(updated)

    if verbose:
        print(
            f"{outcome.underlying}: ${fetch.price:.2f}, "
            f"unrealized={_fmt_pct(unrealized)}, notes={point.notes or '-'}"
        )

    move = None
    if prior is not None and prior.underlying_price:
        move = (fetch.price - prior.underlying_price) / prior.underlying_price
    return (
        "with_option" if instrument_price is not None else "underlying_only",
        {
            "outcome": updated,
            "point": point,
            "move": move,
            "trigger": trigger,
        },
    )


def _shadow_pnl_pct(*, entry_price: float | None, current_price: float) -> float | None:
    if entry_price is None or entry_price == 0:
        return None
    return (current_price - entry_price) / entry_price


def _eligible_shadow_outcomes(
    *,
    asof: str,
    ticker: str | None,
    max_age_days: int,
) -> list[TradeOutcome]:
    shadow = [
        outcome
        for outcome in load_trade_outcomes()
        if outcome.status == "shadow_rejected"
    ]
    if ticker:
        shadow = [
            outcome
            for outcome in shadow
            if outcome.underlying.upper() == ticker.upper()
        ]
    return [
        outcome
        for outcome in shadow
        if _days_between(outcome.cycle_date, asof) <= max_age_days
    ]


def _update_shadow_one(
    outcome: TradeOutcome,
    *,
    asof: str,
    verbose: bool,
) -> tuple[str, dict]:
    notes: list[str] = []
    working = outcome

    if working.entry_underlying_price is None:
        entry_fetch = fetch_underlying_close(working.underlying, working.cycle_date)
        if entry_fetch.price is None:
            return (
                "failed",
                {
                    "outcome": outcome,
                    "error": entry_fetch.error or "entry fetch failed",
                },
            )
        if entry_fetch.close_date and entry_fetch.close_date != working.cycle_date:
            notes.append(
                f"synthetic entry requested {working.cycle_date}; "
                f"close from {entry_fetch.close_date}"
            )
        working = working.model_copy_validate(
            {
                "entry_triggered": False,
                "entry_date": working.cycle_date,
                "entry_underlying_price": entry_fetch.price,
                "entry_instrument_price": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    fetch = fetch_underlying_close(working.underlying, asof)
    if fetch.price is None:
        return "failed", {"outcome": outcome, "error": fetch.error or "fetch failed"}
    if fetch.close_date and fetch.close_date != asof:
        notes.append(f"last close date {fetch.close_date}")

    unrealized = _shadow_pnl_pct(
        entry_price=working.entry_underlying_price,
        current_price=fetch.price,
    )
    days_held = _days_between(working.entry_date, asof)
    prior = _prior_point(working, asof)
    point = PricePoint(
        trade_id=working.trade_id,
        asof_date=asof,
        underlying_price=fetch.price,
        instrument_price=None,
        unrealized_pnl_pct=unrealized,
        days_held=days_held,
        source="shadow_track",
        notes="; ".join(notes) if notes else None,
    )
    save_price_point(point, replace_same_date=True)
    updated = _recompute_cached_metrics(
        working,
        asof=asof,
        underlying_price=fetch.price,
        instrument_price=None,
    )
    save_trade_outcome(updated)

    if verbose:
        print(
            f"{outcome.underlying}: shadow ${fetch.price:.2f}, "
            f"unrealized={_fmt_pct(unrealized)}, notes={point.notes or '-'}"
        )

    move = None
    if prior is not None and prior.underlying_price:
        move = (fetch.price - prior.underlying_price) / prior.underlying_price
    return (
        "shadow",
        {
            "outcome": updated,
            "point": point,
            "move": move,
            "trigger": None,
        },
    )


def run_batch(
    *,
    asof: str,
    ticker: str | None,
    verbose: bool,
    sync_excel: bool,
    shadow_track_rejected: bool,
    max_shadow_age_days: int,
) -> int:
    outcomes = load_open_trade_outcomes()
    if ticker:
        outcomes = [
            outcome for outcome in outcomes
            if outcome.underlying.upper() == ticker.upper()
        ]
    shadow_outcomes = (
        _eligible_shadow_outcomes(
            asof=asof,
            ticker=ticker,
            max_age_days=max_shadow_age_days,
        )
        if shadow_track_rejected
        else []
    )
    counts = {"underlying_only": 0, "with_option": 0, "shadow": 0, "failed": 0}
    notable: list[tuple[TradeOutcome, PricePoint, float]] = []
    triggers: list[tuple[bool, str]] = []

    for outcome in outcomes:
        try:
            status, payload = _update_one(outcome, asof=asof, verbose=verbose)
        except Exception as exc:
            status = "failed"
            payload = {"outcome": outcome, "error": str(exc)}
        counts[status] += 1
        if status == "failed":
            print(
                f"Warning: failed to update {outcome.underlying}: "
                f"{payload.get('error')}"
            )
            continue
        move = payload.get("move")
        if move is not None and abs(move) > 0.05:
            notable.append((payload["outcome"], payload["point"], float(move)))
        trigger = payload.get("trigger")
        if trigger is not None:
            triggers.append(trigger)

    for outcome in shadow_outcomes:
        try:
            status, payload = _update_shadow_one(
                outcome,
                asof=asof,
                verbose=verbose,
            )
        except Exception as exc:
            status = "failed"
            payload = {"outcome": outcome, "error": str(exc)}
        counts[status] += 1
        if status == "failed":
            print(
                f"Warning: failed to update shadow {outcome.underlying}: "
                f"{payload.get('error')}"
            )
            continue
        move = payload.get("move")
        if move is not None and abs(move) > 0.05:
            notable.append((payload["outcome"], payload["point"], float(move)))

    print(f"PRICE UPDATE - {asof}")
    print("-------------------------")
    print(f"Trades updated:        {counts['underlying_only'] + counts['with_option']}")
    print(f"  underlying only:     {counts['underlying_only']}")
    print(f"  with option chain:   {counts['with_option']}")
    print(f"  shadow rejected:     {counts['shadow']}")
    print(f"  failed to fetch:     {counts['failed']}")
    print()
    print("Notable moves (>5% from prior day):")
    if notable:
        for outcome, point, move in notable:
            print(
                f"  {outcome.underlying:<6} {_fmt_pct(move):>7} "
                f"${point.underlying_price:.2f} "
                f"({outcome.status}, {_fmt_pct(point.unrealized_pnl_pct)} unrealized)"
            )
    else:
        print("  None")
    print()
    triggered_count = sum(1 for triggered, _ in triggers if triggered)
    print(f"Entry triggers met:    {triggered_count}")
    if triggers:
        for _, detail in triggers:
            print(f"  {detail}")
    else:
        print("  None")

    if sync_excel:
        try:
            from src.agent_system.services.excel_sync import ExcelSync

            report = ExcelSync().sync()
            print(
                f"\nExcel sync: {len(report.user_edits_applied)} edits read, "
                f"{len(report.system_fields_written)} updates written"
            )
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"\nExcel sync failed: {exc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update tracked trade prices.")
    parser.add_argument("--asof", default=None, help="As-of date, YYYY-MM-DD.")
    parser.add_argument("--ticker", default=None, help="Restrict to one ticker.")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--no-sync-excel", action="store_true")
    parser.add_argument(
        "--shadow-track-rejected",
        dest="shadow_track_rejected",
        action="store_true",
        default=True,
        help="Update shadow_rejected diagnostics (default).",
    )
    parser.add_argument(
        "--no-shadow-track-rejected",
        dest="shadow_track_rejected",
        action="store_false",
        help="Skip shadow_rejected diagnostics.",
    )
    parser.add_argument(
        "--max-shadow-age-days",
        type=int,
        default=365,
        help="Skip shadow rows older than this many days.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run_batch(
        asof=_asof_date(args.asof),
        ticker=args.ticker,
        verbose=args.verbose,
        sync_excel=not args.no_sync_excel,
        shadow_track_rejected=args.shadow_track_rejected,
        max_shadow_age_days=max(0, args.max_shadow_age_days),
    )


if __name__ == "__main__":
    raise SystemExit(main())
