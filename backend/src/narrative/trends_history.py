"""
narrative/trends_history.py

Historical Google Trends backtest and window-stitching module.

Provides:
  - fetch_term_history     : multi-window pytrends fetch with overlap stitching
  - compute_asvi           : Abnormal Search Volume Index (Da et al. 2011)
  - run_historical_backtest: correlation analysis vs forward SPY returns
  - BacktestResult         : result container with save() and plot()
  - _generate_synthetic_history: fully offline synthetic dataset for testing
  - _stitch_windows        : overlap-averaging stitcher
  - _classify_tier         : term tier classifier
  - BROAD_TERMS, INTERMEDIATE_TERMS, DISTRESS_SPECIFIC_TERMS

Backtest interpretation:
  High ASVI (abnormally high search interest in distress topics) precedes
  negative forward equity returns. Correlation should be negative; more
  negative = higher signal quality. Distress-specific terms spike sharply
  around crises and have the strongest predictive value.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("narrative.trends_history")
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Term taxonomy (3 tiers)
# ---------------------------------------------------------------------------

BROAD_TERMS: List[str] = [
    "stock market",
    "economy",
    "investing",
    "stocks",
    "finance",
]

INTERMEDIATE_TERMS: List[str] = [
    "recession",
    "inflation",
    "interest rates",
    "unemployment",
]

DISTRESS_SPECIFIC_TERMS: List[str] = [
    "bank failure",
    "bank run",
    "stock market crash",
    "debt crisis",
    "credit crunch",
]

ALL_HISTORY_TERMS: List[str] = BROAD_TERMS + INTERMEDIATE_TERMS + DISTRESS_SPECIFIC_TERMS


def _classify_tier(term: str) -> str:
    """Return 'broad', 'intermediate', 'distress_specific', or 'unknown'."""
    if term in BROAD_TERMS:
        return "broad"
    if term in INTERMEDIATE_TERMS:
        return "intermediate"
    if term in DISTRESS_SPECIFIC_TERMS:
        return "distress_specific"
    return "unknown"


# ---------------------------------------------------------------------------
# Window stitching
# ---------------------------------------------------------------------------

def _stitch_windows(
    windows: Sequence[Tuple[pd.DatetimeIndex, pd.Series, pd.Series]],
) -> pd.Series:
    """
    Stitch overlapping pytrends windows into one continuous normalized series.

    Each window is (date_index, term_series, anchor_series).
    Within each window: normalized = term / anchor * 100 (anchor=0 → NaN → 0).
    Overlapping dates are averaged across all contributing windows.

    Returns a sorted pd.Series indexed by date.
    """
    per_date: Dict[pd.Timestamp, List[float]] = {}

    for dates, term_s, anchor_s in windows:
        for dt, t_val, a_val in zip(dates, term_s.values, anchor_s.values):
            if a_val and not np.isnan(a_val) and a_val != 0:
                norm = float(t_val) / float(a_val) * 100.0
            else:
                norm = float(t_val) if not np.isnan(t_val) else 0.0
            per_date.setdefault(pd.Timestamp(dt), []).append(norm)

    if not per_date:
        return pd.Series(dtype=float)

    dates_sorted = sorted(per_date.keys())
    values = [float(np.mean(per_date[d])) for d in dates_sorted]
    return pd.Series(values, index=pd.DatetimeIndex(dates_sorted))


# ---------------------------------------------------------------------------
# ASVI computation
# ---------------------------------------------------------------------------

def compute_asvi(series: pd.Series, warmup: int = 8) -> pd.Series:
    """
    Compute Abnormal Search Volume Index.

    ASVI(t) = log(SVI(t) + 1) - log(median(SVI[t-warmup : t]) + 1)

    For t < warmup, returns NaN.
    A constant series yields ≈ 0 after warmup.
    A spike above the baseline yields positive ASVI.
    """
    values = series.values.astype(float)
    n = len(values)
    result = np.full(n, np.nan)

    for i in range(warmup, n):
        baseline_window = values[max(0, i - warmup): i]
        baseline = np.median(baseline_window)
        result[i] = np.log1p(values[i]) - np.log1p(baseline)

    return pd.Series(result, index=series.index)


# ---------------------------------------------------------------------------
# Synthetic history generator (offline / testing)
# ---------------------------------------------------------------------------

def _generate_synthetic_history(n_weeks: int = 900, seed: int = 42) -> pd.DataFrame:
    """
    Generate a fully offline synthetic history DataFrame.

    Columns: one per term in ALL_HISTORY_TERMS (14 terms),
             plus 'spy_return' and 'spy_cumulative'.
    Index: weekly DatetimeIndex (Mondays), n_weeks rows.

    Crisis events are planted at irregular intervals; distress-specific terms
    spike sharply 1–4 weeks before each crisis trough, guaranteeing negative
    correlation between their ASVI and forward SPY returns.
    """
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2008-01-07")
    index = pd.date_range(start, periods=n_weeks, freq="W-MON")

    # ── SPY weekly returns ──────────────────────────────────────────────────
    spy_ret = rng.normal(0.002, 0.022, n_weeks)

    # Plant crisis drawdowns
    crisis_weeks = [30, 90, 170, 260, 340, 430, 530, 620, 720, 810]
    for cw in crisis_weeks:
        if cw + 6 < n_weeks:
            spy_ret[cw:cw + 6] -= rng.uniform(0.025, 0.06, 6)

    spy_cumulative = np.cumprod(1 + spy_ret)

    # ── Term search interest ────────────────────────────────────────────────
    data: Dict[str, np.ndarray] = {}

    # Pre-compute 4-week forward cumulative return at each time step — used to
    # bake in negative ASVI→future-return correlation for all term tiers.
    # fwd4[t] = spy_ret[t+1] + ... + spy_ret[t+4] (approximate linear sum)
    fwd4 = np.zeros(n_weeks)
    for t in range(n_weeks - 4):
        fwd4[t] = spy_ret[t + 1 : t + 5].sum()
    # Normalise to [0,1] range (inverted: bad future = 1, good future = 0)
    fwd4_min, fwd4_max = fwd4.min(), fwd4.max()
    fwd4_norm = 1.0 - (fwd4 - fwd4_min) / (fwd4_max - fwd4_min + 1e-9)

    for term in BROAD_TERMS:
        base = rng.uniform(40, 70)
        noise = rng.normal(0, 5, n_weeks)
        vals = np.clip(base + noise, 0, 100)
        # Crisis-window elevation (1-4w before each trough)
        for cw in crisis_weeks:
            for lag in range(1, 5):
                idx = cw - lag
                if 0 <= idx < n_weeks:
                    vals[idx] = min(100, vals[idx] + rng.uniform(6, 14))
        # Global forward-return component — ensures negative ASVI→fwd correlation
        vals = np.clip(vals + fwd4_norm * 12.0, 0, 100)
        data[term] = vals

    for term in INTERMEDIATE_TERMS:
        base = rng.uniform(20, 45)
        noise = rng.normal(0, 6, n_weeks)
        vals = np.clip(base + noise, 0, 100)
        for cw in crisis_weeks:
            for lag in range(1, 6):
                idx = cw - lag
                if 0 <= idx < n_weeks:
                    vals[idx] = min(100, vals[idx] + rng.uniform(12, 22))
        vals = np.clip(vals + fwd4_norm * 18.0, 0, 100)
        data[term] = vals

    for term in DISTRESS_SPECIFIC_TERMS:
        base = rng.uniform(5, 15)
        noise = rng.normal(0, 3, n_weeks)
        vals = np.clip(base + noise, 0, 100)
        # Sharp pre-crisis spikes
        for cw in crisis_weeks:
            for lag in range(1, 5):
                idx = cw - lag
                if 0 <= idx < n_weeks:
                    vals[idx] = min(100, vals[idx] + rng.uniform(35, 65))
        vals = np.clip(vals + fwd4_norm * 30.0, 0, 100)
        data[term] = vals

    df = pd.DataFrame(data, index=index)
    df["spy_return"] = spy_ret
    df["spy_cumulative"] = spy_cumulative
    return df


# ---------------------------------------------------------------------------
# pytrends single-term fetch (used by validate_trends_live.py)
# ---------------------------------------------------------------------------

def fetch_term_history(
    term: str,
    start: str,
    end: Optional[str] = None,
    geo: str = "US",
    delay_range: Tuple[float, float] = (3.0, 8.0),
) -> pd.Series:
    """
    Fetch historical weekly Google Trends data for a single term by stitching
    overlapping 5-year windows.

    Requires pytrends to be installed. Raises ImportError if not.
    Returns a weekly pd.Series indexed by date, anchor-normalized.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError as exc:
        raise ImportError(
            "pytrends required: pip install pytrends"
        ) from exc

    from narrative.trends import ANCHOR_TERM  # reuse existing anchor

    end_dt = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now()
    start_dt = datetime.strptime(start, "%Y-%m-%d")

    # Build overlapping 4-year windows stepping by 3 years
    window_months = 48
    step_months = 36
    windows_raw: List[Tuple[pd.DatetimeIndex, pd.Series, pd.Series]] = []

    cur_start = start_dt
    while cur_start < end_dt:
        cur_end = min(cur_start + timedelta(days=window_months * 30), end_dt)
        tf = (
            f"{cur_start.strftime('%Y-%m-%d')} "
            f"{cur_end.strftime('%Y-%m-%d')}"
        )
        try:
            pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 30), retries=2, backoff_factor=1.5)
            pytrends.build_payload([ANCHOR_TERM, term], cat=0, timeframe=tf, geo=geo)
            df = pytrends.interest_over_time()
            if df is not None and not df.empty and term in df.columns:
                dti = pd.DatetimeIndex(df.index)
                windows_raw.append((dti, df[term].astype(float), df[ANCHOR_TERM].astype(float)))
        except Exception as exc:
            logger.warning("fetch_term_history window %s failed: %s", tf, exc)

        cur_start += timedelta(days=step_months * 30)
        if cur_start < end_dt:
            delay = delay_range[0] + random.random() * (delay_range[1] - delay_range[0])
            time.sleep(delay)

    if not windows_raw:
        return pd.Series(dtype=float, name=term)

    stitched = _stitch_windows(windows_raw)
    stitched.name = term
    return stitched


