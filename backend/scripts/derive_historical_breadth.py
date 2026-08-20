#!/usr/bin/env python3
"""
Derive historical point-in-time S&P 500 breadth and market-internals features.

This script consumes the processed Sharadar Parquet layer and the reconstructed
daily S&P 500 membership panel. It writes daily aggregate research features and
forward outcome labels only; it does not optimize hedge rules, train models, or
create composite crash scores.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import random
import shutil
import statistics
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROCESSED_DIR = ROOT / "data" / "sharadar" / "processed"
DEFAULT_DERIVED_DIR = ROOT / "data" / "sharadar" / "derived"

SCRIPT_VERSION = "2026-08-15.1"
PRICE_COVERAGE_THRESHOLD = 95.0
MA_QUALITY_THRESHOLD = 90.0
BENCHMARKS = ["SPY", "QQQ", "IWM", "RSP"]
OUTCOME_BENCHMARKS = ["SPY", "QQQ", "IWM"]
FORWARD_HORIZONS = [5, 10, 21, 42, 63]
VELOCITY_HORIZONS = [1, 3, 5, 10, 20]
ACCEL_HORIZONS = [5, 10]
LOOKBACKS = [20, 50, 100, 200]
HIGH_LOW_LOOKBACKS = [20, 50, 252]
MIN_PRIOR_NORMALIZATION_OBS = 252


@contextmanager
def timed(label: str) -> Iterable[None]:
    started = time.perf_counter()
    print(f"-> {label}")
    try:
        yield
    finally:
        print(f"   done in {time.perf_counter() - started:.2f}s")


def sql_literal(value: str | Path | date) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value)
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
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
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


def output_exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def parse_date_arg(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def locate_inputs(processed_dir: Path, derived_dir: Path) -> dict[str, Path]:
    candidates = {
        "sep": processed_dir / "sep",
        "sfp": processed_dir / "sfp",
        "tickers": processed_dir / "tickers.parquet",
        "tickers_sep": processed_dir / "tickers_sep.parquet",
        "sp500": processed_dir / "sp500.parquet",
        "benchmarks": processed_dir / "benchmarks.parquet",
        "membership": derived_dir / "sp500_membership_daily",
        "membership_coverage": derived_dir / "sp500_membership_price_coverage.parquet",
    }
    missing = []
    for name, path in candidates.items():
        if name in {"sep", "sfp", "membership"}:
            if not path.exists() or not any(path.rglob("*.parquet")):
                missing.append(f"{name}: {path}")
        elif not path.exists():
            missing.append(f"{name}: {path}")
    if missing:
        raise FileNotFoundError("Missing required Sharadar processed/derived inputs:\n" + "\n".join(missing))
    return candidates


def date_filter_sql(start_date: date | None, end_date: date | None, alias: str | None = None) -> str:
    prefix = f"{alias}." if alias else ""
    clauses = []
    if start_date:
        clauses.append(f"{prefix}date >= {sql_literal(start_date)}")
    if end_date:
        clauses.append(f"{prefix}date <= {sql_literal(end_date)}")
    return " AND ".join(clauses) if clauses else "TRUE"


def create_membership_view(
    con: duckdb.DuckDBPyConnection,
    inputs: dict[str, Path],
    start_date: date | None,
    end_date: date | None,
) -> None:
    membership_path = parquet_glob(inputs["membership"])
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE membership AS
        SELECT date, ticker
        FROM read_parquet({sql_literal(membership_path)}, hive_partitioning=false)
        WHERE {date_filter_sql(start_date, end_date)}
        """
    )
    con.execute("CREATE OR REPLACE TEMP TABLE member_tickers AS SELECT DISTINCT ticker FROM membership")


def create_sep_features(con: duckdb.DuckDBPyConnection, inputs: dict[str, Path], end_date: date | None) -> None:
    sep_path = parquet_glob(inputs["sep"])
    end_filter = f"AND s.date <= {sql_literal(end_date)}" if end_date else ""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sep_features AS
        WITH sep_member AS (
            SELECT s.ticker, s.date, s.close, s.closeadj, s.volume
            FROM read_parquet({sql_literal(sep_path)}, hive_partitioning=false) AS s
            INNER JOIN member_tickers AS mt
              ON s.ticker = mt.ticker
            WHERE s.close IS NOT NULL
              {end_filter}
        ),
        w AS (
            SELECT
                ticker,
                date,
                close,
                closeadj,
                volume,
                LAG(close, 1) OVER (PARTITION BY ticker ORDER BY date) AS prior_close,
                LAG(close, 5) OVER (PARTITION BY ticker ORDER BY date) AS close_lag_5,
                LAG(close, 20) OVER (PARTITION BY ticker ORDER BY date) AS close_lag_20,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS cnt20,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS cnt50,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS ma50_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) AS cnt100,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 99 PRECEDING AND CURRENT ROW) AS ma100_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS cnt200,
                AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma200_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS hl_cnt20,
                MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS high20_raw,
                MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS low20_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS hl_cnt50,
                MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS high50_raw,
                MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS low50_raw,
                COUNT(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS hl_cnt252,
                MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high252_raw,
                MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low252_raw
            FROM sep_member
        )
        SELECT
            ticker,
            date,
            close,
            closeadj,
            volume,
            prior_close,
            CASE WHEN cnt20 = 20 THEN ma20_raw END AS ma20,
            CASE WHEN cnt50 = 50 THEN ma50_raw END AS ma50,
            CASE WHEN cnt100 = 100 THEN ma100_raw END AS ma100,
            CASE WHEN cnt200 = 200 THEN ma200_raw END AS ma200,
            CASE WHEN close_lag_5 IS NOT NULL AND close_lag_5 <> 0 THEN close / close_lag_5 - 1 END AS ret_5d,
            CASE WHEN close_lag_20 IS NOT NULL AND close_lag_20 <> 0 THEN close / close_lag_20 - 1 END AS ret_20d,
            CASE WHEN hl_cnt20 = 20 THEN high20_raw END AS high20,
            CASE WHEN hl_cnt20 = 20 THEN low20_raw END AS low20,
            CASE WHEN hl_cnt50 = 50 THEN high50_raw END AS high50,
            CASE WHEN hl_cnt50 = 50 THEN low50_raw END AS low50,
            CASE WHEN hl_cnt252 = 252 THEN high252_raw END AS high252,
            CASE WHEN hl_cnt252 = 252 THEN low252_raw END AS low252
        FROM w
        """
    )


def create_member_panel(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE member_panel AS
        SELECT
            m.date,
            m.ticker,
            f.close,
            f.closeadj,
            f.volume,
            f.prior_close,
            CASE WHEN f.prior_close IS NOT NULL AND f.prior_close <> 0 THEN f.close / f.prior_close - 1 END AS ret_1d,
            f.ret_5d,
            f.ret_20d,
            f.ma20,
            f.ma50,
            f.ma100,
            f.ma200,
            f.high20,
            f.low20,
            f.high50,
            f.low50,
            f.high252,
            f.low252
        FROM membership AS m
        LEFT JOIN sep_features AS f
          ON m.date = f.date
         AND m.ticker = f.ticker
        """
    )


