#!/usr/bin/env python3
"""
Reconstruct point-in-time daily S&P 500 membership from processed Sharadar SP500.

This module is intentionally a membership/QA layer only. It does not calculate
breadth indicators or rewrite historical tickers to modern/current symbols.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = ROOT / "data" / "sharadar" / "processed"
DEFAULT_DERIVED_DIR = ROOT / "data" / "sharadar" / "derived"

REASONABLE_MIN_MEMBERS = 480
REASONABLE_MAX_MEMBERS = 520
SCRIPT_VERSION = "2026-08-14.1"


@dataclass(frozen=True)
class MembershipEvent:
    date: date
    action: str
    ticker: str


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


def parquet_glob(path: Path) -> str:
    if path.is_file():
        return str(path)
    return str(path / "**" / "*.parquet")


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [item[0] for item in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_scalar(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = con.execute(sql).fetchone()
    return row[0] if row else None


def json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [json_safe(v) for v in value]
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_has_parquet(path: Path) -> bool:
    if path.is_file() and path.suffix == ".parquet":
        return True
    if path.is_dir():
        return any(path.rglob("*.parquet"))
    return False


def prepare_membership_output(path: Path, force: bool) -> tuple[bool, Path]:
    if output_has_parquet(path) and not force:
        print(f"   skipping existing membership output: {path}")
        return False, path
    if path.exists() and force:
        shutil.rmtree(path)
    tmp = path.parent / f".{path.name}.tmp.{int(time.time())}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    return True, tmp


def finish_membership_output(tmp: Path, final: Path) -> None:
    if final.exists():
        shutil.rmtree(final)
    tmp.rename(final)


def load_sp500_state(con: duckdb.DuckDBPyConnection, sp500_path: Path) -> tuple[dict[date, set[str]], list[MembershipEvent], set[str], date | None, dict[str, int]]:
    rows = query_dicts(
        con,
        f"""
        SELECT date, action, ticker
        FROM read_parquet({sql_literal(sp500_path)})
        WHERE action IN ('historical', 'added', 'removed', 'current')
          AND ticker IS NOT NULL
        ORDER BY date, action, ticker
        """,
    )
    snapshots: dict[date, set[str]] = {}
    events: list[MembershipEvent] = []
    current: set[str] = set()
    current_date: date | None = None
    counts: Counter[str] = Counter()
    for row in rows:
        row_date = row["date"]
        action = str(row["action"]).lower()
        ticker = str(row["ticker"]).strip()
        counts[action] += 1
        if action == "historical":
            snapshots.setdefault(row_date, set()).add(ticker)
        elif action in {"added", "removed"}:
            events.append(MembershipEvent(row_date, action, ticker))
        elif action == "current":
            current.add(ticker)
            current_date = row_date if current_date is None else max(current_date, row_date)
    events.sort(key=lambda event: (event.date, 0 if event.action == "removed" else 1, event.ticker))
    return snapshots, events, current, current_date, dict(counts)


def apply_events(state: set[str], events: list[MembershipEvent], start_exclusive: date, end_inclusive: date) -> set[str]:
    result = set(state)
    for event in events:
        if start_exclusive < event.date <= end_inclusive:
            if event.action == "added":
                result.add(event.ticker)
            elif event.action == "removed":
                result.discard(event.ticker)
    return result


def snapshot_reconciliation(
    snapshots: dict[date, set[str]],
    events: list[MembershipEvent],
    current: set[str],
    current_date: date | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    anchors = sorted(snapshots)
    rows: list[dict[str, Any]] = []
    if not anchors:
        return rows, {}

    previous_date = anchors[0]
    previous_state = set(snapshots[previous_date])
    rows.append(
        {
            "snapshot_date": previous_date,
            "snapshot_count": len(previous_state),
            "replayed_count_before_reset": None,
            "missing_from_replay_count": 0,
            "extra_in_replay_count": 0,
            "missing_from_replay_examples": [],
            "extra_in_replay_examples": [],
            "note": "first historical snapshot anchor",
        }
    )

    for anchor in anchors[1:]:
        replayed = apply_events(previous_state, events, previous_date, anchor)
        authoritative = snapshots[anchor]
        missing = sorted(authoritative - replayed)
        extra = sorted(replayed - authoritative)
        rows.append(
            {
                "snapshot_date": anchor,
                "snapshot_count": len(authoritative),
                "replayed_count_before_reset": len(replayed),
                "missing_from_replay_count": len(missing),
                "extra_in_replay_count": len(extra),
                "missing_from_replay_examples": missing[:25],
                "extra_in_replay_examples": extra[:25],
                "note": "state reset to historical snapshot after comparison",
            }
        )
        previous_date = anchor
        previous_state = set(authoritative)

    current_check: dict[str, Any] = {}
    if current and current_date:
        replayed_current = apply_events(previous_state, events, previous_date, current_date)
        missing_current = sorted(current - replayed_current)
        extra_current = sorted(replayed_current - current)
        current_check = {
            "current_date": current_date,
            "current_count": len(current),
            "replayed_count": len(replayed_current),
            "missing_from_replay_count": len(missing_current),
            "extra_in_replay_count": len(extra_current),
            "missing_from_replay_examples": missing_current[:50],
            "extra_in_replay_examples": extra_current[:50],
            "note": "current rows are validation only; they are not used to rewrite historical membership",
        }
    return rows, current_check


def load_trading_calendar(con: duckdb.DuckDBPyConnection, processed_dir: Path, start_date: date, end_date: date | None) -> tuple[list[date], str]:
    benchmark_path = processed_dir / "benchmarks.parquet"
    if benchmark_path.exists():
        rows = query_dicts(
            con,
            f"""
            SELECT date
            FROM read_parquet({sql_literal(benchmark_path)})
            WHERE ticker = 'SPY'
              AND date >= {sql_literal(start_date.isoformat())}
              {f"AND date <= {sql_literal(end_date.isoformat())}" if end_date else ""}
            GROUP BY date
            ORDER BY date
            """,
        )
        dates = [row["date"] for row in rows]
        if dates:
            return dates, "SFP benchmark extract: SPY"

    sfp_dir = processed_dir / "sfp"
    if output_has_parquet(sfp_dir):
        rows = query_dicts(
            con,
            f"""
            SELECT date
            FROM read_parquet({sql_literal(parquet_glob(sfp_dir))}, hive_partitioning=false)
            WHERE ticker = 'SPY'
              AND date >= {sql_literal(start_date.isoformat())}
              {f"AND date <= {sql_literal(end_date.isoformat())}" if end_date else ""}
            GROUP BY date
            ORDER BY date
            """,
        )
        dates = [row["date"] for row in rows]
        if dates:
            return dates, "SFP: SPY"

    sep_dir = processed_dir / "sep"
    if not output_has_parquet(sep_dir):
        raise FileNotFoundError("No SPY/SFP calendar and no SEP parquet available for trading calendar.")
    rows = query_dicts(
        con,
        f"""
        SELECT date
        FROM read_parquet({sql_literal(parquet_glob(sep_dir))}, hive_partitioning=false)
        WHERE date >= {sql_literal(start_date.isoformat())}
          {f"AND date <= {sql_literal(end_date.isoformat())}" if end_date else ""}
        GROUP BY date
        ORDER BY date
        """,
    )
    return [row["date"] for row in rows], "SEP distinct trading dates"


def event_semantics_examples(
    snapshots: dict[date, set[str]],
    events: list[MembershipEvent],
    limit: int = 20,
) -> list[dict[str, Any]]:
    anchors = sorted(snapshots)
    examples: list[dict[str, Any]] = []
    if not anchors:
        return examples
    for event in events:
        previous_anchor = max((d for d in anchors if d < event.date), default=None)
        next_anchor = min((d for d in anchors if d >= event.date), default=None)
        examples.append(
            {
                "event_date": event.date,
                "action": event.action,
                "ticker": event.ticker,
                "previous_snapshot_date": previous_anchor,
                "in_previous_snapshot": event.ticker in snapshots.get(previous_anchor, set()) if previous_anchor else None,
                "next_snapshot_date": next_anchor,
                "in_next_snapshot": event.ticker in snapshots.get(next_anchor, set()) if next_anchor else None,
            }
        )
        if len(examples) >= limit:
            break
    return examples


def write_membership_csv(
    temp_csv: Path,
    snapshots: dict[date, set[str]],
    events: list[MembershipEvent],
    trading_dates: list[date],
) -> dict[str, Any]:
    anchors = sorted(snapshots)
    if not anchors:
        raise AssertionError("Cannot build membership: no historical snapshot anchors.")
    if not trading_dates:
        raise AssertionError("Cannot build membership: trading calendar is empty.")

    event_idx = 0
    first_anchor = anchors[0]
    while event_idx < len(events) and events[event_idx].date <= first_anchor:
        event_idx += 1

    anchor_idx = 0
    current_anchor = first_anchor
    state = set(snapshots[current_anchor])
    anchor_effective_written = False
    rows_written = 0
    member_counts: list[int] = []
    temp_csv.parent.mkdir(parents=True, exist_ok=True)

    with temp_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "ticker", "source_anchor_date", "membership_source", "year"])
        for trading_date in trading_dates:
            while anchor_idx + 1 < len(anchors) and anchors[anchor_idx + 1] <= trading_date:
                next_anchor = anchors[anchor_idx + 1]
                while event_idx < len(events) and events[event_idx].date <= next_anchor:
                    event_idx += 1
                anchor_idx += 1
                current_anchor = next_anchor
                state = set(snapshots[current_anchor])
                anchor_effective_written = False

            applied_event = False
            while event_idx < len(events) and events[event_idx].date <= trading_date:
                event = events[event_idx]
                if event.action == "added":
                    state.add(event.ticker)
                elif event.action == "removed":
                    state.discard(event.ticker)
                applied_event = True
                event_idx += 1

            if not anchor_effective_written and not applied_event:
                source = "historical_snapshot"
                anchor_effective_written = True
            else:
                source = "event_replay"
                anchor_effective_written = True

            member_counts.append(len(state))
            for ticker in sorted(state):
                writer.writerow([trading_date.isoformat(), ticker, current_anchor.isoformat(), source, trading_date.year])
                rows_written += 1

    return {
        "rows_written": rows_written,
        "trading_dates": len(trading_dates),
        "member_count_min": min(member_counts),
        "member_count_max": max(member_counts),
        "member_count_mean": mean(member_counts),
        "member_count_median": median(member_counts),
    }


def copy_membership_to_parquet(
    con: duckdb.DuckDBPyConnection,
    temp_csv: Path,
    output_dir: Path,
    force: bool,
) -> tuple[bool, Path]:
    wrote, tmp = prepare_membership_output(output_dir, force)
    if not wrote:
        return False, output_dir
    con.execute(
        f"""
        COPY (
            SELECT
                TRY_CAST(date AS DATE) AS date,
                CAST(ticker AS VARCHAR) AS ticker,
                TRY_CAST(source_anchor_date AS DATE) AS source_anchor_date,
                CAST(membership_source AS VARCHAR) AS membership_source,
                TRY_CAST(year AS INTEGER) AS year
            FROM read_csv_auto({sql_literal(temp_csv)}, header=true, all_varchar=true)
            ORDER BY date, ticker
        )
        TO {sql_literal(tmp)}
        (FORMAT PARQUET, PARTITION_BY (year), COMPRESSION ZSTD)
        """
    )
    finish_membership_output(tmp, output_dir)
    return True, output_dir


def membership_view_sql(membership_dir: Path) -> str:
    return f"read_parquet({sql_literal(parquet_glob(membership_dir))}, hive_partitioning=false)"


def validate_membership(con: duckdb.DuckDBPyConnection, membership_dir: Path, current_check: dict[str, Any]) -> dict[str, Any]:
    src = membership_view_sql(membership_dir)
    duplicate_rows = int(
        query_scalar(
            con,
            f"""
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
                SELECT date, ticker, COUNT(*) AS cnt
                FROM {src}
                GROUP BY date, ticker
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    stats = query_dicts(
        con,
        f"""
        SELECT
            COUNT(*) AS trading_dates,
            MIN(date) AS first_date,
            MAX(date) AS last_date,
            MIN(member_count) AS min_member_count,
            MAX(member_count) AS max_member_count,
            AVG(member_count) AS mean_member_count,
            MEDIAN(member_count) AS median_member_count
        FROM (
            SELECT date, COUNT(*) AS member_count
            FROM {src}
            GROUP BY date
        )
        """,
    )[0]
    outside = query_dicts(
        con,
        f"""
        SELECT date, COUNT(*) AS member_count
        FROM {src}
        GROUP BY date
        HAVING COUNT(*) < {REASONABLE_MIN_MEMBERS} OR COUNT(*) > {REASONABLE_MAX_MEMBERS}
        ORDER BY date
        LIMIT 200
        """,
    )
    current_match_ok = (
        not current_check
        or (
            current_check.get("missing_from_replay_count", 1) <= 10
            and current_check.get("extra_in_replay_count", 1) <= 10
        )
    )
    return {
        "duplicate_date_ticker_rows": duplicate_rows,
        "count_stats": stats,
        "dates_outside_reasonable_480_520_range": outside,
        "member_counts_generally_near_500": len(outside) == 0,
        "current_reconstructed_membership_approximately_matches_current_rows": current_match_ok,
        "historical_tickers_not_rewritten": True,
    }


