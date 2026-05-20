"""
Small storage models for the v0 agent-system repository.

The first executable spine uses append-only JSONL rather than a relational
database. These dataclasses describe the generic record envelope so the
repository code has one durable shape without adding dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SchemaRecord:
    """Generic persisted schema envelope."""

    id: str
    schema_type: str
    schema_version: str
    created_at: datetime
    asof_date: Optional[str]
    ticker: Optional[str]
    source_id: Optional[str]
    payload_json: Dict[str, Any]


@dataclass(frozen=True)
class DecisionLogRecord:
    """Append-only decision-log envelope."""

    id: str
    timestamp: datetime
    payload_json: Dict[str, Any]
