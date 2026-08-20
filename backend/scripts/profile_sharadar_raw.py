#!/usr/bin/env python3
"""
Profile raw Sharadar bulk CSVs without loading giant files into Python memory.

This script is intentionally read-only with respect to backend/data/sharadar/raw.
It uses DuckDB to stream CSV scans directly from disk and writes compact Markdown,
JSON, and small sample CSV artifacts that describe what is actually present in a
local Sharadar bulk download.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT / "data" / "sharadar" / "raw"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "sharadar" / "profile"

MB = 1024 * 1024
GB = 1024 * MB
SMALL_EXACT_BYTES = 250 * MB
DEFAULT_SAMPLE_PROFILE_ROWS = 100_000
HEADER_SCAN_ROWS = 10_000
ROW_ESTIMATE_SAMPLE_ROWS = 25_000

LIKELY_ID_COLUMNS = {
    "ticker",
    "permaticker",
    "investorid",
    "ownerid",
    "securityid",
    "companyid",
    "date",
    "dimension",
}

CATEGORICAL_COLUMNS = {
    "table",
    "dimension",
    "action",
    "status",
    "sector",
    "industry",
    "exchange",
    "category",
    "type",
    "event",
    "eventtype",
    "transactioncode",
    "transactiontype",
    "isdelisted",
}

DATE_HINTS = (
    "date",
    "updated",
    "period",
    "quarter",
    "firstprice",
    "lastprice",
)

PRICE_FIELD_HINTS = (
    "open",
    "high",
    "low",
    "close",
    "closeadj",
    "adjclose",
    "adjusted",
    "closeunadj",
    "volume",
    "dividend",
    "split",
    "lastupdated",
)

TABLE_KEY_CANDIDATES: dict[str, list[list[str]]] = {
    "SEP": [["ticker", "date"]],
    "SFP": [["ticker", "date"]],
    "DAILY": [["ticker", "date"], ["permaticker", "date"]],
    "SP500": [["ticker", "date", "action"], ["ticker", "date"], ["ticker", "calendardate"]],
    "TICKERS": [["ticker"], ["permaticker"]],
    "SF1": [
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod"],
        ["ticker", "dimension", "datekey"],
        ["permaticker", "dimension", "datekey"],
    ],
    "SF2": [
        ["ticker", "filingdate", "transactiondate", "ownername", "transactioncode"],
        ["permaticker", "filingdate", "transactiondate", "ownername", "transactioncode"],
    ],
    "SF3": [["investorid", "permaticker", "calendardate"], ["investorid", "ticker", "calendardate"]],
    "SF3A": [["investorid", "permaticker", "calendardate"], ["investorid", "ticker", "calendardate"]],
    "SF3B": [["investorid", "permaticker", "calendardate"], ["investorid", "ticker", "calendardate"]],
    "EVENTS": [["ticker", "date", "event"], ["ticker", "date", "eventtype"], ["ticker", "date"]],
    "ACTIONS": [["ticker", "date", "action"], ["ticker", "action", "date"]],
    "METRICS": [["ticker"], ["permaticker"], ["ticker", "date"]],
    "INDICATORS": [["table", "indicator"], ["table", "field"], ["code"]],
}


@dataclass
class StepTimer:
    name: str
    seconds: float


@dataclass
class TableProfile:
    table: str
    file_name: str
    path: str
    size_bytes: int
    size_human: str
    columns: list[str] = field(default_factory=list)
    schema: list[dict[str, Any]] = field(default_factory=list)
    first_rows: list[dict[str, Any]] = field(default_factory=list)
    last_rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: dict[str, Any] = field(default_factory=dict)
    nulls: list[dict[str, Any]] = field(default_factory=list)
    distinct_counts: dict[str, Any] = field(default_factory=dict)
    duplicate_checks: list[dict[str, Any]] = field(default_factory=list)
    date_ranges: dict[str, Any] = field(default_factory=dict)
    categorical_values: dict[str, Any] = field(default_factory=dict)
    sample_csv: str | None = None
    table_specific: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    step_timings: list[StepTimer] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    success: bool = True
    error: str | None = None


@contextmanager
def timed_step(profile: TableProfile, name: str) -> Iterable[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        profile.step_timings.append(StepTimer(name, round(time.perf_counter() - started, 3)))


def require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "DuckDB is required for this profiler. Install it with "
            "`python3 -m pip install duckdb` or install backend/requirements.txt."
        ) from exc
    return duckdb


def human_size(size_bytes: int) -> str:
    if size_bytes >= GB:
        return f"{size_bytes / GB:.2f} GB"
    if size_bytes >= MB:
        return f"{size_bytes / MB:.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def normalize_col(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def table_name_from_path(path: Path) -> str:
    match = re.match(r"SHARADAR_([A-Z0-9]+)(?:_|$)", path.name.upper())
    if match:
        return match.group(1)
    return path.stem.upper()


def safe_view_name(index: int, table: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", table.lower())
    return f"raw_profile_{index}_{clean}"


def read_csv_expr(path: Path, infer_sample_rows: int, all_varchar: bool = False) -> str:
    return (
        "read_csv_auto("
        f"{sql_literal(str(path))}, "
        "header=true, "
        f"sample_size={infer_sample_rows}, "
        "ignore_errors=true, "
        "union_by_name=false, "
        f"all_varchar={'true' if all_varchar else 'false'}"
        ")"
    )


def query_dicts(con: Any, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_scalar(con: Any, sql: str) -> Any:
    row = con.execute(sql).fetchone()
    if row is None:
        return None
    return row[0]


def json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def read_header(path: Path) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            row = next(csv.reader(fh), [])
    except UnicodeDecodeError as exc:
        issues.append(f"UTF-8 decode issue while reading header: {exc}")
        with path.open("r", encoding="latin-1", newline="") as fh:
            row = next(csv.reader(fh), [])
    except StopIteration:
        row = []

    if not row:
        issues.append("CSV header is empty.")
        return row, issues

    blank_positions = [str(i + 1) for i, col in enumerate(row) if not str(col).strip()]
    if blank_positions:
        issues.append(f"Blank column names at positions: {', '.join(blank_positions)}")

    seen: dict[str, int] = {}
    duplicates: list[str] = []
    for col in row:
        seen[col] = seen.get(col, 0) + 1
        if seen[col] == 2:
            duplicates.append(col)
    if duplicates:
        issues.append(f"Duplicate header names: {', '.join(duplicates)}")

    return row, issues


def scan_shape_issues(path: Path, expected_columns: int, max_rows: int = HEADER_SCAN_ROWS) -> list[str]:
    issues: list[str] = []
    if expected_columns <= 0:
        return issues
    inconsistent = 0
    duplicate_header_rows = 0
    rows_seen = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            for row in reader:
                rows_seen += 1
                if len(row) != expected_columns:
                    inconsistent += 1
                if row == header:
                    duplicate_header_rows += 1
                if rows_seen >= max_rows:
                    break
    except UnicodeDecodeError as exc:
        issues.append(f"UTF-8 decode issue in first {max_rows:,} rows: {exc}")
    except csv.Error as exc:
        issues.append(f"CSV parsing issue in first {max_rows:,} rows: {exc}")

    if inconsistent:
        issues.append(
            f"{inconsistent:,} of first {rows_seen:,} sampled rows had a column count "
            f"different from the header ({expected_columns})."
        )
    if duplicate_header_rows:
        issues.append(f"{duplicate_header_rows:,} duplicate header rows found in first {rows_seen:,} sampled rows.")
    return issues


def estimate_row_count_from_bytes(path: Path, sample_rows: int = ROW_ESTIMATE_SAMPLE_ROWS) -> dict[str, Any]:
    size = path.stat().st_size
    try:
        with path.open("rb") as fh:
            header = fh.readline()
            total_bytes = 0
            rows = 0
            while rows < sample_rows:
                line = fh.readline()
                if not line:
                    break
                rows += 1
                total_bytes += len(line)
    except OSError as exc:
        return {"value": None, "method": "estimate_failed", "error": str(exc)}

    if rows == 0:
        return {"value": 0, "method": "exact_empty_or_header_only"}

    avg_bytes = total_bytes / rows
    estimated = max(0, round((size - len(header)) / avg_bytes))
    return {
        "value": estimated,
        "method": f"estimated_from_first_{rows}_rows",
        "sample_rows": rows,
        "average_data_row_bytes": round(avg_bytes, 2),
    }


def exact_row_count(con: Any, view: str) -> int:
    return int(query_scalar(con, f"SELECT COUNT(*) FROM {quote_ident(view)}") or 0)


def lower_column_map(columns: Iterable[str]) -> dict[str, str]:
    return {normalize_col(col): col for col in columns}


def find_col(columns: Iterable[str], wanted: str) -> str | None:
    return lower_column_map(columns).get(normalize_col(wanted))


def existing_cols(columns: Iterable[str], wanted: Iterable[str]) -> list[str]:
    mapping = lower_column_map(columns)
    found: list[str] = []
    for name in wanted:
        col = mapping.get(normalize_col(name))
        if col is not None and col not in found:
            found.append(col)
    return found


def is_date_column(column: str) -> bool:
    name = normalize_col(column)
    return any(hint in name for hint in DATE_HINTS)


def date_cast_expr(column: str) -> str:
    quoted = quote_ident(column)
    as_text = f"CAST({quoted} AS VARCHAR)"
    return (
        "COALESCE("
        f"TRY_CAST({quoted} AS DATE), "
        f"CAST(try_strptime({as_text}, '%Y%m%d') AS DATE), "
        f"CAST(try_strptime({as_text}, '%Y-%m-%d') AS DATE)"
        ")"
    )


def scope_sql(view: str, full_scope: bool, sample_rows: int) -> str:
    if full_scope:
        return quote_ident(view)
    return f"(SELECT * FROM {quote_ident(view)} LIMIT {sample_rows}) AS sampled_scope"


def profile_scope_label(full_scope: bool, sample_rows: int) -> str:
    return "exact_full_table" if full_scope else f"sample_first_{sample_rows}_rows"


def calculate_nulls(
    con: Any,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> list[dict[str, Any]]:
    if not columns:
        return []
    source = scope_sql(view, full_scope, sample_rows)
    count_sql = f"SELECT COUNT(*) AS row_count FROM {source}"
    denominator = int(query_scalar(con, count_sql) or 0)
    if denominator == 0:
        return [
            {"column": col, "null_count": 0, "null_pct": None, "scope": profile_scope_label(full_scope, sample_rows)}
            for col in columns
        ]

    chunks: list[list[str]] = [columns[i : i + 80] for i in range(0, len(columns), 80)]
    by_column: dict[str, int] = {}
    for chunk in chunks:
        parts = [
            f"SUM(CASE WHEN {quote_ident(col)} IS NULL THEN 1 ELSE 0 END) AS {quote_ident(col)}"
            for col in chunk
        ]
        row = query_dicts(con, f"SELECT {', '.join(parts)} FROM {source}")[0]
        for col, value in row.items():
            by_column[col] = int(value or 0)

    return [
        {
            "column": col,
            "null_count": by_column.get(col, 0),
            "null_pct": round((by_column.get(col, 0) / denominator) * 100, 4),
            "profiled_rows": denominator,
            "scope": profile_scope_label(full_scope, sample_rows),
        }
        for col in columns
    ]


def distinct_count(
    con: Any,
    view: str,
    column: str,
    full_scope: bool,
    sample_rows: int,
    where_sql: str | None = None,
) -> dict[str, Any]:
    source = scope_sql(view, full_scope, sample_rows)
    where = f" WHERE {where_sql}" if where_sql else ""
    value = query_scalar(con, f"SELECT COUNT(DISTINCT {quote_ident(column)}) FROM {source}{where}")
    return {
        "column": column,
        "distinct_count": int(value or 0),
        "scope": profile_scope_label(full_scope, sample_rows),
    }


def value_counts(
    con: Any,
    view: str,
    column: str,
    full_scope: bool,
    sample_rows: int,
    limit: int = 10,
    where_sql: str | None = None,
) -> list[dict[str, Any]]:
    source = scope_sql(view, full_scope, sample_rows)
    quoted = quote_ident(column)
    where = f" WHERE {where_sql}" if where_sql else ""
    sql = (
        f"SELECT CAST({quoted} AS VARCHAR) AS value, COUNT(*) AS row_count "
        f"FROM {source}{where} "
        f"GROUP BY 1 ORDER BY row_count DESC NULLS LAST, value LIMIT {limit}"
    )
    return query_dicts(con, sql)


def calculate_date_range(
    con: Any,
    view: str,
    column: str,
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    source = scope_sql(view, full_scope, sample_rows)
    expr = date_cast_expr(column)
    sql = (
        f"SELECT MIN({expr}) AS min_date, MAX({expr}) AS max_date, "
        f"COUNT({expr}) AS parsed_rows, COUNT(*) AS profiled_rows "
        f"FROM {source}"
    )
    try:
        row = query_dicts(con, sql)[0]
    except Exception:
        quoted = quote_ident(column)
        fallback_expr = f"TRY_CAST({quoted} AS DATE)"
        row = query_dicts(
            con,
            f"SELECT MIN({fallback_expr}) AS min_date, MAX({fallback_expr}) AS max_date, "
            f"COUNT({fallback_expr}) AS parsed_rows, COUNT(*) AS profiled_rows FROM {source}",
        )[0]
    row["scope"] = profile_scope_label(full_scope, sample_rows)
    return row


def duplicate_count_for_key(
    con: Any,
    view: str,
    key_columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    source = scope_sql(view, full_scope, sample_rows)
    keys = ", ".join(quote_ident(col) for col in key_columns)
    not_null = " AND ".join(f"{quote_ident(col)} IS NOT NULL" for col in key_columns)
    sql = (
        "SELECT COALESCE(SUM(cnt - 1), 0) AS duplicate_rows, COUNT(*) AS duplicate_keys "
        f"FROM (SELECT {keys}, COUNT(*) AS cnt FROM {source} "
        f"WHERE {not_null} GROUP BY {keys} HAVING COUNT(*) > 1)"
    )
    row = query_dicts(con, sql)[0]
    row.update({"key": key_columns, "scope": profile_scope_label(full_scope, sample_rows)})
    return row


def infer_key_candidates(table: str, columns: list[str]) -> list[list[str]]:
    mapping = lower_column_map(columns)
    candidates = TABLE_KEY_CANDIDATES.get(table.upper(), [])
    found: list[list[str]] = []
    for candidate in candidates:
        actual = [mapping.get(normalize_col(col)) for col in candidate]
        if all(actual):
            actual_clean = [col for col in actual if col is not None]
            if actual_clean not in found:
                found.append(actual_clean)
    if found:
        return found

    generic: list[str] = []
    for name in ("ticker", "permaticker", "investorid", "date", "dimension"):
        col = mapping.get(normalize_col(name))
        if col:
            generic.append(col)
    return [generic] if len(generic) >= 2 else []


def representative_distincts(
    con: Any,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in columns:
        if normalize_col(col) in CATEGORICAL_COLUMNS:
            try:
                result[col] = value_counts(con, view, col, full_scope, sample_rows)
            except Exception as exc:
                result[col] = {"error": str(exc)}
    return result


def likely_identifier_distincts(
    con: Any,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for col in columns:
        if normalize_col(col) in LIKELY_ID_COLUMNS:
            try:
                result[col] = distinct_count(con, view, col, full_scope, sample_rows)
            except Exception as exc:
                result[col] = {"error": str(exc)}
    return result


def detect_sort_order(rows: list[dict[str, Any]], ticker_col: str, date_col: str) -> dict[str, Any]:
    pairs = [
        (str(row.get(ticker_col) or ""), str(row.get(date_col) or ""))
        for row in rows
        if row.get(ticker_col) is not None and row.get(date_col) is not None
    ]
    if len(pairs) < 2:
        return {"sampled_rows": len(pairs), "ticker_date_sorted": None, "date_ticker_sorted": None}
    ticker_date_sorted = all(pairs[i] <= pairs[i + 1] for i in range(len(pairs) - 1))
    date_pairs = [(d, t) for t, d in pairs]
    date_ticker_sorted = all(date_pairs[i] <= date_pairs[i + 1] for i in range(len(date_pairs) - 1))
    return {
        "sampled_rows": len(pairs),
        "ticker_date_sorted": ticker_date_sorted,
        "date_ticker_sorted": date_ticker_sorted,
    }


def filter_example_rows(
    con: Any,
    view: str,
    column: str,
    contains: list[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    quoted = quote_ident(column)
    clauses = [f"LOWER(CAST({quoted} AS VARCHAR)) LIKE {sql_literal('%' + item.lower() + '%')}" for item in contains]
    sql = f"SELECT * FROM {quote_ident(view)} WHERE {' OR '.join(clauses)} LIMIT {limit}"
    return query_dicts(con, sql)


def run_specific_checks(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    dispatch = {
        "SEP": profile_sep,
        "SP500": profile_sp500,
        "TICKERS": profile_tickers,
        "SFP": profile_sfp,
        "SF1": profile_sf1,
        "DAILY": profile_daily,
        "SF2": profile_sf2,
        "SF3": profile_sf3_family,
        "SF3A": profile_sf3_family,
        "SF3B": profile_sf3_family,
        "EVENTS": profile_events,
        "ACTIONS": profile_actions,
        "METRICS": profile_metrics,
        "INDICATORS": profile_indicators,
    }
    func = dispatch.get(table.upper())
    if not func:
        return {}
    try:
        return func(con, table, view, columns, full_scope, sample_rows)
    except Exception as exc:
        return {"error": str(exc)}


def profile_sep(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    ticker_col = find_col(columns, "ticker")
    date_col = find_col(columns, "date")
    checks: dict[str, Any] = {
        "inspected_fields": existing_cols(
            columns,
            [
                "ticker",
                "date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "dividends",
                "closeunadj",
                "closeadj",
                "adjclose",
                "lastupdated",
            ],
        ),
        "price_columns_available": [col for col in columns if any(hint in normalize_col(col) for hint in PRICE_FIELD_HINTS)],
    }
    if ticker_col:
        checks["unique_tickers"] = distinct_count(con, view, ticker_col, full_scope, sample_rows)
    if date_col:
        checks["date_range"] = calculate_date_range(con, view, date_col, full_scope, sample_rows)
    if ticker_col and date_col:
        checks["duplicate_ticker_date"] = duplicate_count_for_key(con, view, [ticker_col, date_col], full_scope, sample_rows)
        sample_pairs = query_dicts(
            con,
            f"SELECT {quote_ident(ticker_col)}, {quote_ident(date_col)} FROM {quote_ident(view)} LIMIT 5000",
        )
        checks["sort_order_sample"] = detect_sort_order(sample_pairs, ticker_col, date_col)
        tickers = [
            row["value"]
            for row in value_counts(con, view, ticker_col, full_scope, sample_rows, limit=5)
            if row.get("value") is not None
        ]
        if tickers:
            in_list = ", ".join(sql_literal(str(ticker)) for ticker in tickers)
            checks["first_last_date_by_sample_ticker"] = query_dicts(
                con,
                f"SELECT CAST({quote_ident(ticker_col)} AS VARCHAR) AS ticker, "
                f"MIN({date_cast_expr(date_col)}) AS first_date, "
                f"MAX({date_cast_expr(date_col)}) AS last_date, COUNT(*) AS rows "
                f"FROM {quote_ident(view)} WHERE CAST({quote_ident(ticker_col)} AS VARCHAR) IN ({in_list}) "
                f"GROUP BY 1 ORDER BY 1",
            )
    checks["delisted_presence_inferable_from_sep"] = any(
        normalize_col(col) in {"isdelisted", "lastpricedate"} for col in columns
    )
    return checks


def profile_sp500(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {"columns": columns}
    ticker_col = find_col(columns, "ticker")
    if ticker_col:
        checks["unique_tickers"] = distinct_count(con, view, ticker_col, full_scope, sample_rows)
    for name in ("action", "status"):
        col = find_col(columns, name)
        if col:
            checks[f"{col}_values"] = value_counts(con, view, col, full_scope, sample_rows, limit=20)
            checks[f"{col}_addition_examples"] = filter_example_rows(con, view, col, ["add", "addition", "current"], 5)
            checks[f"{col}_deletion_examples"] = filter_example_rows(con, view, col, ["delete", "removal", "removed"], 5)
    checks["date_fields"] = {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)}
    keys = infer_key_candidates(table, columns)
    checks["duplicate_behavior"] = [
        duplicate_count_for_key(con, view, key, full_scope, sample_rows) for key in keys
    ]
    action_col = find_col(columns, "action")
    status_col = find_col(columns, "status")
    date_cols = [col for col in columns if is_date_column(col)]
    if action_col and date_cols:
        checks["likely_historical_membership_logic"] = (
            "Schema has an action-like field and date-like field(s); reconstructing membership likely "
            "requires replaying local additions/deletions rather than treating rows as one static list."
        )
    elif status_col and date_cols:
        checks["likely_historical_membership_logic"] = (
            "Schema has status-like and date-like fields; inspect distinct status values to determine "
            "whether rows are snapshots, events, or both."
        )
    else:
        checks["likely_historical_membership_logic"] = (
            "No clear action/status plus date structure was detected from the actual schema."
        )
    return checks


def profile_tickers(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    fields = [
        "ticker",
        "permaticker",
        "table",
        "exchange",
        "category",
        "sector",
        "industry",
        "firstpricedate",
        "lastpricedate",
        "firstquarter",
        "lastquarter",
        "isdelisted",
    ]
    checks["requested_fields_present"] = existing_cols(columns, fields)
    checks["related_ticker_fields"] = [col for col in columns if "ticker" in normalize_col(col)]
    checks["total_securities"] = exact_row_count(con, view)

    table_col = find_col(columns, "table")
    if table_col:
        checks["table_counts"] = value_counts(con, view, table_col, True, sample_rows, limit=30)
        checks["sep_securities"] = int(
            query_scalar(
                con,
                f"SELECT COUNT(*) FROM {quote_ident(view)} "
                f"WHERE UPPER(CAST({quote_ident(table_col)} AS VARCHAR)) = 'SEP'",
            )
            or 0
        )
        checks["sfp_securities"] = int(
            query_scalar(
                con,
                f"SELECT COUNT(*) FROM {quote_ident(view)} "
                f"WHERE UPPER(CAST({quote_ident(table_col)} AS VARCHAR)) = 'SFP'",
            )
            or 0
        )
    delisted_col = find_col(columns, "isdelisted")
    if delisted_col:
        checks["delisted_counts"] = value_counts(con, view, delisted_col, True, sample_rows, limit=10)
        checks["delisted_securities"] = int(
            query_scalar(
                con,
                f"SELECT COUNT(*) FROM {quote_ident(view)} WHERE "
                f"LOWER(CAST({quote_ident(delisted_col)} AS VARCHAR)) IN ('y', 'yes', 'true', '1')",
            )
            or 0
        )
    for name in ("ticker", "permaticker"):
        col = find_col(columns, name)
        if col:
            checks[f"unique_{name}s"] = distinct_count(con, view, col, True, sample_rows)
            checks[f"duplicate_{name}s"] = duplicate_count_for_key(con, view, [col], True, sample_rows)
    return checks


def profile_sfp(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "price_columns_available": [col for col in columns if any(hint in normalize_col(col) for hint in PRICE_FIELD_HINTS)]
    }
    ticker_col = find_col(columns, "ticker")
    date_col = find_col(columns, "date")
    if ticker_col:
        checks["unique_tickers"] = distinct_count(con, view, ticker_col, full_scope, sample_rows)
    if date_col:
        checks["date_range"] = calculate_date_range(con, view, date_col, full_scope, sample_rows)
    if ticker_col and date_col:
        checks["duplicate_ticker_date"] = duplicate_count_for_key(con, view, [ticker_col, date_col], full_scope, sample_rows)
        etfs = ["SPY", "QQQ", "IWM", "RSP"]
        in_list = ", ".join(sql_literal(item) for item in etfs)
        checks["major_etf_sample_rows"] = query_dicts(
            con,
            f"SELECT * FROM {quote_ident(view)} WHERE UPPER(CAST({quote_ident(ticker_col)} AS VARCHAR)) "
            f"IN ({in_list}) ORDER BY {quote_ident(ticker_col)}, {quote_ident(date_col)} DESC LIMIT 20",
        )
    return checks


def profile_sf1(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    dimension_col = find_col(columns, "dimension")
    ticker_col = find_col(columns, "ticker")
    if dimension_col:
        checks["dimensions_available"] = value_counts(con, view, dimension_col, full_scope, sample_rows, limit=30)
        examples: dict[str, Any] = {}
        for dimension in ("ARQ", "ART", "MRY", "MRT"):
            rows = query_dicts(
                con,
                f"SELECT * FROM {quote_ident(view)} WHERE UPPER(CAST({quote_ident(dimension_col)} AS VARCHAR)) = "
                f"{sql_literal(dimension)} LIMIT 3",
            )
            if rows:
                examples[dimension] = rows
        checks["dimension_example_rows"] = examples
    checks["date_fields"] = {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)}
    checks["identifier_fields"] = existing_cols(columns, ["ticker", "permaticker"])
    if ticker_col:
        checks["unique_tickers"] = distinct_count(con, view, ticker_col, full_scope, sample_rows)
    return checks


def profile_daily(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    id_cols = existing_cols(columns, ["ticker", "permaticker"])
    date_col = find_col(columns, "date")
    metric_columns = [col for col in columns if col not in id_cols and not is_date_column(col)]
    checks: dict[str, Any] = {
        "ticker_identifier_fields": id_cols,
        "daily_metric_columns": metric_columns,
    }
    if date_col:
        checks["date_range"] = calculate_date_range(con, view, date_col, full_scope, sample_rows)
    ticker_col = find_col(columns, "ticker") or find_col(columns, "permaticker")
    if ticker_col:
        checks["unique_ticker_count"] = distinct_count(con, view, ticker_col, full_scope, sample_rows)
    checks["duplicate_key_behavior"] = [
        duplicate_count_for_key(con, view, key, full_scope, sample_rows)
        for key in infer_key_candidates(table, columns)
    ]
    return checks


def profile_sf2(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    transaction_fields = [
        col
        for col in columns
        if any(token in normalize_col(col) for token in ("transaction", "trans", "code", "owner", "type"))
    ]
    checks: dict[str, Any] = {
        "ticker_identifier_fields": existing_cols(columns, ["ticker", "permaticker"]),
        "transaction_date_fields": [col for col in columns if is_date_column(col) and "transaction" in normalize_col(col)],
        "transaction_type_fields": transaction_fields,
        "primary_key_candidates": infer_key_candidates(table, columns),
        "date_fields": {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)},
    }
    checks["duplicate_key_behavior"] = [
        duplicate_count_for_key(con, view, key, full_scope, sample_rows)
        for key in checks["primary_key_candidates"]
    ]
    for col in transaction_fields[:5]:
        if normalize_col(col) in CATEGORICAL_COLUMNS or "code" in normalize_col(col) or "type" in normalize_col(col):
            checks[f"{col}_values"] = value_counts(con, view, col, full_scope, sample_rows, limit=20)
    return checks


def profile_sf3_family(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    investor_cols = [col for col in columns if "investor" in normalize_col(col)]
    ticker_cols = existing_cols(columns, ["ticker", "permaticker"])
    quarter_cols = [col for col in columns if "quarter" in normalize_col(col)]
    checks: dict[str, Any] = {
        "investor_identifier_fields": investor_cols,
        "ticker_identifier_fields": ticker_cols,
        "filing_calendar_date_fields": [col for col in columns if is_date_column(col)],
        "quarter_fields": quarter_cols,
        "primary_key_candidates": infer_key_candidates(table, columns),
        "date_fields": {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)},
    }
    investor_col = find_col(columns, "investorid") or (investor_cols[0] if investor_cols else None)
    if investor_col:
        checks["unique_investor_count"] = distinct_count(con, view, investor_col, full_scope, sample_rows)
    checks["duplicate_key_behavior"] = [
        duplicate_count_for_key(con, view, key, full_scope, sample_rows)
        for key in checks["primary_key_candidates"]
    ]
    return checks


def profile_events(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    event_cols = [col for col in columns if any(token in normalize_col(col) for token in ("event", "category", "type"))]
    checks: dict[str, Any] = {
        "event_date_fields": [col for col in columns if is_date_column(col)],
        "event_type_category_fields": event_cols,
        "ticker_identifier_fields": existing_cols(columns, ["ticker", "permaticker"]),
        "date_fields": {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)},
    }
    for col in event_cols:
        checks[f"{col}_values"] = value_counts(con, view, col, full_scope, sample_rows, limit=30)
    return checks


def profile_actions(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    action_cols = [col for col in columns if any(token in normalize_col(col) for token in ("action", "type", "category"))]
    checks: dict[str, Any] = {
        "action_type_fields": action_cols,
        "ticker_identifier_fields": existing_cols(columns, ["ticker", "permaticker"]),
        "effective_date_fields": [col for col in columns if is_date_column(col)],
        "date_fields": {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)},
    }
    for col in action_cols:
        checks[f"{col}_values"] = value_counts(con, view, col, full_scope, sample_rows, limit=30)
    return checks


def profile_metrics(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "date_fields": {col: calculate_date_range(con, view, col, full_scope, sample_rows) for col in columns if is_date_column(col)}
    }
    ticker_col = find_col(columns, "ticker")
    if ticker_col:
        checks["unique_tickers"] = distinct_count(con, view, ticker_col, True, sample_rows)
    date_cols = [col for col in columns if is_date_column(col)]
    distinct_dates: dict[str, Any] = {}
    for col in date_cols:
        distinct_dates[col] = distinct_count(con, view, col, full_scope, sample_rows)
    checks["distinct_date_counts"] = distinct_dates
    if not date_cols:
        checks["current_vs_historical_evidence"] = "No date-like fields detected; this looks more like current/latest metadata."
    else:
        max_dates = max((item.get("distinct_count", 0) for item in distinct_dates.values() if isinstance(item, dict)), default=0)
        if max_dates <= 5:
            checks["current_vs_historical_evidence"] = (
                "Only a small number of distinct date values detected in profiled scope; likely current/latest observations."
            )
        else:
            checks["current_vs_historical_evidence"] = (
                "Multiple distinct date values detected; this may contain historical observations."
            )
    return checks


def profile_indicators(
    con: Any,
    table: str,
    view: str,
    columns: list[str],
    full_scope: bool,
    sample_rows: int,
) -> dict[str, Any]:
    metadata_fields = [
        col
        for col in columns
        if any(
            token in normalize_col(col)
            for token in ("table", "field", "code", "name", "description", "unit", "key", "filter")
        )
    ]
    checks: dict[str, Any] = {
        "metadata_fields": metadata_fields,
        "representative_rows": query_dicts(con, f"SELECT * FROM {quote_ident(view)} LIMIT 20"),
    }
    for col in existing_cols(columns, ["table", "field", "code", "name", "indicator"]):
        checks[f"{col}_values"] = value_counts(con, view, col, True, sample_rows, limit=50)
    return checks


def make_sample_rows(
    con: Any,
    view: str,
    sample_size: int,
    full_profile: bool,
) -> list[dict[str, Any]]:
    first_count = min(sample_size, 25)
    rows = query_dicts(con, f"SELECT * FROM {quote_ident(view)} LIMIT {first_count}")
    if full_profile and len(rows) < sample_size:
        remaining = sample_size - len(rows)
        try:
            random_rows = query_dicts(
                con,
                f"SELECT * FROM {quote_ident(view)} USING SAMPLE reservoir({remaining} ROWS)",
            )
            rows.extend(random_rows)
        except Exception:
            pass
    return rows[:sample_size]


def write_sample_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: json_safe(row.get(col)) for col in columns})


def markdown_escape(value: Any, max_len: int = 120) -> str:
    if value is None:
        return ""
    text = str(json_safe(value))
    text = text.replace("\n", " ").replace("\r", " ").replace("|", "\\|")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def rows_to_markdown(rows: list[dict[str, Any]], columns: list[str] | None = None, max_rows: int = 10) -> str:
    if not rows:
        return "_No rows available._"
    if columns is None:
        columns = list(rows[0].keys())
    rows = rows[:max_rows]
    header = "| " + " | ".join(markdown_escape(col, 60) for col in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(markdown_escape(row.get(col), 80) for col in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def dict_to_markdown(value: Any, depth: int = 0) -> str:
    if value is None:
        return "_None._"
    if isinstance(value, list):
        if not value:
            return "_None._"
        if all(isinstance(item, dict) for item in value):
            columns: list[str] = []
            for item in value:
                for key in item.keys():
                    if key not in columns:
                        columns.append(key)
            return rows_to_markdown(value, columns=columns, max_rows=30)
        return "\n".join(f"- `{markdown_escape(item)}`" for item in value)
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"**{markdown_escape(key)}**")
                lines.append(dict_to_markdown(item, depth + 1))
            else:
                lines.append(f"- `{markdown_escape(key)}`: {markdown_escape(item)}")
        return "\n".join(lines) if lines else "_None._"
    return markdown_escape(value)


def build_markdown_report(profiles: list[TableProfile], raw_dir: Path, total_size: int) -> str:
    generated = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Sharadar Raw CSV Profile",
        "",
        f"Generated: `{generated}`",
        f"Raw directory: `{raw_dir}`",
        f"Total raw CSV size: `{human_size(total_size)}`",
        "",
        "## Summary",
        "",
    ]
    summary_rows = []
    for profile in profiles:
        date_min, date_max = primary_date_range(profile)
        summary_rows.append(
            {
                "Table": profile.table,
                "Size": profile.size_human,
                "Rows": row_count_label(profile.row_count),
                "Columns": len(profile.columns),
                "Unique tickers": unique_ticker_label(profile),
                "Date min": date_min or "",
                "Date max": date_max or "",
                "Issues": "; ".join(profile.issues[:3] + profile.warnings[:2]),
            }
        )
    lines.append(rows_to_markdown(summary_rows, columns=["Table", "Size", "Rows", "Columns", "Unique tickers", "Date min", "Date max", "Issues"], max_rows=200))
    lines.append("")

    for profile in profiles:
        lines.extend(
            [
                f"## {profile.table}",
                "",
                f"File: `{profile.file_name}`",
                f"Size: `{profile.size_bytes}` bytes (`{profile.size_human}`)",
                f"Rows: `{row_count_label(profile.row_count)}`",
                f"Columns: `{len(profile.columns)}`",
                f"Elapsed: `{profile.elapsed_seconds:.2f}s`",
                "",
            ]
        )
        if profile.error:
            lines.extend(["### Error", "", f"`{profile.error}`", ""])
            continue
        if profile.issues or profile.warnings:
            lines.extend(["### Issues And Warnings", ""])
            for item in profile.issues:
                lines.append(f"- {item}")
            for item in profile.warnings:
                lines.append(f"- Warning: {item}")
            lines.append("")

        lines.extend(["### Schema", ""])
        schema_rows = []
        nulls_by_col = {row["column"]: row for row in profile.nulls}
        for row in profile.schema:
            col = row.get("column_name") or row.get("Column") or row.get("column")
            null_row = nulls_by_col.get(str(col), {})
            schema_rows.append(
                {
                    "Column": col,
                    "Type": row.get("column_type") or row.get("Type") or row.get("type"),
                    "Null Count": null_row.get("null_count", ""),
                    "Null %": null_row.get("null_pct", ""),
                    "Null Scope": null_row.get("scope", ""),
                }
            )
        lines.append(rows_to_markdown(schema_rows, columns=["Column", "Type", "Null Count", "Null %", "Null Scope"], max_rows=300))
        lines.append("")

        lines.extend(["### First 5 Rows", "", rows_to_markdown(profile.first_rows, profile.columns, max_rows=5), ""])
        if profile.last_rows:
            lines.extend(["### Last 5 Rows", "", rows_to_markdown(profile.last_rows, profile.columns, max_rows=5), ""])
        else:
            lines.extend(["### Last 5 Rows", "", "_Skipped in fast mode or not inexpensive for this table._", ""])

        lines.extend(["### Date Coverage", "", dict_to_markdown(profile.date_ranges), ""])
        lines.extend(["### Identifier Distinct Counts", "", dict_to_markdown(profile.distinct_counts), ""])
        lines.extend(["### Categorical Values", "", dict_to_markdown(profile.categorical_values), ""])
        lines.extend(["### Duplicate Key Checks", "", dict_to_markdown(profile.duplicate_checks), ""])
        if profile.table_specific:
            lines.extend(["### Table-Specific Checks", "", dict_to_markdown(profile.table_specific), ""])
        if profile.sample_csv:
            lines.extend(["### Sample CSV", "", f"`{profile.sample_csv}`", ""])
        if profile.step_timings:
            timing_rows = [{"Step": t.name, "Seconds": t.seconds} for t in profile.step_timings]
            lines.extend(["### Timing", "", rows_to_markdown(timing_rows, columns=["Step", "Seconds"], max_rows=100), ""])

    return "\n".join(lines).rstrip() + "\n"


def row_count_label(row_count: dict[str, Any]) -> str:
    value = row_count.get("value")
    if value is None:
        return "unknown"
    method = row_count.get("method", "")
    prefix = "~" if str(method).startswith("estimated") else ""
    return f"{prefix}{int(value):,}"


def primary_date_range(profile: TableProfile) -> tuple[str | None, str | None]:
    preferred_names = ["date", "calendardate", "datekey", "lastupdated"]
    for wanted in preferred_names:
        col = find_col(profile.date_ranges.keys(), wanted)
        if col and isinstance(profile.date_ranges.get(col), dict):
            row = profile.date_ranges[col]
            return (markdown_escape(row.get("min_date")), markdown_escape(row.get("max_date")))
    for row in profile.date_ranges.values():
        if isinstance(row, dict):
            return (markdown_escape(row.get("min_date")), markdown_escape(row.get("max_date")))
    return (None, None)


def unique_ticker_label(profile: TableProfile) -> str:
    for key, item in profile.distinct_counts.items():
        if normalize_col(key) == "ticker" and isinstance(item, dict):
            value = item.get("distinct_count")
            if value is not None:
                prefix = "~" if str(item.get("scope", "")).startswith("sample") else ""
                return f"{prefix}{int(value):,}"
    for key in ("unique_tickers", "unique_ticker_count"):
        item = profile.table_specific.get(key)
        if isinstance(item, dict) and item.get("distinct_count") is not None:
            prefix = "~" if str(item.get("scope", "")).startswith("sample") else ""
            return f"{prefix}{int(item['distinct_count']):,}"
    return ""


def profile_file(
    con: Any,
    path: Path,
    index: int,
    sample_size: int,
    full_profile: bool,
    sample_profile_rows: int,
    output_dir: Path,
    infer_sample_rows: int,
) -> TableProfile:
    table = table_name_from_path(path)
    profile = TableProfile(
        table=table,
        file_name=path.name,
        path=str(path),
        size_bytes=path.stat().st_size,
        size_human=human_size(path.stat().st_size),
    )
    started = time.perf_counter()
    view = safe_view_name(index, table)
    exact_scope = full_profile or profile.size_bytes <= SMALL_EXACT_BYTES

    try:
        with timed_step(profile, "header_scan"):
            header, header_issues = read_header(path)
            profile.columns = header
            profile.issues.extend(header_issues)
            profile.issues.extend(scan_shape_issues(path, len(header)))

        with timed_step(profile, "duckdb_view_and_schema"):
            expr = read_csv_expr(path, infer_sample_rows)
            try:
                con.execute(f"CREATE OR REPLACE TEMP VIEW {quote_ident(view)} AS SELECT * FROM {expr}")
                profile.schema = query_dicts(con, f"DESCRIBE SELECT * FROM {quote_ident(view)}")
            except Exception as exc:
                profile.warnings.append(
                    f"Typed DuckDB inference failed; retrying all columns as VARCHAR. Original error: {exc}"
                )
                expr = read_csv_expr(path, infer_sample_rows, all_varchar=True)
                con.execute(f"CREATE OR REPLACE TEMP VIEW {quote_ident(view)} AS SELECT * FROM {expr}")
                profile.schema = query_dicts(con, f"DESCRIBE SELECT * FROM {quote_ident(view)}")
            duckdb_columns = [str(row["column_name"]) for row in profile.schema if row.get("column_name") is not None]
            if duckdb_columns and duckdb_columns != profile.columns:
                profile.warnings.append("DuckDB column names differ from raw header after parsing/inference.")
                profile.columns = duckdb_columns

        with timed_step(profile, "example_rows"):
            profile.first_rows = query_dicts(con, f"SELECT * FROM {quote_ident(view)} LIMIT 5")
            if exact_scope:
                count_for_offset = exact_row_count(con, view)
                if count_for_offset > 5:
                    profile.last_rows = query_dicts(
                        con,
                        f"SELECT * FROM {quote_ident(view)} LIMIT 5 OFFSET {max(0, count_for_offset - 5)}",
                    )
                else:
                    profile.last_rows = profile.first_rows

        with timed_step(profile, "row_count"):
            if exact_scope:
                profile.row_count = {"value": exact_row_count(con, view), "method": "exact_duckdb_count"}
            else:
                profile.row_count = estimate_row_count_from_bytes(path)
                profile.warnings.append(
                    "Row count is estimated in default mode; run with --full-profile for exact DuckDB count."
                )

        with timed_step(profile, "null_profile"):
            profile.nulls = calculate_nulls(con, view, profile.columns, exact_scope, sample_profile_rows)
            if not exact_scope:
                profile.warnings.append(
                    "Null counts and percentages are sample-based in default mode for large tables."
                )

        with timed_step(profile, "date_ranges"):
            for col in profile.columns:
                if is_date_column(col):
                    try:
                        profile.date_ranges[col] = calculate_date_range(con, view, col, exact_scope, sample_profile_rows)
                    except Exception as exc:
                        profile.date_ranges[col] = {"error": str(exc), "scope": profile_scope_label(exact_scope, sample_profile_rows)}

        with timed_step(profile, "distincts_and_categories"):
            profile.distinct_counts = likely_identifier_distincts(con, view, profile.columns, exact_scope, sample_profile_rows)
            profile.categorical_values = representative_distincts(con, view, profile.columns, exact_scope, sample_profile_rows)

        with timed_step(profile, "duplicate_key_checks"):
            profile.duplicate_checks = [
                duplicate_count_for_key(con, view, key, exact_scope, sample_profile_rows)
                for key in infer_key_candidates(table, profile.columns)
            ]
            if not exact_scope and profile.duplicate_checks:
                profile.warnings.append("Duplicate key checks are sample-based in default mode for this table.")

        with timed_step(profile, "table_specific_checks"):
            profile.table_specific = run_specific_checks(
                con,
                table,
                view,
                profile.columns,
                exact_scope,
                sample_profile_rows,
            )

        with timed_step(profile, "sample_csv"):
            sample_rows = make_sample_rows(con, view, max(20, min(sample_size, 50)), full_profile)
            sample_path = output_dir / "sample_rows" / f"{table}_sample.csv"
            write_sample_csv(sample_path, sample_rows, profile.columns)
            profile.sample_csv = str(sample_path)

    except Exception as exc:
        profile.success = False
        profile.error = str(exc)
    finally:
        profile.elapsed_seconds = round(time.perf_counter() - started, 3)
        try:
            con.execute(f"DROP VIEW IF EXISTS {quote_ident(view)}")
        except Exception:
            pass
    return profile


def write_json_report(path: Path, profiles: list[TableProfile], raw_dir: Path, total_size: int) -> None:
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "raw_dir": str(raw_dir),
        "total_size_bytes": total_size,
        "total_size_human": human_size(total_size),
        "tables_found": len(profiles),
        "tables_successfully_profiled": sum(1 for profile in profiles if profile.success),
        "tables_with_warnings_or_errors": sum(1 for profile in profiles if profile.warnings or profile.issues or profile.error),
        "tables": [json_safe(profile.__dict__) for profile in profiles],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=json_safe)


def print_final_summary(profiles: list[TableProfile], raw_dir: Path, output_dir: Path, total_size: int) -> None:
    print("\nFinal Sharadar raw profile summary")
    print("=" * 40)
    headers = ["Table", "Size", "Rows", "Columns", "Unique tickers", "Date min", "Date max", "Issues"]
    rows: list[list[str]] = []
    for profile in profiles:
        date_min, date_max = primary_date_range(profile)
        issue_count = len(profile.issues) + len(profile.warnings) + (1 if profile.error else 0)
        rows.append(
            [
                profile.table,
                profile.size_human,
                row_count_label(profile.row_count),
                str(len(profile.columns)),
                unique_ticker_label(profile),
                date_min or "",
                date_max or "",
                str(issue_count),
            ]
        )
    widths = [len(header) for header in headers]
    for row in rows:
        widths = [max(width, len(cell)) for width, cell in zip(widths, row)]

    print(" | ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(cell.ljust(width) for cell, width in zip(row, widths)))

    successes = sum(1 for profile in profiles if profile.success)
    warnings_or_errors = sum(1 for profile in profiles if profile.warnings or profile.issues or profile.error)
    print("")
    print(f"Total raw dataset size: {human_size(total_size)}")
    print(f"Total tables found: {len(profiles)}")
    print(f"Tables successfully profiled: {successes}")
    print(f"Tables with warnings/errors: {warnings_or_errors}")
    print(f"Markdown report: {output_dir / 'sharadar_profile.md'}")
    print(f"JSON report: {output_dir / 'sharadar_profile.json'}")
    print(f"Sample rows: {output_dir / 'sample_rows'}")
    print(f"Raw directory was read only: {raw_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile local Sharadar raw CSV files with DuckDB without loading them into Python memory."
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR, help="Directory containing raw Sharadar CSVs.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for profile artifacts.")
    parser.add_argument("--sample-size", type=int, default=25, help="Sample CSV rows per table, capped to 50.")
    parser.add_argument(
        "--full-profile",
        action="store_true",
        help="Run exact full-table counts, null profiles, duplicate checks, and date ranges even on giant files.",
    )
    parser.add_argument(
        "--sample-profile-rows",
        type=int,
        default=DEFAULT_SAMPLE_PROFILE_ROWS,
        help="Rows used for sample-based null/distinct/duplicate checks in default mode.",
    )
    parser.add_argument(
        "--infer-sample-rows",
        type=int,
        default=20_480,
        help="DuckDB rows sampled for type inference.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_dir = args.raw_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "sample_rows").mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        raise SystemExit(f"Raw directory does not exist: {raw_dir}")
    files = sorted(raw_dir.glob("*.csv"))
    if not files:
        raise SystemExit(f"No CSV files found in {raw_dir}")

    duckdb = require_duckdb()
    con = duckdb.connect(database=":memory:")
    try:
        con.execute("SET preserve_insertion_order=false")
    except Exception:
        pass

    total_size = sum(path.stat().st_size for path in files)
    print(f"Found {len(files)} raw Sharadar CSVs in {raw_dir}")
    print(f"Total raw CSV size: {human_size(total_size)}")
    print(f"Mode: {'full profile' if args.full_profile else 'fast sampled profile'}")

    profiles: list[TableProfile] = []
    for idx, path in enumerate(files, start=1):
        table = table_name_from_path(path)
        print(f"\n[{idx}/{len(files)}] Profiling {table} ({path.name}, {human_size(path.stat().st_size)})")
        profile = profile_file(
            con=con,
            path=path,
            index=idx,
            sample_size=max(1, args.sample_size),
            full_profile=args.full_profile,
            sample_profile_rows=max(1, args.sample_profile_rows),
            output_dir=output_dir,
            infer_sample_rows=max(1, args.infer_sample_rows),
        )
        profiles.append(profile)
        status = "ok" if profile.success else "error"
        print(
            f"  {status}: rows={row_count_label(profile.row_count)} "
            f"cols={len(profile.columns)} elapsed={profile.elapsed_seconds:.2f}s "
            f"issues={len(profile.issues)} warnings={len(profile.warnings)}"
        )
        if profile.error:
            print(f"  error: {profile.error}")

    markdown_path = output_dir / "sharadar_profile.md"
    json_path = output_dir / "sharadar_profile.json"
    markdown_path.write_text(build_markdown_report(profiles, raw_dir, total_size), encoding="utf-8")
    write_json_report(json_path, profiles, raw_dir, total_size)
    print_final_summary(profiles, raw_dir, output_dir, total_size)


if __name__ == "__main__":
    main()