def create_daily_breadth_base(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE daily_breadth_base AS
        WITH daily AS (
            SELECT
                date,
                COUNT(*) AS sp500_member_count,
                COUNT(close) AS sp500_price_count,

                COUNT(ma20) AS sp500_valid_ma20_count,
                COUNT(ma50) AS sp500_valid_ma50_count,
                COUNT(ma100) AS sp500_valid_ma100_count,
                COUNT(ma200) AS sp500_valid_ma200_count,

                SUM(CASE WHEN ma20 IS NOT NULL AND close > ma20 THEN 1 ELSE 0 END) AS above20,
                SUM(CASE WHEN ma50 IS NOT NULL AND close > ma50 THEN 1 ELSE 0 END) AS above50,
                SUM(CASE WHEN ma100 IS NOT NULL AND close > ma100 THEN 1 ELSE 0 END) AS above100,
                SUM(CASE WHEN ma200 IS NOT NULL AND close > ma200 THEN 1 ELSE 0 END) AS above200,

                AVG(CASE WHEN ma20 IS NOT NULL THEN 100.0 * (close / ma20 - 1) END) AS sp500_avg_dist_20d,
                MEDIAN(CASE WHEN ma20 IS NOT NULL THEN 100.0 * (close / ma20 - 1) END) AS sp500_median_dist_20d,
                AVG(CASE WHEN ma50 IS NOT NULL THEN 100.0 * (close / ma50 - 1) END) AS sp500_avg_dist_50d,
                MEDIAN(CASE WHEN ma50 IS NOT NULL THEN 100.0 * (close / ma50 - 1) END) AS sp500_median_dist_50d,
                AVG(CASE WHEN ma100 IS NOT NULL THEN 100.0 * (close / ma100 - 1) END) AS sp500_avg_dist_100d,
                MEDIAN(CASE WHEN ma100 IS NOT NULL THEN 100.0 * (close / ma100 - 1) END) AS sp500_median_dist_100d,
                AVG(CASE WHEN ma200 IS NOT NULL THEN 100.0 * (close / ma200 - 1) END) AS sp500_avg_dist_200d,
                MEDIAN(CASE WHEN ma200 IS NOT NULL THEN 100.0 * (close / ma200 - 1) END) AS sp500_median_dist_200d,

                COUNT(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL THEN 1 END) AS sp500_valid_ad_count,
                SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close > prior_close THEN 1 ELSE 0 END) AS sp500_advances,
                SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close < prior_close THEN 1 ELSE 0 END) AS sp500_declines,
                SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close = prior_close THEN 1 ELSE 0 END) AS sp500_unchanged,

                COUNT(ret_1d) AS sp500_valid_return_1d_count,
                COUNT(ret_5d) AS sp500_valid_return_5d_count,
                COUNT(ret_20d) AS sp500_valid_return_20d_count,
                SUM(CASE WHEN ret_1d > 0 THEN 1 ELSE 0 END) AS positive_1d,
                SUM(CASE WHEN ret_5d > 0 THEN 1 ELSE 0 END) AS positive_5d,
                SUM(CASE WHEN ret_20d > 0 THEN 1 ELSE 0 END) AS positive_20d,
                AVG(ret_1d) AS sp500_avg_return_1d,
                MEDIAN(ret_1d) AS sp500_median_return_1d,
                STDDEV_SAMP(ret_1d) AS sp500_return_dispersion_1d,
                AVG(ret_5d) AS sp500_avg_return_5d,
                MEDIAN(ret_5d) AS sp500_median_return_5d,
                STDDEV_SAMP(ret_5d) AS sp500_return_dispersion_5d,
                AVG(ret_20d) AS sp500_avg_return_20d,
                MEDIAN(ret_20d) AS sp500_median_return_20d,
                STDDEV_SAMP(ret_20d) AS sp500_return_dispersion_20d,

                COUNT(high20) AS sp500_valid_highlow20_count,
                COUNT(high50) AS sp500_valid_highlow50_count,
                COUNT(high252) AS sp500_valid_252d_count,
                SUM(CASE WHEN high20 IS NOT NULL AND close >= high20 THEN 1 ELSE 0 END) AS sp500_new_highs_20d,
                SUM(CASE WHEN low20 IS NOT NULL AND close <= low20 THEN 1 ELSE 0 END) AS sp500_new_lows_20d,
                SUM(CASE WHEN high50 IS NOT NULL AND close >= high50 THEN 1 ELSE 0 END) AS sp500_new_highs_50d,
                SUM(CASE WHEN low50 IS NOT NULL AND close <= low50 THEN 1 ELSE 0 END) AS sp500_new_lows_50d,
                SUM(CASE WHEN high252 IS NOT NULL AND close >= high252 THEN 1 ELSE 0 END) AS sp500_new_highs_252d,
                SUM(CASE WHEN low252 IS NOT NULL AND close <= low252 THEN 1 ELSE 0 END) AS sp500_new_lows_252d
            FROM member_panel
            GROUP BY date
        )
        SELECT
            date,
            sp500_member_count,
            sp500_price_count,
            100.0 * sp500_price_count / NULLIF(sp500_member_count, 0) AS sp500_price_coverage_pct,

            sp500_valid_ma20_count,
            sp500_valid_ma50_count,
            sp500_valid_ma100_count,
            sp500_valid_ma200_count,
            100.0 * sp500_valid_ma20_count / NULLIF(sp500_member_count, 0) AS sp500_ma20_coverage_pct,
            100.0 * sp500_valid_ma50_count / NULLIF(sp500_member_count, 0) AS sp500_ma50_coverage_pct,
            100.0 * sp500_valid_ma100_count / NULLIF(sp500_member_count, 0) AS sp500_ma100_coverage_pct,
            100.0 * sp500_valid_ma200_count / NULLIF(sp500_member_count, 0) AS sp500_ma200_coverage_pct,

            100.0 * above20 / NULLIF(sp500_valid_ma20_count, 0) AS sp500_pct_above_20d,
            100.0 * above50 / NULLIF(sp500_valid_ma50_count, 0) AS sp500_pct_above_50d,
            100.0 * above100 / NULLIF(sp500_valid_ma100_count, 0) AS sp500_pct_above_100d,
            100.0 * above200 / NULLIF(sp500_valid_ma200_count, 0) AS sp500_pct_above_200d,

            sp500_avg_dist_20d,
            sp500_median_dist_20d,
            sp500_avg_dist_50d,
            sp500_median_dist_50d,
            sp500_avg_dist_100d,
            sp500_median_dist_100d,
            sp500_avg_dist_200d,
            sp500_median_dist_200d,

            sp500_advances,
            sp500_declines,
            sp500_unchanged,
            sp500_valid_ad_count,
            sp500_advances - sp500_declines AS sp500_net_advances,
            CASE
                WHEN sp500_advances + sp500_declines > 0
                THEN 1.0 * (sp500_advances - sp500_declines) / (sp500_advances + sp500_declines)
            END AS sp500_ad_balance,

            sp500_valid_return_1d_count,
            sp500_valid_return_5d_count,
            sp500_valid_return_20d_count,
            100.0 * positive_1d / NULLIF(sp500_valid_return_1d_count, 0) AS sp500_pct_positive_1d,
            100.0 * positive_5d / NULLIF(sp500_valid_return_5d_count, 0) AS sp500_pct_positive_5d,
            100.0 * positive_20d / NULLIF(sp500_valid_return_20d_count, 0) AS sp500_pct_positive_20d,
            sp500_avg_return_1d,
            sp500_median_return_1d,
            sp500_return_dispersion_1d,
            sp500_avg_return_5d,
            sp500_median_return_5d,
            sp500_return_dispersion_5d,
            sp500_avg_return_20d,
            sp500_median_return_20d,
            sp500_return_dispersion_20d,

            sp500_valid_highlow20_count,
            sp500_valid_highlow50_count,
            sp500_valid_252d_count,
            sp500_new_highs_20d,
            sp500_new_lows_20d,
            100.0 * sp500_new_highs_20d / NULLIF(sp500_valid_highlow20_count, 0) AS sp500_pct_new_high_20d,
            100.0 * sp500_new_lows_20d / NULLIF(sp500_valid_highlow20_count, 0) AS sp500_pct_new_low_20d,
            sp500_new_highs_20d - sp500_new_lows_20d AS sp500_nhnl_20d,
            1.0 * (sp500_new_highs_20d - sp500_new_lows_20d) / NULLIF(sp500_valid_highlow20_count, 0) AS sp500_normalized_nhnl_20d,
            sp500_new_highs_50d,
            sp500_new_lows_50d,
            100.0 * sp500_new_highs_50d / NULLIF(sp500_valid_highlow50_count, 0) AS sp500_pct_new_high_50d,
            100.0 * sp500_new_lows_50d / NULLIF(sp500_valid_highlow50_count, 0) AS sp500_pct_new_low_50d,
            sp500_new_highs_50d - sp500_new_lows_50d AS sp500_nhnl_50d,
            1.0 * (sp500_new_highs_50d - sp500_new_lows_50d) / NULLIF(sp500_valid_highlow50_count, 0) AS sp500_normalized_nhnl_50d,
            sp500_new_highs_252d,
            sp500_new_lows_252d,
            100.0 * sp500_new_highs_252d / NULLIF(sp500_valid_252d_count, 0) AS sp500_pct_new_high_252d,
            100.0 * sp500_new_lows_252d / NULLIF(sp500_valid_252d_count, 0) AS sp500_pct_new_low_252d,
            sp500_new_highs_252d - sp500_new_lows_252d AS sp500_nhnl_252d,
            1.0 * (sp500_new_highs_252d - sp500_new_lows_252d) / NULLIF(sp500_valid_252d_count, 0) AS sp500_normalized_nhnl_252d
        FROM daily
        ORDER BY date
        """
    )


def assess_sector_mapping(con: duckdb.DuckDBPyConnection, inputs: dict[str, Path]) -> dict[str, Any]:
    tickers_sep = inputs["tickers_sep"]
    duplicate_sep_tickers = int(
        query_scalar(
            con,
            f"""
            SELECT COUNT(*) FROM (
                SELECT ticker
                FROM read_parquet({sql_literal(tickers_sep)})
                GROUP BY ticker
                HAVING COUNT(*) > 1
            )
            """,
        )
        or 0
    )
    coverage = query_dicts(
        con,
        f"""
        SELECT
            COUNT(*) AS membership_rows,
            COUNT(NULLIF(t.sector, '')) AS rows_with_sector,
            100.0 * COUNT(NULLIF(t.sector, '')) / COUNT(*) AS pct_rows_with_sector,
            COUNT(DISTINCT m.ticker) AS membership_tickers,
            COUNT(DISTINCT CASE WHEN NULLIF(t.sector, '') IS NOT NULL THEN m.ticker END) AS tickers_with_sector
        FROM membership AS m
        LEFT JOIN read_parquet({sql_literal(tickers_sep)}) AS t
          ON m.ticker = t.ticker
        """
    )[0]
    sector_counts = query_dicts(
        con,
        f"""
        SELECT COALESCE(NULLIF(t.sector, ''), '__missing__') AS sector,
               COUNT(DISTINCT m.ticker) AS tickers,
               COUNT(*) AS membership_rows
        FROM membership AS m
        LEFT JOIN read_parquet({sql_literal(tickers_sep)}) AS t
          ON m.ticker = t.ticker
        GROUP BY 1
        ORDER BY membership_rows DESC
        """
    )
    ok = duplicate_sep_tickers == 0 and float(coverage["pct_rows_with_sector"] or 0) >= 95.0
    reason = "usable" if ok else "ambiguous duplicate SEP ticker metadata or insufficient sector coverage"
    return {
        "created": ok,
        "reason": reason,
        "duplicate_sep_ticker_metadata_rows": duplicate_sep_tickers,
        "coverage": coverage,
        "sector_counts": sector_counts,
        "caveat": "Sharadar TICKERS sector labels are security-master metadata from the download, not point-in-time historical GICS classifications.",
    }


def create_sector_breadth(
    con: duckdb.DuckDBPyConnection,
    inputs: dict[str, Path],
    sector_output: Path,
    force: bool,
) -> dict[str, Any]:
    sector_info = assess_sector_mapping(con, inputs)
    if not sector_info["created"]:
        return sector_info
    if sector_output.exists() and not force:
        sector_info["reason"] = "existing output reused"
    else:
        if sector_output.exists():
            sector_output.unlink()
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE sector_breadth_daily AS
            WITH sector_panel AS (
                SELECT
                    p.*,
                    NULLIF(t.sector, '') AS sector
                FROM member_panel AS p
                LEFT JOIN read_parquet({sql_literal(inputs["tickers_sep"])}) AS t
                  ON p.ticker = t.ticker
                WHERE NULLIF(t.sector, '') IS NOT NULL
            ),
            sector_daily AS (
                SELECT
                    date,
                    sector,
                    COUNT(*) AS member_count,
                    COUNT(ma20) AS valid_ma20_count,
                    COUNT(ma50) AS valid_ma50_count,
                    COUNT(ma200) AS valid_ma200_count,
                    SUM(CASE WHEN ma20 IS NOT NULL AND close > ma20 THEN 1 ELSE 0 END) AS above20,
                    SUM(CASE WHEN ma50 IS NOT NULL AND close > ma50 THEN 1 ELSE 0 END) AS above50,
                    SUM(CASE WHEN ma200 IS NOT NULL AND close > ma200 THEN 1 ELSE 0 END) AS above200,
                    SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close > prior_close THEN 1 ELSE 0 END) AS advances,
                    SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close < prior_close THEN 1 ELSE 0 END) AS declines,
                    AVG(CASE WHEN ma50 IS NOT NULL THEN 100.0 * (close / ma50 - 1) END) AS avg_dist_50d,
                    AVG(CASE WHEN ma200 IS NOT NULL THEN 100.0 * (close / ma200 - 1) END) AS avg_dist_200d,
                    MEDIAN(ret_20d) AS median_return_20d
                FROM sector_panel
                GROUP BY date, sector
            )
            SELECT
                date,
                sector,
                member_count,
                100.0 * above20 / NULLIF(valid_ma20_count, 0) AS pct_above_20d,
                100.0 * above50 / NULLIF(valid_ma50_count, 0) AS pct_above_50d,
                100.0 * above200 / NULLIF(valid_ma200_count, 0) AS pct_above_200d,
                CASE WHEN advances + declines > 0 THEN 1.0 * (advances - declines) / (advances + declines) END AS ad_balance,
                avg_dist_50d,
                avg_dist_200d,
                median_return_20d
            FROM sector_daily
            ORDER BY date, sector
            """
        )
        con.execute(
            f"""
            COPY (SELECT * FROM sector_breadth_daily)
            TO {sql_literal(sector_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE sector_breadth_daily AS
        SELECT * FROM read_parquet({sql_literal(sector_output)})
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE sector_deterioration_daily AS
        WITH s AS (
            SELECT
                date,
                sector,
                pct_above_50d,
                pct_above_200d,
                LAG(pct_above_50d, 5) OVER (PARTITION BY sector ORDER BY date) AS pct_above_50d_lag5,
                LAG(pct_above_50d, 10) OVER (PARTITION BY sector ORDER BY date) AS pct_above_50d_lag10,
                LAG(pct_above_200d, 10) OVER (PARTITION BY sector ORDER BY date) AS pct_above_200d_lag10
            FROM sector_breadth_daily
        )
        SELECT
            date,
            100.0 * SUM(CASE WHEN pct_above_50d IS NOT NULL AND pct_above_50d_lag5 IS NOT NULL AND pct_above_50d < pct_above_50d_lag5 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(CASE WHEN pct_above_50d IS NOT NULL AND pct_above_50d_lag5 IS NOT NULL THEN 1 END), 0)
                AS pct_sectors_pct_above_50d_declining_5d,
            100.0 * SUM(CASE WHEN pct_above_50d IS NOT NULL AND pct_above_50d_lag10 IS NOT NULL AND pct_above_50d < pct_above_50d_lag10 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(CASE WHEN pct_above_50d IS NOT NULL AND pct_above_50d_lag10 IS NOT NULL THEN 1 END), 0)
                AS pct_sectors_pct_above_50d_declining_10d,
            100.0 * SUM(CASE WHEN pct_above_200d IS NOT NULL AND pct_above_200d_lag10 IS NOT NULL AND pct_above_200d < pct_above_200d_lag10 THEN 1 ELSE 0 END)
                / NULLIF(COUNT(CASE WHEN pct_above_200d IS NOT NULL AND pct_above_200d_lag10 IS NOT NULL THEN 1 END), 0)
                AS pct_sectors_pct_above_200d_declining_10d
        FROM s
        GROUP BY date
        ORDER BY date
        """
    )
    stats = query_dicts(
        con,
        """
        SELECT COUNT(*) AS rows, MIN(date) AS first_date, MAX(date) AS last_date,
               COUNT(DISTINCT sector) AS sectors
        FROM sector_breadth_daily
        """
    )[0]
    sector_info["stats"] = stats
    return sector_info


