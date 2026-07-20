"""CLI for manually managing TradeOutcome lifecycle states.

Examples:
    python -m scripts.trade_outcome_cli decide --ticker EME --cycle-id 5cc6ea7b --decision TAKE --reason "fits AI infrastructure thesis"
    python -m scripts.trade_outcome_cli enter --ticker EME --cycle-id 5cc6ea7b --date 2026-06-12 --price 822.54
    python -m scripts.trade_outcome_cli mark --ticker EME --cycle-id 5cc6ea7b --price 845.20 --date 2026-06-15
    python -m scripts.trade_outcome_cli close --ticker EME --cycle-id 5cc6ea7b --date 2026-09-15 --price 871.20 --reason target_hit
    python -m scripts.trade_outcome_cli audit --ticker EME --cycle-id 5cc6ea7b --thesis-played-out YES --win-source thesis --system-contribution STRONG --notes "Backlog growth exceeded expectations"
    python -m scripts.trade_outcome_cli list --status open
    python -m scripts.trade_outcome_cli show --ticker EME --cycle-id 5cc6ea7b
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.agent_system.schemas.portfolio_plan import PortfolioPlan
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.schemas.trade_outcome import PricePoint, TradeOutcome
from src.agent_system.services.option_pricing import (
    fetch_option_chain_price,
    parse_option_from_description,
)
from src.agent_system.services.shadow_outcome_builder import build_shadow_outcome
from src.agent_system.services.trade_outcome_builder import build_trade_outcome
from src.agent_system.storage.repository import (
    list_schemas,
    load_decision_log_entries_by_cycle,
    load_latest_regime_state,
    load_price_points,
    load_regime_states_range,
    load_trade_outcome,
    load_trade_outcomes,
    load_trade_outcomes_by_cycle,
    save_price_point,
    save_trade_outcome,
)


STATUS_ORDER = [
    "proposed",
    "watching",
    "skipped",
    "shadow_rejected",
    "open",
    "closed_target",
    "closed_stop",
    "closed_time",
    "closed_falsifier",
    "closed_thesis",
    "closed_discretionary",
]

CLOSED_STATUS_BY_REASON = {
    "target_hit": "closed_target",
    "target": "closed_target",
    "stop_hit": "closed_stop",
    "stop": "closed_stop",
    "time_stop": "closed_time",
    "time": "closed_time",
    "falsifier": "closed_falsifier",
    "thesis_broken": "closed_thesis",
    "thesis": "closed_thesis",
    "discretionary": "closed_discretionary",
}


@dataclass
class SimulatedEntryQuote:
    outcome: TradeOutcome
    underlying_price: float | None
    underlying_price_date: str | None
    instrument_price: float | None
    status: str
    notes: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit(f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


def _days_between(start: str | None, end: str) -> int:
    if not start:
        return 0
    return max(0, (_parse_date(end) - _parse_date(start)).days)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1%}"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0%}"


def _fmt_int(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return str(int(value))


def _short_cycle(cycle_id: str) -> str:
    return cycle_id[:8]


def _find_outcome(*, ticker: str, cycle_id: str) -> TradeOutcome:
    ticker_key = ticker.upper()
    matches = [
        outcome
        for outcome in load_trade_outcomes_by_cycle(cycle_id)
        if outcome.underlying.upper() == ticker_key
    ]
    if not matches:
        raise SystemExit(
            f"No TradeOutcome found for ticker={ticker!r}, cycle_id={cycle_id!r}."
        )
    if len(matches) > 1:
        print("Multiple TradeOutcome records matched; specify by trade_id in storage:")
        for outcome in matches:
            print(f"  {outcome.trade_id}  {outcome.underlying}  {outcome.status}")
        raise SystemExit(2)
    return matches[0]


def _ensure_lifecycle_allowed(outcome: TradeOutcome) -> None:
    if outcome.status == "shadow_rejected":
        raise SystemExit(
            "Cannot apply lifecycle actions to shadow_rejected trades. "
            "Use a regular TradeOutcome for actual positions."
        )


def _portfolio_nav_for_cycle(cycle_id: str) -> float | None:
    for plan in list_schemas(PortfolioPlan, limit=1000):
        if plan.cycle_id == cycle_id:
            return plan.nav_unlevered_usd
    return None


def _all_portfolio_plans() -> list[PortfolioPlan]:
    return list_schemas(PortfolioPlan, limit=1_000_000)


def _cycle_matches(stored_cycle_id: str, requested_cycle_id: str) -> bool:
    return stored_cycle_id == requested_cycle_id or stored_cycle_id.startswith(
        requested_cycle_id
    )


def _find_plan(cycle_id: str) -> PortfolioPlan:
    matches = [
        plan for plan in _all_portfolio_plans()
        if _cycle_matches(plan.cycle_id, cycle_id)
    ]
    unique: dict[str, PortfolioPlan] = {}
    for plan in matches:
        unique.setdefault(plan.cycle_id, plan)
    if not unique:
        raise SystemExit(f"No PortfolioPlan found for cycle_id={cycle_id!r}.")
    if len(unique) > 1:
        print("Multiple PortfolioPlan records matched:")
        for matched in unique:
            print(f"  {matched}")
        raise SystemExit(2)
    return next(iter(unique.values()))


def _trade_ideas_by_id() -> dict[str, TradeIdea]:
    by_id: dict[str, TradeIdea] = {}
    for trade in list_schemas(TradeIdea, limit=1_000_000):
        if trade.id and trade.id not in by_id:
            by_id[trade.id] = trade
    return by_id


def _outcomes_matching_cycle(cycle_id: str) -> list[TradeOutcome]:
    return [
        outcome for outcome in load_trade_outcomes()
        if _cycle_matches(outcome.cycle_id, cycle_id)
    ]


def _resolve_simulate_asof(outcomes: list[TradeOutcome], requested: str | None) -> str:
    if requested:
        asof = _parse_date(requested)
    else:
        asof = _parse_date(outcomes[0].cycle_date)
    today = date.today()
    if asof > today:
        raise SystemExit(
            f"simulate_entry asof date {asof.isoformat()} is in the future; "
            f"today is {today.isoformat()}."
        )
    return asof.isoformat()


def _fetch_underlying_close(ticker: str, asof_date: str) -> tuple[float | None, str | None, str | None]:
    import yfinance as yf

    asof = _parse_date(asof_date)
    start = asof - timedelta(days=14)
    end = asof + timedelta(days=1)
    last_error: str | None = None
    for attempt in range(2):
        try:
            history = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=end.isoformat(),
                auto_adjust=False,
            )
            if history is None or history.empty or "Close" not in history:
                return None, None, "no close history"
            closes = history["Close"].dropna()
            if closes.empty:
                return None, None, "no close prices"
            return float(closes.iloc[-1]), closes.index[-1].date().isoformat(), None
        except Exception as exc:
            last_error = str(exc)
            if attempt == 0:
                time.sleep(1.0)
                continue
    return None, None, last_error or "price fetch failed"


def _fetch_simulated_quote(
    outcome: TradeOutcome,
    *,
    asof_date: str,
) -> SimulatedEntryQuote:
    underlying_price, actual_date, error = _fetch_underlying_close(
        outcome.underlying,
        asof_date,
    )
    if underlying_price is None:
        return SimulatedEntryQuote(
            outcome=outcome,
            underlying_price=None,
            underlying_price_date=None,
            instrument_price=None,
            status="failed",
            notes=error,
        )

    notes: list[str] = []
    if actual_date and actual_date != asof_date:
        notes.append(f"requested {asof_date}; yfinance close from {actual_date}")

    instrument_price: float | None = None
    status = "ready"
    if outcome.instrument_type in {"option_underlying", "spread"}:
        parsed = parse_option_from_description(outcome.instrument_description)
        if parsed is None:
            status = "underlying_only"
            notes.append("option description parse failed")
        else:
            fetched = fetch_option_chain_price(
                outcome.underlying,
                parsed["expiry"],
                parsed["strikes"],
                parsed["option_type"],
            )
            if fetched is None:
                status = "underlying_only"
                notes.append("option chain unavailable; using underlying-only")
            else:
                instrument_price = fetched

    return SimulatedEntryQuote(
        outcome=outcome,
        underlying_price=underlying_price,
        underlying_price_date=actual_date,
        instrument_price=instrument_price,
        status=status,
        notes="; ".join(notes) if notes else None,
    )


def _pnl_pct(
    outcome: TradeOutcome,
    *,
    underlying_price: float,
    instrument_price: float | None = None,
) -> float | None:
    if outcome.entry_underlying_price is None:
        return None
    if (
        instrument_price is not None
        and outcome.entry_instrument_price is not None
    ):
        entry = outcome.entry_instrument_price
        current = instrument_price
    else:
        entry = outcome.entry_underlying_price
        current = underlying_price
    if entry == 0:
        return None
    sign = -1.0 if outcome.direction == "short" else 1.0
    return sign * ((current - entry) / entry)


def _price_point(
    outcome: TradeOutcome,
    *,
    asof_date: str,
    underlying_price: float,
    instrument_price: float | None = None,
    notes: str | None = None,
) -> PricePoint:
    pnl = _pnl_pct(
        outcome,
        underlying_price=underlying_price,
        instrument_price=instrument_price,
    )
    return PricePoint(
        trade_id=outcome.trade_id,
        asof_date=asof_date,
        underlying_price=underlying_price,
        instrument_price=instrument_price,
        unrealized_pnl_pct=pnl,
        days_held=_days_between(outcome.entry_date, asof_date),
        source="manual",
        notes=notes,
    )


def _with_update(outcome: TradeOutcome, **updates) -> TradeOutcome:
    updates["updated_at"] = _now()
    return outcome.model_copy_validate(updates)


def _recompute_cached_metrics(outcome: TradeOutcome) -> TradeOutcome:
    points = load_price_points(outcome.trade_id)
    if not points:
        return outcome
    latest = points[-1]
    pnls = [
        point.unrealized_pnl_pct
        for point in points
        if point.unrealized_pnl_pct is not None
    ]
    return _with_update(
        outcome,
        current_underlying_price=latest.underlying_price,
        current_instrument_price=latest.instrument_price,
        current_unrealized_pnl_pct=latest.unrealized_pnl_pct,
        max_drawdown_pct=min(pnls) if pnls else None,
        max_runup_pct=max(pnls) if pnls else None,
        days_held=latest.days_held if outcome.entry_date else outcome.days_held,
        days_since_proposed=_days_between(outcome.cycle_date, latest.asof_date),
        last_price_update=_now(),
    )


def _save_with_price_point(
    outcome: TradeOutcome,
    *,
    asof_date: str,
    underlying_price: float,
    instrument_price: float | None = None,
    notes: str | None = None,
) -> TradeOutcome:
    save_price_point(
        _price_point(
            outcome,
            asof_date=asof_date,
            underlying_price=underlying_price,
            instrument_price=instrument_price,
            notes=notes,
        )
    )
    updated = _recompute_cached_metrics(outcome)
    save_trade_outcome(updated)
    return updated


def cmd_decide(args: argparse.Namespace) -> int:
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _ensure_lifecycle_allowed(outcome)
    status = outcome.status
    if args.decision == "TAKE":
        status = "watching"
    elif args.decision == "SKIP":
        status = "skipped"
    elif args.decision == "WATCH":
        status = "proposed"
    updated = _with_update(
        outcome,
        user_decision=args.decision,
        user_decision_reason=args.reason,
        user_decision_at=_now(),
        status=status,
    )
    save_trade_outcome(updated)
    print(
        f"{updated.underlying}: decision={updated.user_decision}, "
        f"status={updated.status}"
    )
    return 0


def cmd_enter(args: argparse.Namespace) -> int:
    _parse_date(args.date)
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _ensure_lifecycle_allowed(outcome)
    nav = args.portfolio_nav
    if nav is None:
        nav = _portfolio_nav_for_cycle(outcome.cycle_id)
    entry_size_usd = nav * outcome.final_size_pct if nav is not None else None
    instrument_price = (
        args.instrument_price if args.instrument_price is not None else args.price
    )
    opened = _with_update(
        outcome,
        status="open",
        entry_triggered=True,
        entry_date=args.date,
        entry_underlying_price=args.price,
        entry_instrument_price=instrument_price,
        entry_size_usd=entry_size_usd,
        current_underlying_price=args.price,
        current_instrument_price=args.instrument_price,
        current_unrealized_pnl_pct=0.0,
        days_held=0,
        days_since_proposed=_days_between(outcome.cycle_date, args.date),
        max_drawdown_pct=0.0,
        max_runup_pct=0.0,
        last_price_update=_now(),
    )
    save_price_point(
        PricePoint(
            trade_id=opened.trade_id,
            asof_date=args.date,
            underlying_price=args.price,
            instrument_price=args.instrument_price,
            unrealized_pnl_pct=0.0,
            days_held=0,
            source="manual",
            notes=args.notes,
        )
    )
    save_trade_outcome(opened)
    print(f"{opened.underlying}: entered at {args.price:.2f}, status=open")
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    _parse_date(args.date)
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _ensure_lifecycle_allowed(outcome)
    updated = _save_with_price_point(
        outcome,
        asof_date=args.date,
        underlying_price=args.price,
        instrument_price=args.instrument_price,
        notes=args.notes,
    )
    print(
        f"{updated.underlying}: marked {args.price:.2f}, "
        f"unrealized={_fmt_pct(updated.current_unrealized_pnl_pct)}"
    )
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    _parse_date(args.date)
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _ensure_lifecycle_allowed(outcome)
    if outcome.entry_date is None or outcome.entry_underlying_price is None:
        raise SystemExit("Cannot close a trade before recording an entry.")
    status = CLOSED_STATUS_BY_REASON.get(args.reason, args.reason)
    if status not in STATUS_ORDER or not status.startswith("closed_"):
        raise SystemExit(
            "Unknown close reason. Use target_hit, stop_hit, time_stop, "
            "falsifier, thesis_broken, discretionary, or a closed_* status."
        )
    realized = _pnl_pct(
        outcome,
        underlying_price=args.price,
        instrument_price=args.instrument_price,
    )
    realized_usd = (
        outcome.entry_size_usd * realized
        if outcome.entry_size_usd is not None and realized is not None
        else None
    )
    closing_point = _price_point(
        outcome,
        asof_date=args.date,
        underlying_price=args.price,
        instrument_price=args.instrument_price,
        notes=args.notes,
    )
    save_price_point(closing_point)
    closed = _with_update(
        outcome,
        status=status,
        exit_date=args.date,
        exit_underlying_price=args.price,
        exit_instrument_price=args.instrument_price,
        exit_reason=args.reason,
        current_underlying_price=args.price,
        current_instrument_price=args.instrument_price,
        current_unrealized_pnl_pct=closing_point.unrealized_pnl_pct,
        realized_pnl_pct=realized,
        realized_pnl_usd=realized_usd,
        days_held=closing_point.days_held,
        days_since_proposed=_days_between(outcome.cycle_date, args.date),
        last_price_update=_now(),
    )
    closed = _recompute_cached_metrics(closed)
    save_trade_outcome(closed)
    print(f"{closed.underlying}: closed {status}, realized={_fmt_pct(realized)}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _ensure_lifecycle_allowed(outcome)
    updated = _with_update(
        outcome,
        thesis_played_out=args.thesis_played_out,
        win_source=args.win_source,
        system_contribution=args.system_contribution,
        audit_notes=args.notes,
    )
    save_trade_outcome(updated)
    print(f"{updated.underlying}: audit updated")
    return 0


def _backfill_cycle(
    plan: PortfolioPlan,
    *,
    trade_lookup: dict[str, TradeIdea],
    dry_run: bool,
) -> dict[str, int | str]:
    accepted = 0
    created = 0
    skipped = 0
    missing = 0
    for decision in plan.trade_decisions:
        if decision.decision == "rejected_portfolio" or decision.final_size_pct <= 0:
            continue
        accepted += 1
        if load_trade_outcome(decision.trade_id) is not None:
            skipped += 1
            print(f"{plan.cycle_id}: skip {decision.trade_id} (already exists)")
            continue
        trade_idea = trade_lookup.get(decision.trade_id)
        if trade_idea is None:
            missing += 1
            print(f"{plan.cycle_id}: missing TradeIdea {decision.trade_id}")
            continue
        outcome = build_trade_outcome(
            trade_idea=trade_idea,
            decision=decision,
            cycle_id=plan.cycle_id,
            cycle_date=plan.created_at.date().isoformat(),
        )
        if outcome is None:
            continue
        if dry_run:
            print(
                f"{plan.cycle_id}: would create {outcome.trade_id} "
                f"{outcome.underlying} {outcome.final_size_pct:.1%}"
            )
        else:
            save_trade_outcome(outcome)
            print(
                f"{plan.cycle_id}: created {outcome.trade_id} "
                f"{outcome.underlying}"
            )
        created += 1
    return {
        "cycle_id": plan.cycle_id,
        "accepted": accepted,
        "created": created,
        "skipped": skipped,
        "missing": missing,
    }


def _backfill_shadow_rejected_cycle(
    plan: PortfolioPlan,
    *,
    trade_lookup: dict[str, TradeIdea],
    dry_run: bool,
) -> dict[str, int]:
    accepted = 0
    created = 0
    skipped = 0
    missing = 0
    cycle_date = plan.created_at.date().isoformat()
    for entry in load_decision_log_entries_by_cycle(plan.cycle_id):
        if entry.decision != "rejected":
            continue
        accepted += 1
        trade_id = entry.trade_idea_id
        if not trade_id:
            missing += 1
            print(f"{plan.cycle_id}: missing trade_idea_id for {entry.candidate}")
            continue
        if load_trade_outcome(trade_id) is not None:
            skipped += 1
            print(f"{plan.cycle_id}: skip {trade_id} (already exists)")
            continue
        trade_idea = trade_lookup.get(trade_id)
        if trade_idea is None:
            missing += 1
            print(f"{plan.cycle_id}: missing TradeIdea {trade_id}")
            continue
        outcome = build_shadow_outcome(
            trade_idea=trade_idea,
            decision_log_entry=asdict(entry),
            cycle_id=plan.cycle_id,
            cycle_date=cycle_date,
        )
        if outcome is None:
            continue
        if dry_run:
            print(
                f"{plan.cycle_id}: would create shadow {outcome.trade_id} "
                f"{outcome.underlying}"
            )
        else:
            save_trade_outcome(outcome)
            print(
                f"{plan.cycle_id}: created shadow {outcome.trade_id} "
                f"{outcome.underlying}"
            )
        created += 1
    return {
        "accepted": accepted,
        "created": created,
        "skipped": skipped,
        "missing": missing,
    }


def cmd_backfill(args: argparse.Namespace) -> int:
    if args.all_cycles:
        plans_by_cycle: dict[str, PortfolioPlan] = {}
        for plan in _all_portfolio_plans():
            plans_by_cycle.setdefault(plan.cycle_id, plan)
        plans = list(plans_by_cycle.values())
    else:
        plans = [_find_plan(args.cycle_id)]
    trade_lookup = _trade_ideas_by_id()
    summaries = [
        _backfill_cycle(plan, trade_lookup=trade_lookup, dry_run=args.dry_run)
        for plan in plans
    ]
    shadow_summaries: dict[str, dict[str, int]] = {}
    if args.shadow_rejected:
        for plan in plans:
            shadow_summaries[plan.cycle_id] = _backfill_shadow_rejected_cycle(
                plan,
                trade_lookup=trade_lookup,
                dry_run=args.dry_run,
            )
    print()
    print("BACKFILL SUMMARY")
    shadow_header = f" {'Shadow':>8}" if args.shadow_rejected else ""
    print(
        f"{'Cycle':<36} {'Accepted':>8} {'Created':>8} "
        f"{'Skipped':>8} {'Missing':>8}{shadow_header}"
    )
    print("-" * (85 if args.shadow_rejected else 76))
    for summary in summaries:
        shadow_created = ""
        if args.shadow_rejected:
            shadow = shadow_summaries.get(str(summary["cycle_id"]), {})
            shadow_created = f" {int(shadow.get('created', 0)):>8}"
        print(
            f"{str(summary['cycle_id']):<36} "
            f"{int(summary['accepted']):>8} "
            f"{int(summary['created']):>8} "
            f"{int(summary['skipped']):>8} "
            f"{int(summary['missing']):>8}"
            f"{shadow_created}"
        )
    return 0


def _format_money(value: float | None, *, dash_for_none: bool = False) -> str:
    if value is None:
        return "-" if dash_for_none else "n/a"
    return f"${value:.2f}"


def _simulate_status_label(status: str) -> str:
    if status == "ready":
        return "✓ ready"
    if status == "underlying_only":
        return "⚠ underlying only"
    if status == "failed":
        return "✗ failed"
    return f"✗ {status}"


def _simulate_notes(quote: SimulatedEntryQuote) -> str | None:
    parts = []
    if quote.notes:
        parts.append(quote.notes)
    return "; ".join(parts) if parts else None


def _eligible_simulate_outcomes(
    *,
    cycle_id: str,
    tickers: list[str] | None,
) -> tuple[list[TradeOutcome], list[TradeOutcome]]:
    outcomes = _outcomes_matching_cycle(cycle_id)
    if tickers:
        ticker_set = {ticker.upper() for ticker in tickers}
        outcomes = [
            outcome for outcome in outcomes
            if outcome.underlying.upper() in ticker_set
        ]
    proposed = [outcome for outcome in outcomes if outcome.status == "proposed"]
    skipped = [outcome for outcome in outcomes if outcome.status != "proposed"]
    return proposed, skipped


def _print_simulate_table(
    *,
    cycle_id: str,
    asof_date: str,
    quotes: list[SimulatedEntryQuote],
    skipped: list[TradeOutcome],
) -> None:
    print(f"SIMULATE ENTRY - cycle {cycle_id[:8]} - asof {asof_date}")
    print("-" * 101)
    print(
        f"{'Ticker':<8} {'Instrument':<40} {'Underlying':>12} "
        f"{'Premium':>10} {'Size':>7}  Status"
    )
    for quote in quotes:
        outcome = quote.outcome
        print(
            f"{outcome.underlying:<8} "
            f"{outcome.instrument_description[:40]:<40} "
            f"{_format_money(quote.underlying_price):>12} "
            f"{_format_money(quote.instrument_price, dash_for_none=True):>10} "
            f"{outcome.final_size_pct:>6.1%}  "
            f"{_simulate_status_label(quote.status)}"
        )
    for outcome in skipped:
        print(
            f"{outcome.underlying:<8} "
            f"{outcome.instrument_description[:40]:<40} "
            f"{'n/a':>12} "
            f"{'-':>10} "
            f"{outcome.final_size_pct:>6.1%}  "
            f"✗ already {outcome.status}"
        )

    ready_count = sum(
        1 for quote in quotes if quote.status in {"ready", "underlying_only"}
    )
    failed_count = sum(1 for quote in quotes if quote.status == "failed")
    print()
    print(f"{ready_count} trades ready, {failed_count} failed")
    warnings = [quote for quote in quotes if quote.notes]
    if warnings:
        print()
        print("Notes:")
        for quote in warnings:
            print(f"  {quote.outcome.underlying}: {quote.notes}")


def _apply_simulated_entry(
    quote: SimulatedEntryQuote,
    *,
    asof_date: str,
) -> bool:
    outcome = quote.outcome
    if quote.underlying_price is None or quote.status == "failed":
        print(f"Skip {outcome.underlying}: failed price fetch")
        return False
    nav = _portfolio_nav_for_cycle(outcome.cycle_id)
    entry_size_usd = nav * outcome.final_size_pct if nav is not None else None
    now = _now()
    opened = outcome.model_copy_validate(
        {
            "user_decision": "TAKE",
            "user_decision_reason": "Simulated entry via simulate_entry",
            "user_decision_at": now,
            "entry_triggered": True,
            "entry_date": asof_date,
            "entry_underlying_price": quote.underlying_price,
            "entry_instrument_price": quote.instrument_price,
            "entry_size_usd": entry_size_usd,
            "status": "open",
            "current_underlying_price": quote.underlying_price,
            "current_instrument_price": quote.instrument_price,
            "current_unrealized_pnl_pct": 0.0,
            "days_held": 0,
            "days_since_proposed": _days_between(outcome.cycle_date, asof_date),
            "max_drawdown_pct": 0.0,
            "max_runup_pct": 0.0,
            "last_price_update": now,
            "updated_at": now,
        }
    )
    save_price_point(
        PricePoint(
            trade_id=opened.trade_id,
            asof_date=asof_date,
            underlying_price=quote.underlying_price,
            instrument_price=quote.instrument_price,
            unrealized_pnl_pct=0.0,
            days_held=0,
            source="yfinance",
            notes=_simulate_notes(quote),
        )
    )
    save_trade_outcome(opened)
    return True


def cmd_simulate_entry(args: argparse.Namespace) -> int:
    proposed, skipped = _eligible_simulate_outcomes(
        cycle_id=args.cycle_id,
        tickers=args.ticker,
    )
    if not proposed and not skipped:
        print(f"No TradeOutcome records found for cycle_id={args.cycle_id!r}.")
        return 0
    if not proposed:
        print("No proposed trades eligible for simulated entry.")
        if skipped:
            print("Skipped existing non-proposed trades:")
            for outcome in skipped:
                print(f"  {outcome.underlying}: {outcome.status}")
        return 0

    asof_date = _resolve_simulate_asof(proposed + skipped, args.asof)
    quotes: list[SimulatedEntryQuote] = []
    for outcome in proposed:
        try:
            quotes.append(_fetch_simulated_quote(outcome, asof_date=asof_date))
        except Exception as exc:
            quotes.append(
                SimulatedEntryQuote(
                    outcome=outcome,
                    underlying_price=None,
                    underlying_price_date=None,
                    instrument_price=None,
                    status="failed",
                    notes=str(exc),
                )
            )

    _print_simulate_table(
        cycle_id=args.cycle_id,
        asof_date=asof_date,
        quotes=quotes,
        skipped=skipped,
    )

    applicable = [
        quote for quote in quotes
        if quote.status in {"ready", "underlying_only"} and quote.underlying_price is not None
    ]
    if not applicable:
        print("No entries applied.")
        return 0
    if not args.auto_yes:
        response = input(f"Apply simulated entries for {len(applicable)} trades? (y/n): ")
        if response.strip().lower() != "y":
            print("No entries applied.")
            return 0

    applied = 0
    skipped_failed = 0
    for quote in quotes:
        if quote not in applicable:
            skipped_failed += 1
            continue
        if _apply_simulated_entry(quote, asof_date=asof_date):
            applied += 1
        else:
            skipped_failed += 1
    print()
    print(f"Applied: {applied} entries")
    print(f"Skipped: {skipped_failed} (failed price fetch)")
    return 0


def _filtered_outcomes(args: argparse.Namespace) -> list[TradeOutcome]:
    outcomes = load_trade_outcomes()
    if getattr(args, "exclude_shadow", False):
        outcomes = [
            outcome for outcome in outcomes if outcome.status != "shadow_rejected"
        ]
    if getattr(args, "status", None):
        outcomes = [outcome for outcome in outcomes if outcome.status == args.status]
    if getattr(args, "cycle_id", None):
        outcomes = [
            outcome for outcome in outcomes
            if _cycle_matches(outcome.cycle_id, args.cycle_id)
        ]
    if getattr(args, "ticker", None):
        ticker = args.ticker.upper()
        outcomes = [
            outcome for outcome in outcomes if outcome.underlying.upper() == ticker
        ]
    return sorted(outcomes, key=lambda item: (item.cycle_date, item.underlying))


def cmd_list(args: argparse.Namespace) -> int:
    outcomes = _filtered_outcomes(args)
    cycle_filter_only = (
        getattr(args, "cycle_id", None) is not None
        and getattr(args, "status", None) is None
        and getattr(args, "ticker", None) is None
    )

    if not outcomes:
        if cycle_filter_only:
            print("CYCLE OUTCOMES (0)")
            print("  (no trade outcomes for this cycle)")
            return 0
        print("No trade outcomes found.")
        return 0

    if outcomes:
        if cycle_filter_only:
            print(f"CYCLE OUTCOMES ({len(outcomes)})")
        print(
            f"{'Ticker':<8} {'Cycle':<10} {'Status':<22} {'User':<6} "
            f"{'Size':>7} {'Unrlzd':>8} {'Realized':>9} {'Held':>5}"
        )
        print("-" * 82)
        for outcome in outcomes:
            print(
                f"{outcome.underlying:<8} "
                f"{_short_cycle(outcome.cycle_id):<10} "
                f"{outcome.status:<22} "
                f"{(outcome.user_decision or '-'): <6} "
                f"{outcome.final_size_pct:>6.1%} "
                f"{_fmt_pct(outcome.current_unrealized_pnl_pct):>8} "
                f"{_fmt_pct(outcome.realized_pnl_pct):>9} "
                f"{_fmt_int(outcome.days_held):>5}"
            )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    if outcome.status == "shadow_rejected":
        print("SYSTEM-REJECTED SHADOW TRACKING")
    print("TRADE OUTCOME")
    print(f"  trade_id:       {outcome.trade_id}")
    print(f"  cycle_id:       {outcome.cycle_id}")
    print(f"  underlying:     {outcome.underlying}")
    print(f"  status:         {outcome.status}")
    print(f"  user_decision:  {outcome.user_decision or 'n/a'}")
    print(f"  instrument:     {outcome.instrument_description}")
    print(f"  size:           {outcome.final_size_pct:.1%}")
    print(
        f"  entry:          {outcome.entry_date or 'n/a'} @ "
        f"{outcome.entry_underlying_price or 'n/a'}"
    )
    print(f"  current:        {outcome.current_underlying_price or 'n/a'}")
    print(f"  unrealized:     {_fmt_pct(outcome.current_unrealized_pnl_pct)}")
    print(f"  realized:       {_fmt_pct(outcome.realized_pnl_pct)}")
    print(f"  exit:           {outcome.exit_date or 'n/a'} ({outcome.exit_reason or 'n/a'})")
    print()
    _print_price_history(outcome)
    return 0


def _print_price_history(outcome: TradeOutcome) -> None:
    print("PRICE HISTORY")
    points = load_price_points(outcome.trade_id)
    if not points:
        print("  none")
        return
    print(
        f"{'Date':<12} {'Underlying':>12} {'Instrument':>12} "
        f"{'PnL':>9} {'Days':>5} {'Source':<10} Notes"
    )
    print("-" * 82)
    for point in points:
        instrument = (
            f"{point.instrument_price:.2f}"
            if point.instrument_price is not None
            else "n/a"
        )
        print(
            f"{point.asof_date:<12} "
            f"{point.underlying_price:>12.2f} "
            f"{instrument:>12} "
            f"{_fmt_pct(point.unrealized_pnl_pct):>9} "
            f"{point.days_held:>5} "
            f"{point.source:<10} "
            f"{point.notes or ''}"
        )


def cmd_prices(args: argparse.Namespace) -> int:
    outcome = _find_outcome(ticker=args.ticker, cycle_id=args.cycle_id)
    _print_price_history(outcome)
    return 0


def _avg(values: list[float | int | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    return mean(cleaned) if cleaned else None


def cmd_stats(_args: argparse.Namespace) -> int:
    all_outcomes = load_trade_outcomes()
    shadow = [
        outcome for outcome in all_outcomes if outcome.status == "shadow_rejected"
    ]
    outcomes = [
        outcome for outcome in all_outcomes if outcome.status != "shadow_rejected"
    ]
    main_status_order = [
        status for status in STATUS_ORDER if status != "shadow_rejected"
    ]
    total = len(outcomes)
    counts = {status: 0 for status in main_status_order}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1

    closed = [outcome for outcome in outcomes if outcome.status.startswith("closed_")]
    open_trades = [outcome for outcome in outcomes if outcome.status == "open"]
    wins = [
        outcome for outcome in closed
        if outcome.realized_pnl_pct is not None and outcome.realized_pnl_pct > 0
    ]
    losses = [
        outcome for outcome in closed
        if outcome.realized_pnl_pct is not None and outcome.realized_pnl_pct <= 0
    ]
    win_rate = len(wins) / len(wins + losses) if wins or losses else None

    print("TRADE OUTCOME SUMMARY")
    print("---------------------")
    print(f"Total proposed:        {total}")
    print("Status breakdown:")
    for status in main_status_order:
        pct = f" ({counts[status] / total:.0%})" if total else ""
        print(f"  {status:<21} {counts[status]:>4}{pct}")
    print()
    print(f"Closed trades:         {len(closed)}")
    print(
        f"  Win rate:            {_fmt_rate(win_rate)} "
        f"({len(wins)}W {len(losses)}L)"
    )
    print(f"  Avg realized P&L:    {_fmt_pct(_avg([o.realized_pnl_pct for o in closed]))}")
    print(f"  Avg held days:       {_fmt_int(_avg([o.days_held for o in closed]))}")
    print()
    print(f"Open trades:           {len(open_trades)}")
    print(
        "  Avg unrealized P&L:  "
        f"{_fmt_pct(_avg([o.current_unrealized_pnl_pct for o in open_trades]))}"
    )
    print(f"  Avg days held:       {_fmt_int(_avg([o.days_held for o in open_trades]))}")
    print()
    print("System contribution (closed trades):")
    for label in ("STRONG", "NEUTRAL", "WEAK"):
        count = sum(1 for outcome in closed if outcome.system_contribution == label)
        print(f"  {label:<21} {count:>4}")
    print()
    print("Thesis playout:")
    for label in ("YES", "PARTIAL", "NO"):
        count = sum(1 for outcome in closed if outcome.thesis_played_out == label)
        print(f"  {label:<21} {count:>4}")
    if shadow:
        shadow_avg = _avg([o.current_unrealized_pnl_pct for o in shadow])
        accepted_open_avg = _avg(
            [o.current_unrealized_pnl_pct for o in open_trades]
        )
        print()
        print("SHADOW-TRACKED REJECTED CANDIDATES")
        print("---------------------------------")
        print(f"Total shadow rows:    {len(shadow)}")
        print(f"  Avg unrealized P&L: {_fmt_pct(shadow_avg)}")
        print(f"  Avg days tracked:   {_fmt_int(_avg([o.days_held for o in shadow]))}")
        print()
        print("Comparison: shadow rejected vs accepted-and-held trades:")
        if open_trades:
            print(f"  Accepted avg unrealized:     {_fmt_pct(accepted_open_avg)}")
            print(f"  Shadow rejected avg unreal:  {_fmt_pct(shadow_avg)}")
            print(
                "  Differential:                "
                f"{_fmt_pct((accepted_open_avg or 0) - (shadow_avg or 0))}"
            )
        else:
            print("  No accepted open trades to compare.")
    return 0


def _regime_avg_data_quality(state: dict[str, Any]) -> float | None:
    qualities = state.get("layer_data_quality") or {}
    values = [float(value) for value in qualities.values() if value is not None]
    return mean(values) if values else None


def _fmt_plain_float(value: Any, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _print_regime_summary(state: dict[str, Any]) -> None:
    print("LATEST REGIME STATE")
    print("-------------------")
    print(f"Date:         {state.get('asof_date', 'n/a')}")
    print(f"Environment:  {state.get('environment') or 'n/a'}")
    print(f"Score:        {_fmt_plain_float(state.get('score_total'))}/100")
    print(f"Confidence:   {_fmt_plain_float(state.get('confidence'))}/100")
    print(f"Data quality: {_fmt_plain_float(_regime_avg_data_quality(state), 2)}")
    print()
    print("Layer scores:")
    for layer in ("monetary", "credit", "volatility", "breadth", "positioning"):
        score = state.get(f"layer_{layer}")
        quality = (state.get("layer_data_quality") or {}).get(layer)
        status = (state.get("layer_statuses") or {}).get(layer, "n/a")
        print(
            f"  {layer:<12} {_fmt_plain_float(score, 2):>5}/10  "
            f"dq={_fmt_plain_float(quality, 2):>4}  {status}"
        )


def cmd_check_regime(args: argparse.Namespace) -> int:
    if args.history is None:
        state = load_latest_regime_state()
        if state is None:
            print("No regime states found.")
            return 0
        _print_regime_summary(state)
        return 0

    history = max(1, args.history)
    states = load_regime_states_range("0000-00-00", "9999-99-99")[-history:]
    if not states:
        print("No regime states found.")
        return 0

    print(f"RECENT REGIME HISTORY (last {len(states)} days)")
    print("-" * 65)
    print(f"{'Date':<12} {'Score':>6}  {'Env':<32} {'DQ':>5} {'Conf':>6}")
    for state in reversed(states):
        dq = _regime_avg_data_quality(state)
        env = (state.get("environment") or "n/a")[:32]
        print(
            f"{state.get('asof_date', 'n/a'):<12} "
            f"{_fmt_plain_float(state.get('score_total')):>6}  "
            f"{env:<32} "
            f"{_fmt_plain_float(dq, 2):>5} "
            f"{_fmt_plain_float(state.get('confidence')):>6}"
        )
    return 0


def _sync_report_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return f'"{value}"' if " " in value else value
    return str(value)


SYNC_FIELD_LABELS = {
    "Q": "entry_price",
    "S": "exit_price",
    "U": "realized_pnl",
    "V": "days_held",
    "AA": "current_price",
    "AB": "current_underlying",
    "AC": "last_price_update",
    "AD": "unrealized_pnl",
    "AE": "pipeline_verdict",
    "AF": "pipeline_rejection_reason",
}


def _column_sort_key(column: str) -> int:
    value = 0
    for char in column:
        value = value * 26 + (ord(char.upper()) - ord("A") + 1)
    return value


def _sync_cell_value(write) -> str:
    value = write.new_value
    if value is None:
        return "cleared"
    if write.column in {"Q", "S", "AA", "AB"} and isinstance(value, (int, float)):
        return f"${value:,.2f}"
    if write.column in {"U", "AD"} and isinstance(value, (int, float)):
        return f"{value:+.2%}"
    if write.column in {"K", "L"} and isinstance(value, (int, float)):
        return f"{value:.2%}"
    if write.column == "V" and isinstance(value, (int, float)):
        return str(int(value))
    return _sync_report_value(value)


def _print_system_write_detail(underlying: str, cycle_id_short: str, writes: list) -> None:
    prefix = f"  {underlying:<8} {cycle_id_short:<10} "
    continuation = " " * len(prefix)
    for index, write in enumerate(sorted(writes, key=lambda item: _column_sort_key(item.column))):
        label = SYNC_FIELD_LABELS.get(write.column, write.field_name)
        line = f"{write.column} ({label})={_sync_cell_value(write)}"
        print(f"{prefix if index == 0 else continuation}{line}")


def _print_sync_report(report, *, verbose: bool) -> None:
    print(f"EXCEL SYNC - {report.log_path}")
    if report.dry_run:
        print("(dry run; no files updated)")
    print("-" * 52)
    print()

    print("User edits read from Excel:")
    if report.user_edits_applied:
        for edit in report.user_edits_applied:
            status = ""
            if edit.status_before != edit.status_after:
                status = f" (status: {edit.status_before} -> {edit.status_after})"
            print(
                f"  {edit.underlying:<8} {edit.cycle_id_short:<10} "
                f"{edit.field_name}: {_sync_report_value(edit.old_value)} -> "
                f"{_sync_report_value(edit.new_value)}{status}"
            )
    else:
        print("  (none)")
    print()

    if report.conflicts:
        print("Conflicts (Excel value won):")
        for conflict in report.conflicts:
            print(
                f"  {conflict.underlying:<8} {conflict.cycle_id_short:<10} "
                f"{conflict.field_name}: CLI had "
                f"{_sync_report_value(conflict.storage_value)}, Excel had "
                f"{_sync_report_value(conflict.excel_value)} - using Excel value"
            )
        print()

    print("System fields written to Excel:")
    if report.system_fields_written:
        grouped: dict[tuple[str, str], list] = {}
        for write in report.system_fields_written:
            key = (write.underlying, write.cycle_id_short)
            grouped.setdefault(key, []).append(write)
        for (underlying, cycle_id_short), writes in grouped.items():
            if report.dry_run or verbose:
                _print_system_write_detail(underlying, cycle_id_short, writes)
                continue
            print(
                f"  {underlying:<8} {cycle_id_short:<10} "
                f"{len(writes)} columns updated"
            )
    else:
        print("  (none)")
    print()

    if report.system_overwrites:
        print("System overwrites (TradeOutcome value won):")
        for overwrite in report.system_overwrites:
            print(
                f"  {overwrite.underlying:<8} {overwrite.cycle_id_short:<10} "
                f"{overwrite.field_name}: Excel had "
                f"{_sync_report_value(overwrite.excel_value)}, TradeOutcome had "
                f"{_sync_report_value(overwrite.storage_value)} - "
                "using TradeOutcome value"
            )
        print()

    print("New outcomes appended to Excel:")
    if report.outcomes_appended:
        for appended in report.outcomes_appended:
            print(
                f"  {appended.underlying:<8} {appended.cycle_id_short:<10} "
                f"row {appended.row_index}"
            )
    else:
        print("  (none)")
    print()

    print("New rejected candidates appended to Excel:")
    if report.rejected_candidates_appended:
        for appended in report.rejected_candidates_appended:
            print(
                f"  {appended.underlying:<8} {appended.cycle_id_short:<10} "
                f"row {appended.row_index}"
            )
    else:
        print("  (none)")
    print()

    print("Warnings:")
    if report.warnings:
        for warning in report.warnings:
            print(
                f"  {(warning.underlying or '-'): <8} "
                f"{(warning.cycle_id_short or '-'): <10} {warning.message}"
            )
    else:
        print("  (none)")
    print()

    print("Summary:")
    print(
        f"  {len(report.user_edits_applied)} user edits read, "
        f"{report.ignored_user_edits} ignored"
    )
    print(f"  {len(report.system_fields_written)} system field updates written")
    print(f"  {len(report.outcomes_appended)} new outcomes appended")
    print(
        f"  {len(report.rejected_candidates_appended)} "
        "new rejected candidates appended"
    )
    print(f"  {len(report.conflicts)} conflicts")
    print(f"  {len(report.system_overwrites)} system overwrites")
    print(f"  {len(report.warnings)} warnings")


def cmd_sync_excel(args: argparse.Namespace) -> int:
    from src.agent_system.services.excel_sync import ExcelSync

    report = ExcelSync(log_warnings=False).sync(dry_run=args.dry_run)
    _print_sync_report(report, verbose=args.verbose)
    return 0


def cmd_which_backend(_args: argparse.Namespace) -> int:
    import os

    from src.agent_system.storage.backend import get_backend

    backend = get_backend()
    backend_name = os.environ.get("AGENT_STORAGE_BACKEND", "postgres").lower()

    print(f"Active backend: {backend_name}")
    print(f"Class:          {backend.__class__.__name__}")

    if backend_name == "postgres":
        dsn = os.environ.get("DATABASE_URL", "")
        if "@" in dsn:
            prefix, suffix = dsn.split("@", 1)
            if ":" in prefix:
                proto_user = prefix.rsplit(":", 1)[0]
                print(f"Database:       {proto_user}:***@{suffix}")
            else:
                print(f"Database:       {prefix}@{suffix}")
    elif backend_name == "jsonl":
        from src.agent_system.storage.jsonl_backend import DEFAULT_DATA_ROOT

        print(f"Data root:      {DEFAULT_DATA_ROOT.absolute()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage TradeOutcome lifecycle states."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    decide = subparsers.add_parser("decide")
    decide.add_argument("--ticker", required=True)
    decide.add_argument("--cycle-id", required=True)
    decide.add_argument("--decision", required=True, choices=["TAKE", "SKIP", "WATCH"])
    decide.add_argument("--reason", default=None)
    decide.set_defaults(func=cmd_decide)

    enter = subparsers.add_parser("enter")
    enter.add_argument("--ticker", required=True)
    enter.add_argument("--cycle-id", required=True)
    enter.add_argument("--date", required=True)
    enter.add_argument("--price", required=True, type=float)
    enter.add_argument("--instrument-price", type=float, default=None)
    enter.add_argument("--portfolio-nav", type=float, default=None)
    enter.add_argument("--notes", default=None)
    enter.set_defaults(func=cmd_enter)

    simulate_entry = subparsers.add_parser("simulate_entry")
    simulate_entry.add_argument("--cycle-id", required=True)
    simulate_entry.add_argument("--asof", default=None)
    simulate_entry.add_argument("--ticker", action="append", default=None)
    simulate_entry.add_argument("--auto-yes", action="store_true")
    simulate_entry.set_defaults(func=cmd_simulate_entry)

    mark = subparsers.add_parser("mark")
    mark.add_argument("--ticker", required=True)
    mark.add_argument("--cycle-id", required=True)
    mark.add_argument("--date", required=True)
    mark.add_argument("--price", required=True, type=float)
    mark.add_argument("--instrument-price", type=float, default=None)
    mark.add_argument("--notes", default=None)
    mark.set_defaults(func=cmd_mark)

    close = subparsers.add_parser("close")
    close.add_argument("--ticker", required=True)
    close.add_argument("--cycle-id", required=True)
    close.add_argument("--date", required=True)
    close.add_argument("--price", required=True, type=float)
    close.add_argument("--instrument-price", type=float, default=None)
    close.add_argument("--reason", required=True)
    close.add_argument("--notes", default=None)
    close.set_defaults(func=cmd_close)

    audit = subparsers.add_parser("audit")
    audit.add_argument("--ticker", required=True)
    audit.add_argument("--cycle-id", required=True)
    audit.add_argument(
        "--thesis-played-out",
        choices=["YES", "PARTIAL", "NO"],
        default=None,
    )
    audit.add_argument(
        "--win-source",
        choices=["thesis", "direction", "timing", "luck", "sizing"],
        default=None,
    )
    audit.add_argument(
        "--system-contribution",
        choices=["STRONG", "NEUTRAL", "WEAK"],
        default=None,
    )
    audit.add_argument("--notes", default=None)
    audit.set_defaults(func=cmd_audit)

    backfill = subparsers.add_parser("backfill")
    cycle_group = backfill.add_mutually_exclusive_group(required=True)
    cycle_group.add_argument("--cycle-id", default=None)
    cycle_group.add_argument("--all-cycles", action="store_true")
    backfill.add_argument("--dry-run", action="store_true")
    backfill.add_argument(
        "--shadow-rejected",
        action="store_true",
        help="Also create shadow_rejected TradeOutcomes from decision_log entries.",
    )
    backfill.set_defaults(func=cmd_backfill)

    list_cmd = subparsers.add_parser("list")
    list_cmd.add_argument("--status", choices=STATUS_ORDER, default=None)
    list_cmd.add_argument("--cycle-id", default=None)
    list_cmd.add_argument("--ticker", default=None)
    list_cmd.add_argument("--exclude-shadow", action="store_true")
    list_cmd.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show")
    show.add_argument("--ticker", required=True)
    show.add_argument("--cycle-id", required=True)
    show.set_defaults(func=cmd_show)

    prices = subparsers.add_parser("prices")
    prices.add_argument("--ticker", required=True)
    prices.add_argument("--cycle-id", required=True)
    prices.set_defaults(func=cmd_prices)

    stats = subparsers.add_parser("stats")
    stats.set_defaults(func=cmd_stats)

    check_regime = subparsers.add_parser("check_regime")
    check_regime.add_argument("--history", type=int, default=None)
    check_regime.set_defaults(func=cmd_check_regime)

    sync_excel = subparsers.add_parser("sync_excel")
    sync_excel.add_argument("--dry-run", action="store_true")
    sync_excel.add_argument("--verbose", action="store_true")
    sync_excel.set_defaults(func=cmd_sync_excel)

    which_backend = subparsers.add_parser("which_backend")
    which_backend.set_defaults(func=cmd_which_backend)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
