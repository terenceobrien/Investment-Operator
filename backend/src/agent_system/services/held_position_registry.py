"""Live registry of held, watched, and recently closed trade outcomes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Literal

from src.agent_system.storage.repository import load_trade_outcomes


HeldPositionStatus = Literal["open", "watching", "recently_closed"]


@dataclass(frozen=True)
class HeldPositionRecord:
    ticker: str
    status: HeldPositionStatus
    cycle_id: str
    priority_id: str | None
    priority_label: str | None
    priority_scenarios: list[str]
    closed_at: datetime | None
    closed_reason: str | None
    days_since_close: int | None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value[:10])
    except ValueError:
        return None
    return datetime.combine(parsed.date(), time.min, tzinfo=timezone.utc)


def _sort_key(record: HeldPositionRecord) -> datetime:
    if record.closed_at is not None:
        return record.closed_at
    return datetime.max.replace(tzinfo=timezone.utc)


def get_held_positions(
    *,
    include_watching: bool = True,
    recently_closed_window_days: int = 30,
) -> dict[str, list[HeldPositionRecord]]:
    """Return ticker -> held-position records, sorted most recent first.

    A ticker can appear under multiple priorities across cycles, so each entry
    is a list. The registry reads trade outcomes live on every call.
    """

    now = datetime.now(timezone.utc)
    records_by_ticker: dict[str, list[HeldPositionRecord]] = {}
    for outcome in load_trade_outcomes():
        status: HeldPositionStatus | None = None
        closed_at: datetime | None = None
        days_since_close: int | None = None
        if outcome.status == "open":
            status = "open"
        elif outcome.status == "watching" and include_watching:
            status = "watching"
        elif outcome.status.startswith("closed_"):
            closed_at = _parse_date(outcome.exit_date)
            if closed_at is None:
                continue
            days_since_close = max(0, (now.date() - closed_at.date()).days)
            if days_since_close <= recently_closed_window_days:
                status = "recently_closed"
        if status is None:
            continue

        ticker = outcome.underlying.upper()
        priority_id = outcome.originating_priority_id
        if priority_id is None:
            priority_id = outcome.priority_theme
        record = HeldPositionRecord(
            ticker=ticker,
            status=status,
            cycle_id=outcome.originating_cycle_id or outcome.cycle_id,
            priority_id=priority_id,
            priority_label=outcome.originating_priority_label or outcome.priority_theme,
            priority_scenarios=list(outcome.originating_priority_scenarios or []),
            closed_at=closed_at,
            closed_reason=outcome.exit_reason,
            days_since_close=days_since_close,
        )
        records_by_ticker.setdefault(ticker, []).append(record)

    for records in records_by_ticker.values():
        records.sort(key=_sort_key, reverse=True)
    return records_by_ticker
