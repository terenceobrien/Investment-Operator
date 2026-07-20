"""Repository facade for agent-system persistence.

Public function signatures in this module are intentionally stable; callers do
not need to know which storage backend is active.

Fragile caller audit:
- ``run_monte_carlo_standalone.py`` imports private helpers
  ``_read_jsonl`` and ``_schema_records_path``. Compatibility shims are kept
  here until that loader is moved onto public repository functions.
- ``test_repository.py`` imports private path helpers. Those are preserved.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar
from uuid import uuid4

from src.agent_system.paths import (
    agent_system_data_root,
    decision_log_path,
    schema_records_path,
)
from src.agent_system.schemas.common import BaseSchema
from src.agent_system.schemas.trade_outcome import PricePoint, TradeOutcome
from src.agent_system.storage.backend import get_backend
from src.agent_system.schemas.deep_fundamental import (
    DeepFundamentalReport,
    SingleNameResearchContextPack,
)

T = TypeVar("T", bound=BaseSchema)

MATCH_ALL_LOG_RECORDS = "*"
REPLACE_EXISTING_BY = "__replace_existing_by__"


@dataclass(frozen=True)
class DecisionLogEntry:
    """Single decision_log row, normalized for read consumption."""

    id: int
    cycle_id: str
    candidate: str
    decision: str
    conviction_rating: str
    rule_applied: str
    summary: str
    weakest_link: str
    trade_idea_id: str | None
    timestamp: datetime
    created_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _data_dir() -> Path:
    return agent_system_data_root()


def _schema_records_path() -> Path:
    return schema_records_path()


def _decision_log_path() -> Path:
    return decision_log_path()


def _trade_outcomes_path() -> Path:
    return _data_dir() / "trade_outcomes.jsonl"


def _price_points_path() -> Path:
    return _data_dir() / "price_points.jsonl"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _extract_metadata(obj: BaseSchema) -> tuple[Optional[str], Optional[str], Optional[str]]:
    payload = obj.model_dump()
    asof_date = payload.get("asof_date")
    ticker = payload.get("ticker") or payload.get("underlying")
    source_id = (
        payload.get("source_priority_id")
        or payload.get("source_narrative_state_asof")
        or None
    )
    return asof_date, ticker, source_id


def _read_jsonl(path: Path) -> list[Dict[str, Any]]:
    """Compatibility JSONL reader for legacy private callers."""

    if path == _schema_records_path():
        return get_backend().read_all(collection="schema_records")
    if path == _trade_outcomes_path():
        return get_backend().read_all(collection="trade_outcomes")
    if path == _decision_log_path():
        return get_backend().query_log_by_field(
            log_name="decision_log",
            field=MATCH_ALL_LOG_RECORDS,
            value=MATCH_ALL_LOG_RECORDS,
        )
    if path == _price_points_path():
        return get_backend().query_log_by_field(
            log_name="price_points",
            field=MATCH_ALL_LOG_RECORDS,
            value=MATCH_ALL_LOG_RECORDS,
        )
    if not path.exists():
        return []
    rows: list[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _append_jsonl(path: Path, row: Dict[str, Any]) -> None:
    """Legacy helper retained for private tests; public code uses backends."""

    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[Dict[str, Any]]) -> None:
    """Legacy helper retained for private tests; public code uses backends."""

    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
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


def _row_created_at(row: dict[str, Any]) -> datetime:
    value = row.get("created_at")
    payload = row.get("payload_json")
    if value is None and isinstance(payload, dict):
        value = payload.get("created_at")
    return _parse_datetime(value)


def save_schema(obj: BaseSchema, *, schema_type: str | None = None) -> str:
    """
    Persist a frozen schema object and return its durable id.

    If the object does not already have an id, the repository assigns one and
    stores that id inside the payload so retrieval rehydrates the same object.
    """

    record_id = obj.id or str(uuid4())
    persisted = obj.model_copy(update={"id": record_id})
    created_at = getattr(persisted, "created_at", _utcnow())
    asof_date, ticker, source_id = _extract_metadata(persisted)
    resolved_schema_type = schema_type or type(obj).__name__
    row = {
        "id": record_id,
        "schema_type": resolved_schema_type,
        "schema_version": persisted.schema_version,
        "created_at": created_at.isoformat(),
        "asof_date": asof_date,
        "ticker": ticker,
        "source_id": source_id,
        "payload_json": persisted.model_dump(mode="json"),
    }
    get_backend().write_record(
        collection="schema_records",
        record_id=record_id,
        payload=row,
        indexed_fields={
            "schema_type": resolved_schema_type,
            "asof_date": asof_date,
            "ticker": ticker,
            "source_id": source_id,
        },
    )
    return record_id


def get_schema(record_id: str, model_type: type[T]) -> T:
    """Load one schema record by id and validate it as ``model_type``."""

    row = get_backend().read_record(
        collection="schema_records",
        record_id=record_id,
    )
    if row is not None:
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            return model_type.model_validate(payload)
    raise KeyError(f"No schema record found for id={record_id!r}")


def list_schemas(model_type: type[T], limit: int = 50) -> list[T]:
    """Return recent records that validate as ``model_type``."""

    schema_type = model_type.__name__
    rows = get_backend().query_by_field(
        collection="schema_records",
        field="schema_type",
        value=schema_type,
    )
    results: list[T] = []
    for row in sorted(rows, key=_row_created_at, reverse=True):
        payload = row.get("payload_json")
        if not isinstance(payload, dict):
            continue
        try:
            results.append(model_type.model_validate(payload))
        except Exception:
            continue
        if len(results) >= limit:
            break
    return results


def save_decision_log_entry(entry: dict) -> str:
    """Append a decision log entry and return its id."""

    record_id = str(uuid4())
    timestamp = _utcnow().isoformat()
    payload = dict(entry)
    payload.setdefault("id", record_id)
    payload.setdefault("timestamp", timestamp)
    row = {
        "id": record_id,
        "timestamp": payload["timestamp"],
        "payload_json": payload,
    }
    get_backend().append_to_log(
        log_name="decision_log",
        record=row,
        indexed_fields={
            "id": record_id,
            "timestamp": payload["timestamp"],
            "cycle_id": payload.get("cycle_id"),
            "candidate": payload.get("candidate"),
        },
    )
    return record_id


def list_decision_log_entries(limit: int = 50) -> list[dict]:
    """Return recent decision log payloads."""

    rows = get_backend().query_log_by_field(
        log_name="decision_log",
        field=MATCH_ALL_LOG_RECORDS,
        value=MATCH_ALL_LOG_RECORDS,
    )
    payloads: list[dict] = []
    for row in reversed(rows):
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(payload)
        else:
            payloads.append(row)
        if len(payloads) >= limit:
            break
    return payloads


def _log_row_id(row: dict[str, Any]) -> int:
    raw_id = row.get("id")
    if isinstance(raw_id, int):
        return raw_id
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return 0


def _decision_log_payload(
    row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    wrapper = row.get("payload")
    if not isinstance(wrapper, dict):
        wrapper = row
    payload = wrapper.get("payload_json")
    if isinstance(payload, dict):
        return payload, wrapper
    return wrapper, wrapper


def _decision_log_entry_from_row(row: dict[str, Any]) -> DecisionLogEntry:
    payload, wrapper = _decision_log_payload(row)
    timestamp = _parse_datetime(
        payload.get("timestamp")
        or wrapper.get("timestamp")
        or row.get("created_at")
    )
    created_at = _parse_datetime(
        row.get("created_at")
        or wrapper.get("created_at")
        or payload.get("created_at")
        or timestamp
    )
    trade_idea_id = payload.get("trade_idea_id") or payload.get("trade_id")
    return DecisionLogEntry(
        id=_log_row_id(row),
        cycle_id=str(payload.get("cycle_id") or wrapper.get("cycle_id") or ""),
        candidate=str(payload.get("candidate") or wrapper.get("candidate") or ""),
        decision=str(payload.get("decision") or ""),
        conviction_rating=str(payload.get("conviction_rating") or ""),
        rule_applied=str(payload.get("rule_applied") or ""),
        summary=str(payload.get("summary") or ""),
        weakest_link=str(payload.get("weakest_link") or ""),
        trade_idea_id=str(trade_idea_id) if trade_idea_id is not None else None,
        timestamp=timestamp,
        created_at=created_at,
    )


def load_decision_log_entries_by_cycle(cycle_id: str) -> list[DecisionLogEntry]:
    """Return all decision_log rows for a cycle, ordered by timestamp."""

    rows = get_backend().query_log_rows_by_field(
        log_name="decision_log",
        field="cycle_id",
        value=cycle_id,
    )
    entries: list[DecisionLogEntry] = []
    for row in rows:
        entry = _decision_log_entry_from_row(row)
        if entry.cycle_id == cycle_id:
            entries.append(entry)
    return sorted(entries, key=lambda entry: (entry.timestamp, entry.id))


def save_regime_state(state: dict) -> str:
    """Save a RegimeState dict through the storage backend.

    Returns the record_id, which is the asof_date. Re-saving the same date is
    an intentional upsert so daily cron retries are idempotent.
    """

    record_id = state["asof_date"]
    get_backend().write_record(
        collection="regime_states",
        record_id=record_id,
        payload=state,
        indexed_fields={"asof_date": record_id},
    )
    return record_id


def load_regime_state(asof_date: str) -> Optional[dict]:
    """Load a RegimeState by asof_date. Returns a dict or None."""

    return get_backend().read_record(
        collection="regime_states",
        record_id=asof_date,
    )


def load_latest_regime_state() -> Optional[dict]:
    """Load the most recent RegimeState by asof_date."""

    all_states = get_backend().read_all(collection="regime_states")
    if not all_states:
        return None
    return max(all_states, key=lambda state: state.get("asof_date", ""))


def load_regime_states_range(start_date: str, end_date: str) -> list[dict]:
    """Load all RegimeStates with asof_date in [start_date, end_date]."""

    all_states = get_backend().read_all(collection="regime_states")
    return sorted(
        [
            state
            for state in all_states
            if start_date <= state.get("asof_date", "") <= end_date
        ],
        key=lambda state: state["asof_date"],
    )


def save_trade_outcome(outcome: TradeOutcome) -> str:
    """Save or update a TradeOutcome record. Returns the storage key."""

    record_id = outcome.trade_id
    persisted = outcome.model_copy(update={"id": record_id})
    get_backend().write_record(
        collection="trade_outcomes",
        record_id=record_id,
        payload=persisted.model_dump(mode="json"),
        indexed_fields={
            "cycle_id": persisted.cycle_id,
            "status": persisted.status,
            "underlying": persisted.underlying,
            "trade_id": persisted.trade_id,
            "originating_priority_id": persisted.originating_priority_id,
        },
    )
    return record_id


def _outcome_from_row(row: dict[str, Any]) -> TradeOutcome | None:
    payload = row.get("payload_json")
    if not isinstance(payload, dict):
        payload = row
    try:
        return TradeOutcome.model_validate(payload)
    except Exception:
        return None


def load_trade_outcome(trade_id: str) -> Optional[TradeOutcome]:
    """Load the latest TradeOutcome for a given trade_id."""

    row = get_backend().read_record(
        collection="trade_outcomes",
        record_id=trade_id,
    )
    if row is None:
        return None
    return _outcome_from_row(row)


def load_trade_outcomes() -> list[TradeOutcome]:
    """Load latest TradeOutcome records keyed by trade_id."""

    outcomes: list[TradeOutcome] = []
    for row in get_backend().read_all(collection="trade_outcomes"):
        outcome = _outcome_from_row(row)
        if outcome is not None:
            outcomes.append(outcome)
    return outcomes


def load_trade_outcomes_by_cycle(cycle_id: str) -> list[TradeOutcome]:
    """Load all latest TradeOutcome records for a given cycle_id."""

    return [
        outcome
        for outcome in load_trade_outcomes()
        if outcome.cycle_id == cycle_id
    ]


def load_open_trade_outcomes() -> list[TradeOutcome]:
    """Load all TradeOutcome records with status 'open' or 'watching'."""

    return [
        outcome
        for outcome in load_trade_outcomes()
        if outcome.status in {"open", "watching"}
    ]


def save_price_point(point: PricePoint, *, replace_same_date: bool = False) -> None:
    """Append one PricePoint to the price history log for its trade_id."""

    record_id = point.id or str(uuid4())
    persisted = point.model_copy(update={"id": record_id})
    row = {
        "id": record_id,
        "schema_type": "PricePoint",
        "schema_version": persisted.schema_version,
        "created_at": persisted.created_at.isoformat(),
        "trade_id": persisted.trade_id,
        "asof_date": persisted.asof_date,
        "payload_json": persisted.model_dump(mode="json"),
    }
    indexed_fields: dict[str, Any] = {
        "trade_id": persisted.trade_id,
        "asof_date": persisted.asof_date,
    }
    if replace_same_date:
        indexed_fields[REPLACE_EXISTING_BY] = ("trade_id", "asof_date")
    get_backend().append_to_log(
        log_name="price_points",
        record=row,
        indexed_fields=indexed_fields,
    )


def _price_point_row_matches(
    row: dict[str, Any],
    *,
    trade_id: str,
    asof_date: str,
) -> bool:
    payload = row.get("payload_json")
    payload_trade_id = payload.get("trade_id") if isinstance(payload, dict) else None
    payload_asof = payload.get("asof_date") if isinstance(payload, dict) else None
    return (
        (row.get("trade_id") == trade_id or payload_trade_id == trade_id)
        and (row.get("asof_date") == asof_date or payload_asof == asof_date)
    )


def load_price_points(trade_id: str) -> list[PricePoint]:
    """Load all PricePoint records for a trade, ordered by asof_date ascending."""

    points: list[PricePoint] = []
    rows = get_backend().query_log_by_field(
        log_name="price_points",
        field="trade_id",
        value=trade_id,
    )
    for row in rows:
        payload = row.get("payload_json")
        if not isinstance(payload, dict):
            payload = row
        try:
            points.append(PricePoint.model_validate(payload))
        except Exception:
            continue
    points.sort(key=lambda point: (point.asof_date, point.created_at))
    return points

# ---------------------------------------------------------------------
# Deep Fundamental Reports
# ---------------------------------------------------------------------

REPO_ROOT = Path(__file__).parents[4]
DEEP_FUNDAMENTAL_DIR = REPO_ROOT/ "data"/ "deep_fundamental_reports"


def _ensure_deep_fundamental_dir() -> None:
    DEEP_FUNDAMENTAL_DIR.mkdir(parents=True, exist_ok=True)


def _deep_fundamental_report_path(
    ticker: str,
    as_of_date: str,
    cycle_id: str | None = None,
) -> Path:
    """
    Creates a stable path for a deep fundamental report.

    Standalone:
        data/deep_fundamental_reports/standalone/MU/2026-06-25.json

    Routed cycle:
        data/deep_fundamental_reports/cycles/{cycle_id}/MU/2026-06-25.json
    """

    clean_ticker = ticker.upper()

    if cycle_id:
        return (
            DEEP_FUNDAMENTAL_DIR
            / "cycles"
            / cycle_id
            / clean_ticker
            / f"{as_of_date}.json"
        )

    return (
        DEEP_FUNDAMENTAL_DIR
        / "standalone"
        / clean_ticker
        / f"{as_of_date}.json"
    )


def save_deep_fundamental_report(report: DeepFundamentalReport) -> Path:
    """
    Save a DeepFundamentalReport as JSON.
    """

    _ensure_deep_fundamental_dir()

    path = _deep_fundamental_report_path(
        ticker=report.ticker,
        as_of_date=str(report.as_of_date),
        cycle_id=report.cycle_id,
    )

    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )

    return path


def load_deep_fundamental_report(
    ticker: str,
    as_of_date: str,
    cycle_id: str | None = None,
) -> DeepFundamentalReport:
    """
    Load a single DeepFundamentalReport.
    """

    path = _deep_fundamental_report_path(
        ticker=ticker,
        as_of_date=as_of_date,
        cycle_id=cycle_id,
    )

    if not path.exists():
        raise FileNotFoundError(f"Deep fundamental report not found: {path}")

    return DeepFundamentalReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def load_deep_fundamental_reports_by_cycle(
    cycle_id: str,
) -> list[DeepFundamentalReport]:
    """
    Load all deep fundamental reports for a routed research cycle.
    """

    cycle_dir = DEEP_FUNDAMENTAL_DIR / "cycles" / cycle_id

    if not cycle_dir.exists():
        return []

    reports: list[DeepFundamentalReport] = []

    for path in sorted(cycle_dir.glob("*/*.json")):
        reports.append(
            DeepFundamentalReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        )

    return reports


def load_latest_deep_fundamental_report(
    ticker: str,
    cycle_id: str | None = None,
) -> DeepFundamentalReport | None:
    """
    Load the most recent report for a ticker.
    Useful for dashboard display and rerun comparison.
    """

    clean_ticker = ticker.upper()

    if cycle_id:
        ticker_dir = DEEP_FUNDAMENTAL_DIR / "cycles" / cycle_id / clean_ticker
    else:
        ticker_dir = DEEP_FUNDAMENTAL_DIR / "standalone" / clean_ticker

    if not ticker_dir.exists():
        return None

    paths = sorted(ticker_dir.glob("*.json"))

    if not paths:
        return None

    latest_path = paths[-1]

    return DeepFundamentalReport.model_validate_json(
        latest_path.read_text(encoding="utf-8")
    )


def list_deep_fundamental_reports(
    ticker: str | None = None,
    cycle_id: str | None = None,
) -> list[Path]:
    """
    List saved deep fundamental report paths.

    This is useful for debugging and simple CLI inspection.
    """

    if cycle_id:
        base_dir = DEEP_FUNDAMENTAL_DIR / "cycles" / cycle_id
    else:
        base_dir = DEEP_FUNDAMENTAL_DIR / "standalone"

    if ticker:
        base_dir = base_dir / ticker.upper()

    if not base_dir.exists():
        return []

    return sorted(base_dir.glob("**/*.json"))


# ---------------------------------------------------------------------
# Single-name research contexts
# ---------------------------------------------------------------------

RESEARCH_CONTEXT_DIR = _data_dir() / "research_contexts"


def _research_context_path(ticker: str, as_of_date: date | str) -> Path:
    clean_ticker = ticker.upper().strip()
    return RESEARCH_CONTEXT_DIR / clean_ticker / f"{as_of_date}.json"


def save_research_context_pack(pack: SingleNameResearchContextPack) -> Path:
    """Save a SingleNameResearchContextPack as JSON."""

    path = _research_context_path(pack.ticker, pack.as_of_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(pack.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return path


def load_research_context_pack(
    ticker: str,
    as_of_date: date | str,
) -> SingleNameResearchContextPack | None:
    path = _research_context_path(ticker, as_of_date)
    if not path.exists():
        return None
    return SingleNameResearchContextPack.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def load_latest_research_context_pack(
    ticker: str,
) -> SingleNameResearchContextPack | None:
    clean_ticker = ticker.upper().strip()
    ticker_dir = RESEARCH_CONTEXT_DIR / clean_ticker
    if not ticker_dir.exists():
        return None
    paths = sorted(ticker_dir.glob("*.json"))
    if not paths:
        return None
    return SingleNameResearchContextPack.model_validate_json(
        paths[-1].read_text(encoding="utf-8")
    )


def list_research_context_packs(ticker: str | None = None) -> list[Path]:
    base_dir = RESEARCH_CONTEXT_DIR
    if ticker:
        base_dir = base_dir / ticker.upper().strip()
    if not base_dir.exists():
        return []
    return sorted(base_dir.glob("**/*.json"))
