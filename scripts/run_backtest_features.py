from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import argparse
import pandas as pd

from backend.src.backtest.features import build_research_frame


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate historical regime features + scores (open + close signal times)."
    )
    ap.add_argument("--start",    required=True,  help="Start date YYYY-MM-DD")
    ap.add_argument("--end",      required=True,  help="End date YYYY-MM-DD")
    ap.add_argument("--out",      default="data/backtests/regime_scored_1d.parquet",
                                  help="Output parquet path")
    ap.add_argument("--csv",      default="",     help="Optional CSV output path")
    ap.add_argument("--force",    action="store_true", help="Force re-download from yfinance")
    ap.add_argument("--no-fred",  action="store_true", help="Skip FRED data (faster, credit/breadth layers degrade to neutral)")
    ap.add_argument("--horizon",  default="default", choices=["default", "swing", "investor"],
                                  help="Scoring horizon — affects layer weights")
    ap.add_argument("--zscore-window", type=int, default=252,
                                  help="Rolling window for z-score calculations (default 252)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = build_research_frame(
        start=args.start,
        end=args.end,
        use_fred=not args.no_fred,
        horizon=args.horizon,
        zscore_window=args.zscore_window,
        force_download=args.force,
    )

    # Save outputs
    df.to_parquet(out_path, index=False)
    print("✅ Saved:", out_path)

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False)
        print("✅ Saved:", csv_path)

    print(f"Rows: {len(df)}  Date range: {df['date'].min()} → {df['date'].max()}")

    # Preview — shows both old and new scoring columns
    preview_cols = [
        "date", "signal_time",
        "score_total", "confidence", "environment", "layer_agreement",
        "layer_monetary", "layer_credit", "layer_volatility",
        "layer_breadth", "layer_positioning",
        "fwd_ret_cc_1d", "fwd_ret_cc_5d",
        "fwd_5d_max_drawdown_pct", "fwd_5d_max_upside_pct",
    ]
    existing = [c for c in preview_cols if c in df.columns]
    print("\nPreview (last 10 rows):")
    print(df[existing].tail(10).to_string())

    # Missingness report
    print("\nMissingness report:")
    check_cols = [
        "score_total", "layer_monetary", "layer_credit",
        "layer_volatility", "layer_breadth", "layer_positioning",
        "layer_agreement", "hy_spread_level", "vix_term_slope",
        "new_highs_minus_lows_z", "fwd_ret_cc_5d",
    ]
    for c in check_cols:
        if c in df.columns:
            miss = df[c].isna().mean() * 100
            dq_flag = " ⚠" if miss > 50 else ""
            print(f"  {c:<30} {miss:5.1f}% missing{dq_flag}")

    # Layer data quality summary (close signal only)
    close_df = df[df["signal_time"] == "close"]
    dq_cols = [c for c in df.columns if c.startswith("dq_")]
    if dq_cols:
        print("\nLayer data quality (close signal, mean across all dates):")
        for c in dq_cols:
            mean_dq = close_df[c].mean()
            layer = c.replace("dq_", "")
            bar = "█" * int(mean_dq * 10) + "░" * (10 - int(mean_dq * 10))
            print(f"  {layer:<12} {bar} {mean_dq:.0%}")

    print("\nDone.")


if __name__ == "__main__":
    main()