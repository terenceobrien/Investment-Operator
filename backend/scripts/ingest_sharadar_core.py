#!/usr/bin/env python3
"""
Convert core Sharadar raw CSVs into local Parquet datasets for Helix research.

This script is deliberately limited to data foundation work:
- SEP, SFP, SP500, and TICKERS CSV -> canonical Parquet
- benchmark ETF extract from SFP
- metadata/QA/manifest files
- optional call into build_sp500_membership.py

It does not calculate breadth, drawdowns, signals, scores, or crash labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW_DIR = ROOT / "data" / "sharadar" / "raw"
DEFAULT_PROCESSED_DIR = ROOT / "data" / "sharadar" / "processed"
DEFAULT_DERIVED_DIR = ROOT / "data" / "sharadar" / "derived"

PRICE_COLUMNS = ["ticker", "date", "open", "high", "low", "close", "volume", "closeadj", "closeunadj", "lastupdated"]
SP500_COLUMNS = ["date", "action", "ticker", "name", "contraticker", "contraname", "note"]
TICKERS_COLUMNS = [
    "table",
    "permaticker",
    "ticker",
    "name",
    "exchange",
    "isdelisted",
    "category",
    "cusips",
    "siccode",
    "sicsector",
    "sicindustry",
    "figi",
    "famaindustry",
    "sector",
    "industry",
    "scalemarketcap",
    "scalerevenue",
    "relatedtickers",
    "currency",
    "location",
    "lastupdated",
    "firstadded",
    "firstpricedate",
    "lastpricedate",
    "firstquarter",
    "lastquarter",
    "secfilings",
    "companysite",
]

BENCHMARK_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "RSP",
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
]

SCRIPT_VERSION = "2026-08-14.1"
MB = 1024 * 1024
GB = 1024 * MB


@contextmanager
def timed(label: str) -> Iterable[None]:
    started = time.perf_counter()
    print(f"-> {label}")
    try:
        yield
    finally:
        print(f"   done in {time.perf_counter() - started:.2f}s")


def sql_literal(value: str | Path) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def human_size(size_bytes: int) -> str:
    if size_bytes >= GB:
        return f"{size_bytes / GB:.2f} GB"
    if size_bytes >= MB:
        return f"{size_bytes / MB:.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


def path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def parquet_glob(path: Path) -> str:
    if path.is_file():
        return str(path)
    return str(path / "**" / "*.parquet")


def read_csv_expr(path: Path) -> str:
    return (
        "read_csv_auto("
        f"{sql_literal(path)}, "
        "header=true, "
        "all_varchar=true, "
        "ignore_errors=false, "
        "sample_size=20480"
        ")"
    )


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [item[0] for item in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def json_safe(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return next(csv.reader(fh))


def schema_hash(columns: list[str]) -> str:
    return hashlib.sha256("\n".join(columns).encode("utf-8")).hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT.parent, text=True).strip()
    except Exception:
        return None


def find_raw_file(raw_dir: Path, table: str) -> Path:
    matches = sorted(raw_dir.glob(f"SHARADAR_{table}_*.csv"))
    if not matches:
        raise FileNotFoundError(f"Could not find raw Sharadar {table} CSV in {raw_dir}")
    if len(matches) > 1:
        print(f"Warning: found multiple {table} files; using newest modified file.")
        matches = sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0]


def raw_fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "file_name": path.name,
        "size_bytes": stat.st_size,
        "size_human": human_size(stat.st_size),
        "modified_timestamp": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "columns": read_header(path),
        "schema_hash": schema_hash(read_header(path)),
    }


def output_has_parquet(path: Path) -> bool:
    if path.is_file() and path.suffix == ".parquet":
        return True
    if path.is_dir():
        return any(path.rglob("*.parquet"))
    return False


def prepare_dir_output(path: Path, force: bool) -> tuple[bool, Path]:
    if output_has_parquet(path) and not force:
        print(f"   skipping existing output: {path}")
        return False, path
    if path.exists() and force:
        shutil.rmtree(path)
    tmp = path.parent / f".{path.name}.tmp.{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    return True, tmp


def finish_dir_output(tmp: Path, final: Path) -> None:
    if final.exists():
        shutil.rmtree(final)
    tmp.rename(final)


def write_single_parquet(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    output_path: Path,
    force: bool,
) -> bool:
    if output_path.exists() and not force:
        print(f"   skipping existing output: {output_path}")
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + f".tmp.{int(time.time())}")
    if tmp.exists():
        tmp.unlink()
    con.execute(f"COPY ({sql}) TO {sql_literal(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    tmp.replace(output_path)
    return True


def price_select_sql(raw_path: Path) -> str:
    src = read_csv_expr(raw_path)
    return f"""
        SELECT
            CAST(ticker AS VARCHAR) AS ticker,
            TRY_CAST(date AS DATE) AS date,
            TRY_CAST(open AS DOUBLE) AS open,
            TRY_CAST(high AS DOUBLE) AS high,
            TRY_CAST(low AS DOUBLE) AS low,
            TRY_CAST(close AS DOUBLE) AS close,
            TRY_CAST(volume AS DOUBLE) AS volume,
            TRY_CAST(closeadj AS DOUBLE) AS closeadj,
            TRY_CAST(closeunadj AS DOUBLE) AS closeunadj,
            TRY_CAST(lastupdated AS DATE) AS lastupdated,
            EXTRACT(year FROM TRY_CAST(date AS DATE))::INTEGER AS year
        FROM {src}
        WHERE TRY_CAST(date AS DATE) IS NOT NULL
    """


def ingest_price_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    raw_path: Path,
    output_dir: Path,
    force: bool,
) -> dict[str, Any]:
    raw_cols = read_header(raw_path)
    if raw_cols != PRICE_COLUMNS:
        raise ValueError(f"{table} raw schema mismatch. Expected {PRICE_COLUMNS}, found {raw_cols}")

    final = output_dir / table.lower()
    wrote, tmp = prepare_dir_output(final, force)
    if wrote:
        # Date-first ordering is chosen because downstream breadth research will
        # usually request a cross-section of all constituent prices for date t.
        sql = price_select_sql(raw_path)
        con.execute(
            f"""
            COPY (
                SELECT * FROM ({sql})
                ORDER BY date, ticker
            )
            TO {sql_literal(tmp)}
            (FORMAT PARQUET, PARTITION_BY (year), COMPRESSION ZSTD)
            """
        )
        finish_dir_output(tmp, final)

    stats = parquet_price_stats(con, final)
    validate_price_schema(con, final, table)
    return {
        "table": table,
        "raw_path": str(raw_path),
        "output_path": str(final),
        "wrote": wrote,
        "raw_size_bytes": raw_path.stat().st_size,
        "processed_size_bytes": path_size(final),
        **stats,
    }


def parquet_price_stats(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, Any]:
    glob = parquet_glob(path)
    row = query_dicts(
        con,
        f"""
        SELECT
            COUNT(*) AS rows,
            MIN(date) AS first_date,
            MAX(date) AS last_date,
            COUNT(DISTINCT ticker) AS unique_tickers
        FROM read_parquet({sql_literal(glob)}, hive_partitioning=false)
        """,
    )[0]
    return row


def validate_price_schema(con: duckdb.DuckDBPyConnection, path: Path, table: str) -> None:
    glob = parquet_glob(path)
    rows = query_dicts(
        con,
        f"DESCRIBE SELECT * FROM read_parquet({sql_literal(glob)}, hive_partitioning=false) LIMIT 0",
    )
    columns = [row["column_name"] for row in rows]
    if columns != PRICE_COLUMNS:
        raise AssertionError(f"{table} processed schema mismatch. Expected {PRICE_COLUMNS}, found {columns}")


def ingest_tickers(
    con: duckdb.DuckDBPyConnection,
    raw_path: Path,
    processed_dir: Path,
    force: bool,
) -> dict[str, Any]:
    raw_cols = read_header(raw_path)
    if raw_cols != TICKERS_COLUMNS:
        raise ValueError(f"TICKERS raw schema mismatch. Expected {TICKERS_COLUMNS}, found {raw_cols}")

    src = read_csv_expr(raw_path)
    select_sql = f"""
        SELECT
            CAST("table" AS VARCHAR) AS "table",
            TRY_CAST(permaticker AS BIGINT) AS permaticker,
            CAST(ticker AS VARCHAR) AS ticker,
            CAST(name AS VARCHAR) AS name,
            CAST(exchange AS VARCHAR) AS exchange,
            CAST(isdelisted AS VARCHAR) AS isdelisted,
            CAST(category AS VARCHAR) AS category,
            CAST(cusips AS VARCHAR) AS cusips,
            CAST(siccode AS VARCHAR) AS siccode,
            CAST(sicsector AS VARCHAR) AS sicsector,
            CAST(sicindustry AS VARCHAR) AS sicindustry,
            CAST(figi AS VARCHAR) AS figi,
            CAST(famaindustry AS VARCHAR) AS famaindustry,
            CAST(sector AS VARCHAR) AS sector,
            CAST(industry AS VARCHAR) AS industry,
            CAST(scalemarketcap AS VARCHAR) AS scalemarketcap,
            CAST(scalerevenue AS VARCHAR) AS scalerevenue,
            CAST(relatedtickers AS VARCHAR) AS relatedtickers,
            CAST(currency AS VARCHAR) AS currency,
            CAST(location AS VARCHAR) AS location,
            TRY_CAST(lastupdated AS DATE) AS lastupdated,
            TRY_CAST(firstadded AS DATE) AS firstadded,
            TRY_CAST(firstpricedate AS DATE) AS firstpricedate,
            TRY_CAST(lastpricedate AS DATE) AS lastpricedate,
            TRY_CAST(firstquarter AS DATE) AS firstquarter,
            TRY_CAST(lastquarter AS DATE) AS lastquarter,
            CAST(secfilings AS VARCHAR) AS secfilings,
            CAST(companysite AS VARCHAR) AS companysite
        FROM {src}
    """

    output = processed_dir / "tickers.parquet"
    wrote = write_single_parquet(con, select_sql, output, force)
    for table_name in ("SEP", "SFP"):
        helper = processed_dir / f"tickers_{table_name.lower()}.parquet"
        write_single_parquet(
            con,
            f"""
            SELECT * FROM read_parquet({sql_literal(output)})
            WHERE UPPER("table") = {sql_literal(table_name)}
            ORDER BY ticker, permaticker
            """,
            helper,
            force,
        )

    qa = build_tickers_qa(con, output)
    write_json(processed_dir / "tickers_qa.json", qa)
    write_text(processed_dir / "tickers_qa.md", render_tickers_qa(qa))
    return {
        "table": "TICKERS",
        "raw_path": str(raw_path),
        "output_path": str(output),
        "wrote": wrote,
        "raw_size_bytes": raw_path.stat().st_size,
        "processed_size_bytes": path_size(output) + path_size(processed_dir / "tickers_sep.parquet") + path_size(processed_dir / "tickers_sfp.parquet"),
        "rows": qa["total_rows"],
    }


def build_tickers_qa(con: duckdb.DuckDBPyConnection, tickers_path: Path) -> dict[str, Any]:
    src = f"read_parquet({sql_literal(tickers_path)})"

    def top_dupes(group_cols: list[str], label: str) -> dict[str, Any]:
        cols = ", ".join(quote_ident(c) for c in group_cols)
        rows = query_dicts(
            con,
            f"""
            SELECT {cols}, COUNT(*) AS rows
            FROM {src}
            GROUP BY {cols}
            HAVING COUNT(*) > 1
            ORDER BY rows DESC
            LIMIT 25
            """,
        )
        count = query_scalar(
            con,
            f"""
            SELECT COUNT(*) FROM (
                SELECT {cols}
                FROM {src}
                GROUP BY {cols}
                HAVING COUNT(*) > 1
            )
            """,
        )
        return {"label": label, "duplicate_keys": int(count or 0), "examples": rows}

    mapping_sql = f"""
        SELECT "table", ticker, COUNT(DISTINCT permaticker) AS distinct_permatickers,
               MIN(permaticker) AS sample_min_permaticker,
               MAX(permaticker) AS sample_max_permaticker,
               COUNT(*) AS rows
        FROM {src}
        WHERE ticker IS NOT NULL
        GROUP BY "table", ticker
        HAVING COUNT(DISTINCT permaticker) > 1
        ORDER BY distinct_permatickers DESC, rows DESC
        LIMIT 50
    """
    reverse_mapping_sql = f"""
        SELECT "table", permaticker, COUNT(DISTINCT ticker) AS distinct_tickers,
               MIN(ticker) AS sample_min_ticker,
               MAX(ticker) AS sample_max_ticker,
               COUNT(*) AS rows
        FROM {src}
        WHERE permaticker IS NOT NULL
        GROUP BY "table", permaticker
        HAVING COUNT(DISTINCT ticker) > 1
        ORDER BY distinct_tickers DESC, rows DESC
        LIMIT 50
    """

    return {
        "generated_at": utc_now(),
        "total_rows": int(query_scalar(con, f"SELECT COUNT(*) FROM {src}") or 0),
        "table_counts": query_dicts(con, f'SELECT "table", COUNT(*) AS rows FROM {src} GROUP BY 1 ORDER BY rows DESC'),
        "duplicate_tickers": top_dupes(["ticker"], "duplicate ticker values across all Sharadar tables"),
        "duplicate_permatickers": top_dupes(["permaticker"], "duplicate permaticker values across all Sharadar tables"),
        "duplicate_table_ticker": top_dupes(["table", "ticker"], "duplicate (table, ticker) combinations"),
        "duplicate_table_permaticker": top_dupes(["table", "permaticker"], "duplicate (table, permaticker) combinations"),
        "ticker_to_multiple_permatickers": query_dicts(con, mapping_sql),
        "permaticker_to_multiple_tickers": query_dicts(con, reverse_mapping_sql),
        "note": "Ticker and permaticker are diagnostics only here; no historical SP500 membership tickers are rewritten.",
    }


def ingest_sp500(
    con: duckdb.DuckDBPyConnection,
    raw_path: Path,
    processed_dir: Path,
    force: bool,
) -> dict[str, Any]:
    raw_cols = read_header(raw_path)
    if raw_cols != SP500_COLUMNS:
        raise ValueError(f"SP500 raw schema mismatch. Expected {SP500_COLUMNS}, found {raw_cols}")
    src = read_csv_expr(raw_path)
    select_sql = f"""
        SELECT
            TRY_CAST(date AS DATE) AS date,
            LOWER(CAST(action AS VARCHAR)) AS action,
            CAST(ticker AS VARCHAR) AS ticker,
            CAST(name AS VARCHAR) AS name,
            NULLIF(CAST(contraticker AS VARCHAR), 'N/A') AS contraticker,
            NULLIF(CAST(contraname AS VARCHAR), 'N/A') AS contraname,
            CAST(note AS VARCHAR) AS note
        FROM {src}
        WHERE TRY_CAST(date AS DATE) IS NOT NULL
    """
    output = processed_dir / "sp500.parquet"
    wrote = write_single_parquet(con, f"SELECT * FROM ({select_sql}) ORDER BY date, action, ticker", output, force)

    for action, name in [
        ("historical", "sp500_historical_snapshots.parquet"),
        ("added", "sp500_additions.parquet"),
        ("removed", "sp500_removals.parquet"),
        ("current", "sp500_current.parquet"),
    ]:
        write_single_parquet(
            con,
            f"SELECT * FROM read_parquet({sql_literal(output)}) WHERE action = {sql_literal(action)} ORDER BY date, ticker",
            processed_dir / name,
            force,
        )

    stats = query_dicts(
        con,
        f"""
        SELECT
            COUNT(*) AS rows,
            MIN(date) AS first_date,
            MAX(date) AS last_date,
            COUNT(DISTINCT ticker) AS unique_tickers
        FROM read_parquet({sql_literal(output)})
        """,
    )[0]
    action_values = query_dicts(
        con,
        f"SELECT action, COUNT(*) AS rows FROM read_parquet({sql_literal(output)}) GROUP BY action ORDER BY rows DESC",
    )
    recognized = {"historical", "added", "removed", "current"}
    found = {row["action"] for row in action_values}
    unknown = sorted(found - recognized)
    if unknown:
        raise ValueError(f"Unrecognized SP500 action values: {unknown}")

    historical_dates = int(
        query_scalar(
            con,
            f"SELECT COUNT(DISTINCT date) FROM read_parquet({sql_literal(output)}) WHERE action = 'historical'",
        )
        or 0
    )
    if historical_dates == 0:
        raise AssertionError("SP500 historical snapshot dates do not exist.")

    return {
        "table": "SP500",
        "raw_path": str(raw_path),
        "output_path": str(output),
        "wrote": wrote,
        "raw_size_bytes": raw_path.stat().st_size,
        "processed_size_bytes": path_size(output)
        + path_size(processed_dir / "sp500_historical_snapshots.parquet")
        + path_size(processed_dir / "sp500_additions.parquet")
        + path_size(processed_dir / "sp500_removals.parquet")
        + path_size(processed_dir / "sp500_current.parquet"),
        "action_values": action_values,
        "historical_snapshot_dates": historical_dates,
        **stats,
    }


def build_benchmark_extract(
    con: duckdb.DuckDBPyConnection,
    processed_dir: Path,
    force: bool,
) -> dict[str, Any]:
    sfp_path = processed_dir / "sfp"
    output = processed_dir / "benchmarks.parquet"
    if not output_has_parquet(sfp_path):
        print("   skipping benchmark extract; processed SFP parquet is unavailable")
        return {"output_path": str(output), "wrote": False, "coverage": [], "missing_tickers": BENCHMARK_TICKERS}

    in_list = ", ".join(sql_literal(t) for t in BENCHMARK_TICKERS)
    sql = f"""
        SELECT ticker, date, open, high, low, close, volume, closeadj, closeunadj, lastupdated
        FROM read_parquet({sql_literal(parquet_glob(sfp_path))}, hive_partitioning=false)
        WHERE ticker IN ({in_list})
        ORDER BY ticker, date
    """
    wrote = write_single_parquet(con, sql, output, force)
    coverage = query_dicts(
        con,
        f"""
        SELECT ticker, MIN(date) AS first_price_date, MAX(date) AS last_price_date, COUNT(*) AS row_count
        FROM read_parquet({sql_literal(output)})
        GROUP BY ticker
        ORDER BY ticker
        """,
    ) if output.exists() else []
    found = {row["ticker"] for row in coverage}
    missing = [ticker for ticker in BENCHMARK_TICKERS if ticker not in found]
    if missing:
        print(f"   benchmark tickers absent from SFP extract: {', '.join(missing)}")
    write_json(processed_dir / "benchmark_coverage.json", {"generated_at": utc_now(), "coverage": coverage, "missing_tickers": missing})
    write_text(processed_dir / "benchmark_coverage.md", render_benchmark_coverage(coverage, missing))
    return {"output_path": str(output), "wrote": wrote, "coverage": coverage, "missing_tickers": missing}


def render_benchmark_coverage(coverage: list[dict[str, Any]], missing: list[str]) -> str:
    lines = ["# Sharadar Benchmark Coverage", ""]
    lines.append("| Ticker | First Price Date | Last Price Date | Row Count |")
    lines.append("| --- | --- | --- | --- |")
    for row in coverage:
        lines.append(f"| {row['ticker']} | {row['first_price_date']} | {row['last_price_date']} | {row['row_count']} |")
    if missing:
        lines.extend(["", f"Missing tickers: `{', '.join(missing)}`"])
    return "\n".join(lines) + "\n"


def render_tickers_qa(qa: dict[str, Any]) -> str:
    lines = ["# Sharadar TICKERS QA", ""]
    lines.append(f"Generated: `{qa['generated_at']}`")
    lines.append(f"Total rows: `{qa['total_rows']}`")
    lines.append("")
    lines.append("## Table Counts")
    lines.extend(markdown_table(qa["table_counts"]))
    lines.append("")
    for key in [
        "duplicate_tickers",
        "duplicate_permatickers",
        "duplicate_table_ticker",
        "duplicate_table_permaticker",
    ]:
        item = qa[key]
        lines.append(f"## {item['label']}")
        lines.append(f"Duplicate keys: `{item['duplicate_keys']}`")
        lines.extend(markdown_table(item["examples"]))
        lines.append("")
    lines.append("## Ticker To Multiple Permatickers")
    lines.extend(markdown_table(qa["ticker_to_multiple_permatickers"]))
    lines.append("")
    lines.append("## Permaticker To Multiple Tickers")
    lines.extend(markdown_table(qa["permaticker_to_multiple_tickers"]))
    lines.append("")
    lines.append(qa["note"])
    return "\n".join(lines) + "\n"


def markdown_table(rows: list[dict[str, Any]], limit: int = 50) -> list[str]:
    if not rows:
        return ["_None._"]
    rows = rows[:limit]
    cols: list[str] = []
    for row in rows:
        for col in row:
            if col not in cols:
                cols.append(col)
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(json_safe(row.get(col, ""))).replace("|", "\\|") for col in cols) + " |")
    return lines


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_entry(raw: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    processed_size = int(output.get("processed_size_bytes") or 0)
    raw_size = int(output.get("raw_size_bytes") or raw.get("size_bytes") or 0)
    return {
        "source": raw,
        "output": json_safe(output),
        "compression_ratio_raw_to_parquet": round(raw_size / processed_size, 4) if processed_size else None,
    }


def write_manifest(
    processed_dir: Path,
    raw_files: dict[str, Path],
    outputs: dict[str, Any],
) -> dict[str, Any]:
    raw_entries = {table: raw_fingerprint(path) for table, path in raw_files.items()}
    manifest = {
        "script": "backend/scripts/ingest_sharadar_core.py",
        "script_version": SCRIPT_VERSION,
        "git_commit": git_commit(),
        "ingestion_timestamp": utc_now(),
        "processed_dir": str(processed_dir),
        "tables": {
            table: manifest_entry(raw_entries[table], outputs.get(table, {}))
            for table in raw_entries
        },
        "benchmark_extract": outputs.get("BENCHMARKS"),
    }
    write_json(processed_dir / "manifest.json", manifest)
    return manifest


def raw_files_unchanged(before: dict[str, dict[str, Any]], raw_files: dict[str, Path]) -> list[str]:
    issues: list[str] = []
    for table, path in raw_files.items():
        after = raw_fingerprint(path)
        for key in ("size_bytes", "modified_timestamp", "schema_hash"):
            if before[table][key] != after[key]:
                issues.append(f"{table} raw file changed during ingestion: {key}")
    return issues


def print_storage_summary(outputs: dict[str, Any]) -> None:
    print("\nStorage summary")
    print("Table | Raw | Parquet | Raw/Parquet")
    print("--- | --- | --- | ---")
    for table in ("SEP", "SFP", "SP500", "TICKERS"):
        item = outputs.get(table) or {}
        raw_size = int(item.get("raw_size_bytes") or 0)
        processed_size = int(item.get("processed_size_bytes") or 0)
        ratio = raw_size / processed_size if processed_size else 0
        print(f"{table} | {human_size(raw_size)} | {human_size(processed_size)} | {ratio:.2f}x")


def print_final_summary(outputs: dict[str, Any], membership_summary: dict[str, Any] | None, warnings: list[str]) -> None:
    print("\nSharadar core ingestion complete")
    for table in ("SEP", "SFP"):
        item = outputs.get(table)
        if not item:
            continue
        print(f"\n{table}:")
        print(f"raw size: {human_size(item['raw_size_bytes'])}")
        print(f"processed size: {human_size(item['processed_size_bytes'])}")
        print(f"date range: {item.get('first_date')} -> {item.get('last_date')}")
        print(f"rows: {item.get('rows'):,}")

    sp500 = outputs.get("SP500")
    if sp500:
        action_counts = {row["action"]: row["rows"] for row in sp500["action_values"]}
        print("\nSP500:")
        print(f"snapshot dates: {sp500.get('historical_snapshot_dates')}")
        print(f"additions: {action_counts.get('added', 0)}")
        print(f"removals: {action_counts.get('removed', 0)}")
        print(f"current members: {action_counts.get('current', 0)}")

    if membership_summary:
        print("\nMembership:")
        for line in membership_summary.get("console_lines", []):
            print(line)

    benchmarks = outputs.get("BENCHMARKS", {}).get("coverage", [])
    if benchmarks:
        print("\nBenchmarks:")
        for ticker in ("SPY", "QQQ", "IWM", "RSP"):
            row = next((r for r in benchmarks if r["ticker"] == ticker), None)
            if row:
                print(f"{ticker}: {row['first_price_date']} -> {row['last_price_date']}")

    print("\nWarnings:")
    if warnings:
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("- none")

    print("\nOutput paths:")
    for key in ("SEP", "SFP", "SP500", "TICKERS", "BENCHMARKS"):
        item = outputs.get(key)
        if item:
            print(f"{key}: {item.get('output_path')}")


def run_ingestion(args: argparse.Namespace) -> dict[str, Any]:
    raw_dir = args.raw_dir.expanduser().resolve()
    processed_dir = args.processed_dir.expanduser().resolve()
    derived_dir = args.derived_dir.expanduser().resolve()
    processed_dir.mkdir(parents=True, exist_ok=True)
    derived_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(database=":memory:")
    con.execute("SET preserve_insertion_order=false")
    raw_files = {
        "SEP": find_raw_file(raw_dir, "SEP"),
        "SFP": find_raw_file(raw_dir, "SFP"),
        "SP500": find_raw_file(raw_dir, "SP500"),
        "TICKERS": find_raw_file(raw_dir, "TICKERS"),
    }
    raw_before = {table: raw_fingerprint(path) for table, path in raw_files.items()}
    outputs: dict[str, Any] = {}
    warnings: list[str] = []

    with timed("ingest SP500"):
        outputs["SP500"] = ingest_sp500(con, raw_files["SP500"], processed_dir, args.force)

    with timed("ingest TICKERS and metadata QA"):
        outputs["TICKERS"] = ingest_tickers(con, raw_files["TICKERS"], processed_dir, args.force)

    if not args.skip_sep:
        with timed("ingest SEP partitioned parquet"):
            outputs["SEP"] = ingest_price_table(con, "SEP", raw_files["SEP"], processed_dir, args.force)
    else:
        warnings.append("SEP ingestion skipped by --skip-sep")

    if not args.skip_sfp:
        with timed("ingest SFP partitioned parquet"):
            outputs["SFP"] = ingest_price_table(con, "SFP", raw_files["SFP"], processed_dir, args.force)
    else:
        warnings.append("SFP ingestion skipped by --skip-sfp")

    with timed("build benchmark ETF extract"):
        outputs["BENCHMARKS"] = build_benchmark_extract(con, processed_dir, args.force)

    with timed("write manifest"):
        manifest = write_manifest(processed_dir, raw_files, outputs)

    raw_issues = raw_files_unchanged(raw_before, raw_files)
    warnings.extend(raw_issues)
    if raw_issues:
        raise AssertionError("Raw file immutability check failed: " + "; ".join(raw_issues))

    membership_summary: dict[str, Any] | None = None
    if not args.skip_membership:
        with timed("build point-in-time SP500 membership"):
            script_dir = Path(__file__).resolve().parent
            if str(script_dir) not in sys.path:
                sys.path.insert(0, str(script_dir))
            from build_sp500_membership import build_membership

            membership_summary = build_membership(
                processed_dir=processed_dir,
                derived_dir=derived_dir,
                force=args.force,
            )
    else:
        warnings.append("SP500 membership reconstruction skipped by --skip-membership")

    print_storage_summary(outputs)
    print_final_summary(outputs, membership_summary, warnings)
    return {"outputs": outputs, "manifest": manifest, "membership": membership_summary, "warnings": warnings}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest core Sharadar raw CSVs into canonical local Parquet datasets.")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    parser.add_argument("--force", action="store_true", help="Rewrite existing processed/derived outputs.")
    parser.add_argument("--skip-sep", action="store_true", help="Skip SEP conversion.")
    parser.add_argument("--skip-sfp", action="store_true", help="Skip SFP conversion.")
    parser.add_argument("--skip-membership", action="store_true", help="Do not run build_sp500_membership.py after ingestion.")
    return parser.parse_args()


def main() -> None:
    run_ingestion(parse_args())


if __name__ == "__main__":
    main()
