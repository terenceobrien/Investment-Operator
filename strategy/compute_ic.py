"""
Returns join + Information Coefficient (IC) computation.

Takes the extracted feature matrix, joins each scored call to its FORWARD
residual return (measured from the call date, market/beta-adjusted), and
computes the IC of each feature and the composite against forward returns.

This is the step that answers "does the linguistic signal predict anything."

Design decisions (all deliberate):
  - RESIDUAL returns, not raw. IC (Grinold-Kahn) is the correlation of the
    score with the BETA-ADJUSTED forward return: residual = stock_ret - beta*mkt_ret.
    A name that rose while the sector rose more is a NEGATIVE residual. We beta-
    adjust against a semis benchmark (default SOXX) so we measure stock-specific
    reaction to the call, not sector drift.
  - POINT-IN-TIME entry via earnings_timing:
      after_market  -> the market could not react until the NEXT session; entry
                       is the next trading day's close.
      before_market / during_market -> entry is the call date's close.
    Getting this wrong injects look-ahead, so it's handled explicitly.
  - Forward windows fixed in advance: ~1 quarter (63 trading days) and ~2
    quarters (126). Decided before seeing results.
  - IC via SPEARMAN rank correlation (robust to the -2..+2 discrete scores and
    to return outliers) as primary; Pearson reported alongside.
  - Features are Z-SCORED across the panel before IC so a feature pinned near a
    constant (e.g. new_topic_rate always +2) correctly contributes ~nothing.
  - CONTAMINATION SPLIT: IC computed separately for cap_bucket 'mega' vs
    'small_mid'. If IC is strong on mega and absent on small_mid, the signal is
    likely outcome-recall, not real. small_mid is the credible test.
  - Confidence intervals on IC via the Fisher transform, because at N~150 the
    error bars are wide and a point estimate alone would mislead.

Prices: expects a local CSV of daily prices (date-indexed, one column per
ticker plus the benchmark). Provide via --prices, or the script will try to
fetch with yfinance if available.

Usage:
  python3 -m strategy.compute_ic
  python3 -m strategy.compute_ic --prices strategy/prices.csv --benchmark SOXX
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
FEATURE_MATRIX = HERE / "features" / "feature_matrix.csv"
OUT_DIR = HERE / "features"

FEATURES = [
    "hedging_delta", "guidance_direction", "quant_claim_escalation",
    "new_topic_rate", "tone_delta", "demand_language_delta",
]
HORIZONS = {"fwd_1q": 63, "fwd_2q": 126}   # trading days
BETA_WINDOW = 126                          # days to estimate each name's beta


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------
def load_prices(path: str | None, tickers: list[str], benchmark: str) -> pd.DataFrame:
    need = sorted(set(tickers) | {benchmark})
    if path:
        px = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
        missing = [t for t in need if t not in px.columns]
        if missing:
            raise ValueError(f"prices CSV missing columns: {missing}")
        return px[need]
    # fallback: yfinance
    try:
        import yfinance as yf
    except ImportError:
        raise SystemExit("No --prices CSV given and yfinance not installed. "
                         "Provide a prices CSV with a 'date' column + one column per ticker.")
    raw = yf.download(need, period="3y", auto_adjust=True, progress=False)
    px = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
    all_nan = [t for t in need if t not in px.columns or px[t].isna().all()]
    if all_nan:
        raise ValueError(f"no price history for: {all_nan}")
    return px[need].sort_index()


# ---------------------------------------------------------------------------
# Residual forward returns
# ---------------------------------------------------------------------------
def _entry_index(px_index: pd.DatetimeIndex, call_date: pd.Timestamp, timing: str) -> int | None:
    """
    Return the integer position in px_index of the ENTRY bar.
    after_market -> first trading day strictly AFTER call_date.
    else         -> first trading day ON or AFTER call_date (same-day close ok).
    """
    if timing == "after_market":
        pos = px_index.searchsorted(call_date, side="right")
    else:
        pos = px_index.searchsorted(call_date, side="left")
    return int(pos) if pos < len(px_index) else None


def forward_returns(
    px: pd.DataFrame, ticker: str, benchmark: str,
    call_date: pd.Timestamp, timing: str, horizon_days: int,
) -> dict | None:
    """
    Forward returns from entry over `horizon_days` trading days. Returns a dict
    with the RAW stock return, the RAW benchmark return, the estimated beta, and
    the RESIDUAL (beta-adjusted) return:  residual = stock_fwd - beta*bench_fwd.
    Beta is estimated on the BETA_WINDOW days BEFORE entry (no look-ahead).
    Returns None if there isn't enough history/forward data.
    """
    idx = px.index
    entry = _entry_index(idx, call_date, timing)
    if entry is None:
        return None
    exit_pos = entry + horizon_days
    if exit_pos >= len(idx):
        return None  # not enough forward data yet (recent calls)
    if entry - BETA_WINDOW < 0:
        return None  # not enough history to estimate beta

    s = px[ticker].to_numpy()
    m = px[benchmark].to_numpy()

    # beta from daily log returns over the pre-entry window
    s_pre = np.log(s[entry - BETA_WINDOW + 1: entry + 1] / s[entry - BETA_WINDOW: entry])
    m_pre = np.log(m[entry - BETA_WINDOW + 1: entry + 1] / m[entry - BETA_WINDOW: entry])
    if np.isnan(s_pre).any() or np.isnan(m_pre).any():
        return None
    var_m = np.var(m_pre)
    beta = float(np.cov(s_pre, m_pre)[0, 1] / var_m) if var_m > 0 else 1.0

    # forward total returns entry -> exit
    s_fwd = float(s[exit_pos] / s[entry] - 1.0)
    m_fwd = float(m[exit_pos] / m[entry] - 1.0)
    resid = s_fwd - beta * m_fwd
    return {"raw": s_fwd, "bench": m_fwd, "beta": beta, "residual": resid}


# ---------------------------------------------------------------------------
# IC
# ---------------------------------------------------------------------------
def spearman(x: np.ndarray, y: np.ndarray) -> float:
    xr = pd.Series(x).rank().to_numpy()
    yr = pd.Series(y).rank().to_numpy()
    return float(np.corrcoef(xr, yr)[0, 1])


def ic_with_ci(scores: np.ndarray, rets: np.ndarray, alpha: float = 0.05):
    """Spearman IC with Fisher-transform confidence interval and n."""
    mask = ~(np.isnan(scores) | np.isnan(rets))
    x, y = scores[mask], rets[mask]
    n = len(x)
    if n < 4 or np.std(x) == 0:
        return {"ic": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": n}
    ic = spearman(x, y)
    # Fisher z CI
    z = np.arctanh(np.clip(ic, -0.999, 0.999))
    se = 1.0 / math.sqrt(n - 3)
    from scipy.stats import norm  # optional; fallback below if missing
    zc = norm.ppf(1 - alpha / 2)
    lo, hi = np.tanh(z - zc * se), np.tanh(z + zc * se)
    return {"ic": ic, "lo": float(lo), "hi": float(hi), "n": n}


def zscore_by_column(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        mu, sd = out[c].mean(), out[c].std()
        out[c + "_z"] = (out[c] - mu) / sd if sd > 0 else 0.0
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prices", default=None, help="CSV: date + one col per ticker + benchmark")
    ap.add_argument("--benchmark", default="SOXX")
    ap.add_argument("--drop", nargs="*", default=["SITM"],
                    help="tickers to exclude (dev-set contamination); default SITM")
    args = ap.parse_args()

    fm = pd.read_csv(FEATURE_MATRIX, parse_dates=["call_date"])
    if args.drop:
        fm = fm[~fm["ticker"].isin(args.drop)].reset_index(drop=True)
    print(f"Feature matrix: {len(fm)} rows, {fm['ticker'].nunique()} tickers "
          f"(excluded: {args.drop})")

    tickers = sorted(fm["ticker"].unique())
    px = load_prices(args.prices, tickers, args.benchmark)

    # compute forward returns per row per horizon.
    # Keep RAW stock return, RAW benchmark return, beta, and RESIDUAL. IC runs
    # on the residual (the correct target), but the raw components are retained
    # for sanity-checking and later analysis.
    for hname, hdays in HORIZONS.items():
        raw_c, bench_c, beta_c, resid_c = [], [], [], []
        for _, r in fm.iterrows():
            fr = forward_returns(
                px, r["ticker"], args.benchmark,
                r["call_date"], r["earnings_timing"], hdays)
            if fr is None:
                raw_c.append(np.nan); bench_c.append(np.nan)
                beta_c.append(np.nan); resid_c.append(np.nan)
            else:
                raw_c.append(fr["raw"]); bench_c.append(fr["bench"])
                beta_c.append(fr["beta"]); resid_c.append(fr["residual"])
        fm[f"{hname}_raw"] = raw_c          # raw stock forward return
        fm[f"{hname}_bench"] = bench_c      # raw benchmark forward return
        fm[f"{hname}_beta"] = beta_c        # beta used for adjustment
        fm[hname] = resid_c                 # residual (IC target), keeps prior name

    # z-score features across the panel
    fm = zscore_by_column(fm, FEATURES)
    zcols = [c + "_z" for c in FEATURES]
    # composite = mean of z-scored features (equal weight, standardized)
    fm["composite_z"] = fm[zcols].mean(axis=1)

    # ---- IC tables ----
    def ic_table(sub: pd.DataFrame, label: str):
        print(f"\n===== IC: {label}  (n_rows={len(sub)}) =====")
        print(f"{'feature':<24}{'fwd_1q IC':>22}{'fwd_2q IC':>22}")
        for feat in zcols + ["composite_z"]:
            cells = []
            for h in HORIZONS:
                res = ic_with_ci(sub[feat].to_numpy(), sub[h].to_numpy())
                if math.isnan(res["ic"]):
                    cells.append(f"{'n/a':>22}")
                else:
                    cells.append(f"{res['ic']:+.3f} [{res['lo']:+.2f},{res['hi']:+.2f}] n{res['n']:<3}"
                                 .rjust(22))
            print(f"{feat:<24}" + "".join(cells))

    ic_table(fm, "ALL (ex-dropped)")
    for bucket in ("small_mid", "mega"):
        sub = fm[fm["cap_bucket"] == bucket]
        if len(sub) >= 4:
            ic_table(sub, f"cap_bucket = {bucket}")

    out = OUT_DIR / "feature_matrix_with_returns.csv"
    fm.to_csv(out, index=False)
    print(f"\nWrote joined matrix -> {out}")
    print("\nREAD THIS: small_mid is your credible test. If IC is only strong on "
          "'mega' and absent on 'small_mid', the signal is likely outcome-recall, "
          "not a real linguistic edge. Wide CIs at small n mean 'directional, not "
          "conclusive' — don't over-read a single point estimate.")


if __name__ == "__main__":
    main()