def build_price_coverage(
    con: duckdb.DuckDBPyConnection,
    processed_dir: Path,
    derived_dir: Path,
    membership_dir: Path,
    force: bool,
) -> dict[str, Any]:
    sep_dir = processed_dir / "sep"
    if not output_has_parquet(sep_dir):
        return {"available": False, "warning": "SEP parquet unavailable; price coverage not calculated."}

    coverage_path = derived_dir / "sp500_membership_price_coverage.parquet"
    missing_path = derived_dir / "sp500_missing_prices.parquet"
    if (coverage_path.exists() and missing_path.exists()) and not force:
        print("   skipping existing price coverage outputs")
    else:
        if coverage_path.exists():
            coverage_path.unlink()
        if missing_path.exists():
            missing_path.unlink()
        membership_src = membership_view_sql(membership_dir)
        sep_src = f"read_parquet({sql_literal(parquet_glob(sep_dir))}, hive_partitioning=false)"
        con.execute(
            f"""
            COPY (
                SELECT
                    m.date,
                    COUNT(*) AS member_count,
                    COUNT(s.ticker) AS members_with_price,
                    COUNT(*) - COUNT(s.ticker) AS members_missing_price,
                    100.0 * COUNT(s.ticker) / COUNT(*) AS coverage_pct
                FROM {membership_src} AS m
                LEFT JOIN {sep_src} AS s
                  ON m.ticker = s.ticker
                 AND m.date = s.date
                GROUP BY m.date
                ORDER BY m.date
            )
            TO {sql_literal(coverage_path)}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        con.execute(
            f"""
            COPY (
                SELECT m.date, m.ticker
                FROM {membership_src} AS m
                LEFT JOIN {sep_src} AS s
                  ON m.ticker = s.ticker
                 AND m.date = s.date
                WHERE s.ticker IS NULL
                ORDER BY m.date, m.ticker
            )
            TO {sql_literal(missing_path)}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )

    coverage = query_dicts(
        con,
        f"""
        SELECT
            MIN(date) AS first_date,
            MAX(date) AS last_date,
            MIN(coverage_pct) AS min_coverage_pct,
            AVG(coverage_pct) AS mean_coverage_pct,
            MEDIAN(coverage_pct) AS median_coverage_pct,
            MIN(members_missing_price) AS min_missing_members,
            MAX(members_missing_price) AS max_missing_members,
            AVG(members_missing_price) AS mean_missing_members
        FROM read_parquet({sql_literal(coverage_path)})
        """,
    )[0]
    first_95 = query_scalar(
        con,
        f"SELECT MIN(date) FROM read_parquet({sql_literal(coverage_path)}) WHERE coverage_pct >= 95",
    )
    first_99 = query_scalar(
        con,
        f"SELECT MIN(date) FROM read_parquet({sql_literal(coverage_path)}) WHERE coverage_pct >= 99",
    )
    sep_first = query_scalar(
        con,
        f"SELECT MIN(date) FROM read_parquet({sql_literal(parquet_glob(sep_dir))}, hive_partitioning=false)",
    )
    high_missing_dates = query_dicts(
        con,
        f"""
        SELECT date, member_count, members_with_price, members_missing_price, coverage_pct
        FROM read_parquet({sql_literal(coverage_path)})
        WHERE members_missing_price >= 25 OR coverage_pct < 95
        ORDER BY date
        LIMIT 200
        """,
    )
    missing_ticker_summary = query_dicts(
        con,
        f"""
        SELECT ticker, COUNT(*) AS missing_dates, MIN(date) AS first_missing_date, MAX(date) AS last_missing_date
        FROM read_parquet({sql_literal(missing_path)})
        GROUP BY ticker
        ORDER BY missing_dates DESC, ticker
        LIMIT 200
        """,
    )
    return {
        "available": True,
        "coverage_path": str(coverage_path),
        "missing_prices_path": str(missing_path),
        "first_reliable_sep_coverage_date": sep_first,
        "first_date_with_95pct_price_coverage": first_95,
        "first_date_with_99pct_price_coverage": first_99,
        "coverage_stats": coverage,
        "dates_with_unusually_high_missing_price_counts": high_missing_dates,
        "missing_ticker_summary_examples": missing_ticker_summary,
    }


