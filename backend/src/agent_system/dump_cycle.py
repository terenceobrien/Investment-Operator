"""
Dump all records for a specific cycle from the Postgres backend.

psycopg3-native version. Uses psycopg.rows.dict_row instead of the deprecated
psycopg2.extras.RealDictCursor.

Usage:
    cd /Users/terenceobrien/AI_Financial_Operator/backend
    python3 dump_cycle.py 8b1dcfdb-1dd2-4ccf-8afa-be2ab2dae01e
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("psycopg (v3) not installed. Run: pip install 'psycopg[binary]'")
    sys.exit(1)


def fetch_decision_log(conn, cycle_id: str) -> list[dict]:
    """Pull decision_log entries for this cycle. Tries common table names."""
    candidate_tables = ["decision_log", "decision_log_entries", "decisions"]
    for table in candidate_tables:
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE cycle_id = %s ORDER BY created_at",
                    (cycle_id,),
                )
                rows = cur.fetchall()
                print(f"Found {len(rows)} entries in `{table}`")
                return rows
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            continue
        except psycopg.errors.UndefinedColumn:
            conn.rollback()
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(f"SELECT * FROM {table} LIMIT 5")
                    sample = cur.fetchall()
                    print(f"Table `{table}` exists but no cycle_id column.")
                    if sample:
                        print(f"  Columns: {list(sample[0].keys())}")
            except Exception:
                conn.rollback()
            continue

    print("Could not find decision_log table. Listing public tables:")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        for row in cur.fetchall():
            print(f"  - {row['table_name']}")
    return []


def fetch_schema_record(conn, record_id: str) -> dict | None:
    """Pull a single schema record. Tries schema_records then dedicated tables."""
    candidate_tables = ["schema_records", "trade_ideas", "schemas"]
    for table in candidate_tables:
        try:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(f"SELECT * FROM {table} WHERE id = %s", (record_id,))
                row = cur.fetchone()
                if row is not None:
                    return row
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            continue
        except Exception:
            conn.rollback()
            continue
    return None


def main(cycle_id: str) -> int:
    load_dotenv()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set in environment or .env file.")
        return 1

    print("Connecting to Postgres...")
    with psycopg.connect(database_url) as conn:
        print(f"Looking up cycle {cycle_id}")
        print()

        decisions = fetch_decision_log(conn, cycle_id)
        if not decisions:
            print("No decisions found. The cycle may not have written to this database,")
            print("or the table layout is different than expected.")
            return 1

        print()
        print("=" * 70)
        print(f"Decisions for cycle {cycle_id}")
        print("=" * 70)
        print(f"  {'TICKER':<8} {'DECISION':<10} {'CONVICTION':<10} TRADE_ID")
        for row in decisions:
            ticker = row.get("candidate") or row.get("ticker") or "?"
            decision = row.get("decision") or "?"
            conv = row.get("conviction_rating") or "?"
            trade_id = row.get("trade_idea_id") or row.get("trade_id") or "n/a"
            print(f"  {ticker:<8} {decision:<10} {conv:<10} {trade_id}")

        trade_ids = [
            row.get("trade_idea_id") or row.get("trade_id")
            for row in decisions
        ]
        trade_ids = [tid for tid in trade_ids if tid]
        print()
        print(f"Pulling {len(trade_ids)} trade ideas...")
        trades = {}
        for tid in trade_ids:
            record = fetch_schema_record(conn, tid)
            if record:
                trades[tid] = record
        print(f"Retrieved {len(trades)} records")
        print()

        print("=" * 70)
        print("Which priority surfaced each accepted ticker?")
        print("=" * 70)
        for row in decisions:
            if row.get("decision") != "accepted":
                continue
            ticker = row.get("candidate") or row.get("ticker")
            trade = trades.get(row.get("trade_idea_id") or row.get("trade_id"))
            if not trade:
                print(f"  {ticker:<8} <- record not found")
                continue
            payload = trade.get("payload_json")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}
            priority = (payload or {}).get("research_priority", {})
            theme = priority.get("theme", "?")[:80]
            print(f"  {ticker:<8} <- {theme}")

        print()
        print("=" * 70)
        print("Rejection reasons for non-accepted candidates")
        print("=" * 70)
        for row in decisions:
            if row.get("decision") == "accepted":
                continue
            ticker = row.get("candidate") or row.get("ticker")
            summary = (row.get("summary") or "")[:100]
            rule = row.get("rule_applied") or row.get("weakest_link") or "?"
            print(f"  {ticker:<8} {rule:<22} {summary}")

        output_path = Path(f"cycle_dump_{cycle_id}.json")
        payload = {
            "cycle_id": cycle_id,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "decision_log_entries": decisions,
            "trade_ideas": list(trades.values()),
        }
        output_path.write_text(json.dumps(payload, indent=2, default=str))
        print()
        print(f"Full dump written to: {output_path.resolve()}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 dump_cycle.py <cycle_id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))