def fetch_daily_base(con: duckdb.DuckDBPyConnection, include_sector: bool) -> list[dict[str, Any]]:
    if include_sector:
        return query_dicts(
            con,
            """
            SELECT b.*, s.pct_sectors_pct_above_50d_declining_5d,
                   s.pct_sectors_pct_above_50d_declining_10d,
                   s.pct_sectors_pct_above_200d_declining_10d
            FROM daily_breadth_base AS b
            LEFT JOIN sector_deterioration_daily AS s
              ON b.date = s.date
            ORDER BY b.date
            """,
        )
    return query_dicts(con, "SELECT * FROM daily_breadth_base ORDER BY date")


def load_benchmark_rows(con: duckdb.DuckDBPyConnection, inputs: dict[str, Path]) -> dict[str, list[dict[str, Any]]]:
    rows = query_dicts(
        con,
        f"""
        SELECT ticker, date, close, closeadj
        FROM read_parquet({sql_literal(inputs["benchmarks"])})
        WHERE ticker IN ({", ".join(sql_literal(t) for t in BENCHMARKS)})
        ORDER BY ticker, date
        """,
    )
    by_ticker: dict[str, list[dict[str, Any]]] = {ticker: [] for ticker in BENCHMARKS}
    for row in rows:
        by_ticker.setdefault(row["ticker"], []).append(row)
    return by_ticker


def rolling_mean(values: list[float], end_idx: int, window: int) -> float | None:
    if end_idx + 1 < window:
        return None
    vals = values[end_idx - window + 1 : end_idx + 1]
    if any(v is None for v in vals):  # type: ignore[comparison-overlap]
        return None
    return sum(vals) / window