# ---------------------------------------------------------------------------
# Backtest result containers
# ---------------------------------------------------------------------------

@dataclass
class TermBacktestResult:
    term: str
    tier: str
    n_observations: int
    corr_asvi_fwd_1w: float
    p_val_1w: float
    corr_asvi_fwd_4w: float
    p_val_4w: float
    corr_asvi_fwd_8w: float
    p_val_8w: float
    corr_asvi_fwd_13w: float
    p_val_13w: float
    signal_quality: float  # max(0, -corr_4w) * (1 - p_val_4w)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    term_results: List[TermBacktestResult]
    start: str
    end: str
    use_synthetic: bool
    run_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "term_results": [r.to_dict() for r in self.term_results],
            "start": self.start,
            "end": self.end,
            "use_synthetic": self.use_synthetic,
            "run_at_utc": self.run_at_utc,
        }

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame([r.to_dict() for r in self.term_results])

    def plot(self, path: str) -> None:
        """Save a bar chart of signal_quality per term, coloured by tier."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        df = self.to_dataframe().sort_values("signal_quality", ascending=True)
        tier_colors = {
            "broad": "#5b8dd9",
            "intermediate": "#e8a838",
            "distress_specific": "#d95b5b",
            "unknown": "#888888",
        }
        colors = [tier_colors.get(t, "#888888") for t in df["tier"]]

        fig, ax = plt.subplots(figsize=(12, max(5, len(df) * 0.55)))
        bars = ax.barh(df["term"], df["signal_quality"], color=colors)
        ax.set_xlabel("Signal Quality  (higher = stronger leading indicator)")
        ax.set_title("Google Trends ASVI — Signal Quality by Term")
        ax.axvline(0, color="#444", lw=0.8, ls="--")

        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=c, label=k.replace("_", " ").title())
            for k, c in tier_colors.items()
            if k != "unknown"
        ]
        ax.legend(handles=legend_elements, loc="lower right", fontsize=8)

        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)


def plot_signal_quality(
    term_results: List[TermBacktestResult],
    path: str,
) -> None:
    """
    Save a scatter chart of (correlation, p-value) per term, coloured by tier.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tier_colors = {
        "broad": "#5b8dd9",
        "intermediate": "#e8a838",
        "distress_specific": "#d95b5b",
        "unknown": "#888888",
    }

    fig, ax = plt.subplots(figsize=(8, 5))
    for r in term_results:
        color = tier_colors.get(r.tier, "#888888")
        ax.scatter(r.corr_asvi_fwd_4w, r.p_val_4w, color=color, s=60, zorder=3)
        ax.annotate(r.term, (r.corr_asvi_fwd_4w, r.p_val_4w),
                    fontsize=7, textcoords="offset points", xytext=(4, 2))

    ax.axhline(0.05, color="#888", ls="--", lw=0.8, label="p = 0.05")
    ax.axvline(0, color="#888", ls="--", lw=0.8)
    ax.set_xlabel("Correlation: ASVI → Fwd-4w SPY Return")
    ax.set_ylabel("p-value")
    ax.set_title("Signal Quality: ASVI vs Forward SPY Returns (4-week)")
    ax.invert_yaxis()

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=c, label=k.replace("_", " ").title())
        for k, c in tier_colors.items() if k != "unknown"
    ]
    ax.legend(handles=legend_elements, fontsize=8)

    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

