"""Forward-outcome tests for directional analogue match sets.

This module validates the standalone directional analogue matcher against later
macro outcomes. It does not produce scenario probabilities or touch the forecast
runner, BVAR, blend, legacy analogue matcher, or rolling composite.

Both neighbor-label modes are reported:
- in_sample: the original measurement, where a neighbor's full forward outcome
  is used whenever it fits inside known history.
- pit_observable: a point-in-time observable measurement, where a neighbor's
  outcome is used only if neighbor_date + horizon <= query_date.

The shrunk share is an a-priori beta-binomial style regularizer, not fitted:
share_shrunk = (kernel_weight_sum * share_raw + prior_strength * base_rate)
               / (kernel_weight_sum + prior_strength).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    DEFAULT_FORWARD_BUFFER_QUARTERS,
    DEFAULT_TREND_WEIGHT,
    AnalogueMatch,
    AnalogueMatcherError,
    default_library_path,
    load_directional_feature_library,
    match_analogues,
)
from src.agent_system.forecasting.scenario_classifier.data import default_cache_dir
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    load_directional_feature_cache,
)
from src.agent_system.forecasting.scenario_classifier.nber_dates import (
    NBER_PEAKS,
    parse_quarter,
    recession_within,
)


DEFAULT_HORIZON_QUARTERS = 8
DEFAULT_PRIOR_STRENGTH = 3.0
DEFAULT_MIN_POOL = 30
OUTPUT_FILENAME = "forward_outcome_results.csv"
COVID_FORWARD_WINDOW_START = pd.Period("2020Q1", freq="Q")
COVID_FORWARD_WINDOW_END = pd.Period("2020Q2", freq="Q")
MODE_IN_SAMPLE = "in_sample"
MODE_PIT = "pit_observable"
SHARE_MODES: tuple[str, ...] = (MODE_PIT, MODE_IN_SAMPLE)
SHARE_VERSIONS: tuple[str, ...] = ("shrunk", "raw")
MIN_EVALUABLE_CUTS: tuple[int, ...] = (1, 3, 5, 8)


class ForwardOutcomeError(RuntimeError):
    """Raised when forward-outcome testing would hide missing information."""


def default_output_path() -> Path:
    return default_cache_dir() / OUTPUT_FILENAME


def eligible_query_dates(
    library: str | Path | pd.DataFrame | None = None,
    *,
    horizon: int = DEFAULT_HORIZON_QUARTERS,
    forward_buffer_quarters: int = DEFAULT_FORWARD_BUFFER_QUARTERS,
) -> tuple[pd.Period, ...]:
    """Return query dates with point-in-time candidates and known forward history."""

    horizon_q = _validate_positive_int(horizon, "horizon")
    buffer_q = _validate_positive_int(forward_buffer_quarters, "forward_buffer_quarters")
    frame = load_directional_feature_library(library)
    periods = list(frame["_as_of_period"])
    min_period = min(periods)
    max_period = max(periods)
    last_eligible = max_period - horizon_q
    eligible = tuple(
        period
        for period in periods
        if period <= last_eligible
        and pit_candidate_pool_size(periods, period, buffer_q) > 0
    )
    if not eligible:
        raise ForwardOutcomeError(
            f"No eligible query dates for horizon={horizon_q}; library range "
            f"{min_period}..{max_period}, last eligible would be {last_eligible}"
        )
    return eligible


def pit_candidate_pool_size(
    periods: list[pd.Period] | tuple[pd.Period, ...],
    query: pd.Period,
    forward_buffer_quarters: int = DEFAULT_FORWARD_BUFFER_QUARTERS,
) -> int:
    buffer_q = _validate_positive_int(forward_buffer_quarters, "forward_buffer_quarters")
    cutoff = parse_quarter(query) - buffer_q
    return int(sum(1 for period in periods if period <= cutoff))


def compute_forward_outcome_results(
    library: str | Path | pd.DataFrame | None = None,
    *,
    horizon: int = DEFAULT_HORIZON_QUARTERS,
    w: float = DEFAULT_TREND_WEIGHT,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    min_pool: int = DEFAULT_MIN_POOL,
    credit_spread_series: pd.Series | None = None,
) -> pd.DataFrame:
    """Compute per-query forward-outcome rows for all eligible library dates."""

    horizon_q = _validate_positive_int(horizon, "horizon")
    weight = _validate_w(w)
    prior = _validate_nonnegative_float(prior_strength, "prior_strength")
    min_pool_count = _validate_positive_int(min_pool, "min_pool")
    frame = load_directional_feature_library(library)
    periods = list(frame["_as_of_period"])
    max_known = max(periods)
    eligible = set(eligible_query_dates(frame, horizon=horizon_q))
    credit_spread = (
        _coerce_credit_spread_series(credit_spread_series)
        if credit_spread_series is not None
        else _load_credit_spread_series()
    )
    rows: list[dict[str, Any]] = []
    for query in periods:
        if query not in eligible:
            continue
        actual = recession_within(query, horizon_q, max_known_quarter=max_known)
        fwd_credit_spread_change = _forward_credit_spread_change(
            credit_spread,
            query,
            horizon_q,
        )
        excluded_2020 = _forward_window_intersects(
            query,
            horizon_q,
            COVID_FORWARD_WINDOW_START,
            COVID_FORWARD_WINDOW_END,
        )
        pool_size = pit_candidate_pool_size(periods, query)
        if pool_size < min_pool_count:
            rows.append(
                _empty_outcome_row(
                    query=query,
                    status="insufficient_pool",
                    pit_candidate_pool_size_value=pool_size,
                    actual_recession=actual,
                    fwd_credit_spread_change=fwd_credit_spread_change,
                    excluded_2020_flag=excluded_2020,
                )
            )
            continue

        try:
            match_result = match_analogues(query, w=weight, library=frame)
        except AnalogueMatcherError as exc:
            if "no point-in-time candidates" in str(exc):
                raise ForwardOutcomeError(
                    f"Eligibility bug: query {query} had no point-in-time candidates"
                ) from exc
            raise

        if not match_result.matches:
            rows.append(
                _empty_outcome_row(
                    query=query,
                    status="unprecedented_state",
                    pit_candidate_pool_size_value=pool_size,
                    actual_recession=actual,
                    fwd_credit_spread_change=fwd_credit_spread_change,
                    excluded_2020_flag=excluded_2020,
                )
            )
            continue

        in_sample = compute_neighbor_recession_share(
            match_result.matches,
            query=query,
            horizon=horizon_q,
            max_known_quarter=max_known,
            mode=MODE_IN_SAMPLE,
        )
        pit = compute_neighbor_recession_share(
            match_result.matches,
            query=query,
            horizon=horizon_q,
            max_known_quarter=max_known,
            mode=MODE_PIT,
        )
        rows.append(
            _scored_outcome_row(
                query=query,
                pit_candidate_pool_size_value=pool_size,
                n_matches=len(match_result.matches),
                actual_recession=actual,
                fwd_credit_spread_change=fwd_credit_spread_change,
                excluded_2020_flag=excluded_2020,
                in_sample=in_sample,
                pit=pit,
            )
        )

    result = pd.DataFrame(rows)
    if result.empty:
        raise ForwardOutcomeError("No forward-outcome rows were produced")
    _add_shrunk_columns(result, prior)
    result.attrs["prior_strength"] = prior
    result.attrs["min_pool"] = min_pool_count
    result.attrs["base_rates"] = {
        mode: base_rate_for_mode(result, mode)
        for mode in SHARE_MODES
    }
    return result


def compute_neighbor_recession_share(
    matches: tuple[AnalogueMatch, ...] | list[AnalogueMatch],
    *,
    query: pd.Period | str,
    horizon: int,
    max_known_quarter: pd.Period | str,
    mode: str,
) -> dict[str, float | int]:
    """Compute one mode's weighted neighbor recession share."""

    if mode not in SHARE_MODES:
        raise ForwardOutcomeError(f"unknown neighbor label mode: {mode}")
    query_period = parse_quarter(query)
    horizon_q = _validate_positive_int(horizon, "horizon")
    max_known = parse_quarter(max_known_quarter)
    numerator = 0.0
    denominator = 0.0
    evaluable_count = 0
    dropped_future_count = 0
    dropped_unresolved_count = 0
    unresolved_kernel_weight = 0.0
    for match in matches:
        neighbor = parse_quarter(match.analogue_date)
        neighbor_end = neighbor + horizon_q
        if mode == MODE_PIT and neighbor_end > query_period:
            dropped_unresolved_count += 1
            unresolved_kernel_weight += float(match.kernel_weight)
            continue
        if neighbor_end > max_known:
            dropped_future_count += 1
            continue
        neighbor_recession = recession_within(
            neighbor,
            horizon_q,
            max_known_quarter=max_known,
        )
        weight = float(match.kernel_weight)
        denominator += weight
        numerator += weight * float(neighbor_recession)
        evaluable_count += 1

    share = numerator / denominator if denominator > 0.0 else np.nan
    return {
        "share_raw": float(share),
        "evaluable_neighbor_count": int(evaluable_count),
        "kernel_weight_sum": float(denominator),
        "dropped_future_count": int(dropped_future_count),
        "dropped_unresolved_count": int(dropped_unresolved_count),
        "unresolved_kernel_weight": float(unresolved_kernel_weight),
    }


