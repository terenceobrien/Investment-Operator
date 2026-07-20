"""One-time migration of JSONL storage data to Postgres.

Reads from the JSONL backend and writes to the Postgres backend through the
StorageBackend abstraction. After migration, both backends should contain
equivalent backend-managed data.

The migration is idempotent for keyed records: re-running overwrites existing
Postgres records with the same record_id. Logs are append-only and therefore
not safely idempotent, so the script refuses to re-migrate a log that already
has Postgres rows unless --force-logs is supplied.

Usage:
    python -m scripts.migrate_jsonl_to_postgres
    python -m scripts.migrate_jsonl_to_postgres --apply
    python -m scripts.migrate_jsonl_to_postgres --apply --force-logs
    python -m scripts.migrate_jsonl_to_postgres --apply --collection trade_outcomes
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)

from src.agent_system.storage.jsonl_backend import (  # noqa: E402
    MATCH_ALL_LOG_RECORDS,
    JsonlBackend,
)
from src.agent_system.storage.postgres_backend import (  # noqa: E402
    COLLECTION_COLUMN_MAP,
    DEDICATED_COLLECTIONS,
    DEDICATED_LOGS,
    LOG_COLUMN_MAP,
    LOG_TABLE_MAP,
    PostgresBackend,
)


logger = logging.getLogger(__name__)

LEGACY_KEYED_JSONL_COLLECTIONS = {
    "schema_records",
    "trade_outcomes",
}

NON_STORAGE_DIRECTORIES = {
    "calibration",
    "cycles",
    "data_cache",
    "diagnostics",
    "macro_agent_evals",
    "positions",
    "priorities",
    "scenarios",
    "screen_evals",
    "thematic_agent_evals",
}


@dataclass
class CollectionMigrationResult:
    name: str
    kind: str
    records_found: int = 0
    records_written: int = 0
    records_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    collections: list[CollectionMigrationResult] = field(default_factory=list)
    logs: list[CollectionMigrationResult] = field(default_factory=list)
    log_already_migrated: list[str] = field(default_factory=list)

    @property
    def total_records_found(self) -> int:
        return sum(c.records_found for c in self.collections + self.logs)

    @property
    def total_records_written(self) -> int:
        return sum(c.records_written for c in self.collections + self.logs)

    @property
    def total_errors(self) -> int:
        return sum(len(c.errors) for c in self.collections + self.logs)


def _payload_candidates(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [payload]
    nested = payload.get("payload_json")
    if isinstance(nested, dict):
        candidates.append(nested)
    return candidates


def _field_value(payload: dict[str, Any], field_name: str) -> Any:
    for candidate in _payload_candidates(payload):
        if field_name in candidate:
            return candidate[field_name]
    return None


def _derive_indexed_fields(
    payload: dict[str, Any],
    collection: str,
    kind: str,
) -> dict[str, Any]:
    """Pull indexed field values from a payload based on backend column maps."""

    if kind == "collection":
        fields = COLLECTION_COLUMN_MAP.get(collection, [])
    elif kind == "log":
        fields = LOG_COLUMN_MAP.get(collection, [])
    else:
        return {}

    result: dict[str, Any] = {}
    for field_name in fields:
        value = _field_value(payload, field_name)
        if value is not None:
            result[field_name] = value
    return result


def _derive_record_id(payload: dict[str, Any], collection: str, fallback: str) -> str:
    """Determine the record_id to use when writing a keyed record."""

    if collection == "trade_outcomes":
        trade_id = _field_value(payload, "trade_id")
        if trade_id:
            return str(trade_id)
    record_id = _field_value(payload, "id")
    if record_id:
        return str(record_id)
    return fallback


def _discover_collections(source: JsonlBackend) -> list[str]:
    """Find backend-managed keyed collections in the JSONL data root."""

    data_root = source.data_root
    collections: set[str] = set()

    for path in sorted(data_root.iterdir()):
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        if path.name in NON_STORAGE_DIRECTORIES:
            continue
        if any(path.glob("*.json")):
            collections.add(path.name)

    for path in sorted(data_root.glob("*.jsonl")):
        if path.name.startswith((".", "_")):
            continue
        if path.stem in LEGACY_KEYED_JSONL_COLLECTIONS:
            collections.add(path.stem)

    return sorted(collections)


def _discover_logs(source: JsonlBackend, keyed_collections: list[str]) -> list[str]:
    """Find append-only JSONL logs in the data root."""

    keyed = set(keyed_collections)
    logs: list[str] = []
    for path in sorted(source.data_root.glob("*.jsonl")):
        if path.name.startswith((".", "_")):
            continue
        if path.stem in keyed:
            continue
        logs.append(path.stem)
    return logs


def _migrate_collection(
    collection: str,
    source: JsonlBackend,
    dest: PostgresBackend,
    *,
    dry_run: bool,
) -> CollectionMigrationResult:
    result = CollectionMigrationResult(name=collection, kind="collection")
    try:
        records = source.read_all(collection=collection)
    except Exception as exc:
        result.errors.append(f"Failed to read source: {exc}")
        return result

    result.records_found = len(records)
    for index, payload in enumerate(records):
        try:
            record_id = _derive_record_id(payload, collection, f"record_{index}")
            indexed_fields = _derive_indexed_fields(payload, collection, "collection")

            if dry_run:
                result.records_skipped += 1
                if index < 3:
                    print(
                        f"  [dry-run] would write {collection}/{record_id} "
                        f"(indexed: {list(indexed_fields.keys())})"
                    )
                continue

            dest.write_record(
                collection=collection,
                record_id=record_id,
                payload=payload,
                indexed_fields=indexed_fields,
            )
            result.records_written += 1
        except Exception as exc:
            result.errors.append(f"Record {index}: {exc}")
            logger.warning("Failed to migrate %s record %d: %s", collection, index, exc)
    return result


def _migrate_log(
    log_name: str,
    source: JsonlBackend,
    dest: PostgresBackend,
    *,
    dry_run: bool,
) -> CollectionMigrationResult:
    result = CollectionMigrationResult(name=log_name, kind="log")
    try:
        records = source.query_log_by_field(
            log_name=log_name,
            field=MATCH_ALL_LOG_RECORDS,
            value=MATCH_ALL_LOG_RECORDS,
        )
    except Exception as exc:
        result.errors.append(f"Failed to read source: {exc}")
        return result

    result.records_found = len(records)
    for index, payload in enumerate(records):
        try:
            indexed_fields = _derive_indexed_fields(payload, log_name, "log")
            if dry_run:
                result.records_skipped += 1
                if index < 3:
                    print(
                        f"  [dry-run] would append to {log_name} "
                        f"(indexed: {list(indexed_fields.keys())})"
                    )
                continue

            dest.append_to_log(
                log_name=log_name,
                record=payload,
                indexed_fields=indexed_fields,
            )
            result.records_written += 1
        except Exception as exc:
            result.errors.append(f"Record {index}: {exc}")
            logger.warning("Failed to migrate %s record %d: %s", log_name, index, exc)
    return result


def _count_postgres_log_rows(log_name: str, dest: PostgresBackend) -> int:
    if log_name in DEDICATED_LOGS:
        table = LOG_TABLE_MAP.get(log_name, log_name)
        sql = f"SELECT COUNT(*) FROM {table}"
        params: tuple[Any, ...] = ()
    else:
        sql = "SELECT COUNT(*) FROM generic_log_entries WHERE log_name = %s"
        params = (log_name,)

    with dest._connect() as conn:  # Backend does not expose count APIs.
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return int(row[0]) if row else 0


def _check_log_already_migrated(log_name: str, dest: PostgresBackend) -> bool:
    return _count_postgres_log_rows(log_name, dest) > 0


def run_migration(
    *,
    apply: bool,
    only_collection: Optional[str] = None,
    force_logs: bool = False,
    verbose: bool = False,
) -> MigrationReport:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)

    source = JsonlBackend()
    dest = PostgresBackend()
    report = MigrationReport()

    discovered_collections = _discover_collections(source)
    discovered_logs = _discover_logs(source, discovered_collections)

    collections_to_migrate = discovered_collections
    logs_to_migrate = discovered_logs
    if only_collection:
        collections_to_migrate = [
            name for name in discovered_collections if name == only_collection
        ]
        logs_to_migrate = [name for name in discovered_logs if name == only_collection]
        if not collections_to_migrate and not logs_to_migrate:
            print(f"Collection or log {only_collection!r} not found in {source.data_root}")
            return report

    if collections_to_migrate:
        print(f"\nMigrating {len(collections_to_migrate)} keyed collection(s)...")
        for collection in collections_to_migrate:
            print(f"  * {collection}")
            result = _migrate_collection(
                collection,
                source,
                dest,
                dry_run=not apply,
            )
            report.collections.append(result)

    if logs_to_migrate:
        print(f"\nMigrating {len(logs_to_migrate)} append-only log(s)...")
        for log_name in logs_to_migrate:
            if apply and not force_logs and _check_log_already_migrated(log_name, dest):
                print(
                    f"  ! {log_name} already has records in Postgres; skipping "
                    "(use --force-logs to override)"
                )
                report.log_already_migrated.append(log_name)
                continue
            print(f"  * {log_name}")
            result = _migrate_log(log_name, source, dest, dry_run=not apply)
            report.logs.append(result)

    return report


def print_report(report: MigrationReport, apply: bool) -> None:
    print("\n" + "=" * 70)
    print("MIGRATION COMPLETE" if apply else "DRY RUN SUMMARY (no data written)")
    print("=" * 70)

    if report.collections:
        print("\nKeyed collections:")
        print(f"  {'Name':<35} {'Found':>8} {'Written':>8} {'Errors':>8}")
        print(f"  {'-' * 35} {'-' * 8:>8} {'-' * 8:>8} {'-' * 8:>8}")
        for collection in report.collections:
            written = collection.records_written if apply else collection.records_skipped
            print(
                f"  {collection.name:<35} {collection.records_found:>8} "
                f"{written:>8} {len(collection.errors):>8}"
            )

    if report.logs:
        print("\nAppend-only logs:")
        print(f"  {'Name':<35} {'Found':>8} {'Written':>8} {'Errors':>8}")
        print(f"  {'-' * 35} {'-' * 8:>8} {'-' * 8:>8} {'-' * 8:>8}")
        for log in report.logs:
            written = log.records_written if apply else log.records_skipped
            print(
                f"  {log.name:<35} {log.records_found:>8} "
                f"{written:>8} {len(log.errors):>8}"
            )

    if report.log_already_migrated:
        skipped = ", ".join(report.log_already_migrated)
        print(f"\nLogs skipped (already migrated): {skipped}")

    print(f"\nTotal records found:   {report.total_records_found}")
    if apply:
        print(f"Total records written: {report.total_records_written}")
    print(f"Total errors:          {report.total_errors}")

    if report.total_errors > 0:
        print("\nErrors by collection:")
        for collection in report.collections + report.logs:
            if not collection.errors:
                continue
            print(f"  {collection.name}:")
            for error in collection.errors[:5]:
                print(f"    - {error}")
            if len(collection.errors) > 5:
                print(f"    ... and {len(collection.errors) - 5} more")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate JSONL data to Postgres.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually run the migration. Without this flag, runs as dry-run.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Migrate only one collection or log by name.",
    )
    parser.add_argument(
        "--force-logs",
        action="store_true",
        help=(
            "Re-migrate logs even if Postgres already has rows for them. "
            "WARNING: this can create duplicate log records."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging.")
    args = parser.parse_args()

    report = run_migration(
        apply=args.apply,
        only_collection=args.collection,
        force_logs=args.force_logs,
        verbose=args.verbose,
    )
    print_report(report, apply=args.apply)
    return 1 if report.total_errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