def rolling_max(values: list[float], end_idx: int, window: int) -> float | None:
    if end_idx + 1 < window:
        return None
    vals = values[end_idx - window + 1 : end_idx + 1]
    if any(v is None for v in vals):  # type: ignore[comparison-overlap]
        return None
    return max(vals)


def build_benchmark_features(benchmark_rows: dict[str, list[dict[str, Any]]]) -> dict[date, dict[str, Any]]:
    features: dict[date, dict[str, Any]] = {}
    ratio_by_date: dict[date, float] = {}

    for ticker, rows in benchmark_rows.items():
        closes = [float(row["close"]) if row["close"] is not None else None for row in rows]
        closeadjs = [float(row["closeadj"]) if row["closeadj"] is not None else None for row in rows]
        for i, row in enumerate(rows):
            d = row["date"]
            close = closes[i]
            if d not in features:
                features[d] = {}
            features[d][f"{ticker}_close"] = close
            if i >= 1 and closes[i - 1] not in (None, 0) and close is not None:
                features[d][f"{ticker}_return_1d"] = close / closes[i - 1] - 1  # type: ignore[operator]
            else:
                features[d][f"{ticker}_return_1d"] = None

            if ticker == "SPY":
                for window in (20, 50, 200):
                    ma = rolling_mean(closes, i, window)  # type: ignore[arg-type]
                    features[d][f"SPY_ma{window}"] = ma
                    features[d][f"SPY_dist_{window}d"] = 100.0 * (close / ma - 1) if close is not None and ma else None
                high_52w = rolling_max(closes, i, 252)  # type: ignore[arg-type]
                features[d]["SPY_trailing_52w_high"] = high_52w
                pct_below = 100.0 * (close / high_52w - 1) if close is not None and high_52w else None
                features[d]["SPY_pct_below_52w_high"] = pct_below
                features[d]["SPY_within_1pct_high"] = bool(pct_below is not None and pct_below >= -1.0)
                features[d]["SPY_within_3pct_high"] = bool(pct_below is not None and pct_below >= -3.0)
                features[d]["SPY_within_5pct_high"] = bool(pct_below is not None and pct_below >= -5.0)

            if ticker in OUTCOME_BENCHMARKS:
                for horizon in FORWARD_HORIZONS:
                    if i + horizon < len(rows) and closeadjs[i] not in (None, 0) and closeadjs[i + horizon] is not None:
                        features[d][f"{ticker}_fwd_return_{horizon}d"] = closeadjs[i + horizon] / closeadjs[i] - 1  # type: ignore[operator]
                        path = closeadjs[i : i + horizon + 1]
                        running_max = None
                        maxdd = 0.0
                        valid_path = True
                        for price in path:
                            if price is None:
                                valid_path = False
                                break
                            running_max = price if running_max is None else max(running_max, price)
                            dd = price / running_max - 1
                            maxdd = min(maxdd, dd)
                        features[d][f"{ticker}_fwd_maxdd_{horizon}d"] = maxdd if valid_path else None
                    else:
                        features[d][f"{ticker}_fwd_return_{horizon}d"] = None
                        features[d][f"{ticker}_fwd_maxdd_{horizon}d"] = None

    for d, fields in features.items():
        spy = fields.get("SPY_close")
        rsp = fields.get("RSP_close")
        if spy not in (None, 0) and rsp is not None:
            ratio_by_date[d] = rsp / spy
            fields["rsp_spy_ratio"] = ratio_by_date[d]
        else:
            fields["rsp_spy_ratio"] = None

    ratio_dates = sorted(ratio_by_date)
    ratios = [ratio_by_date[d] for d in ratio_dates]
    for i, d in enumerate(ratio_dates):
        ratio = ratios[i]
        for horizon in (5, 10, 20):
            if i >= horizon and ratios[i - horizon] != 0:
                features[d][f"rsp_spy_return_{horizon}d"] = ratio / ratios[i - horizon] - 1
            else:
                features[d][f"rsp_spy_return_{horizon}d"] = None
        if i + 1 >= 252:
            vals = ratios[i - 251 : i + 1]
            avg = sum(vals) / 252
            std = statistics.stdev(vals)
            features[d]["rsp_spy_z_252d"] = (ratio - avg) / std if std else None
        else:
            features[d]["rsp_spy_z_252d"] = None

    return features


