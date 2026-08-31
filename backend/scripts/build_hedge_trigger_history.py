#!/usr/bin/env python3
"""Build canonical historical daily hedge-trigger states from existing research data.

This is a deterministic local transformation. It does not fetch market data,
call the live hedge-trigger endpoint, or optimize thresholds. Outcome labels,
when present, are retained only after trigger states are calculated.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
OUTPUT_PATH = BACKEND_ROOT / "data" / "risk" / "hedge_trigger_history.parquet"
DEFAULT_SOURCE = BACKEND_ROOT / "data" / "sharadar" / "derived" / "sp500_breadth_daily_v2.csv"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.risk.hedge_trigger import (  # noqa: E402
    BREADTH_DISPERSION_20D_THRESHOLD,
    BREADTH_NEW_LOWS_252D_THRESHOLD,
    BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD,
    BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD,
    BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD,
    BREADTH_SECTOR_DECLINE_PCT_THRESHOLD,
    CREDIT_BAA10Y_CHG_10D_THRESHOLD,
    CREDIT_BAA10Y_THRESHOLD,
    CREDIT_BAA_AAA_CHG_10D_THRESHOLD,
    CREDIT_BAA_AAA_THRESHOLD,
    VOL_VIX_CHG_5D_THRESHOLD,
    VOL_VIX_THRESHOLD,
    VOL_VVIX_THRESHOLD,
)


class BuildError(RuntimeError):
    """Raised when the canonical history cannot be built or validated."""


SOURCE_COLUMN_MAP = {
    "date": "date",
    "dispersion_20d": "sp500_return_dispersion_20d",
    "pct_new_lows_252d": "sp500_pct_new_low_252d",
    "breadth_20dma_velocity_5d": "sp500_pct_above_20d_chg_5d",
    "breadth_50dma_velocity_10d": "sp500_pct_above_50d_chg_10d",
    "breadth_200dma_velocity_10d": "sp500_pct_above_200d_chg_10d",
    "sector_deterioration_pct": "pct_sectors_pct_above_50d_declining_10d",
    "baa10y": "BAA 10Y Spread",
    "baa_aaa": "BAA - AAA Spread",
    "vix": "VIX Spot",
    "vvix": "VVIX",
}

OPTIONAL_LABEL_MAP = {
    "forward_42d_max_drawdown": "SPY_fwd_maxdd_42d",
    "threat_42d_10pct": "SPY_fwd42_dd_ge_10pct",
}

REQUIRED_VALUE_COLUMNS = [
    "dispersion_20d",
    "pct_new_lows_252d",
    "breadth_20dma_velocity_5d",
    "breadth_50dma_velocity_10d",
    "breadth_200dma_velocity_10d",
    "sector_deterioration_pct",
    "baa10y",
    "baa_aaa",
    "baa10y_change_10d",
    "baa_aaa_change_10d",
    "vix",
    "vix_change_5d",
    "vvix",
]

OUTPUT_COLUMNS = [
    "date",
    "dispersion_20d",
    "pct_new_lows_252d",
    "breadth_20dma_velocity_5d",
    "breadth_50dma_velocity_10d",
    "breadth_200dma_velocity_10d",
    "sector_deterioration_count",
    "sector_deterioration_pct",
    "bhr_dispersion_trigger",
    "bhr_new_lows_trigger",
    "bhr_20dma_velocity_trigger",
    "bhr_50dma_velocity_trigger",
    "bhr_200dma_velocity_trigger",
    "bhr_sector_trigger",
    "bhr_signals_firing",
    "bhr_active",
    "baa10y",
    "baa_aaa",
    "baa10y_change_10d",
    "baa_aaa_change_10d",
    "credit_baa10y_level_trigger",
    "credit_baa_aaa_level_trigger",
    "credit_baa10y_velocity_trigger",
    "credit_baa_aaa_velocity_trigger",
    "credit_signals_firing",
    "credit_stress",
    "vix",
    "vix_change_5d",
    "vvix",
    "vol_vix_level_trigger",
    "vol_vix_velocity_trigger",
    "vol_vvix_trigger",
    "vol_signals_firing",
    "vol_stress",
    "hedge_trigger_active",
    "hedge_stage",
    "hedge_stage_label",
    "data_quality_ok",
    "missing_required_fields",
]

STAGE_LABELS = {
    0: "Normal",
    1: "Breadth Fragility",
    2: "Confirmed Hedge Trigger",
    3: "Multi-Family Stress",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build backend/data/risk/hedge_trigger_history.parquet."
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help="Existing historical breadth/credit/vol source file.",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help="Destination Parquet path.",
    )
    return parser.parse_args()


def read_source(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise BuildError(f"source file does not exist: {path}")
    if path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path)
    elif path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, low_memory=False)
    else:
        raise BuildError(f"unsupported source file type: {path}")

    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = [source for source in SOURCE_COLUMN_MAP.values() if source not in frame.columns]
    if missing:
        raise BuildError(f"source file is missing required columns: {missing}")
    return frame


def to_numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def available_observation_diff(series: pd.Series, periods: int) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return clean.diff(periods).reindex(series.index)


def high_trigger(series: pd.Series, threshold: float) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").ge(threshold).fillna(False)


def low_trigger(series: pd.Series, threshold: float) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").le(threshold).fillna(False)


def missing_fields(row: pd.Series) -> str:
    missing = [column for column in REQUIRED_VALUE_COLUMNS if pd.isna(row[column])]
    return ",".join(missing)


def build_history(source: pd.DataFrame) -> pd.DataFrame:
    source_clean = source.copy()
    source_clean["_parsed_date"] = pd.to_datetime(
        source[SOURCE_COLUMN_MAP["date"]],
        format="mixed",
        errors="coerce",
    ).dt.date
    source_clean = source_clean.dropna(subset=["_parsed_date"])
    source_clean = source_clean.drop_duplicates("_parsed_date", keep="last")
    source_clean = source_clean.sort_values("_parsed_date").reset_index(drop=True)

    out = pd.DataFrame()
    out["date"] = source_clean["_parsed_date"]
    for output_column, source_column in SOURCE_COLUMN_MAP.items():
        if output_column == "date":
            continue
        out[output_column] = to_numeric(source_clean, source_column)

    out["baa10y_change_10d"] = available_observation_diff(out["baa10y"], 10)
    out["baa_aaa_change_10d"] = available_observation_diff(out["baa_aaa"], 10)
    out["vix_change_5d"] = available_observation_diff(out["vix"], 5)
    out["sector_deterioration_count"] = (
        (out["sector_deterioration_pct"] * 11.0 / 100.0).round().astype("Int64")
    )

    out["bhr_dispersion_trigger"] = high_trigger(
        out["dispersion_20d"],
        BREADTH_DISPERSION_20D_THRESHOLD,
    )
    out["bhr_new_lows_trigger"] = high_trigger(
        out["pct_new_lows_252d"],
        BREADTH_NEW_LOWS_252D_THRESHOLD,
    )
    out["bhr_20dma_velocity_trigger"] = low_trigger(
        out["breadth_20dma_velocity_5d"],
        BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD,
    )
    out["bhr_50dma_velocity_trigger"] = low_trigger(
        out["breadth_50dma_velocity_10d"],
        BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD,
    )
    out["bhr_200dma_velocity_trigger"] = low_trigger(
        out["breadth_200dma_velocity_10d"],
        BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD,
    )
    out["bhr_sector_trigger"] = high_trigger(
        out["sector_deterioration_pct"],
        BREADTH_SECTOR_DECLINE_PCT_THRESHOLD,
    )

    bhr_cols = [
        "bhr_dispersion_trigger",
        "bhr_new_lows_trigger",
        "bhr_20dma_velocity_trigger",
        "bhr_50dma_velocity_trigger",
        "bhr_200dma_velocity_trigger",
        "bhr_sector_trigger",
    ]
    out["bhr_signals_firing"] = out[bhr_cols].sum(axis=1).astype("int64")
    out["bhr_active"] = out["bhr_signals_firing"].gt(0)

    out["credit_baa10y_level_trigger"] = high_trigger(
        out["baa10y"],
        CREDIT_BAA10Y_THRESHOLD,
    )
    out["credit_baa_aaa_level_trigger"] = high_trigger(
        out["baa_aaa"],
        CREDIT_BAA_AAA_THRESHOLD,
    )
    out["credit_baa10y_velocity_trigger"] = high_trigger(
        out["baa10y_change_10d"],
        CREDIT_BAA10Y_CHG_10D_THRESHOLD,
    )
    out["credit_baa_aaa_velocity_trigger"] = high_trigger(
        out["baa_aaa_change_10d"],
        CREDIT_BAA_AAA_CHG_10D_THRESHOLD,
    )

    credit_cols = [
        "credit_baa10y_level_trigger",
        "credit_baa_aaa_level_trigger",
        "credit_baa10y_velocity_trigger",
        "credit_baa_aaa_velocity_trigger",
    ]
    out["credit_signals_firing"] = out[credit_cols].sum(axis=1).astype("int64")
    out["credit_stress"] = out["credit_signals_firing"].gt(0)

    out["vol_vix_level_trigger"] = high_trigger(out["vix"], VOL_VIX_THRESHOLD)
    out["vol_vix_velocity_trigger"] = high_trigger(
        out["vix_change_5d"],
        VOL_VIX_CHG_5D_THRESHOLD,
    )
    out["vol_vvix_trigger"] = high_trigger(out["vvix"], VOL_VVIX_THRESHOLD)

    vol_cols = [
        "vol_vix_level_trigger",
        "vol_vix_velocity_trigger",
        "vol_vvix_trigger",
    ]
    out["vol_signals_firing"] = out[vol_cols].sum(axis=1).astype("int64")
    out["vol_stress"] = out["vol_signals_firing"].gt(0)

    out["hedge_trigger_active"] = out["bhr_active"] & (
        out["credit_stress"] | out["vol_stress"]
    )

    out["hedge_stage"] = 0
    out.loc[out["bhr_active"], "hedge_stage"] = 1
    out.loc[
        out["bhr_active"] & (out["credit_stress"] ^ out["vol_stress"]),
        "hedge_stage",
    ] = 2
    out.loc[
        out["bhr_active"] & out["credit_stress"] & out["vol_stress"],
        "hedge_stage",
    ] = 3
    out["hedge_stage_label"] = out["hedge_stage"].map(STAGE_LABELS)

    out["missing_required_fields"] = out.apply(missing_fields, axis=1)
    out["data_quality_ok"] = out["missing_required_fields"].eq("")

    for output_column, source_column in OPTIONAL_LABEL_MAP.items():
        if source_column in source_clean.columns:
            if output_column == "threat_42d_10pct":
                out[output_column] = to_numeric(source_clean, source_column).fillna(0).astype(bool)
            else:
                out[output_column] = to_numeric(source_clean, source_column)

    final_columns = [
        *OUTPUT_COLUMNS,
        *[column for column in OPTIONAL_LABEL_MAP if column in out.columns],
    ]
    return out[final_columns].sort_values("date").reset_index(drop=True)


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def validate_threshold_equality() -> None:
    checks = {
        "bhr_dispersion_trigger": bool(
            high_trigger(pd.Series([BREADTH_DISPERSION_20D_THRESHOLD]), BREADTH_DISPERSION_20D_THRESHOLD).iloc[0]
        ),
        "bhr_new_lows_trigger": bool(
            high_trigger(pd.Series([BREADTH_NEW_LOWS_252D_THRESHOLD]), BREADTH_NEW_LOWS_252D_THRESHOLD).iloc[0]
        ),
        "bhr_20dma_velocity_trigger": bool(
            low_trigger(
                pd.Series([BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD]),
                BREADTH_PCT_ABOVE_20D_CHG_5D_THRESHOLD,
            ).iloc[0]
        ),
        "bhr_50dma_velocity_trigger": bool(
            low_trigger(
                pd.Series([BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD]),
                BREADTH_PCT_ABOVE_50D_CHG_10D_THRESHOLD,
            ).iloc[0]
        ),
        "bhr_200dma_velocity_trigger": bool(
            low_trigger(
                pd.Series([BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD]),
                BREADTH_PCT_ABOVE_200D_CHG_10D_THRESHOLD,
            ).iloc[0]
        ),
        "bhr_sector_trigger": bool(
            high_trigger(
                pd.Series([BREADTH_SECTOR_DECLINE_PCT_THRESHOLD]),
                BREADTH_SECTOR_DECLINE_PCT_THRESHOLD,
            ).iloc[0]
        ),
        "credit_baa10y_level_trigger": bool(
            high_trigger(pd.Series([CREDIT_BAA10Y_THRESHOLD]), CREDIT_BAA10Y_THRESHOLD).iloc[0]
        ),
        "credit_baa_aaa_level_trigger": bool(
            high_trigger(pd.Series([CREDIT_BAA_AAA_THRESHOLD]), CREDIT_BAA_AAA_THRESHOLD).iloc[0]
        ),
        "credit_baa10y_velocity_trigger": bool(
            high_trigger(
                pd.Series([CREDIT_BAA10Y_CHG_10D_THRESHOLD]),
                CREDIT_BAA10Y_CHG_10D_THRESHOLD,
            ).iloc[0]
        ),
        "credit_baa_aaa_velocity_trigger": bool(
            high_trigger(
                pd.Series([CREDIT_BAA_AAA_CHG_10D_THRESHOLD]),
                CREDIT_BAA_AAA_CHG_10D_THRESHOLD,
            ).iloc[0]
        ),
        "vol_vix_level_trigger": bool(
            high_trigger(pd.Series([VOL_VIX_THRESHOLD]), VOL_VIX_THRESHOLD).iloc[0]
        ),
        "vol_vix_velocity_trigger": bool(
            high_trigger(pd.Series([VOL_VIX_CHG_5D_THRESHOLD]), VOL_VIX_CHG_5D_THRESHOLD).iloc[0]
        ),
        "vol_vvix_trigger": bool(
            high_trigger(pd.Series([VOL_VVIX_THRESHOLD]), VOL_VVIX_THRESHOLD).iloc[0]
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise BuildError(f"threshold equality did not fire for: {failed}")


def validate_history(frame: pd.DataFrame, output_path: Path) -> dict[str, Any]:
    if not output_path.exists():
        raise BuildError(f"output file was not created: {output_path}")
    if frame.empty:
        raise BuildError("output dataset is empty")
    if frame["date"].isna().any():
        raise BuildError("output contains null dates")
    duplicate_dates = int(frame["date"].duplicated().sum())
    if duplicate_dates:
        raise BuildError(f"output contains duplicate dates: {duplicate_dates}")

    validate_threshold_equality()

    bhr_cols = [
        "bhr_dispersion_trigger",
        "bhr_new_lows_trigger",
        "bhr_20dma_velocity_trigger",
        "bhr_50dma_velocity_trigger",
        "bhr_200dma_velocity_trigger",
        "bhr_sector_trigger",
    ]
    credit_cols = [
        "credit_baa10y_level_trigger",
        "credit_baa_aaa_level_trigger",
        "credit_baa10y_velocity_trigger",
        "credit_baa_aaa_velocity_trigger",
    ]
    vol_cols = [
        "vol_vix_level_trigger",
        "vol_vix_velocity_trigger",
        "vol_vvix_trigger",
    ]
    if not frame["bhr_active"].equals(frame[bhr_cols].sum(axis=1).gt(0)):
        raise BuildError("bhr_active does not equal the OR of BHR triggers")
    if not frame["credit_stress"].equals(frame[credit_cols].sum(axis=1).gt(0)):
        raise BuildError("credit_stress does not equal the OR of credit triggers")
    if not frame["vol_stress"].equals(frame[vol_cols].sum(axis=1).gt(0)):
        raise BuildError("vol_stress does not equal the OR of volatility triggers")

    expected_final = frame["bhr_active"] & (frame["credit_stress"] | frame["vol_stress"])
    if not frame["hedge_trigger_active"].equals(expected_final):
        raise BuildError("hedge_trigger_active does not match BHR AND (credit OR vol)")

    outcome_columns = set(OPTIONAL_LABEL_MAP)
    trigger_columns = set(bhr_cols + credit_cols + vol_cols + REQUIRED_VALUE_COLUMNS)
    if outcome_columns & trigger_columns:
        raise BuildError("outcome-label columns are included in trigger inputs")

    active_count = int(frame["hedge_trigger_active"].sum())
    active_share = float(frame["hedge_trigger_active"].mean())
    if not (1400 <= active_count <= 2000 and 0.20 <= active_share <= 0.28):
        raise BuildError(
            "materially unexpected hedge-trigger count/share; inspect source units. "
            f"active_count={active_count}, active_share={active_share:.2%}"
        )

    stage_distribution = {
        int(stage): int(count)
        for stage, count in frame["hedge_stage"].value_counts().sort_index().items()
    }
    return {
        "first_date": min(frame["date"]).isoformat(),
        "last_date": max(frame["date"]).isoformat(),
        "total_rows": int(len(frame)),
        "bhr_active_days": int(frame["bhr_active"].sum()),
        "credit_stress_days": int(frame["credit_stress"].sum()),
        "vol_stress_days": int(frame["vol_stress"].sum()),
        "hedge_trigger_active_days": active_count,
        "active_share": active_share,
        "stage_distribution": stage_distribution,
        "duplicate_dates": duplicate_dates,
        "data_quality_ok_days": int(frame["data_quality_ok"].sum()),
        "missing_field_counts": {
            column: int(frame[column].isna().sum())
            for column in REQUIRED_VALUE_COLUMNS
            if int(frame[column].isna().sum()) > 0
        },
        "outcome_labels_retained": [column for column in OPTIONAL_LABEL_MAP if column in frame.columns],
        "outcome_labels_used_in_trigger_calculation": False,
    }


def print_summary(summary: dict[str, Any], source_path: Path, output_path: Path) -> None:
    print("Hedge-trigger history built")
    print(f"  source: {source_path}")
    print(f"  output: {output_path}")
    print(f"  first date: {summary['first_date']}")
    print(f"  last date: {summary['last_date']}")
    print(f"  total rows: {summary['total_rows']:,}")
    print(f"  BHR-active days: {summary['bhr_active_days']:,}")
    print(f"  credit-stress days: {summary['credit_stress_days']:,}")
    print(f"  vol-stress days: {summary['vol_stress_days']:,}")
    print(f"  final hedge-trigger-active days: {summary['hedge_trigger_active_days']:,}")
    print(f"  active share: {summary['active_share']:.2%}")
    print(f"  stage distribution: {summary['stage_distribution']}")
    print(f"  duplicate dates: {summary['duplicate_dates']}")
    print("  threshold equality fires correctly: True")
    print("  outcome labels used in trigger calculation: False")
    print(f"  outcome labels retained: {summary['outcome_labels_retained']}")
    print(f"  data-quality OK days: {summary['data_quality_ok_days']:,}")
    print(f"  missing field counts: {summary['missing_field_counts']}")


def run() -> dict[str, Any]:
    args = parse_args()
    source_path = Path(args.source).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    source = read_source(source_path)
    history = build_history(source)
    atomic_write_parquet(history, output_path)
    written = pd.read_parquet(output_path)
    written["date"] = pd.to_datetime(written["date"], errors="coerce").dt.date
    summary = validate_history(written, output_path)
    print_summary(summary, source_path, output_path)
    return summary


def main() -> int:
    try:
        run()
        return 0
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
