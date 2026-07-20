"""Postgres backend implementation for the StorageBackend abstraction.

Connects via DATABASE_URL environment variable. Uses psycopg v3.
Tables are defined in postgres_schema.sql (apply once via init_schema).

Routing:
- Known collection names route to their dedicated tables.
- Unknown collection names route to the generic_records catch-all.
- Same pattern for logs (dedicated tables for price_points/decision_log,
  catch-all in generic_log_entries).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from src.agent_system.storage.backend import StorageBackend


logger = logging.getLogger(__name__)

REPLACE_EXISTING_BY = "__replace_existing_by__"
MATCH_ALL_LOG_RECORDS = "*"


DEDICATED_COLLECTIONS = {
    "schema_records",
    "trade_outcomes",
    "regime_states",
    "portfolio_plans",
    "trade_ideas",
    "trade_scenario_analyses",
    "macro_forecast_results",
    "historical_calibration_results",
    "monte_carlo_results",
    "convictions",
    "fundamental_analyses",
    "narrative_analyses",
    "thematic_maps",
    "research_priorities",
    "positions_snapshots",
    "scenario_sets",
    "clarification_requests",
    "fundamental_screens",
}

DEDICATED_LOGS = {
    "price_points",
    "decision_log",
    "decision_log_entries",
}

LOG_TABLE_MAP = {
    "price_points": "price_points",
    "decision_log": "decision_log_entries",
    "decision_log_entries": "decision_log_entries",
}

COLLECTION_COLUMN_MAP = {
    "schema_records": ["schema_type", "asof_date", "ticker", "source_id"],
    "trade_outcomes": ["cycle_id", "underlying", "status"],
    "regime_states": ["asof_date"],
    "portfolio_plans": ["cycle_id"],
    "trade_ideas": ["underlying"],
    "trade_scenario_analyses": ["trade_id"],
    "macro_forecast_results": ["asof_date"],
    "historical_calibration_results": ["asof_date"],
    "monte_carlo_results": ["cycle_id"],
    "fundamental_analyses": ["ticker"],
    "narrative_analyses": ["ticker"],
    "fundamental_screens": ["ticker"],
}

LOG_COLUMN_MAP = {
    "price_points": ["trade_id", "asof_date"],
    "decision_log": ["cycle_id", "candidate"],
    "decision_log_entries": ["cycle_id", "candidate"],
}


class PostgresBackend(StorageBackend):
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        if not self.dsn:
            raise RuntimeError(
                "PostgresBackend requires DATABASE_URL env var or explicit dsn argument."
            )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        logger.info("PostgresBackend initialized successfully")

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.dsn)

    def write_record(
        self,
        *,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        indexed_fields = self._clean_indexed_fields(indexed_fields or {})
        if collection in DEDICATED_COLLECTIONS:
            self._write_dedicated_record(collection, record_id, payload, indexed_fields)
        else:
            self._write_generic_record(collection, record_id, payload, indexed_fields)

    def _write_dedicated_record(
        self,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        indexed_fields: dict[str, Any],
    ) -> None:
        indexed_columns = [
            column
            for column in COLLECTION_COLUMN_MAP.get(collection, [])
            if column in indexed_fields
        ]
        insert_columns = ["record_id", *indexed_columns, "payload"]
        placeholders = ", ".join(["%s"] * len(insert_columns))
        update_columns = [*indexed_columns, "payload"]
        update_set = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in update_columns
        )
        sql = f"""
            INSERT INTO {collection} ({", ".join(insert_columns)})
            VALUES ({placeholders})
            ON CONFLICT (record_id) DO UPDATE
            SET {update_set},
                updated_at = NOW()
        """
        params = [
            record_id,
            *(indexed_fields[column] for column in indexed_columns),
            Jsonb(payload),
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
            conn.commit()

    def _write_generic_record(
        self,
        collection: str,
        record_id: str,
        payload: dict[str, Any],
        indexed_fields: dict[str, Any],
    ) -> None:
        sql = """
            INSERT INTO generic_records (
                collection, record_id, payload, indexed_fields, updated_at
            )
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (collection, record_id) DO UPDATE
            SET payload = EXCLUDED.payload,
                indexed_fields = EXCLUDED.indexed_fields,
                updated_at = NOW()
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (collection, record_id, Jsonb(payload), Jsonb(indexed_fields)),
                )
            conn.commit()

    def read_record(
        self,
        *,
        collection: str,
        record_id: str,
    ) -> Optional[dict[str, Any]]:
        if collection in DEDICATED_COLLECTIONS:
            sql = f"SELECT payload FROM {collection} WHERE record_id = %s"
            params: tuple[Any, ...] = (record_id,)
        else:
            sql = """
                SELECT payload FROM generic_records
                WHERE collection = %s AND record_id = %s
            """
            params = (collection, record_id)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
        return row[0] if row else None

    def read_all(self, *, collection: str) -> list[dict[str, Any]]:
        if collection in DEDICATED_COLLECTIONS:
            sql = f"SELECT payload FROM {collection} ORDER BY created_at"
            params: tuple[Any, ...] = ()
        else:
            sql = """
                SELECT payload FROM generic_records
                WHERE collection = %s
                ORDER BY created_at
            """
            params = (collection,)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [row[0] for row in rows]

    def query_by_field(
        self,
        *,
        collection: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        if collection in DEDICATED_COLLECTIONS:
            if field in COLLECTION_COLUMN_MAP.get(collection, []):
                sql = (
                    f"SELECT payload FROM {collection} "
                    f"WHERE {field} = %s ORDER BY created_at"
                )
                params: tuple[Any, ...] = (value,)
            else:
                sql = (
                    f"SELECT payload FROM {collection} "
                    "WHERE payload->>%s = %s ORDER BY created_at"
                )
                params = (field, str(value))
        else:
            sql = """
                SELECT payload FROM generic_records
                WHERE collection = %s
                  AND (indexed_fields->>%s = %s OR payload->>%s = %s)
                ORDER BY created_at
            """
            params = (collection, field, str(value), field, str(value))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [row[0] for row in rows]

    def append_to_log(
        self,
        *,
        log_name: str,
        record: dict[str, Any],
        indexed_fields: Optional[dict[str, Any]] = None,
    ) -> None:
        indexed_fields = indexed_fields or {}
        replace_fields = tuple(indexed_fields.get(REPLACE_EXISTING_BY, ()))
        stored_indexed_fields = self._clean_indexed_fields(indexed_fields)

        with self._connect() as conn:
            with conn.cursor() as cur:
                if replace_fields:
                    self._delete_matching_log_rows(
                        cur,
                        log_name=log_name,
                        record=record,
                        indexed_fields=stored_indexed_fields,
                        replace_fields=replace_fields,
                    )
                if log_name in DEDICATED_LOGS:
                    self._insert_dedicated_log(
                        cur,
                        log_name=log_name,
                        record=record,
                        indexed_fields=stored_indexed_fields,
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO generic_log_entries
                            (log_name, payload, indexed_fields)
                        VALUES (%s, %s, %s)
                        """,
                        (log_name, Jsonb(record), Jsonb(stored_indexed_fields)),
                    )
            conn.commit()

    def _insert_dedicated_log(
        self,
        cur,
        *,
        log_name: str,
        record: dict[str, Any],
        indexed_fields: dict[str, Any],
    ) -> None:
        table = self._log_table(log_name)
        columns = ["payload"]
        values: list[Any] = [Jsonb(record)]
        for column in LOG_COLUMN_MAP.get(log_name, []):
            if column in indexed_fields:
                columns.append(column)
                values.append(indexed_fields[column])
            elif column in record:
                columns.append(column)
                values.append(record[column])
        sql = f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({", ".join(["%s"] * len(columns))})
        """
        cur.execute(sql, values)

    def query_log_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        if log_name in DEDICATED_LOGS:
            table = self._log_table(log_name)
            if field == MATCH_ALL_LOG_RECORDS:
                sql = f"SELECT payload FROM {table} ORDER BY id"
                params: tuple[Any, ...] = ()
            elif field in LOG_COLUMN_MAP.get(log_name, []):
                sql = f"SELECT payload FROM {table} WHERE {field} = %s ORDER BY id"
                params = (value,)
            else:
                sql = f"SELECT payload FROM {table} WHERE payload->>%s = %s ORDER BY id"
                params = (field, str(value))
        else:
            if field == MATCH_ALL_LOG_RECORDS:
                sql = """
                    SELECT payload FROM generic_log_entries
                    WHERE log_name = %s
                    ORDER BY id
                """
                params = (log_name,)
            else:
                sql = """
                    SELECT payload FROM generic_log_entries
                    WHERE log_name = %s
                      AND (indexed_fields->>%s = %s OR payload->>%s = %s)
                    ORDER BY id
                """
                params = (log_name, field, str(value), field, str(value))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [row[0] for row in rows]

    def query_log_rows_by_field(
        self,
        *,
        log_name: str,
        field: str,
        value: Any,
    ) -> list[dict[str, Any]]:
        if log_name in DEDICATED_LOGS:
            table = self._log_table(log_name)
            if field == MATCH_ALL_LOG_RECORDS:
                sql = f"SELECT id, payload, created_at FROM {table} ORDER BY id"
                params: tuple[Any, ...] = ()
            elif field in LOG_COLUMN_MAP.get(log_name, []):
                sql = (
                    f"SELECT id, payload, created_at FROM {table} "
                    f"WHERE {field} = %s ORDER BY id"
                )
                params = (value,)
            else:
                sql = (
                    f"SELECT id, payload, created_at FROM {table} "
                    "WHERE payload->>%s = %s ORDER BY id"
                )
                params = (field, str(value))
        else:
            if field == MATCH_ALL_LOG_RECORDS:
                sql = """
                    SELECT id, payload, created_at FROM generic_log_entries
                    WHERE log_name = %s
                    ORDER BY id
                """
                params = (log_name,)
            else:
                sql = """
                    SELECT id, payload, created_at FROM generic_log_entries
                    WHERE log_name = %s
                      AND (indexed_fields->>%s = %s OR payload->>%s = %s)
                    ORDER BY id
                """
                params = (log_name, field, str(value), field, str(value))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "payload": row[1],
                "created_at": row[2],
            }
            for row in rows
        ]

    def _delete_matching_log_rows(
        self,
        cur,
        *,
        log_name: str,
        record: dict[str, Any],
        indexed_fields: dict[str, Any],
        replace_fields: tuple[str, ...],
    ) -> None:
        if log_name in DEDICATED_LOGS:
            table = self._log_table(log_name)
            clauses: list[str] = []
            params: list[Any] = []
            for field in replace_fields:
                value = indexed_fields.get(field, record.get(field))
                if field in LOG_COLUMN_MAP.get(log_name, []):
                    clauses.append(f"{field} = %s")
                    params.append(value)
                else:
                    clauses.append("payload->>%s = %s")
                    params.extend([field, str(value)])
            cur.execute(f"DELETE FROM {table} WHERE {' AND '.join(clauses)}", params)
            return

        clauses = ["log_name = %s"]
        params = [log_name]
        for field in replace_fields:
            value = indexed_fields.get(field, record.get(field))
            clauses.append("(indexed_fields->>%s = %s OR payload->>%s = %s)")
            params.extend([field, str(value), field, str(value)])
        cur.execute(
            f"DELETE FROM generic_log_entries WHERE {' AND '.join(clauses)}",
            params,
        )

    def _log_table(self, log_name: str) -> str:
        return LOG_TABLE_MAP[log_name]

    def _clean_indexed_fields(self, indexed_fields: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in indexed_fields.items()
            if key != REPLACE_EXISTING_BY
        }


def init_schema(dsn: Optional[str] = None) -> None:
    """Apply postgres_schema.sql to the database. Idempotent and safe to re-run."""

    dsn = dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("init_schema requires DATABASE_URL or explicit dsn argument.")

    schema_path = Path(__file__).parent / "postgres_schema.sql"
    sql = schema_path.read_text(encoding="utf-8")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    logger.info("Schema applied successfully to %s", dsn.split("@")[-1])