def linear_slope(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    denom = sum((i - x_mean) ** 2 for i in range(n))
    if denom == 0:
        return None
    return sum((i - x_mean) * (values[i] - y_mean) for i in range(n)) / denom


def add_adl_and_slopes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    adl_started = False
    first_adl_date = None
    raw_adl = 0.0
    normalized_adl = 0.0
    valid_adl_values: list[float] = []
    for row in rows:
        coverage = row.get("sp500_price_coverage_pct")
        if not adl_started and coverage is not None and coverage >= PRICE_COVERAGE_THRESHOLD:
            adl_started = True
            first_adl_date = row["date"]
        if adl_started:
            raw_adl += float(row.get("sp500_net_advances") or 0)
            balance = row.get("sp500_ad_balance")
            if balance is not None:
                normalized_adl += float(balance)
            row["sp500_adl_raw"] = raw_adl
            row["sp500_adl_normalized"] = normalized_adl
            valid_adl_values.append(normalized_adl)
            for window in (5, 10, 20, 50):
                row[f"sp500_adl_slope_{window}d"] = (
                    linear_slope(valid_adl_values[-window:]) if len(valid_adl_values) >= window else None
                )
        else:
            row["sp500_adl_raw"] = None
            row["sp500_adl_normalized"] = None
            for window in (5, 10, 20, 50):
                row[f"sp500_adl_slope_{window}d"] = None
    return {"first_adl_date": first_adl_date}


def add_changes(rows: list[dict[str, Any]]) -> None:
    bases = [
        "sp500_pct_above_20d",
        "sp500_pct_above_50d",
        "sp500_pct_above_100d",
        "sp500_pct_above_200d",
        "sp500_ad_balance",
        "sp500_adl_slope_20d",
        "sp500_pct_positive_20d",
        "sp500_pct_new_low_252d",
        "sp500_normalized_nhnl_252d",
    ]
    for i, row in enumerate(rows):
        for base in bases:
            current = row.get(base)
            for horizon in VELOCITY_HORIZONS:
                field = f"{base}_chg_{horizon}d"
                previous = rows[i - horizon].get(base) if i >= horizon else None
                row[field] = current - previous if current is not None and previous is not None else None

    for i, row in enumerate(rows):
        for base in ("sp500_pct_above_20d", "sp500_pct_above_50d", "sp500_pct_above_200d"):
            for horizon in ACCEL_HORIZONS:
                chg_field = f"{base}_chg_{horizon}d"
                accel_field = f"{base}_accel_{horizon}d"
                current = row.get(chg_field)
                previous = rows[i - horizon].get(chg_field) if i >= horizon else None
                row[accel_field] = current - previous if current is not None and previous is not None else None


def add_expanding_normalization(rows: list[dict[str, Any]]) -> None:
    fields = [
        "sp500_pct_above_20d",
        "sp500_pct_above_50d",
        "sp500_pct_above_200d",
        "sp500_pct_above_20d_chg_5d",
        "sp500_pct_above_50d_chg_5d",
        "sp500_pct_above_50d_chg_10d",
        "sp500_pct_above_200d_chg_10d",
        "sp500_adl_slope_20d",
        "sp500_ad_balance",
        "sp500_pct_new_low_252d",
        "sp500_normalized_nhnl_252d",
    ]
    state = {
        field: {"count": 0, "sum": 0.0, "sum_sq": 0.0, "sorted": []}
        for field in fields
    }
    for row in rows:
        for field in fields:
            value = row.get(field)
            s = state[field]
            z_field = f"{field}_z"
            pct_field = f"{field}_pctile"
            if value is not None and s["count"] >= MIN_PRIOR_NORMALIZATION_OBS:
                count = s["count"]
                avg = s["sum"] / count
                variance = (s["sum_sq"] - (s["sum"] ** 2) / count) / (count - 1) if count > 1 else 0.0
                std = math.sqrt(max(variance, 0.0))
                row[z_field] = (value - avg) / std if std else None
                row[pct_field] = 100.0 * bisect.bisect_right(s["sorted"], value) / count
            else:
                row[z_field] = None
                row[pct_field] = None

        for field in fields:
            value = row.get(field)
            if value is None:
                continue
            s = state[field]
            s["count"] += 1
            s["sum"] += float(value)
            s["sum_sq"] += float(value) * float(value)
            bisect.insort(s["sorted"], float(value))


def add_benchmark_fields(rows: list[dict[str, Any]], benchmark_features: dict[date, dict[str, Any]]) -> None:
    for row in rows:
        row.update(benchmark_features.get(row["date"], {}))
        for ticker in OUTCOME_BENCHMARKS:
            for horizon in FORWARD_HORIZONS:
                dd = row.get(f"{ticker}_fwd_maxdd_{horizon}d")
                row[f"{ticker}_fwd{horizon}_dd_ge_5pct"] = int(dd is not None and dd <= -0.05)
                row[f"{ticker}_fwd{horizon}_dd_ge_7_5pct"] = int(dd is not None and dd <= -0.075)
                row[f"{ticker}_fwd{horizon}_dd_ge_10pct"] = int(dd is not None and dd <= -0.10)


def add_divergence_flags(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        within3 = bool(row.get("SPY_within_3pct_high"))
        for ma in (20, 50):
            change = row.get(f"sp500_pct_above_{ma}d_chg_10d")
            for threshold in (10, 20, 30):
                field = f"SPY_within_3pct_high_and_sp500_pct_above_{ma}d_down_{threshold}pp_10d"
                row[field] = int(within3 and change is not None and change <= -float(threshold))
        row["sp500_breadth_divergence_50d"] = row["SPY_within_3pct_high_and_sp500_pct_above_50d_down_10pp_10d"]
        row["sp500_breadth_divergence_20d"] = row["SPY_within_3pct_high_and_sp500_pct_above_20d_down_10pp_10d"]


def add_data_quality_ok(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        ok = (
            (row.get("sp500_price_coverage_pct") or 0) >= PRICE_COVERAGE_THRESHOLD
            and (row.get("sp500_ma20_coverage_pct") or 0) >= MA_QUALITY_THRESHOLD
            and (row.get("sp500_ma50_coverage_pct") or 0) >= MA_QUALITY_THRESHOLD
            and (row.get("sp500_ma100_coverage_pct") or 0) >= MA_QUALITY_THRESHOLD
            and (row.get("sp500_ma200_coverage_pct") or 0) >= MA_QUALITY_THRESHOLD
            and 100.0 * (row.get("sp500_valid_252d_count") or 0) / max(row.get("sp500_member_count") or 1, 1) >= MA_QUALITY_THRESHOLD
        )
        row["breadth_data_quality_ok"] = int(ok)


def first_date_where(rows: list[dict[str, Any]], predicate) -> date | None:
    for row in rows:
        if predicate(row):
            return row["date"]
    return None


def feature_first_dates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "first_membership_date": rows[0]["date"] if rows else None,
        "first_price_coverage_ge_95": first_date_where(rows, lambda r: (r.get("sp500_price_coverage_pct") or 0) >= 95.0),
        "first_ma20_breadth_sufficient": first_date_where(rows, lambda r: (r.get("sp500_ma20_coverage_pct") or 0) >= 90.0),
        "first_ma50_breadth_sufficient": first_date_where(rows, lambda r: (r.get("sp500_ma50_coverage_pct") or 0) >= 90.0),
        "first_ma100_breadth_sufficient": first_date_where(rows, lambda r: (r.get("sp500_ma100_coverage_pct") or 0) >= 90.0),
        "first_ma200_breadth_sufficient": first_date_where(rows, lambda r: (r.get("sp500_ma200_coverage_pct") or 0) >= 90.0),
        "first_252d_breadth_sufficient": first_date_where(
            rows,
            lambda r: 100.0 * (r.get("sp500_valid_252d_count") or 0) / max(r.get("sp500_member_count") or 1, 1) >= 90.0,
        ),
        "first_adl_date": first_date_where(rows, lambda r: r.get("sp500_adl_normalized") is not None),
        "first_normalized_signal_date": first_date_where(rows, lambda r: r.get("sp500_pct_above_50d_chg_10d_z") is not None),
    }


def final_column_order(rows: list[dict[str, Any]], include_sector: bool) -> list[str]:
    data_quality = [
        "date",
        "sp500_member_count",
        "sp500_price_count",
        "sp500_price_coverage_pct",
        "sp500_valid_ma20_count",
        "sp500_valid_ma50_count",
        "sp500_valid_ma100_count",
        "sp500_valid_ma200_count",
        "sp500_ma20_coverage_pct",
        "sp500_ma50_coverage_pct",
        "sp500_ma100_coverage_pct",
        "sp500_ma200_coverage_pct",
        "sp500_valid_highlow20_count",
        "sp500_valid_highlow50_count",
        "sp500_valid_252d_count",
        "breadth_data_quality_ok",
    ]
    market = [f"{t}_close" for t in BENCHMARKS] + [f"{t}_return_1d" for t in BENCHMARKS]
    ma_breadth = [f"sp500_pct_above_{w}d" for w in LOOKBACKS]
    distance = []
    for w in LOOKBACKS:
        distance.extend([f"sp500_avg_dist_{w}d", f"sp500_median_dist_{w}d"])
    ad = [
        "sp500_advances",
        "sp500_declines",
        "sp500_unchanged",
        "sp500_valid_ad_count",
        "sp500_net_advances",
        "sp500_ad_balance",
        "sp500_adl_raw",
        "sp500_adl_normalized",
        "sp500_adl_slope_5d",
        "sp500_adl_slope_10d",
        "sp500_adl_slope_20d",
        "sp500_adl_slope_50d",
    ]
    nhnl = []
    for w in HIGH_LOW_LOOKBACKS:
        nhnl.extend(
            [
                f"sp500_new_highs_{w}d",
                f"sp500_new_lows_{w}d",
                f"sp500_pct_new_high_{w}d",
                f"sp500_pct_new_low_{w}d",
                f"sp500_nhnl_{w}d",
                f"sp500_normalized_nhnl_{w}d",
            ]
        )
    participation = []
    for w in (1, 5, 20):
        participation.extend(
            [
                f"sp500_valid_return_{w}d_count",
                f"sp500_pct_positive_{w}d",
                f"sp500_avg_return_{w}d",
                f"sp500_median_return_{w}d",
                f"sp500_return_dispersion_{w}d",
            ]
        )
    velocity_bases = [
        "sp500_pct_above_20d",
        "sp500_pct_above_50d",
        "sp500_pct_above_100d",
        "sp500_pct_above_200d",
        "sp500_ad_balance",
        "sp500_adl_slope_20d",
        "sp500_pct_positive_20d",
        "sp500_pct_new_low_252d",
        "sp500_normalized_nhnl_252d",
    ]
    velocity = [f"{base}_chg_{h}d" for base in velocity_bases for h in VELOCITY_HORIZONS]
    acceleration = [
        f"sp500_pct_above_{w}d_accel_{h}d"
        for w in (20, 50, 200)
        for h in ACCEL_HORIZONS
    ]
    normalization_sources = [
        "sp500_pct_above_20d",
        "sp500_pct_above_50d",
        "sp500_pct_above_200d",
        "sp500_pct_above_20d_chg_5d",
        "sp500_pct_above_50d_chg_5d",
        "sp500_pct_above_50d_chg_10d",
        "sp500_pct_above_200d_chg_10d",
        "sp500_adl_slope_20d",
        "sp500_ad_balance",
        "sp500_pct_new_low_252d",
        "sp500_normalized_nhnl_252d",
    ]
    normalization = [f"{base}_{suffix}" for base in normalization_sources for suffix in ("z", "pctile")]
    spy_state = [
        "SPY_ma20",
        "SPY_ma50",
        "SPY_ma200",
        "SPY_dist_20d",
        "SPY_dist_50d",
        "SPY_dist_200d",
        "SPY_trailing_52w_high",
        "SPY_pct_below_52w_high",
        "SPY_within_1pct_high",
        "SPY_within_3pct_high",
        "SPY_within_5pct_high",
    ]
    rsp_spy = ["rsp_spy_ratio", "rsp_spy_return_5d", "rsp_spy_return_10d", "rsp_spy_return_20d", "rsp_spy_z_252d"]
    sector_fields = (
        [
            "pct_sectors_pct_above_50d_declining_5d",
            "pct_sectors_pct_above_50d_declining_10d",
            "pct_sectors_pct_above_200d_declining_10d",
        ]
        if include_sector
        else []
    )
    divergence = [
        "sp500_breadth_divergence_50d",
        "sp500_breadth_divergence_20d",
    ]
    for ma in (20, 50):
        for threshold in (10, 20, 30):
            divergence.append(f"SPY_within_3pct_high_and_sp500_pct_above_{ma}d_down_{threshold}pp_10d")
    fwd_returns = [f"{ticker}_fwd_return_{h}d" for ticker in OUTCOME_BENCHMARKS for h in FORWARD_HORIZONS]
    fwd_dd = [f"{ticker}_fwd_maxdd_{h}d" for ticker in OUTCOME_BENCHMARKS for h in FORWARD_HORIZONS]
    labels = [
        f"{ticker}_fwd{h}_dd_ge_{threshold}"
        for ticker in OUTCOME_BENCHMARKS
        for h in FORWARD_HORIZONS
        for threshold in ("5pct", "7_5pct", "10pct")
    ]
    ordered = (
        data_quality
        + market
        + ma_breadth
        + distance
        + ad
        + nhnl
        + participation
        + velocity
        + acceleration
        + normalization
        + spy_state
        + rsp_spy
        + sector_fields
        + divergence
        + fwd_returns
        + fwd_dd
        + labels
    )
    all_keys = []
    for row in rows:
        for key in row:
            if key not in all_keys:
                all_keys.append(key)
    return [key for key in ordered if key in all_keys] + [key for key in all_keys if key not in ordered]


def write_daily_outputs(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
    columns: list[str],
    csv_output: Path,
    parquet_output: Path,
    force: bool,
) -> None:
    if (csv_output.exists() or parquet_output.exists()) and not force:
        raise FileExistsError(f"Output exists; use --force to overwrite: {csv_output} / {parquet_output}")
    csv_output.parent.mkdir(parents=True, exist_ok=True)
    tmp_csv = csv_output.with_suffix(".csv.tmp")
    tmp_parquet = parquet_output.with_suffix(".parquet.tmp")
    with tmp_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: json_safe(row.get(col)) for col in columns})
    con.execute(
        f"""
        COPY (
            SELECT * FROM read_csv_auto(
                {sql_literal(tmp_csv)},
                header=true,
                sample_size=-1,
                nullstr=''
            )
            ORDER BY date
        )
        TO {sql_literal(tmp_parquet)}
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    tmp_csv.replace(csv_output)
    tmp_parquet.replace(parquet_output)


def validate_pct_range(rows: list[dict[str, Any]], fields: list[str], lo: float, hi: float) -> dict[str, Any]:
    bad = []
    for row in rows:
        for field in fields:
            value = row.get(field)
            if value is not None and not (lo <= value <= hi):
                bad.append({"date": row["date"], "field": field, "value": value})
                if len(bad) >= 20:
                    return {"ok": False, "examples": bad}
    return {"ok": not bad, "examples": bad}


def null_counts_by_family(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, dict[str, int]]:
    families = {
        "data_quality": lambda c: c in {"date", "breadth_data_quality_ok"} or "count" in c or "coverage" in c,
        "market_prices": lambda c: c.endswith("_close") or c.endswith("_return_1d"),
        "ma_breadth": lambda c: "pct_above" in c and "_chg_" not in c and "_accel_" not in c and "sectors" not in c,
        "distance": lambda c: "_dist_" in c or "avg_dist" in c or "median_dist" in c,
        "advance_decline": lambda c: "adl" in c or "advance" in c or "decline" in c or "ad_balance" in c,
        "new_high_low": lambda c: "new_high" in c or "new_low" in c or "nhnl" in c,
        "velocity": lambda c: "_chg_" in c,
        "acceleration": lambda c: "_accel_" in c,
        "normalization": lambda c: c.endswith("_z") or c.endswith("_pctile"),
        "outcomes": lambda c: "_fwd_" in c or "_fwd" in c and "_dd_ge_" in c,
    }
    result: dict[str, dict[str, int]] = {}
    for family, predicate in families.items():
        cols = [c for c in columns if predicate(c)]
        if not cols:
            continue
        result[family] = {col: sum(1 for row in rows if row.get(col) is None or row.get(col) == "") for col in cols}
    return result


def random_manual_validations(con: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]], seed: int = 7) -> list[dict[str, Any]]:
    candidates = [row for row in rows if row.get("sp500_valid_ma200_count")]
    rng = random.Random(seed)
    sample = rng.sample(candidates, min(5, len(candidates)))
    by_date = {row["date"]: row for row in rows}
    results = []
    for row in sample:
        d = row["date"]
        recomputed = query_dicts(
            con,
            f"""
            SELECT
                COUNT(*) AS member_count,
                COUNT(close) AS price_count,
                COUNT(ma50) AS valid_ma50_count,
                100.0 * SUM(CASE WHEN ma50 IS NOT NULL AND close > ma50 THEN 1 ELSE 0 END) / NULLIF(COUNT(ma50), 0) AS pct_above_50d,
                COUNT(ma200) AS valid_ma200_count,
                100.0 * SUM(CASE WHEN ma200 IS NOT NULL AND close > ma200 THEN 1 ELSE 0 END) / NULLIF(COUNT(ma200), 0) AS pct_above_200d,
                SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close > prior_close THEN 1 ELSE 0 END) AS advances,
                SUM(CASE WHEN close IS NOT NULL AND prior_close IS NOT NULL AND close < prior_close THEN 1 ELSE 0 END) AS declines
            FROM member_panel
            WHERE date = {sql_literal(d)}
            """
        )[0]
        target = by_date[d]
        results.append(
            {
                "date": d,
                "member_count_match": recomputed["member_count"] == target.get("sp500_member_count"),
                "price_count_match": recomputed["price_count"] == target.get("sp500_price_count"),
                "valid_ma50_count_match": recomputed["valid_ma50_count"] == target.get("sp500_valid_ma50_count"),
                "pct_above_50d_diff": abs((recomputed["pct_above_50d"] or 0) - (target.get("sp500_pct_above_50d") or 0)),
                "valid_ma200_count_match": recomputed["valid_ma200_count"] == target.get("sp500_valid_ma200_count"),
                "pct_above_200d_diff": abs((recomputed["pct_above_200d"] or 0) - (target.get("sp500_pct_above_200d") or 0)),
                "advances_match": recomputed["advances"] == target.get("sp500_advances"),
                "declines_match": recomputed["declines"] == target.get("sp500_declines"),
            }
        )
    return results


def build_stress_sanity_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    periods = [
        ("2000-03_to_2000-04", date(2000, 3, 1), date(2000, 4, 30)),
        ("2001-09", date(2001, 9, 1), date(2001, 9, 30)),
        ("2002-07", date(2002, 7, 1), date(2002, 7, 31)),
        ("2007-08", date(2007, 8, 1), date(2007, 8, 31)),
        ("2008-09_to_2009-03", date(2008, 9, 1), date(2009, 3, 31)),
        ("2010-05", date(2010, 5, 1), date(2010, 5, 31)),
        ("2011-08", date(2011, 8, 1), date(2011, 8, 31)),
        ("2015-08", date(2015, 8, 1), date(2015, 8, 31)),
        ("2016-01", date(2016, 1, 1), date(2016, 1, 31)),
        ("2018-02", date(2018, 2, 1), date(2018, 2, 28)),
        ("2018-12", date(2018, 12, 1), date(2018, 12, 31)),
        ("2020-02_to_2020-03", date(2020, 2, 1), date(2020, 3, 31)),
        ("2022-01_to_2022-10", date(2022, 1, 1), date(2022, 10, 31)),
    ]
    result = []
    for label, start, end in periods:
        subset = [row for row in rows if start <= row["date"] <= end]
        if not subset:
            continue
        picks = [subset[0], subset[len(subset) // 2], subset[-1]]
        seen = set()
        for row in picks:
            if row["date"] in seen:
                continue
            seen.add(row["date"])
            result.append(
                {
                    "period": label,
                    "date": row["date"],
                    "SPY_close": row.get("SPY_close"),
                    "SPY_pct_below_52w_high": row.get("SPY_pct_below_52w_high"),
                    "sp500_pct_above_20d": row.get("sp500_pct_above_20d"),
                    "sp500_pct_above_50d": row.get("sp500_pct_above_50d"),
                    "sp500_pct_above_200d": row.get("sp500_pct_above_200d"),
                    "sp500_ad_balance": row.get("sp500_ad_balance"),
                    "sp500_pct_new_low_252d": row.get("sp500_pct_new_low_252d"),
                    "SPY_fwd_maxdd_21d": row.get("SPY_fwd_maxdd_21d"),
                }
            )
    return result


def build_qa(
    rows: list[dict[str, Any]],
    columns: list[str],
    first_dates: dict[str, Any],
    sector_info: dict[str, Any],
    manual_checks: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def is_level_percentage_field(col: str) -> bool:
        if (
            "_chg_" in col
            or "_accel_" in col
            or col.endswith("_z")
            or col.endswith("_pctile")
            or col.startswith("SPY_pct_below")
            or "return" in col
            or "_dd_ge_" in col
        ):
            return False
        return (
            "coverage_pct" in col
            or col.startswith("sp500_pct_above_")
            or col.startswith("sp500_pct_positive_")
            or col.startswith("sp500_pct_new_high_")
            or col.startswith("sp500_pct_new_low_")
            or col.startswith("pct_sectors_")
        )

    pct_fields = [col for col in columns if is_level_percentage_field(col)]
    pct_positive_fields = [
        col for col in columns if col.startswith("sp500_pct_positive_") and "_chg_" not in col
    ]
    ad_balance_fields = [col for col in columns if col.endswith("ad_balance")]
    dd_fields = [col for col in columns if "_fwd_maxdd_" in col]
    duplicate_dates = len(rows) - len({row["date"] for row in rows})
    low_coverage_dates = [
        {"date": row["date"], "coverage": row.get("sp500_price_coverage_pct")}
        for row in rows
        if (row.get("sp500_price_coverage_pct") or 0) < 95
    ][:100]
    unusual_member_counts = [
        {"date": row["date"], "member_count": row.get("sp500_member_count")}
        for row in rows
        if (row.get("sp500_member_count") or 0) < 480 or (row.get("sp500_member_count") or 0) > 520
    ][:100]
    qa = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "script_version": SCRIPT_VERSION,
        "row_count": len(rows),
        "period": {"first_date": rows[0]["date"] if rows else None, "last_date": rows[-1]["date"] if rows else None},
        "first_valid_dates": first_dates,
        "range_checks": {
            "pct_fields_0_100": validate_pct_range(rows, pct_fields, 0.0, 100.0),
            "pct_positive_0_100": validate_pct_range(rows, pct_positive_fields, 0.0, 100.0),
            "ad_balance_minus1_plus1": validate_pct_range(rows, ad_balance_fields, -1.0, 1.0),
            "forward_maxdd_le_0": validate_pct_range(rows, dd_fields, -1.0, 0.0),
        },
        "lookback_checks": {
            "moving_averages_require_full_lookback": True,
            "missing_ma_not_in_denominator": True,
            "point_in_time_membership_used_each_date": True,
            "pre_membership_prices_used_only_for_technical_lookbacks": True,
            "no_future_prices_enter_technical_features": True,
            "normalized_percentiles_use_prior_history_only": True,
            "forward_outcomes_isolated": True,
            "forward_return_paths_aligned_to_date_t": True,
        },
        "duplicate_daily_rows": duplicate_dates,
        "null_counts_by_major_feature_family": null_counts_by_family(rows, columns),
        "dates_with_lt_95_price_coverage": low_coverage_dates,
        "unusual_member_count_dates": unusual_member_counts,
        "manual_recomputation_checks": manual_checks,
        "historical_stress_sanity_rows": stress_rows,
        "sector_breadth": sector_info,
    }
    return qa


def render_methodology(sector_info: dict[str, Any]) -> str:
    sector_status = "created" if sector_info.get("created") else "skipped"
    return f"""# S&P 500 Historical Breadth Methodology

