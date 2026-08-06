"""JSONL backend implementation.

Maps the abstract StorageBackend interface to JSONL files under
data/agent_system/.

Layout:
  data/agent_system/{collection}/{record_id}.json
  data/agent_system/{log_name}.jsonl

The reader also scans legacy ``data/agent_system/{collection}.jsonl`` files so
the abstraction is backward-compatible without a migration step.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Optional

from src.agent_system.paths import agent_system_data_root
from src.agent_system.storage.backend import StorageBackend


DEFAULT_DATA_ROOT = agent_system_data_root(create=False)
MATCH_ALL_LOG_RECORDS = "*"
REPLACE_EXISTING_BY = "__replace_existing_by__"


class JsonlBackend(StorageBackend):
    def __init__(self, data_root: Optional[Path] = None):
        self._data_root = data_root

    @property
    def data_root(self) -> Path:
        root = self._data_root or agent_system_data_root()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _collection_dir(self, collection: str) -> Path:
        path = self.data_root / collection
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _record_path(self, collection: str, record_id: str) -> Path:
        safe_id = record_id.replace("/", "_").replace("\\", "_")
        if ".." in safe_id:
            raise ValueError(f"Invalid record_id: {record_id!r}")
        return self._collection_dir(collection) / f"{safe_id}.json"

    def _legacy_collection_path(self, collection: str) -> Path:
        return self.data_root / f"{collection}.jsonl"

    def _log_path(self, log_name: str) -> Path:
        return self.data_root / f"{log_name}.jsonl"

    def write_record(
        self,
        *,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        path = self._record_path(collection, record_id)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as fh:
            json.dump(payload, fh, indent=2, default=str)
            fh.write("\n")
            tmp_path = Path(fh.name)
        tmp_path.replace(path)

    def read_record(
        self,
        *,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        path = self._record_path(collection, record_id)
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

        for record in reversed(self._read_legacy_collection(collection)):
            if self._record_matches_id(record, record_id):
                return record
        return None

    def read_all(self, *, collection: str) -> list[dict[str, Any]]:
        records = self._read_legacy_collection(collection)
        directory = self._collection_dir(collection)
        for path in sorted(directory.glob("*.json")):
            with path.open("r", encoding="utf-8") as fh:
                records.append(json.load(fh))
        return self._dedupe_keyed_records(records)

    def query_by_field(
        self,
        *,
        collection: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        return [
            record
            for record in self.read_all(collection=collection)
            if self._field_value(record, field) == value
        ]

    def append_to_log(
        self,
        *,
        log_name: str,
        record: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        path = self._log_path(log_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        replace_fields = tuple((indexed_fields or {}).get(REPLACE_EXISTING_BY, ()))
        if replace_fields:
            rows = [
                existing
                for existing in self._read_jsonl(path)
                if not self._matches_fields(existing, record, replace_fields)
            ]
            rows.append(record)
            self._write_jsonl(path, rows)
            return
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, sort_keys=True) + "\n")

    def query_log_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        path = self._log_path(log_name)
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        for record in self._read_jsonl(path):
            if (
                field == MATCH_ALL_LOG_RECORDS
                or self._field_value(record, field) == value
            ):
                results.append(record)
        return results

    def query_log_rows_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        path = self._log_path(log_name)
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        for index, record in enumerate(self._read_jsonl(path), start=1):
            if (
                field == MATCH_ALL_LOG_RECORDS
                or self._field_value(record, field) == value
            ):
                results.append(
                    {
                        "id": index,
                        "payload": record,
                        "created_at": self._log_record_created_at(record),
                    }
                )
        return results

    def _read_legacy_collection(self, collection: str) -> list[dict[str, Any]]:
        return self._read_jsonl(self._legacy_collection_path(collection))

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
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

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            suffix=".tmp",
        ) as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str, sort_keys=True) + "\n")
            tmp_path = Path(fh.name)
        tmp_path.replace(path)

    def _record_matches_id(self, record: dict[str, Any], record_id: str) -> bool:
        payload = record.get("payload_json")
        payload_id = payload.get("id") if isinstance(payload, dict) else None
        payload_trade_id = (
            payload.get("trade_id") if isinstance(payload, dict) else None
        )
        return record_id in {
            record.get("id"),
            record.get("trade_id"),
            payload_id,
            payload_trade_id,
        }

    def _dedupe_keyed_records(
        self,
        records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        anonymous: list[dict[str, Any]] = []
        for record in records:
            key = self._record_key(record)
            if key is None:
                anonymous.append(record)
                continue
            latest[key] = record
        return anonymous + list(latest.values())

    def _record_key(self, record: dict[str, Any]) -> str | None:
        payload = record.get("payload_json")
        if isinstance(payload, dict):
            return (
                payload.get("id")
                or payload.get("trade_id")
                or record.get("id")
                or record.get("trade_id")
            )
        return record.get("id") or record.get("trade_id")

    def _field_value(self, record: dict[str, Any], field: str) -> Any:
        if field in record:
            return record.get(field)
        payload = record.get("payload_json")
        if isinstance(payload, dict):
            return payload.get(field)
        return None

    def _log_record_created_at(self, record: dict[str, Any]) -> Any:
        payload = record.get("payload_json")
        if isinstance(payload, dict):
            return (
                record.get("created_at")
                or payload.get("created_at")
                or payload.get("timestamp")
            )
        return record.get("created_at") or record.get("timestamp")

    def _matches_fields(
        self,
        existing: dict[str, Any],
        new_record: dict[str, Any],
        fields: tuple[str, ...],
    ) -> bool:
        return all(
            self._field_value(existing, field) == self._field_value(new_record, field)
            for field in fields
        )
