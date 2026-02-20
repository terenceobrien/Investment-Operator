from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import argparse
from pathlib import Path

import pandas as pd

from src.backtest.features import build_daily_feature_frame, score_history_both_signal_times


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
    feats = build_daily_feature_frame(
        start=args.start,
        end=args.end,
        force_download=args.force,
    )

    # 2) Score history for BOTH 'open' and 'close' signal times
    scored = score_history_both_signal_times(feats)

    # 3) Save outputs
    scored.to_parquet(out_path)

    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        # parquet preserves MultiIndex columns; csv doesn't—flatten them
        flat = scored.copy()
        flat.columns = [f"{a}__{b}" for a, b in flat.columns]
        flat.to_csv(csv_path, index=True)

    # 4) Print quick sanity checks
    print("✅ Saved:", out_path)
    print("Rows:", len(scored), "Date range:", str(scored.index.min().date()), "→", str(scored.index.max().date()))

    # Show a small preview of the key columns
    preview = scored[[("open", "score_total"), ("open", "confidence"), ("close", "score_total"), ("close", "confidence")]].tail(5)
    print("\nPreview (last 5 rows):")
    print(preview)

    # Basic missingness
    miss_open = scored[("open", "score_total")].isna().mean() * 100
    miss_close = scored[("close", "score_total")].isna().mean() * 100
    print(f"\nMissing score_total: open={miss_open:.1f}%  close={miss_close:.1f}%")
    print("Done.")


if __name__ == "__main__":
    main()
