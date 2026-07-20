"""Storage backend abstraction.

Default backend: postgres (since the JSONL to Postgres migration).

To revert to JSONL for any reason (debugging, offline work, etc):
    export AGENT_STORAGE_BACKEND=jsonl

Both backends contain the same data as of the migration. JSONL files remain on
disk at data/agent_system/ as a safety net.

All persistence in the agent system goes through this interface. Concrete
backends (JSONL on disk, Postgres) implement the methods. Code calling into
storage doesn't know or care which backend is active.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv


load_dotenv()
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

SUPPORTED_BACKENDS = ("jsonl", "postgres")
_validated = False


class StorageBackend(ABC):
    """Abstract storage backend. Concrete implementations: JsonlBackend."""

    @abstractmethod
    def write_record(
        self,
        *,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        """Write or overwrite a record by collection + record_id."""

    @abstractmethod
    def read_record(
        self,
        *,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        """Read one record by collection + record_id. Returns None if not found."""

    @abstractmethod
    def read_all(self, *, collection: str) -> list[dict[str, Any]]:
        """Read all records in a collection."""

    @abstractmethod
    def query_by_field(
        self,
        *,
        collection: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        """Read all records where indexed_fields[field] == value."""

    @abstractmethod
    def append_to_log(
        self,
        *,
        log_name: str,
        record: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        """Append a record to an append-only log."""

    @abstractmethod
    def query_log_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        """Read all log records where indexed_fields[field] == value."""

    @abstractmethod
    def query_log_rows_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        """Read full log rows, including backend row metadata where available."""


def get_backend() -> StorageBackend:
    """Return the configured backend singleton."""

    global _validated

    backend_name = os.environ.get("AGENT_STORAGE_BACKEND", "postgres").lower()

    if not _validated and backend_name == "postgres":
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "AGENT_STORAGE_BACKEND=postgres requires DATABASE_URL to be set. "
                "Either set DATABASE_URL or set AGENT_STORAGE_BACKEND=jsonl to "
                "use the local backend."
            )
        _validated = True

    if backend_name not in SUPPORTED_BACKENDS:
        raise ValueError(
            f"Unsupported AGENT_STORAGE_BACKEND={backend_name!r}; "
            f"must be one of {SUPPORTED_BACKENDS}"
        )
    if backend_name == "jsonl":
        from src.agent_system.storage.jsonl_backend import JsonlBackend

        return _get_or_create("jsonl", JsonlBackend)
    if backend_name == "postgres":
        from src.agent_system.storage.postgres_backend import PostgresBackend

        return _get_or_create("postgres", PostgresBackend)
    raise RuntimeError(f"Unreachable: backend={backend_name}")


_backend_singletons: dict[str, StorageBackend] = {}


def _get_or_create(name: str, cls: type) -> StorageBackend:
    if name not in _backend_singletons:
        _backend_singletons[name] = cls()
    return _backend_singletons[name]
