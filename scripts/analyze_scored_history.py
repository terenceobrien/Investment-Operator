# scripts/analyze_scored_history.py
from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import argparse
from typing import List, Tuple

import numpy as np
import pandas as pd


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_and_filter(path: Path, signal: str) -> pd.DataFrame:
    """
    Load the research CSV/parquet and filter to the requested signal_time.
    Handles both the old prefixed-column format and the current flat format.
    """
    if path.suffix.lower() == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # ── Current format: signal_time is a row value, columns are unprefixed ──
    if "signal_time" in df.columns:
        df = df[df["signal_time"] == signal].copy()
        df = df.reset_index(drop=True)
        return df

    # ── Legacy format: columns prefixed with open__ / close__ ──
    prefix = f"{signal}__"
    prefixed = [c for c in df.columns if c.startswith(prefix)]
    if prefixed:
        rename = {c: c[len(prefix):] for c in prefixed}
        df = df[prefixed].rename(columns=rename).copy()
        return df

    raise RuntimeError(
        f"Cannot find signal_time column or '{signal}__' prefixed columns. "
        f"Available columns (first 20): {list(df.columns[:20])}"
    )


def decile_table(df: pd.DataFrame, score_col: str, ret_col: str, n: int = 10) -> pd.DataFrame:
    """
    Bucket score into deciles and compute mean/median/hit-rate/count of forward returns.
    """
    x = df[[score_col, ret_col]].dropna().copy()
    if x.empty:
        return pd.DataFrame()

    try:
        x["bucket"] = pd.qcut(x[score_col], n, duplicates="drop")
    except Exception:
        r = x[score_col].rank(method="first")
        x["bucket"] = pd.qcut(r, n, duplicates="drop")

    g = x.groupby("bucket")[ret_col]
    tab = pd.DataFrame({
        "count":        g.size(),
        "mean_ret_%":   g.mean(),
        "median_ret_%": g.median(),
        "hit_rate_%":   g.apply(lambda s: (s > 0).mean()) * 100.0,
        "stdev_%":      g.std(ddof=0),
    })

    ranges = x.groupby("bucket")[score_col].agg(["min", "max", "mean"])
    tab["score_min"]  = ranges["min"]
    tab["score_max"]  = ranges["max"]
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
    Compute stats for score >= threshold (gt) or score <= threshold (lt).
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
            "threshold":    label,
            "count":        int(s.shape[0]),
            "mean_ret_%":   round(float(s.mean()),   3),
            "median_ret_%": round(float(s.median()), 3),
            "hit_rate_%":   round(float((s > 0).mean() * 100.0), 1),
            "stdev_%":      round(float(s.std(ddof=0)), 3),
        })

    return pd.DataFrame(out_rows)


def environment_table(df: pd.DataFrame, ret_col: str) -> pd.DataFrame:
    """
    Compute return stats by environment classification.
    """
    if "environment" not in df.columns:
        return pd.DataFrame()

    rows = []
    for env, grp in df.groupby("environment"):
        s = grp[ret_col].dropna()
        if len(s) < 5:
            continue
        rows.append({
            "environment":  env,
            "count":        int(len(s)),
            "mean_ret_%":   round(float(s.mean()),   3),
            "median_ret_%": round(float(s.median()), 3),
            "hit_rate_%":   round(float((s > 0).mean() * 100.0), 1),
            "p25_%":        round(float(s.quantile(0.25)), 3),
            "p75_%":        round(float(s.quantile(0.75)), 3),
            "stdev_%":      round(float(s.std(ddof=0)), 3),
        })

    return pd.DataFrame(rows).sort_values("mean_ret_%", ascending=False)