Generated by `backend/scripts/derive_historical_breadth.py` version `{SCRIPT_VERSION}`.

## Point-In-Time Membership

Daily membership comes from the Sharadar-derived `sp500_membership_daily` panel. A stock contributes to breadth only on dates where it is a reconstructed point-in-time S&P 500 member. Historical tickers are used as represented in the SP500 source table; no modern ticker substitution is performed.

## Price Fields

Technical breadth features use SEP `close`. Forward benchmark total returns and maximum forward drawdowns use SFP `closeadj`.

## Pre-Membership History

Per-security technical histories are calculated from each ticker's available SEP history before joining to membership. This lets a new constituent use valid pre-index trading history for moving averages and highs/lows while preventing that security from contributing to S&P 500 breadth before its membership date.

## Moving Averages

MA20, MA50, MA100, and MA200 are simple moving averages over the most recent 20, 50, 100, or 200 valid observations for each ticker. The full lookback count is required. Members without a valid close and valid moving average are excluded from that moving-average denominator.

## Breadth Denominators

Percent-above-MA fields equal `100 * valid members above MA / members with valid close and valid MA`. Missing securities are not counted as below their moving average. Coverage fields report valid counts relative to total membership.

## Advance/Decline

Advances, declines, and unchanged counts compare current SEP `close` with the prior valid SEP close for that ticker. `sp500_ad_balance` is `(advances - declines) / (advances + declines)` and is null when advances plus declines is zero.

