"""
Storage layer for agent-system schemas.

The v0 implementation is append-only JSONL under ``data/agent_system`` by
default. It exposes repository functions that accept and return strict
Pydantic schema objects so callers do not depend on the storage format.
"""

from src.agent_system.storage.models import DecisionLogRecord, SchemaRecord
from src.agent_system.storage.repository import (
    get_schema,
    list_decision_log_entries,
    list_schemas,
    save_decision_log_entry,
    save_schema,
)

__all__ = [
    "DecisionLogRecord",
    "SchemaRecord",
    "get_schema",
    "list_decision_log_entries",
    "list_schemas",
    "save_decision_log_entry",
    "save_schema",
]
