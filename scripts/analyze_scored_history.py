# scripts/analyze_scored_history.py
from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import argparse
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd


def _flatten_cols(df: pd.DataFrame) -> pd.DataFrame:
    """If MultiIndex cols like ('open','score_total'), flatten to 'open__score_total'."""
    if isinstance(df.columns, pd.MultiIndex):
        out = df.copy()
        out.columns = [f"{a}__{b}" for a, b in out.columns]
        return out
    return df


def _add_forward_returns(df: pd.DataFrame, price_col: str, horizons: List[int]) -> pd.DataFrame:
    """
    Adds forward close-to-close returns for given horizons: fwd_ret_cc_{h}d
    price_col should be a series of SPY closes aligned to df index.
    """
    out = df.copy()
    px = out[price_col].astype(float)
    for h in horizons:
        out[f"fwd_ret_cc_{h}d"] = (px.shift(-h) / px - 1.0) * 100.0
    return out


def decile_table(df: pd.DataFrame, score_col: str, ret_col: str, n: int = 10) -> pd.DataFrame:
    """
    Bucket score into deciles and compute mean/median/hit-rate/count of forward returns.
    """
    x = df[[score_col, ret_col]].dropna()
    if x.empty:
        return pd.DataFrame()

    # qcut can error if many duplicates; handle gracefully
    try:
        x["bucket"] = pd.qcut(x[score_col], n, duplicates="drop")
    except Exception:
        # fallback: rank-based
        r = x[score_col].rank(method="first")
        x["bucket"] = pd.qcut(r, n, duplicates="drop")

    g = x.groupby("bucket")[ret_col]
    tab = pd.DataFrame({
        "count": g.size(),
        "mean_ret_%": g.mean(),
        "median_ret_%": g.median(),
        "hit_rate_%": (g.apply(lambda s: (s > 0).mean()) * 100.0),
        "stdev_%": g.std(ddof=0),
    })

    # add bucket score ranges
    ranges = x.groupby("bucket")[score_col].agg(["min", "max", "mean"])
    tab["score_min"] = ranges["min"]
    tab["score_max"] = ranges["max"]
    tab["score_mean"] = ranges["mean"]

    return tab.reset_index(drop=False)


def threshold_table(
    df: pd.DataFrame,
    score_col: str,
    ret_col: str,
    thresholds: List[int],
    direction: str = "gt",
) -> pd.DataFrame:
    """
    Compute stats for score > threshold (gt) or score < threshold (lt).
    """
    out_rows = []
    base = df[[score_col, ret_col]].dropna()
    for t in thresholds:
        if direction == "gt":
            m = base[score_col] >= t
            label = f">={t}"
        else:
            m = base[score_col] <= t
            label = f"<={t}"

        s = base.loc[m, ret_col]
        if s.empty:
            out_rows.append({"threshold": label, "count": 0})
            continue

        out_rows.append({
            "threshold": label,
            "count": int(s.shape[0]),
            "mean_ret_%": float(s.mean()),
            "median_ret_%": float(s.median()),
            "hit_rate_%": float((s > 0).mean() * 100.0),
            "stdev_%": float(s.std(ddof=0)),
        })

    return pd.DataFrame(out_rows)


