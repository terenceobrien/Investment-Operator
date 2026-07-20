"""Compare backend-managed record counts between JSONL and Postgres.

Run after migration to confirm the data made it across. Reports any collection
or log where counts differ.

Usage:
    python -m scripts.verify_migration
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
    DEDICATED_COLLECTIONS,
    DEDICATED_LOGS,
    LOG_TABLE_MAP,
    PostgresBackend,
)

from scripts.migrate_jsonl_to_postgres import (  # noqa: E402
    _discover_collections,
    _discover_logs,
)


def count_jsonl_records(source: JsonlBackend, name: str, kind: str) -> int:
    if kind == "collection":
        return len(source.read_all(collection=name))
    if kind == "log":
        return len(
            source.query_log_by_field(
                log_name=name,
                field=MATCH_ALL_LOG_RECORDS,
                value=MATCH_ALL_LOG_RECORDS,
            )
        )
    raise ValueError(f"Unknown kind: {kind}")


def count_postgres_records(dest: PostgresBackend, name: str, kind: str) -> int:
    if kind == "collection":
        if name in DEDICATED_COLLECTIONS:
            sql = f"SELECT COUNT(*) FROM {name}"
            params: tuple[Any, ...] = ()
        else:
            sql = "SELECT COUNT(*) FROM generic_records WHERE collection = %s"
            params = (name,)
    elif kind == "log":
        if name in DEDICATED_LOGS:
            table = LOG_TABLE_MAP.get(name, name)
            sql = f"SELECT COUNT(*) FROM {table}"
            params = ()
        else:
            sql = "SELECT COUNT(*) FROM generic_log_entries WHERE log_name = %s"
            params = (name,)
    else:
        raise ValueError(f"Unknown kind: {kind}")

    with dest._connect() as conn:  # Backend intentionally exposes reads, not counts.
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
    return int(row[0]) if row else 0


def main() -> int:
    source = JsonlBackend()
    dest = PostgresBackend()

    collections = _discover_collections(source)
    logs = _discover_logs(source, collections)

    print("\nVerifying migration: JSONL <-> Postgres record counts")
    print("=" * 70)

    mismatches: list[tuple[str, str, int, int]] = []

    if collections:
        print("\nKeyed collections:")
        print(f"  {'Name':<35} {'JSONL':>8} {'Postgres':>10} {'Match':>8}")
        print(f"  {'-' * 35} {'-' * 8} {'-' * 10} {'-' * 8}")
        for name in collections:
            jsonl_count = count_jsonl_records(source, name, "collection")
            pg_count = count_postgres_records(dest, name, "collection")
            match = "yes" if jsonl_count == pg_count else "no"
            print(f"  {name:<35} {jsonl_count:>8} {pg_count:>10} {match:>8}")
            if jsonl_count != pg_count:
                mismatches.append((name, "collection", jsonl_count, pg_count))

    if logs:
        print("\nAppend-only logs:")
        print(f"  {'Name':<35} {'JSONL':>8} {'Postgres':>10} {'Match':>8}")
        print(f"  {'-' * 35} {'-' * 8} {'-' * 10} {'-' * 8}")
        for name in logs:
            jsonl_count = count_jsonl_records(source, name, "log")
            pg_count = count_postgres_records(dest, name, "log")
            match = "yes" if jsonl_count == pg_count else "no"
            print(f"  {name:<35} {jsonl_count:>8} {pg_count:>10} {match:>8}")
            if jsonl_count != pg_count:
                mismatches.append((name, "log", jsonl_count, pg_count))

    print("\n" + "=" * 70)
    if mismatches:
        print(f"FOUND {len(mismatches)} MISMATCH(ES):")
        for name, kind, jsonl_count, pg_count in mismatches:
            diff = pg_count - jsonl_count
            sign = "+" if diff > 0 else ""
            print(
                f"  {name} ({kind}): JSONL={jsonl_count}, "
                f"Postgres={pg_count} ({sign}{diff})"
            )
        print("\nNote: log mismatches can be caused by re-running with --force-logs.")
        return 1

    print("All counts match. Migration verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