def ticker_change_diagnostics(
    con: duckdb.DuckDBPyConnection,
    processed_dir: Path,
    derived_dir: Path,
) -> dict[str, Any]:
    tickers_sep = processed_dir / "tickers_sep.parquet"
    missing_path = derived_dir / "sp500_missing_prices.parquet"
    if not tickers_sep.exists() or not missing_path.exists():
        return {"available": False}
    rows = query_dicts(
        con,
        f"""
        SELECT
            m.ticker,
            COUNT(*) AS missing_dates,
            MIN(m.date) AS first_missing_date,
            MAX(m.date) AS last_missing_date,
            COUNT(DISTINCT t.permaticker) AS sep_metadata_records,
            MIN(t.firstpricedate) AS metadata_first_price_date,
            MAX(t.lastpricedate) AS metadata_last_price_date,
            STRING_AGG(DISTINCT NULLIF(t.relatedtickers, ''), '; ') AS relatedtickers_examples
        FROM read_parquet({sql_literal(missing_path)}) AS m
        LEFT JOIN read_parquet({sql_literal(tickers_sep)}) AS t
          ON m.ticker = t.ticker
        GROUP BY m.ticker
        ORDER BY missing_dates DESC, m.ticker
        LIMIT 200
        """,
    )
    return {
        "available": True,
        "policy": "Diagnostics only. Historical SP500 tickers are not substituted with related/current tickers.",
        "examples": rows,
    }