def _compute_correlations(
    asvi: pd.Series,
    spy_ret: pd.Series,
) -> Dict[str, float]:
    """
    Compute Pearson correlation between ASVI(t) and fwd SPY return at
    1w, 4w, 8w, 13w horizons. Returns dict with corr_* and p_val_* keys.
    """
    from scipy import stats

    results: Dict[str, float] = {}
    for horizon in (1, 4, 8, 13):
        fwd = spy_ret.shift(-horizon)
        combined = pd.DataFrame({"asvi": asvi, "fwd": fwd}).dropna()
        if len(combined) < 10:
            results[f"corr_asvi_fwd_{horizon}w"] = float("nan")
            results[f"p_val_{horizon}w"] = float("nan")
            continue
        r, p = stats.pearsonr(combined["asvi"], combined["fwd"])
        results[f"corr_asvi_fwd_{horizon}w"] = float(r)
        results[f"p_val_{horizon}w"] = float(p)

    return results


def run_historical_backtest(
    use_synthetic: bool = True,
    start: Optional[str] = None,
    end: Optional[str] = None,
    geo: str = "US",
    delay_range: Tuple[float, float] = (3.0, 8.0),
) -> BacktestResult:
    """
    Run the full historical ASVI backtest.

    Args:
        use_synthetic: If True, use _generate_synthetic_history() — fully offline.
        start:         Start date (YYYY-MM-DD). Ignored when use_synthetic=True.
        end:           End date. Defaults to today when not synthetic.
        geo:           Google Trends geo.
        delay_range:   Rate-limit delay between pytrends requests.

    Returns:
        BacktestResult with one TermBacktestResult per term.
    """
    if use_synthetic:
        df = _generate_synthetic_history()
        start_used = str(df.index[0].date())
        end_used = str(df.index[-1].date())
        spy_ret = df["spy_return"]
        hist: Dict[str, pd.Series] = {t: df[t] for t in ALL_HISTORY_TERMS}
    else:
        if not start:
            raise ValueError("start date required when use_synthetic=False")
        end_used = end or datetime.now().strftime("%Y-%m-%d")
        start_used = start

        hist = {}
        for i, term in enumerate(ALL_HISTORY_TERMS):
            if i > 0:
                delay = delay_range[0] + random.random() * (delay_range[1] - delay_range[0])
                time.sleep(delay)
            logger.info("Fetching history for term '%s' (%d/%d)", term, i + 1, len(ALL_HISTORY_TERMS))
            try:
                hist[term] = fetch_term_history(term, start=start_used, end=end_used,
                                                geo=geo, delay_range=delay_range)
            except Exception as exc:
                logger.error("Failed to fetch '%s': %s", term, exc)
                hist[term] = pd.Series(dtype=float)

        # Fetch SPY via yfinance
        import yfinance as yf
        spy_df = yf.download("SPY", start=start_used, end=end_used,
                             auto_adjust=True, progress=False)
        if isinstance(spy_df.columns, pd.MultiIndex):
            spy_df.columns = spy_df.columns.get_level_values(0)
        spy_weekly = spy_df["Close"].resample("W-MON").last().dropna()
        spy_ret = spy_weekly.pct_change().dropna()

    # Compute ASVI and correlations per term
    term_results: List[TermBacktestResult] = []

    for term in ALL_HISTORY_TERMS:
        raw = hist.get(term)
        if raw is None or raw.empty:
            continue

        # Align raw term data with spy_ret on weekly index
        raw_weekly = raw.resample("W-MON").last() if hasattr(raw.index, "freq") or len(raw) > 1 else raw

        asvi = compute_asvi(raw_weekly)

        # Align asvi to spy_ret index
        common_idx = asvi.index.intersection(spy_ret.index)
        if len(common_idx) < 10:
            # Fall back to positional alignment
            min_len = min(len(asvi.dropna()), len(spy_ret))
            asvi_aligned = asvi.dropna().iloc[:min_len]
            spy_aligned = spy_ret.iloc[:min_len]
            asvi_aligned = asvi_aligned.reset_index(drop=True)
            spy_aligned = spy_aligned.reset_index(drop=True)
            n_obs = min_len
        else:
            asvi_aligned = asvi.loc[common_idx]
            spy_aligned = spy_ret.loc[common_idx]
            n_obs = len(common_idx)

        corrs = _compute_correlations(asvi_aligned, spy_aligned)

        c4 = corrs.get("corr_asvi_fwd_4w", float("nan"))
        p4 = corrs.get("p_val_4w", float("nan"))
        sq = max(0.0, -c4) * (1.0 - p4) if not (np.isnan(c4) or np.isnan(p4)) else 0.0

        term_results.append(TermBacktestResult(
            term=term,
            tier=_classify_tier(term),
            n_observations=n_obs,
            corr_asvi_fwd_1w=corrs.get("corr_asvi_fwd_1w", float("nan")),
            p_val_1w=corrs.get("p_val_1w", float("nan")),
            corr_asvi_fwd_4w=c4,
            p_val_4w=p4,
            corr_asvi_fwd_8w=corrs.get("corr_asvi_fwd_8w", float("nan")),
            p_val_8w=corrs.get("p_val_8w", float("nan")),
            corr_asvi_fwd_13w=corrs.get("corr_asvi_fwd_13w", float("nan")),
            p_val_13w=corrs.get("p_val_13w", float("nan")),
            signal_quality=round(sq, 6),
        ))

    return BacktestResult(
        term_results=term_results,
        start=start_used,
        end=end_used,
        use_synthetic=use_synthetic,
    )
