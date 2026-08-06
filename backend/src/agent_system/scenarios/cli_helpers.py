"""Helper functions for scenario CLI inspection tools."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.agent_system.scenarios.loader import agent_data_dir
from src.agent_system.schemas.trade import TradeIdea


DEFAULT_SCHEMA_RECORDS_PATH = agent_data_dir() / "schema_records.jsonl"


def schema_records_path() -> Path:
    """Return the schema_records.jsonl path that matches scenario storage."""
    return agent_data_dir() / "schema_records.jsonl"


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _payload_for_trade_model(payload: dict) -> dict:
    payload = dict(payload)
    # Some ad-hoc/debug records may carry cycle_id inside payload_json even
    # though TradeIdea forbids that extra field. Use it for filtering, not
    # model validation.
    payload.pop("cycle_id", None)
    return payload


def _cycle_id_matches(row: dict, payload: dict, cycle_id: str | None) -> bool:
    if cycle_id is None:
        return True
    return row.get("cycle_id") == cycle_id or payload.get("cycle_id") == cycle_id


def _iter_matching_trade_rows(
    ticker: str,
    *,
    cycle_id: str | None,
    storage_path: Path,
) -> list[tuple[datetime, TradeIdea]]:
    if not storage_path.exists():
        raise FileNotFoundError(f"schema records file not found: {storage_path}")

    ticker_upper = ticker.upper()
    matches: list[tuple[datetime, TradeIdea]] = []
    with storage_path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Malformed JSON in schema records file {storage_path} "
                    f"on line {line_no}: {exc}"
                ) from exc

            if row.get("schema_type") != "TradeIdea":
                continue
            payload = row.get("payload_json")
            if not isinstance(payload, dict):
                continue
            if str(payload.get("underlying", "")).upper() != ticker_upper:
                continue
            if not _cycle_id_matches(row, payload, cycle_id):
                continue

            try:
                trade = TradeIdea.model_validate(_payload_for_trade_model(payload))
            except Exception:
                continue
            created_at = _parse_created_at(row.get("created_at") or payload.get("created_at"))
            matches.append((created_at, trade))
    return matches


def find_trade_by_ticker(
    ticker: str,
    cycle_id: str | None = None,
    storage_path: Path = DEFAULT_SCHEMA_RECORDS_PATH,
) -> TradeIdea | None:
    """
    Find the most recent scoreable TradeIdea matching ticker and optional cycle.

    Rejected TradeIdeas (expression=None) are not returned because scenario
    payoff scoring needs an actual expression.
    """
    matches = _iter_matching_trade_rows(
        ticker,
        cycle_id=cycle_id,
        storage_path=storage_path,
    )
    scoreable = [(created_at, trade) for created_at, trade in matches if trade.expression]
    if not scoreable:
        return None
    return max(scoreable, key=lambda item: item[0])[1]


def find_latest_trade_any_status(
    ticker: str,
    cycle_id: str | None = None,
    storage_path: Path = DEFAULT_SCHEMA_RECORDS_PATH,
) -> TradeIdea | None:
    """Find the most recent TradeIdea whether accepted or rejected."""
    matches = _iter_matching_trade_rows(
        ticker,
        cycle_id=cycle_id,
        storage_path=storage_path,
    )
    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]