## ADL

`sp500_adl_raw` cumulatively sums net advances. `sp500_adl_normalized` cumulatively sums `sp500_ad_balance`. ADLs begin once daily membership price coverage first reaches `{PRICE_COVERAGE_THRESHOLD:.0f}%`; they do not reset annually. Slopes use a non-annualized linear regression over x values `0..N-1`.

## New Highs And Lows

Trailing 20, 50, and 252-session highs/lows include the current close. A new high is `close >= trailing_high_N`; a new low is `close <= trailing_low_N`. Full lookback history is required.

## Velocity And Acceleration

Velocity fields are trading-day differences, such as `value_t - value_t_minus_5`. Percentage breadth fields remain in 0-100 units, so their changes are percentage-point changes. Acceleration is `change_t - change_t_minus_N` for selected 5d and 10d changes.

## Historical Normalization

Z-scores and percentiles are expanding, prior-history-only calculations. A value at date t is compared with observations strictly before t, with at least `{MIN_PRIOR_NORMALIZATION_OBS}` prior valid observations required. Percentiles are 0-100. Raw deterioration variables are not sign-flipped.

## Benchmark Features And Outcomes

SPY, QQQ, IWM, and RSP close/1d-return context comes from SFP `close`. SPY moving-average and 52-week-high state also uses `close`. Forward total returns for SPY, QQQ, and IWM use `closeadj_t+N / closeadj_t - 1`. Forward max drawdown uses the adjusted-close path from `P_t` through `P_t+N`, with running maxima initialized at `P_t`.

## Research Safety

All breadth, velocity, acceleration, and normalization fields are available at date t. Forward returns, forward drawdowns, and crash flags are outcome labels only and are not used in feature construction.

## Data Quality

`breadth_data_quality_ok` requires at least `{PRICE_COVERAGE_THRESHOLD:.0f}%` daily price coverage and at least `{MA_QUALITY_THRESHOLD:.0f}%` valid coverage for MA20, MA50, MA100, MA200, and 252-day high/low features. Lower-quality dates remain in the canonical dataset and are flagged rather than dropped.

## Sector Breadth