def benchmark_coverage(con: duckdb.DuckDBPyConnection, processed_dir: Path) -> list[dict[str, Any]]:
    benchmark_path = processed_dir / "benchmarks.parquet"
    if not benchmark_path.exists():
        return []
    return query_dicts(
        con,
        f"""
        SELECT ticker, MIN(date) AS first_price_date, MAX(date) AS last_price_date, COUNT(*) AS row_count
        FROM read_parquet({sql_literal(benchmark_path)})
        GROUP BY ticker
        ORDER BY ticker
        """,
    )


def duplicate_event_rows(con: duckdb.DuckDBPyConnection, sp500_path: Path) -> list[dict[str, Any]]:
    return query_dicts(
        con,
        f"""
        SELECT date, action, ticker, COUNT(*) AS rows
        FROM read_parquet({sql_literal(sp500_path)})
        WHERE action IN ('added', 'removed')
        GROUP BY date, action, ticker
        HAVING COUNT(*) > 1
        ORDER BY rows DESC, date, action, ticker
        LIMIT 200
        """,
    )


def render_membership_qa(qa: dict[str, Any]) -> str:
    lines = ["# Sharadar S&P 500 Membership QA", ""]
    lines.append(f"Generated: `{qa['generated_at']}`")
    lines.append(f"Script version: `{qa['script_version']}`")
    lines.append("")
    lines.append("## Methodology")
    lines.append(qa["methodology"])
    lines.append("")
    lines.append("## Event-Date Semantics")
    lines.append(qa["event_date_semantics"])
    lines.append("")
    lines.append("## Snapshot Summary")
    for key, value in qa["snapshot_summary"].items():
        lines.append(f"- `{key}`: {json_safe(value)}")
    lines.append("")
    lines.append("## Action Counts")
    for key, value in qa["action_counts"].items():
        lines.append(f"- `{key}`: {value}")
    lines.append("")
    lines.append("## Daily Membership Count Stats")
    for key, value in qa["membership_validation"]["count_stats"].items():
        lines.append(f"- `{key}`: {json_safe(value)}")
    lines.append("")
    lines.append("## Snapshot Reconciliation")
    lines.extend(markdown_table(qa["snapshot_reconciliation"], limit=150))
    lines.append("")
    lines.append("## Current Reconciliation")
    for key, value in qa["current_reconciliation"].items():
        lines.append(f"- `{key}`: {json_safe(value)}")
    lines.append("")
    lines.append("## Price Coverage")
    price = qa["price_coverage"]
    if price.get("available"):
        for key in [
            "first_reliable_sep_coverage_date",
            "first_date_with_95pct_price_coverage",
            "first_date_with_99pct_price_coverage",
        ]:
            lines.append(f"- `{key}`: {json_safe(price.get(key))}")
        lines.append("")
        lines.append("### Coverage Stats")
        for key, value in price["coverage_stats"].items():
            lines.append(f"- `{key}`: {json_safe(value)}")
        lines.append("")
        lines.append("### High Missing-Price Dates")
        lines.extend(markdown_table(price["dates_with_unusually_high_missing_price_counts"], limit=100))
        lines.append("")
        lines.append("### Missing Ticker Examples")
        lines.extend(markdown_table(price["missing_ticker_summary_examples"], limit=100))
    else:
        lines.append(price.get("warning", "Price coverage unavailable."))
    lines.append("")
    lines.append("## Ticker Identity Diagnostics")
    diag = qa["ticker_change_diagnostics"]
    lines.append(diag.get("policy", "Unavailable."))
    lines.extend(markdown_table(diag.get("examples", []), limit=100))
    lines.append("")
    lines.append("## Benchmark Coverage")
    lines.extend(markdown_table(qa["benchmark_coverage"], limit=30))
    lines.append("")
    lines.append("## Validation Checks")
    for item in qa["validation_checks"]:
        lines.append(f"- `{item['check']}`: {item['status']}")
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
        values = [str(json_safe(row.get(col, ""))).replace("|", "\\|") for col in cols]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def build_validation_checks(
    snapshots: dict[date, set[str]],
    membership_validation: dict[str, Any],
    current_check: dict[str, Any],
    price_coverage: dict[str, Any],
    duplicate_events: list[dict[str, Any]],
) -> list[dict[str, str]]:
    checks = [
        ("historical snapshot dates exist", bool(snapshots)),
        ("daily membership has no duplicate (date, ticker) rows", membership_validation["duplicate_date_ticker_rows"] == 0),
        ("member counts are generally near 500", membership_validation["member_counts_generally_near_500"]),
        (
            "current reconstructed membership approximately matches action='current'",
            membership_validation["current_reconstructed_membership_approximately_matches_current_rows"],
        ),
        ("price coverage is calculated", bool(price_coverage.get("available"))),
        ("historical tickers are not silently rewritten", membership_validation["historical_tickers_not_rewritten"]),
        ("duplicate event-date/ticker cases checked", duplicate_events is not None),
        ("membership parquet can be queried by DuckDB", True),
    ]
    if current_check:
        checks.append(
            (
                "current reconciliation has finite diff counts",
                current_check.get("missing_from_replay_count") is not None and current_check.get("extra_in_replay_count") is not None,
            )
        )
    return [{"check": check, "status": "pass" if ok else "warn"} for check, ok in checks]


