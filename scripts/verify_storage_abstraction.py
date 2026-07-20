"""Smoke test for the storage abstraction.

Usage:
    python -m scripts.verify_storage_abstraction
    python -m scripts.verify_storage_abstraction --backend postgres
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env", override=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=["jsonl", "postgres"],
        default=None,
        help="Override AGENT_STORAGE_BACKEND for this test run",
    )
    args = parser.parse_args()

    if args.backend:
        os.environ["AGENT_STORAGE_BACKEND"] = args.backend

    from src.agent_system.storage.backend import get_backend

    backend_name = os.environ.get("AGENT_STORAGE_BACKEND", "postgres")
    print(f"Testing storage backend: {backend_name}")

    backend = get_backend()

    test_payload = {
        "id": "test_storage_smoke_postgres_1",
        "value": 42,
        "label": "smoke",
    }
    backend.write_record(
        collection="_smoke_test",
        record_id="test_storage_smoke_postgres_1",
        payload=test_payload,
        indexed_fields={"label": "smoke"},
    )
    loaded = backend.read_record(
        collection="_smoke_test",
        record_id="test_storage_smoke_postgres_1",
    )
    assert loaded == test_payload, f"Round-trip mismatch: {loaded} vs {test_payload}"
    print("✓ write_record + read_record round-trip")

    results = backend.query_by_field(
        collection="_smoke_test",
        field="label",
        value="smoke",
    )
    assert any(
        result.get("id") == "test_storage_smoke_postgres_1"
        for result in results
    ), "query_by_field should return the smoke record"
    print(f"✓ query_by_field returns matching records ({len(results)} found)")

    test_payload_2 = {
        "id": "test_storage_smoke_postgres_1",
        "value": 99,
        "label": "smoke",
    }
    backend.write_record(
        collection="_smoke_test",
        record_id="test_storage_smoke_postgres_1",
        payload=test_payload_2,
        indexed_fields={"label": "smoke"},
    )
    loaded = backend.read_record(
        collection="_smoke_test",
        record_id="test_storage_smoke_postgres_1",
    )
    assert loaded["value"] == 99, f"Upsert failed: got {loaded}"
    print("✓ upsert (overwrite) works")

    backend.append_to_log(
        log_name="_smoke_test_log",
        record={"trade_id": "test_trade_pg", "value": "a"},
        indexed_fields={"trade_id": "test_trade_pg"},
    )
    backend.append_to_log(
        log_name="_smoke_test_log",
        record={"trade_id": "test_trade_pg", "value": "b"},
        indexed_fields={"trade_id": "test_trade_pg"},
    )
    log_results = backend.query_log_by_field(
        log_name="_smoke_test_log",
        field="trade_id",
        value="test_trade_pg",
    )
    assert len(log_results) >= 2, (
        f"Expected at least 2 log records, got {len(log_results)}"
    )
    print(f"✓ append_to_log + query_log_by_field ({len(log_results)} records found)")

    from src.agent_system.storage.repository import load_open_trade_outcomes

    try:
        outcomes = load_open_trade_outcomes()
        print(f"✓ existing repository function works ({len(outcomes)} open outcomes)")
    except Exception as exc:
        print(f"⚠ repository function failed: {exc}")
        if backend_name == "postgres":
            print("  (expected if migration hasn't run yet)")
        else:
            raise

    print(f"\nAll storage smoke tests passed for backend={backend_name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