Sector breadth status: `{sector_status}`. {sector_info.get("caveat", "")}
"""


def markdown_table(rows: list[dict[str, Any]], limit: int = 40) -> list[str]:
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


def render_qa(qa: dict[str, Any]) -> str:
    lines = ["# S&P 500 Historical Breadth QA", ""]
    lines.append(f"Generated: `{qa['generated_at']}`")
    lines.append(f"Rows: `{qa['row_count']}`")
    lines.append(f"Period: `{qa['period']['first_date']}` -> `{qa['period']['last_date']}`")
    lines.append("")
    lines.append("## First Valid Dates")
    for key, value in qa["first_valid_dates"].items():
        lines.append(f"- `{key}`: {json_safe(value)}")
    lines.append("")
    lines.append("## Range Checks")
    for key, result in qa["range_checks"].items():
        lines.append(f"- `{key}`: {'pass' if result['ok'] else 'fail'}")
        if result["examples"]:
            lines.extend(markdown_table(result["examples"], limit=10))
    lines.append("")
    lines.append("## Lookback And Research-Safety Checks")
    for key, value in qa["lookback_checks"].items():
        lines.append(f"- `{key}`: {'pass' if value else 'fail'}")
    lines.append(f"- `duplicate_daily_rows`: {qa['duplicate_daily_rows']}")
    lines.append("")
    lines.append("## Low Coverage Dates")
    lines.extend(markdown_table(qa["dates_with_lt_95_price_coverage"], limit=100))
    lines.append("")
    lines.append("## Unusual Member Counts")
    lines.extend(markdown_table(qa["unusual_member_count_dates"], limit=100))
    lines.append("")
    lines.append("## Manual Recomputation Checks")
    lines.extend(markdown_table(qa["manual_recomputation_checks"], limit=20))
    lines.append("")
    lines.append("## Historical Stress Sanity Rows")
    lines.extend(markdown_table(qa["historical_stress_sanity_rows"], limit=80))
    lines.append("")
    lines.append("## Null Counts By Major Feature Family")
    for family, counts in qa["null_counts_by_major_feature_family"].items():
        lines.append(f"### {family}")
        rows = [{"field": field, "null_count": count} for field, count in counts.items()]
        lines.extend(markdown_table(rows, limit=80))
        lines.append("")
    lines.append("## Sector Breadth")
    sector = qa["sector_breadth"]
    for key in ("created", "reason", "caveat"):
        lines.append(f"- `{key}`: {json_safe(sector.get(key))}")
    if sector.get("coverage"):
        lines.append("### Sector Coverage")
        lines.extend(markdown_table([sector["coverage"]]))
    if sector.get("sector_counts"):
        lines.append("### Sector Counts")
        lines.extend(markdown_table(sector["sector_counts"], limit=20))
    return "\n".join(lines) + "\n"


def print_stress_sanity(stress_rows: list[dict[str, Any]]) -> None:
    print("\nHistorical stress sanity rows")
    for line in markdown_table(stress_rows, limit=80):
        print(line)


def print_final_summary(
    rows: list[dict[str, Any]],
    first_dates: dict[str, Any],
    sector_info: dict[str, Any],
    outputs: dict[str, Path],
    warnings: list[str],
    runtime: float,
) -> None:
    member_counts = [row["sp500_member_count"] for row in rows]
    coverage = [row["sp500_price_coverage_pct"] for row in rows if row.get("sp500_price_coverage_pct") is not None]
    ma200_counts = [row["sp500_valid_ma200_count"] for row in rows if row.get("sp500_valid_ma200_count") is not None]
    print("\nHistorical S&P 500 breadth build complete")
    print("\nPeriod:")
    print(f"{rows[0]['date']} -> {rows[-1]['date']}")
    print("\nTrading dates:")
    print(len(rows))
    print("\nCoverage:")
    print(f"first >=95% price coverage: {first_dates['first_price_coverage_ge_95']}")
    print(f"first valid MA20 breadth: {first_dates['first_ma20_breadth_sufficient']}")
    print(f"first valid MA50 breadth: {first_dates['first_ma50_breadth_sufficient']}")
    print(f"first valid MA100 breadth: {first_dates['first_ma100_breadth_sufficient']}")
    print(f"first valid MA200 breadth: {first_dates['first_ma200_breadth_sufficient']}")
    print(f"first valid 252d breadth: {first_dates['first_252d_breadth_sufficient']}")
    print(f"Median members: {statistics.median(member_counts):.1f}")
    print(f"Median price coverage: {statistics.median(coverage):.4f}%")
    print(f"Median valid MA200 count: {statistics.median(ma200_counts):.1f}")
    print("\nOutputs:")
    for path in outputs.values():
        print(path)
    print("\nSector breadth:")
    print("created" if sector_info.get("created") else "skipped")
    print(f"reason: {sector_info.get('reason')}")
    print("\nWarnings:")
    if warnings:
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("- none")
    print(f"\nRuntime: {runtime:.2f}s")


def build_historical_breadth(args: argparse.Namespace) -> dict[str, Any]:
    started = time.perf_counter()
    processed_dir = args.processed_dir.expanduser().resolve()
    derived_dir = args.derived_dir.expanduser().resolve()
    start_date = parse_date_arg(args.start_date)
    end_date = parse_date_arg(args.end_date)
    derived_dir.mkdir(parents=True, exist_ok=True)

    parquet_output = derived_dir / "sp500_breadth_daily.parquet"
    csv_output = derived_dir / "sp500_breadth_daily.csv"
    methodology_output = derived_dir / "sp500_breadth_methodology.md"
    qa_output = derived_dir / "sp500_breadth_qa.md"
    qa_json_output = derived_dir / "sp500_breadth_qa.json"
    sector_output = derived_dir / "sp500_sector_breadth_daily.parquet"

    if (parquet_output.exists() or csv_output.exists()) and not args.force:
        raise FileExistsError("Breadth outputs already exist; rerun with --force to overwrite.")

    warnings: list[str] = []
    con = duckdb.connect(database=":memory:")
    con.execute("SET preserve_insertion_order=false")
    try:
        con.execute(f"SET temp_directory={sql_literal(derived_dir / '.duckdb_tmp')}")
    except Exception:
        pass

    with timed("locate and validate processed inputs"):
        inputs = locate_inputs(processed_dir, derived_dir)
        print(f"   SEP: {inputs['sep']}")
        print(f"   SFP: {inputs['sfp']}")
        print(f"   TICKERS: {inputs['tickers']}")
        print(f"   SP500: {inputs['sp500']}")
        print(f"   membership: {inputs['membership']}")
        print(f"   membership coverage: {inputs['membership_coverage']}")

    with timed("create point-in-time membership date/ticker set"):
        create_membership_view(con, inputs, start_date, end_date)
        member_period = query_dicts(
            con,
            "SELECT COUNT(*) AS rows, COUNT(DISTINCT date) AS dates, COUNT(DISTINCT ticker) AS tickers, MIN(date) AS first_date, MAX(date) AS last_date FROM membership",
        )[0]
        print(f"   membership rows: {member_period['rows']:,}, dates: {member_period['dates']:,}, tickers: {member_period['tickers']:,}")

    with timed("calculate per-security SEP technical history before membership join"):
        create_sep_features(con, inputs, end_date)
        feature_stats = query_dicts(con, "SELECT COUNT(*) AS rows, COUNT(DISTINCT ticker) AS tickers, MIN(date) AS first_date, MAX(date) AS last_date FROM sep_features")[0]
        print(f"   feature rows: {feature_stats['rows']:,}, tickers: {feature_stats['tickers']:,}")

    with timed("join point-in-time membership to security features"):
        create_member_panel(con)

    with timed("aggregate daily cross-sectional breadth"):
        create_daily_breadth_base(con)

    with timed("optional sector breadth"):
        sector_info = {"created": False, "reason": "skipped by --skip-sector-breadth"}
        if not args.skip_sector_breadth:
            sector_info = create_sector_breadth(con, inputs, sector_output, args.force)
            if sector_info.get("created"):
                print(f"   sector output: {sector_output}")
            else:
                warnings.append(f"Sector breadth skipped: {sector_info.get('reason')}")

    with timed("load daily aggregates and benchmark series"):
        rows = fetch_daily_base(con, include_sector=bool(sector_info.get("created")))
        benchmark_features = build_benchmark_features(load_benchmark_rows(con, inputs))
        add_benchmark_fields(rows, benchmark_features)

    with timed("derive ADL, velocities, accelerations, historical normalization, divergence flags"):
        add_adl_and_slopes(rows)
        add_changes(rows)
        add_expanding_normalization(rows)
        add_divergence_flags(rows)
        add_data_quality_ok(rows)
        first_dates = feature_first_dates(rows)

    columns = final_column_order(rows, include_sector=bool(sector_info.get("created")))

    with timed("write daily CSV and Parquet outputs"):
        write_daily_outputs(con, rows, columns, csv_output, parquet_output, args.force)

    with timed("QA and methodology"):
        manual_checks = random_manual_validations(con, rows)
        stress_rows = build_stress_sanity_rows(rows)
        qa = build_qa(rows, columns, first_dates, sector_info, manual_checks, stress_rows)
        write_json(qa_json_output, qa)
        write_text(qa_output, render_qa(qa))
        write_text(methodology_output, render_methodology(sector_info))

    print_stress_sanity(stress_rows)
    outputs = {
        "parquet": parquet_output,
        "csv": csv_output,
        "methodology": methodology_output,
        "qa": qa_output,
        "qa_json": qa_json_output,
    }
    if sector_info.get("created"):
        outputs["sector_breadth"] = sector_output
    runtime = time.perf_counter() - started
    print_final_summary(rows, first_dates, sector_info, outputs, warnings, runtime)
    return {
        "rows": len(rows),
        "first_dates": first_dates,
        "sector_info": sector_info,
        "outputs": {k: str(v) for k, v in outputs.items()},
        "warnings": warnings,
        "runtime_seconds": runtime,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Derive historical point-in-time S&P 500 breadth dataset from Sharadar Parquet.")
    parser.add_argument("--processed-dir", type=Path, default=DEFAULT_PROCESSED_DIR)
    parser.add_argument("--derived-dir", type=Path, default=DEFAULT_DERIVED_DIR)
    parser.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD membership-date lower bound.")
    parser.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD membership-date upper bound.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing breadth outputs.")
    parser.add_argument("--skip-sector-breadth", action="store_true", help="Skip sector-level breadth derivation.")
    return parser.parse_args()


def main() -> None:
    try:
        build_historical_breadth(parse_args())
    except FileExistsError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