def summarize_best_worst(
    tab: pd.DataFrame, metric: str = "mean_ret_%", topk: int = 3
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    t = tab.dropna(subset=[metric]).copy()
    if t.empty:
        return t, t
    best  = t.sort_values(metric, ascending=False).head(topk)
    worst = t.sort_values(metric, ascending=True).head(topk)
    return best, worst


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Analyze scored history from run_backtest_features.py"
    )
    ap.add_argument("--file",     required=True,  help="Path to CSV or parquet from run_backtest_features")
    ap.add_argument("--signal",   choices=["open", "close"], default="close",
                    help="Which signal_time to analyze (default: close)")
    ap.add_argument("--horizons", default="1,5,21",
                    help="Forward horizons in days, comma-separated (default: 1,5,21)")
    ap.add_argument("--outdir",   default="data/backtests/analysis",
                    help="Output directory for CSV tables")
    ap.add_argument("--min-conf", type=float, default=70.0,
                    help="Confidence threshold for filtered analysis (default: 70)")
    args = ap.parse_args()

    path   = Path(args.file)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    horizons = [int(x.strip()) for x in args.horizons.split(",") if x.strip()]

    # ── Load + filter ──
    df = _load_and_filter(path, args.signal)
    print(f"Loaded {len(df)} rows for signal_time='{args.signal}'")
    print(f"Date range: {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"Score range: {df['score_total'].min():.1f} – {df['score_total'].max():.1f}")
    print(f"Environments: {df['environment'].value_counts().to_dict()}")

    score_col = "score_total"
    conf_col  = "confidence"

    # ── Map requested horizons to columns ──
    # Forward returns are stored as decimals (e.g. 0.027 = 2.7%)
    # We multiply by 100 for display/analysis
    horizon_col_map = {
        1:  "fwd_ret_cc_1d",
        3:  "fwd_ret_cc_3d",
        5:  "fwd_ret_cc_5d",
        10: "fwd_ret_cc_10d",
        21: "fwd_ret_cc_21d",
        63: "fwd_ret_cc_63d",
    }

    # Build analysis dataframe with pct-scaled returns
    df_pct = df.copy()
    ret_cols_to_use = []
    for h in horizons:
        raw_col = horizon_col_map.get(h)
        if raw_col and raw_col in df_pct.columns:
            pct_col = f"ret_{h}d_pct"
            df_pct[pct_col] = df_pct[raw_col] * 100.0
            ret_cols_to_use.append((h, pct_col))
        else:
            print(f"  Warning: no column for horizon {h}d — skipping")

    if not ret_cols_to_use:
        raise RuntimeError(
            f"None of the requested horizons {horizons} found in data. "
            f"Available fwd cols: {[c for c in df.columns if 'fwd_ret' in c]}"
        )

    # Confidence-filtered subset
    has_conf = conf_col in df_pct.columns
    if has_conf:
        df_cf = df_pct[df_pct[conf_col] >= args.min_conf].copy()
        print(f"Confidence >= {args.min_conf}: {len(df_cf)} rows ({len(df_cf)/len(df_pct)*100:.0f}%)")

    # ── Run analyses per horizon ──
    for h, ret_col in ret_cols_to_use:
        print(f"\n{'='*60}")
        print(f"SIGNAL={args.signal.upper()}  HORIZON={h}d  ({ret_col})")
        print(f"{'='*60}")

        # 1) Decile table
        dec = decile_table(df_pct, score_col=score_col, ret_col=ret_col, n=10)
        if not dec.empty:
            dec.to_csv(outdir / f"deciles_{args.signal}_{h}d.csv", index=False)
            best, worst = summarize_best_worst(dec)
            print("\nTop deciles:")
            print(best[["bucket","count","score_min","score_max","mean_ret_%","hit_rate_%"]].to_string(index=False))
            print("Bottom deciles:")
            print(worst[["bucket","count","score_min","score_max","mean_ret_%","hit_rate_%"]].to_string(index=False))

        # 2) Threshold tables
        hi = threshold_table(df_pct, score_col, ret_col, [60, 65, 70, 75, 80], "gt")
        lo = threshold_table(df_pct, score_col, ret_col, [40, 35, 30, 25, 20], "lt")
        hi.to_csv(outdir / f"threshold_high_{args.signal}_{h}d.csv", index=False)
        lo.to_csv(outdir / f"threshold_low_{args.signal}_{h}d.csv",  index=False)

        print("\nHigh score thresholds:")
        print(hi.to_string(index=False))
        print("\nLow score thresholds:")
        print(lo.to_string(index=False))

        # 3) Environment table
        env_tab = environment_table(df_pct, ret_col)
        if not env_tab.empty:
            env_tab.to_csv(outdir / f"by_environment_{args.signal}_{h}d.csv", index=False)
            print("\nBy environment:")
            print(env_tab.to_string(index=False))

        # 4) Confidence-filtered
        if has_conf and len(df_cf) >= 30:
            hi_cf = threshold_table(df_cf, score_col, ret_col, [60, 65, 70, 75, 80], "gt")
            lo_cf = threshold_table(df_cf, score_col, ret_col, [40, 35, 30, 25, 20], "lt")
            hi_cf.to_csv(outdir / f"threshold_high_{args.signal}_{h}d_conf{int(args.min_conf)}.csv", index=False)
            lo_cf.to_csv(outdir / f"threshold_low_{args.signal}_{h}d_conf{int(args.min_conf)}.csv",  index=False)
            print(f"\nHigh thresholds (conf>={args.min_conf:.0f}):")
            print(hi_cf.to_string(index=False))
            print(f"\nLow thresholds (conf>={args.min_conf:.0f}):")
            print(lo_cf.to_string(index=False))

    print(f"\n✅ Tables saved to: {outdir}")


if __name__ == "__main__":
    main()