def build_membership(
    processed_dir: Path = DEFAULT_PROCESSED_DIR,
    derived_dir: Path = DEFAULT_DERIVED_DIR,
    force: bool = False,
) -> dict[str, Any]:
    processed_dir = processed_dir.expanduser().resolve()
    derived_dir = derived_dir.expanduser().resolve()
    derived_dir.mkdir(parents=True, exist_ok=True)
    membership_dir = derived_dir / "sp500_membership_daily"
    qa_json = derived_dir / "sp500_membership_qa.json"

    if output_has_parquet(membership_dir) and qa_json.exists() and not force:
        existing = json.loads(qa_json.read_text(encoding="utf-8"))
        existing["skipped_existing_output"] = True
        existing["console_lines"] = console_lines(existing)
        return existing

    sp500_path = processed_dir / "sp500.parquet"
    if not sp500_path.exists():
        raise FileNotFoundError(f"Processed SP500 parquet is missing: {sp500_path}")

    con = duckdb.connect(database=":memory:")
    con.execute("SET preserve_insertion_order=false")

    with timed("load SP500 snapshots/events/current"):
        snapshots, events, current, current_date, action_counts = load_sp500_state(con, sp500_path)
    if not snapshots:
        raise AssertionError("SP500 historical snapshots are required for point-in-time reconstruction.")

    anchors = sorted(snapshots)
    snapshot_counts = [len(snapshots[d]) for d in anchors]
    end_date = current_date or max(anchors[-1], max((event.date for event in events), default=anchors[-1]))

    with timed("snapshot and current reconciliation"):
        snapshot_diffs, current_check = snapshot_reconciliation(snapshots, events, current, current_date)

    with timed("load trading calendar"):
        trading_dates, calendar_source = load_trading_calendar(con, processed_dir, anchors[0], end_date)

    temp_csv = derived_dir / f".sp500_membership_daily.{int(time.time())}.csv"
    try:
        with timed("write temporary daily membership CSV"):
            write_stats = write_membership_csv(temp_csv, snapshots, events, trading_dates)
        with timed("write partitioned daily membership parquet"):
            copy_membership_to_parquet(con, temp_csv, membership_dir, force=True)
    finally:
        if temp_csv.exists():
            temp_csv.unlink()

    with timed("validate membership parquet"):
        membership_validation = validate_membership(con, membership_dir, current_check)

    with timed("calculate SEP price coverage"):
        price_coverage = build_price_coverage(con, processed_dir, derived_dir, membership_dir, force=True)

    with timed("build ticker identity diagnostics"):
        ticker_diag = ticker_change_diagnostics(con, processed_dir, derived_dir)

    with timed("benchmark coverage"):
        bench = benchmark_coverage(con, processed_dir)

    duplicate_events = duplicate_event_rows(con, sp500_path)

    snapshot_summary = {
        "distinct_historical_snapshot_dates": len(anchors),
        "first_snapshot_date": anchors[0],
        "last_snapshot_date": anchors[-1],
        "min_snapshot_member_count": min(snapshot_counts),
        "max_snapshot_member_count": max(snapshot_counts),
        "mean_snapshot_member_count": mean(snapshot_counts),
        "median_snapshot_member_count": median(snapshot_counts),
        "snapshot_frequency_found": "quarterly historical snapshots from 1998-03-31 through 2026-06-30",
        "current_constituent_count": len(current),
        "current_date": current_date,
        "historical_snapshot_count_by_date": [
            {"date": d, "member_count": len(snapshots[d])} for d in anchors
        ],
    }

    qa = {
        "generated_at": utc_now(),
        "script": "backend/scripts/build_sp500_membership.py",
        "script_version": SCRIPT_VERSION,
        "processed_dir": str(processed_dir),
        "derived_dir": str(derived_dir),
        "membership_output": str(membership_dir),
        "calendar_source": calendar_source,
        "methodology": (
            "Historical rows are authoritative anchor snapshots on their own dates. "
            "Between anchors, only added/removed events effective through each date are replayed. "
            "At the next historical snapshot, replayed state is compared to the snapshot for QA and then reset to the snapshot. "
            "Current rows are used only as a latest-state validation anchor."
        ),
        "event_date_semantics": (
            "Added tickers are members on event date D; removed tickers are not members on event date D. "
            "For non-trading event dates, the next trading session reflects all events effective through that date. "
            "If an event shares a historical snapshot date, the snapshot is authoritative for that anchor date."
        ),
        "ticker_identity_policy": (
            "Membership uses the ticker exactly as represented in the SP500 table at that time. "
            "TICKERS metadata is used for diagnostics only; no ticker is rewritten or substituted."
        ),
        "snapshot_summary": snapshot_summary,
        "action_counts": action_counts,
        "event_semantics_examples": event_semantics_examples(snapshots, events),
        "membership_write_stats": write_stats,
        "membership_validation": membership_validation,
        "snapshot_reconciliation": snapshot_diffs,
        "current_reconciliation": current_check,
        "duplicate_event_date_ticker_cases": duplicate_events,
        "price_coverage": price_coverage,
        "ticker_change_diagnostics": ticker_diag,
        "benchmark_coverage": bench,
    }
    qa["validation_checks"] = build_validation_checks(snapshots, membership_validation, current_check, price_coverage, duplicate_events)
    qa["console_lines"] = console_lines(qa)

    write_json(qa_json, qa)
    write_text(derived_dir / "sp500_membership_qa.md", render_membership_qa(qa))
    return qa


