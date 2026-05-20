"""
Append-only JSONL repository for the v0 execution spine.

This deliberately stays generic: schemas go in, schemas come back out. The
storage layer should not know about investment logic yet.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TypeVar
from uuid import uuid4

from src.agent_system.schemas.common import BaseSchema

T = TypeVar("T", bound=BaseSchema)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _data_dir() -> Path:
    default_dir = Path(__file__).resolve().parents[4] / "data" / "agent_system"
    return Path(os.getenv("AGENT_SYSTEM_DATA_DIR", str(default_dir)))


def _schema_records_path() -> Path:
    return _data_dir() / "schema_records.jsonl"


def _decision_log_path() -> Path:
    return _data_dir() / "decision_log.jsonl"


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
    _ensure_parent(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


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
    row = {
        "id": record_id,
        "schema_type": schema_type or type(obj).__name__,
        "schema_version": persisted.schema_version,
        "created_at": created_at.isoformat(),
        "asof_date": asof_date,
        "ticker": ticker,
        "source_id": source_id,
        "payload_json": persisted.model_dump(mode="json"),
    }
    _append_jsonl(_schema_records_path(), row)
    return record_id


def get_schema(record_id: str, model_type: type[T]) -> T:
    """Load one schema record by id and validate it as ``model_type``."""

    for row in _read_jsonl(_schema_records_path()):
        if row.get("id") != record_id:
            continue
        payload = row.get("payload_json")
        if not isinstance(payload, dict):
            break
        return model_type.model_validate(payload)
    raise KeyError(f"No schema record found for id={record_id!r}")


def list_schemas(model_type: type[T], limit: int = 50) -> list[T]:
    """Return recent records that validate as ``model_type``."""

    schema_type = model_type.__name__
    results: list[T] = []
    for row in reversed(_read_jsonl(_schema_records_path())):
        if row.get("schema_type") != schema_type:
            continue
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
    _append_jsonl(_decision_log_path(), row)
    return record_id


def list_decision_log_entries(limit: int = 50) -> list[dict]:
    """Return recent decision log payloads."""

    rows = _read_jsonl(_decision_log_path())
    payloads: list[dict] = []
    for row in reversed(rows):
        payload = row.get("payload_json")
        if isinstance(payload, dict):
            payloads.append(payload)
        if len(payloads) >= limit:
            break
    return payloads