def shrink_neighbor_share(
    share_raw: float,
    kernel_weight_sum: float,
    *,
    base_rate: float,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
) -> float:
    """Apply the a-priori beta-binomial style shrinkage formula."""

    share = _validate_probability(share_raw, "share_raw")
    kernel = _validate_nonnegative_float(kernel_weight_sum, "kernel_weight_sum")
    base = _validate_probability(base_rate, "base_rate")
    prior = _validate_nonnegative_float(prior_strength, "prior_strength")
    denominator = kernel + prior
    if denominator == 0.0:
        raise ForwardOutcomeError("kernel_weight_sum + prior_strength must be positive")
    return float(((kernel * share) + (prior * base)) / denominator)


def run_forward_outcome_analysis(
    library: str | Path | pd.DataFrame | None = None,
    *,
    horizon: int = DEFAULT_HORIZON_QUARTERS,
    w: float = DEFAULT_TREND_WEIGHT,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    min_pool: int = DEFAULT_MIN_POOL,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Compute, summarize, and write the forward-outcome result table."""

    results = compute_forward_outcome_results(
        library,
        horizon=horizon,
        w=w,
        prior_strength=prior_strength,
        min_pool=min_pool,
    )
    path = Path(output_path) if output_path is not None else default_output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(path, index=False)
    metrics: list[dict[str, Any]] = []
    for mode, version in _metric_order():
        metrics.append(
            compute_metric_summary(
                results,
                label="all scored queries",
                mode=mode,
                share_version=version,
            )
        )
        metrics.append(
            compute_metric_summary(
                results.loc[~results["excluded_2020_flag"]].copy(),
                label="excluding forward windows that intersect 2020Q1-2020Q2",
                mode=mode,
                share_version=version,
            )
        )
    return {
        "results": results,
        "output_path": path,
        "metrics": tuple(metrics),
        "base_rates": results.attrs["base_rates"],
        "lead_time_trajectories": {
            mode: lead_time_trajectories(results, mode=mode)
            for mode in SHARE_MODES
        },
        "contamination_summary": contamination_summary(results),
    }


def compute_metric_summary(
    results: pd.DataFrame,
    *,
    label: str,
    mode: str = MODE_IN_SAMPLE,
    share_version: str = "raw",
) -> dict[str, Any]:
    """Summarize correlations and bucket outcomes for one filtered result set."""

    share_col = _share_column(mode, share_version)
    eval_col = _evaluable_count_column(mode)
    if results.empty:
        return _empty_metric_summary(label, mode, share_version)
    scored = _metric_input_frame(results, mode, share_version)
    return {
        "label": label,
        "mode": mode,
        "share_version": share_version,
        "share_column": share_col,
        "total_queries": int(len(results)),
        "scored_queries": int(len(scored)),
        "insufficient_pool": int((results["status"] == "insufficient_pool").sum()),
        "unprecedented_state": int((results["status"] == "unprecedented_state").sum()),
        "no_evaluable_neighbors": int((results["status"] == "ok").sum() - len(scored)),
        "dropped_unresolved_count": int(results["dropped_unresolved_count"].sum()),
        "base_rate": base_rate_for_mode(results, mode),
        "spearman_actual_recession": spearman_rank_correlation(
            scored[share_col],
            scored["actual_recession"].astype(float),
        ),
        "spearman_fwd_credit_spread_change": spearman_rank_correlation(
            scored[share_col],
            scored["fwd_credit_spread_change"],
        ),
        "min_evaluable_ladder": tuple(
            {
                "min_evaluable_neighbors": cut,
                "n": int(len(scored.loc[scored[eval_col] >= cut])),
                "spearman_actual_recession": spearman_rank_correlation(
                    scored.loc[scored[eval_col] >= cut, share_col],
                    scored.loc[scored[eval_col] >= cut, "actual_recession"].astype(float),
                ),
            }
            for cut in MIN_EVALUABLE_CUTS
        ),
        **bucket_table(scored, share_col),
    }


def bucket_table(scored: pd.DataFrame, share_col: str) -> dict[str, Any]:
    """Bucket scored queries by share and summarize outcomes."""

    if scored.empty:
        return {"bucket_method": "empty", "bucket_table": pd.DataFrame()}
    frame = scored.copy()
    unique_values = int(frame[share_col].nunique(dropna=True))
    method = "quintile"
    if unique_values < 5:
        method = "distinct-value groups"
        frame["bucket"] = frame[share_col].map(lambda value: f"share={value:.6f}")
    else:
        try:
            buckets = pd.qcut(
                frame[share_col],
                q=5,
                labels=False,
                duplicates="drop",
            )
            if int(buckets.nunique(dropna=True)) < 5:
                method = "distinct-value groups"
                frame["bucket"] = frame[share_col].map(lambda value: f"share={value:.6f}")
            else:
                frame["bucket"] = buckets.astype(int).map(lambda idx: f"Q{idx + 1}")
        except ValueError:
            method = "distinct-value groups"
            frame["bucket"] = frame[share_col].map(lambda value: f"share={value:.6f}")

    table = (
        frame.groupby("bucket", sort=False)
        .agg(
            n=("query_date", "size"),
            share_min=(share_col, "min"),
            share_max=(share_col, "max"),
            realized_recession_rate=("actual_recession", "mean"),
            mean_fwd_credit_spread_change=("fwd_credit_spread_change", "mean"),
        )
        .reset_index()
    )
    return {"bucket_method": method, "bucket_table": table}


def quintile_table(scored: pd.DataFrame) -> dict[str, Any]:
    """Backward-compatible wrapper for older tests."""

    return bucket_table(scored, "neighbor_recession_share_in_sample_raw")


def spearman_rank_correlation(x: Any, y: Any) -> float:
    """Manual Spearman correlation via average ranks and numpy corrcoef."""

    left = pd.to_numeric(pd.Series(x), errors="coerce")
    right = pd.to_numeric(pd.Series(y), errors="coerce")
    valid = left.notna() & right.notna()
    left_values = left.loc[valid].to_numpy(dtype=float)
    right_values = right.loc[valid].to_numpy(dtype=float)
    if len(left_values) < 2:
        return float("nan")
    left_ranks = _average_ranks(left_values)
    right_ranks = _average_ranks(right_values)
    if np.std(left_ranks) == 0.0 or np.std(right_ranks) == 0.0:
        return float("nan")
    return float(np.corrcoef(left_ranks, right_ranks)[0, 1])


def lead_time_trajectories(
    results: pd.DataFrame,
    *,
    mode: str = MODE_PIT,
    lead_quarters: int = 8,
) -> tuple[dict[str, Any], ...]:
    """Return share paths over the eight quarters preceding each peak plus peak."""

    if results.empty:
        return tuple()
    by_date = {str(row.query_date): row for row in results.itertuples(index=False)}
    available = set(by_date)
    trajectories: list[dict[str, Any]] = []
    for peak in NBER_PEAKS:
        lead_periods = tuple(pd.period_range(peak - lead_quarters, peak, freq="Q"))
        if not any(str(period) in available for period in lead_periods):
            trajectories.append(
                {
                    "peak": str(peak),
                    "status": "skipped_no_library_coverage",
                    "quarters": tuple(),
                }
            )
            continue
        rows: list[dict[str, Any]] = []
        for period in lead_periods:
            record = by_date.get(str(period))
            if record is None:
                rows.append(
                    {
                        "quarter": str(period),
                        "status": "not_eligible",
                        "raw": np.nan,
                        "shrunk": np.nan,
                        "n_matches": 0,
                        "evaluable_neighbors": 0,
                    }
                )
                continue
            raw = getattr(record, _share_column(mode, "raw"))
            shrunk = getattr(record, _share_column(mode, "shrunk"))
            eval_count = getattr(record, _evaluable_count_column(mode))
            status = str(record.status)
            if status == "ok" and pd.isna(raw):
                status = "no_evaluable_neighbors"
            rows.append(
                {
                    "quarter": str(period),
                    "status": status,
                    "raw": float(raw) if pd.notna(raw) else np.nan,
                    "shrunk": float(shrunk) if pd.notna(shrunk) else np.nan,
                    "n_matches": int(record.n_matches),
                    "evaluable_neighbors": int(eval_count),
                }
            )
        trajectories.append(
            {
                "peak": str(peak),
                "status": "ok",
                "mode": mode,
                "quarters": tuple(rows),
            }
        )
    return tuple(trajectories)


def contamination_summary(results: pd.DataFrame) -> dict[str, Any]:
    scored = results[
        (results["status"] == "ok")
        & results["neighbor_recession_share_in_sample_raw"].notna()
    ].copy()
    if scored.empty:
        return {
            "n": 0,
            "mean_contamination_fraction": float("nan"),
            "max_contamination_fraction": float("nan"),
            "top_queries": tuple(),
        }
    top = scored.sort_values(
        ["contamination_weight_fraction", "query_date"],
        ascending=[False, True],
    ).head(10)
    return {
        "n": int(len(scored)),
        "mean_contamination_fraction": float(scored["contamination_weight_fraction"].mean()),
        "max_contamination_fraction": float(scored["contamination_weight_fraction"].max()),
        "top_queries": tuple(
            {
                "query_date": str(row.query_date),
                "contamination_weight_fraction": float(row.contamination_weight_fraction),
                "unresolved_kernel_weight": float(row.unresolved_kernel_weight_in_sample),
                "kernel_weight_sum_in_sample": float(row.kernel_weight_sum_in_sample),
            }
            for row in top.itertuples(index=False)
        ),
    }


def base_rate_for_mode(results: pd.DataFrame, mode: str) -> float:
    if mode not in SHARE_MODES:
        raise ForwardOutcomeError(f"unknown mode for base rate: {mode}")
    eligible = results[results["status"] != "insufficient_pool"]
    if eligible.empty:
        raise ForwardOutcomeError(f"no eligible rows for base-rate computation in {mode}")
    return float(eligible["actual_recession"].astype(float).mean())


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Forward-outcome diagnostics for directional analogue match sets."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run = subparsers.add_parser("run")
    run.add_argument(
        "--library",
        default=None,
        help=f"Directional feature library CSV; defaults to {default_library_path()}.",
    )
    run.add_argument("--horizon", type=int, default=DEFAULT_HORIZON_QUARTERS)
    run.add_argument("--w", type=float, default=DEFAULT_TREND_WEIGHT)
    run.add_argument("--prior-strength", type=float, default=DEFAULT_PRIOR_STRENGTH)
    run.add_argument("--min-pool", type=int, default=DEFAULT_MIN_POOL)
    run.add_argument(
        "--output",
        default=None,
        help=f"Output CSV path; defaults to classifier cache/{OUTPUT_FILENAME}.",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    analysis = run_forward_outcome_analysis(
        args.library,
        horizon=args.horizon,
        w=args.w,
        prior_strength=args.prior_strength,
        min_pool=args.min_pool,
        output_path=args.output,
    )
    results = analysis["results"]
    unprecedented_dates = results.loc[
        results["status"] == "unprecedented_state",
        "query_date",
    ].tolist()
    metric_pool = results[results["status"] != "insufficient_pool"]
    unprecedented_share = (
        len(unprecedented_dates) / len(metric_pool) if len(metric_pool) else float("nan")
    )
    print("Directional Analogue Forward-Outcome Test")
    print(f"library: {args.library or default_library_path()}")
    print(f"output_csv: {analysis['output_path']}")
    print(f"horizon_quarters: {int(args.horizon)}")
    print(f"w: {float(args.w):.3f}")
    print(f"prior_strength: {float(args.prior_strength):.3f}")
    print(f"min_pool: {int(args.min_pool)}")
    print(f"eligible_queries: {len(results)}")
    print(
        f"insufficient_pool: {int((results['status'] == 'insufficient_pool').sum())}; "
        f"unprecedented_state: {len(unprecedented_dates)}; "
        f"scored_rows: {int((results['status'] == 'ok').sum())}"
    )
    print(f"unprecedented_share_of_min_pool_eligible: {_fmt(unprecedented_share)}")
    print(f"unprecedented_state_dates: {', '.join(unprecedented_dates) if unprecedented_dates else '(none)'}")
    print("base_rates:")
    for mode in SHARE_MODES:
        print(f"  {mode}: {_fmt(analysis['base_rates'][mode])}")
    print()
    for summary in analysis["metrics"]:
        _print_metric_summary(summary)
        print()
    _print_contamination_summary(analysis["contamination_summary"])
    print()
    for mode in SHARE_MODES:
        _print_lead_time_trajectories(mode, analysis["lead_time_trajectories"][mode])
        print()
    return 0


def _print_metric_summary(summary: dict[str, Any]) -> None:
    print(
        f"Metrics: mode={summary['mode']} share={summary['share_version']} "
        f"sample={summary['label']}"
    )
    print(f"  total_queries: {summary['total_queries']}")
    print(f"  scored_queries: {summary['scored_queries']}")
    print(f"  insufficient_pool: {summary['insufficient_pool']}")
    print(f"  unprecedented_state: {summary['unprecedented_state']}")
    print(f"  no_evaluable_neighbors: {summary['no_evaluable_neighbors']}")
    print(f"  dropped_unresolved_count: {summary['dropped_unresolved_count']}")
    print(f"  base_rate_used: {_fmt(summary['base_rate'])}")
    print(f"  Spearman share vs actual_recession: {_fmt(summary['spearman_actual_recession'])}")
    print(
        "  Spearman share vs fwd_credit_spread_change: "
        f"{_fmt(summary['spearman_fwd_credit_spread_change'])}"
    )
    print("  Spearman vs actual_recession by minimum evaluable-neighbor cut:")
    for row in summary["min_evaluable_ladder"]:
        print(
            f"    n>={row['min_evaluable_neighbors']}: "
            f"n={row['n']} rho={_fmt(row['spearman_actual_recession'])}"
        )
    print(f"  bucket method: {summary['bucket_method']}")
    table = summary["bucket_table"]
    if table.empty:
        print("  bucket table: empty")
        return
    print(
        f"{'bucket':<16} {'n':>5} {'share_min':>10} {'share_max':>10} "
        f"{'rec_rate':>10} {'mean_credit_chg':>16}"
    )
    display_table = table
    suppressed_singletons = 0
    if summary["bucket_method"] == "distinct-value groups" and len(table) > 12:
        singleton_mask = table["n"] == 1
        suppressed_singletons = int(singleton_mask.sum())
        display_table = table.loc[~singleton_mask].copy()
    for row in display_table.itertuples(index=False):
        print(
            f"{str(row.bucket):<16} "
            f"{int(row.n):>5} "
            f"{float(row.share_min):>10.4f} "
            f"{float(row.share_max):>10.4f} "
            f"{float(row.realized_recession_rate):>10.4f} "
            f"{float(row.mean_fwd_credit_spread_change):>16.4f}"
        )
    if suppressed_singletons:
        print(f"  suppressed singleton distinct groups: {suppressed_singletons}")


def _print_contamination_summary(summary: dict[str, Any]) -> None:
    print("In-sample label contamination summary")
    print(f"  scored_queries: {summary['n']}")
    print(f"  mean_contamination_fraction: {_fmt(summary['mean_contamination_fraction'])}")
    print(f"  max_contamination_fraction: {_fmt(summary['max_contamination_fraction'])}")
    print("  top 10 contaminated queries:")
    if not summary["top_queries"]:
        print("    (none)")
        return
    print(
        f"    {'query':<8} {'fraction':>10} {'unresolved_wt':>14} "
        f"{'in_sample_wt':>14}"
    )
    for row in summary["top_queries"]:
        print(
            f"    {row['query_date']:<8} "
            f"{row['contamination_weight_fraction']:>10.6f} "
            f"{row['unresolved_kernel_weight']:>14.6f} "
            f"{row['kernel_weight_sum_in_sample']:>14.6f}"
        )


def _print_lead_time_trajectories(mode: str, trajectories: tuple[dict[str, Any], ...]) -> None:
    print(
        f"Lead-time trajectories: mode={mode}, raw and shrunk share over "
        "8 quarters before each NBER peak plus the peak quarter"
    )
    for trajectory in trajectories:
        print(f"Peak {trajectory['peak']}: {trajectory['status']}")
        for row in trajectory["quarters"]:
            print(
                f"  {row['quarter']}: "
                f"status={row['status']:<22} "
                f"raw={_fmt(row['raw']):>8} "
                f"shrunk={_fmt(row['shrunk']):>8} "
                f"n_matches={row['n_matches']} "
                f"evaluable={row['evaluable_neighbors']}"
            )


def _empty_outcome_row(
    *,
    query: pd.Period,
    status: str,
    pit_candidate_pool_size_value: int,
    actual_recession: bool,
    fwd_credit_spread_change: float,
    excluded_2020_flag: bool,
) -> dict[str, Any]:
    row = _base_outcome_row(
        query=query,
        status=status,
        pit_candidate_pool_size_value=pit_candidate_pool_size_value,
        n_matches=0,
        actual_recession=actual_recession,
        fwd_credit_spread_change=fwd_credit_spread_change,
        excluded_2020_flag=excluded_2020_flag,
    )
    for mode in SHARE_MODES:
        row[f"neighbor_recession_share_{mode}_raw"] = np.nan
        row[f"neighbor_recession_share_{mode}_shrunk"] = np.nan
        row[f"evaluable_neighbor_count_{mode}"] = 0
        row[f"kernel_weight_sum_{mode}"] = 0.0
    row["dropped_neighbor_count_in_sample"] = 0
    row["dropped_unresolved_count"] = 0
    row["unresolved_kernel_weight_in_sample"] = 0.0
    row["contamination_weight_fraction"] = np.nan
    return row


def _scored_outcome_row(
    *,
    query: pd.Period,
    pit_candidate_pool_size_value: int,
    n_matches: int,
    actual_recession: bool,
    fwd_credit_spread_change: float,
    excluded_2020_flag: bool,
    in_sample: dict[str, float | int],
    pit: dict[str, float | int],
) -> dict[str, Any]:
    row = _base_outcome_row(
        query=query,
        status="ok",
        pit_candidate_pool_size_value=pit_candidate_pool_size_value,
        n_matches=n_matches,
        actual_recession=actual_recession,
        fwd_credit_spread_change=fwd_credit_spread_change,
        excluded_2020_flag=excluded_2020_flag,
    )
    row["neighbor_recession_share_in_sample_raw"] = float(in_sample["share_raw"])
    row["neighbor_recession_share_in_sample_shrunk"] = np.nan
    row["evaluable_neighbor_count_in_sample"] = int(in_sample["evaluable_neighbor_count"])
    row["kernel_weight_sum_in_sample"] = float(in_sample["kernel_weight_sum"])
    row["dropped_neighbor_count_in_sample"] = int(in_sample["dropped_future_count"])
    row["neighbor_recession_share_pit_observable_raw"] = float(pit["share_raw"])
    row["neighbor_recession_share_pit_observable_shrunk"] = np.nan
    row["evaluable_neighbor_count_pit_observable"] = int(pit["evaluable_neighbor_count"])
    row["kernel_weight_sum_pit_observable"] = float(pit["kernel_weight_sum"])
    row["dropped_unresolved_count"] = int(pit["dropped_unresolved_count"])
    row["unresolved_kernel_weight_in_sample"] = float(pit["unresolved_kernel_weight"])
    denominator = float(in_sample["kernel_weight_sum"])
    row["contamination_weight_fraction"] = (
        float(pit["unresolved_kernel_weight"]) / denominator
        if denominator > 0.0
        else np.nan
    )
    return row


def _base_outcome_row(
    *,
    query: pd.Period,
    status: str,
    pit_candidate_pool_size_value: int,
    n_matches: int,
    actual_recession: bool,
    fwd_credit_spread_change: float,
    excluded_2020_flag: bool,
) -> dict[str, Any]:
    return {
        "query_date": str(query),
        "status": status,
        "pit_candidate_pool_size": int(pit_candidate_pool_size_value),
        "n_matches": int(n_matches),
        "actual_recession": bool(actual_recession),
        "fwd_credit_spread_change": float(fwd_credit_spread_change),
        "excluded_2020_flag": bool(excluded_2020_flag),
    }


def _add_shrunk_columns(results: pd.DataFrame, prior_strength: float) -> None:
    for mode in SHARE_MODES:
        base_rate = base_rate_for_mode(results, mode)
        raw_col = _share_column(mode, "raw")
        shrunk_col = _share_column(mode, "shrunk")
        kernel_col = _kernel_weight_column(mode)
        values: list[float] = []
        for row in results.itertuples(index=False):
            share_raw = getattr(row, raw_col)
            kernel_sum = getattr(row, kernel_col)
            if pd.isna(share_raw):
                values.append(np.nan)
                continue
            values.append(
                shrink_neighbor_share(
                    float(share_raw),
                    float(kernel_sum),
                    base_rate=base_rate,
                    prior_strength=prior_strength,
                )
            )
        results[shrunk_col] = values


def _metric_input_frame(
    results: pd.DataFrame,
    mode: str,
    share_version: str,
) -> pd.DataFrame:
    share_col = _share_column(mode, share_version)
    return results[
        (results["status"] == "ok")
        & results[share_col].notna()
    ].copy()


def _empty_metric_summary(label: str, mode: str, share_version: str) -> dict[str, Any]:
    return {
        "label": label,
        "mode": mode,
        "share_version": share_version,
        "share_column": _share_column(mode, share_version),
        "total_queries": 0,
        "scored_queries": 0,
        "insufficient_pool": 0,
        "unprecedented_state": 0,
        "no_evaluable_neighbors": 0,
        "dropped_unresolved_count": 0,
        "base_rate": float("nan"),
        "spearman_actual_recession": float("nan"),
        "spearman_fwd_credit_spread_change": float("nan"),
        "min_evaluable_ladder": tuple(
            {
                "min_evaluable_neighbors": cut,
                "n": 0,
                "spearman_actual_recession": float("nan"),
            }
            for cut in MIN_EVALUABLE_CUTS
        ),
        "bucket_method": "empty",
        "bucket_table": pd.DataFrame(),
    }


def _metric_order() -> tuple[tuple[str, str], ...]:
    return (
        (MODE_PIT, "shrunk"),
        (MODE_PIT, "raw"),
        (MODE_IN_SAMPLE, "shrunk"),
        (MODE_IN_SAMPLE, "raw"),
    )


def _share_column(mode: str, version: str) -> str:
    if mode not in SHARE_MODES:
        raise ForwardOutcomeError(f"unknown share mode: {mode}")
    if version not in SHARE_VERSIONS:
        raise ForwardOutcomeError(f"unknown share version: {version}")
    return f"neighbor_recession_share_{mode}_{version}"


def _evaluable_count_column(mode: str) -> str:
    if mode not in SHARE_MODES:
        raise ForwardOutcomeError(f"unknown share mode: {mode}")
    return f"evaluable_neighbor_count_{mode}"


def _kernel_weight_column(mode: str) -> str:
    if mode not in SHARE_MODES:
        raise ForwardOutcomeError(f"unknown share mode: {mode}")
    return f"kernel_weight_sum_{mode}"


def _forward_credit_spread_change(
    series: pd.Series,
    quarter: pd.Period,
    horizon: int,
) -> float:
    current = parse_quarter(quarter)
    future = current + horizon
    if current not in series.index:
        raise ForwardOutcomeError(f"credit_spread lacks value at {current}")
    if future not in series.index:
        raise ForwardOutcomeError(
            f"credit_spread lacks forward value at {future} for query {current}"
        )
    current_value = _finite_float(series.loc[current], f"credit_spread[{current}]")
    future_value = _finite_float(series.loc[future], f"credit_spread[{future}]")
    return future_value - current_value


def _forward_window_intersects(
    quarter: pd.Period,
    horizon: int,
    window_start: pd.Period,
    window_end: pd.Period,
) -> bool:
    forward_window = set(pd.period_range(quarter + 1, quarter + horizon, freq="Q"))
    covid_window = set(pd.period_range(window_start, window_end, freq="Q"))
    return bool(forward_window & covid_window)


def _load_credit_spread_series() -> pd.Series:
    cache = load_directional_feature_cache()
    if "credit_spread" not in cache.histories:
        raise ForwardOutcomeError("classifier cache is missing transformed credit_spread series")
    return _coerce_credit_spread_series(cache.histories["credit_spread"])


def _coerce_credit_spread_series(series: pd.Series) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        raise ForwardOutcomeError("credit_spread series is empty")
    if not isinstance(clean.index, pd.PeriodIndex):
        clean = clean.copy()
        clean.index = pd.PeriodIndex(clean.index, freq="Q")
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    if not np.isfinite(clean.to_numpy(dtype=float)).all():
        raise ForwardOutcomeError("credit_spread series contains non-finite values")
    return clean


def _average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and sorted_values[end] == sorted_values[start]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    return ranks


def _validate_positive_int(value: int, name: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ForwardOutcomeError(f"{name} must be an integer; got {value!r}") from exc
    if integer < 1:
        raise ForwardOutcomeError(f"{name} must be at least 1; got {value!r}")
    return integer


def _validate_w(w: float) -> float:
    try:
        value = float(w)
    except (TypeError, ValueError) as exc:
        raise ForwardOutcomeError(f"w must be numeric; got {w!r}") from exc
    if not np.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ForwardOutcomeError(f"w must be in [0, 1]; got {w!r}")
    return value


def _validate_nonnegative_float(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ForwardOutcomeError(f"{name} must be numeric; got {value!r}") from exc
    if not np.isfinite(number) or number < 0.0:
        raise ForwardOutcomeError(f"{name} must be finite and non-negative; got {value!r}")
    return number


def _validate_probability(value: float, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ForwardOutcomeError(f"{name} must be numeric; got {value!r}") from exc
    if not np.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ForwardOutcomeError(f"{name} must be in [0, 1]; got {value!r}")
    return number


def _finite_float(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ForwardOutcomeError(f"{label} is non-numeric: {value!r}") from exc
    if not np.isfinite(number):
        raise ForwardOutcomeError(f"{label} is non-finite: {value!r}")
    return number


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
