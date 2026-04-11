from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import argparse
import pandas as pd

from backend.src.backtest.features import build_research_frame

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate historical MarketState features + scores (open + close signal times)."
    )
    ap.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="End date YYYY-MM-DD (yfinance end is effectively exclusive)")
    ap.add_argument("--out", default="data/backtests/market_state_scored_1d.parquet", help="Output parquet path")
    ap.add_argument("--csv", default="", help="Optional CSV output path (leave blank to skip)")
    ap.add_argument("--force", action="store_true", help="Force re-download from yfinance (ignore cache)")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1) Build raw daily features
    df = build_research_frame(
        start=args.start,
        end=args.end,
        force_download=args.force,
    )

    # 2) Save outputs
    df.to_parquet(out_path, index=False)

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False)

    print("✅ Saved:", out_path)
    print("Rows:", len(df), "Date range:", str(df["date"].min()), "→", str(df["date"].max()))

    preview_cols = [
        "date", "signal_time",
        "score_total", "confidence", "environment",
        "fwd_ret_cc_1d", "fwd_ret_cc_5d",
        "fwd_5d_max_drawdown_pct", "fwd_5d_max_upside_pct"
    ]
    existing = [c for c in preview_cols if c in df.columns]
    print("\nPreview (last 10 rows):")
    print(df[existing].tail(10))

    # missingness checks
    for c in ["score_total", "fwd_ret_cc_5d", "fwd_5d_max_drawdown_pct"]:
        if c in df.columns:
            miss = df[c].isna().mean() * 100
            print(f"Missing {c}: {miss:.1f}%")
    print("Done.")
    
if __name__ == "__main__":
    main()