def summarize_best_worst(tab: pd.DataFrame, metric: str = "mean_ret_%", topk: int = 3) -> Tuple[pd.DataFrame, pd.DataFrame]:
    t = tab.dropna(subset=[metric]).copy()
    if t.empty:
        return t, t
    best = t.sort_values(metric, ascending=False).head(topk)
    worst = t.sort_values(metric, ascending=True).head(topk)
    return best, worst


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze scored history output from run_backtest_features.py")
    ap.add_argument("--file", required=True, help="Path to parquet or csv produced by run_backtest_features")
    ap.add_argument("--signal", choices=["open", "close"], default="open", help="Which signal_time to analyze")
    ap.add_argument("--horizons", default="1,3,5", help="Forward horizons in days, comma-separated")
    ap.add_argument("--outdir", default="data/backtests/analysis", help="Output directory for tables (csv)")
    args = ap.parse_args()

    path = Path(args.file)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Load
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path, index_col=0, parse_dates=True)

    df = _flatten_cols(df)
    df.index = pd.to_datetime(df.index)

    sig = args.signal
    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]

    score_col = f"{sig}__score_total"
    conf_col = f"{sig}__confidence"

    # We need a price column to compute forward returns.
    # From run_backtest_features: we included fwd_ret_oc_1d / fwd_ret_cc_1d, but not always spy_close.
    # If your parquet includes 'spy_close' somewhere, use it; otherwise we use existing forward columns.
    # Preferred: compute forward returns off close prices if available.
    # Try to find it.
    price_candidates = [
        f"{sig}__spy_close",
        "spy_close",
        "close__spy_close",
        "open__spy_close",
    ]
    price_col = next((c for c in price_candidates if c in df.columns), None)

    if price_col is not None:
        df = _add_forward_returns(df, price_col=price_col, horizons=horizons)
        ret_cols = [f"fwd_ret_cc_{h}d" for h in horizons]
    else:
        # fallback: use whatever exists
        ret_cols = []
        for h in horizons:
            c = f"{sig}__fwd_ret_cc_{h}d"
            if c in df.columns:
                ret_cols.append(c)
        if not ret_cols and f"{sig}__fwd_ret_cc_1d" in df.columns:
            ret_cols = [f"{sig}__fwd_ret_cc_1d"]

    if score_col not in df.columns:
        raise RuntimeError(f"Missing score column: {score_col}. Available cols sample: {list(df.columns)[:20]}")

    # --- Core analyses ---
    for ret_col in ret_cols:
        # Deciles
        dec = decile_table(df, score_col=score_col, ret_col=ret_col, n=10)
        dec_path = outdir / f"deciles_{sig}_{ret_col}.csv"
        dec.to_csv(dec_path, index=False)

        # Thresholds
        hi = threshold_table(df, score_col=score_col, ret_col=ret_col, thresholds=[60, 65, 70, 75, 80], direction="gt")
        lo = threshold_table(df, score_col=score_col, ret_col=ret_col, thresholds=[40, 35, 30, 25, 20], direction="lt")

        hi_path = outdir / f"threshold_high_{sig}_{ret_col}.csv"
        lo_path = outdir / f"threshold_low_{sig}_{ret_col}.csv"
        hi.to_csv(hi_path, index=False)
        lo.to_csv(lo_path, index=False)

        # With confidence filter (if available)
        if conf_col in df.columns:
            df_cf = df.copy()
            df_cf = df_cf[df_cf[conf_col].notna()]
            # Only keep confidence >= 70 and redo thresholds
            df_cf = df_cf[df_cf[conf_col] >= 70]

            hi_cf = threshold_table(df_cf, score_col=score_col, ret_col=ret_col, thresholds=[60, 65, 70, 75, 80], direction="gt")
            lo_cf = threshold_table(df_cf, score_col=score_col, ret_col=ret_col, thresholds=[40, 35, 30, 25, 20], direction="lt")

            hi_cf.to_csv(outdir / f"threshold_high_{sig}_{ret_col}_conf70.csv", index=False)
            lo_cf.to_csv(outdir / f"threshold_low_{sig}_{ret_col}_conf70.csv", index=False)

        # Print a quick summary to console
        best_dec, worst_dec = summarize_best_worst(dec, metric="mean_ret_%", topk=3)

        print(f"\n=== {sig.upper()} | {ret_col} ===")
        print("Best deciles by mean return:")
        print(best_dec[["bucket", "count", "score_min", "score_max", "mean_ret_%", "hit_rate_%"]].to_string(index=False))
        print("Worst deciles by mean return:")
        print(worst_dec[["bucket", "count", "score_min", "score_max", "mean_ret_%", "hit_rate_%"]].to_string(index=False))

        print("\nHigh thresholds:")
        print(hi.to_string(index=False))
        print("\nLow thresholds:")
        print(lo.to_string(index=False))

        if conf_col in df.columns:
            print("\nHigh thresholds (conf>=70):")
            print(pd.read_csv(outdir / f"threshold_high_{sig}_{ret_col}_conf70.csv").to_string(index=False))
            print("\nLow thresholds (conf>=70):")
            print(pd.read_csv(outdir / f"threshold_low_{sig}_{ret_col}_conf70.csv").to_string(index=False))

    print(f"\n✅ Tables saved to: {outdir}")


if __name__ == "__main__":
    main()