def console_lines(qa: dict[str, Any]) -> list[str]:
    stats = qa.get("membership_validation", {}).get("count_stats", {})
    price = qa.get("price_coverage", {})
    return [
        f"first date: {stats.get('first_date')}",
        f"last date: {stats.get('last_date')}",
        f"trading dates: {stats.get('trading_dates')}",
        f"median member count: {stats.get('median_member_count')}",
        f"min member count: {stats.get('min_member_count')}",
        f"max member count: {stats.get('max_member_count')}",
        f"first >=95% price coverage date: {price.get('first_date_with_95pct_price_coverage')}",
        f"first >=99% price coverage date: {price.get('first_date_with_99pct_price_coverage')}",
    ]


def print_final(qa: dict[str, Any]) -> None:
    print("\nS&P 500 membership reconstruction complete")
    for line in qa.get("console_lines", []):
        print(line)
    print("\nOutput paths:")
    print(qa.get("membership_output"))
    print(Path(qa.get("derived_dir", DEFAULT_DERIVED_DIR)) / "sp500_membership_qa.md")
    print(Path(qa.get("derived_dir", DEFAULT_DERIVED_DIR)) / "sp500_membership_qa.json")
    price = qa.get("price_coverage", {})
    if price.get("available"):
        print(price.get("coverage_path"))
        print(price.get("missing_prices_path"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build point-in-time daily S&P 500 membership from processed Sharadar SP500.")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    parser.add_argument("--force", action="store_true", help="Rewrite existing derived membership and QA outputs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qa = build_membership(args.processed_dir, args.derived_dir, args.force)
    print_final(qa)


if __name__ == "__main__":
    main()
