"""Point-in-time analogue date matching on directional macro-state features.

This module is intentionally standalone. It reads the directional-feature
library built from the scenario-classifier spine cache and returns weighted
historical dates only. It does not map dates to scenarios, produce probability
outputs, call the BVAR, or rewire the existing historical analogue leg.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.data import default_cache_dir
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    DIRECTIONAL_VARIABLES,
    LIBRARY_FILENAME,
)
from src.agent_system.forecasting.scenario_classifier.nber_dates import (
    EXOGENOUS_PEAKS,
    NBER_PEAKS,
    exogenous_cycle_quarters,
    pre_crisis_quarters,
)


DEFAULT_THRESHOLD_PERCENTILE = 10.0
DEFAULT_TREND_WEIGHT = 0.5
DEFAULT_FORWARD_BUFFER_QUARTERS = 4
PAIRWISE_PERCENTILES: tuple[float, ...] = (1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0)
DIAGNOSTIC_THRESHOLD_PERCENTILES: tuple[float, ...] = (1.0, 5.0, 10.0, 25.0, 50.0)


class AnalogueMatcherError(RuntimeError):
    """Raised when analogue matching cannot proceed without silent assumptions."""


@dataclass(frozen=True)
class AnalogueMatch:
    analogue_date: str
    distance: float
    level_distance: float
    trend_distance: float
    kernel_weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalogueMatchResult:
    query_date: str
    matches: tuple[AnalogueMatch, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_date": self.query_date,
            "matches": [match.to_dict() for match in self.matches],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class PairwiseDistanceSummary:
    w: float
    n_dates: int
    n_pairs: int
    distribution: dict[str, float]
    histogram: tuple[dict[str, float | int], ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_library_path() -> Path:
    return default_cache_dir() / LIBRARY_FILENAME


def level_feature_columns() -> tuple[str, ...]:
    return tuple(f"{variable}.level_percentile" for variable in DIRECTIONAL_VARIABLES)


def trend_feature_columns() -> tuple[str, ...]:
    return tuple(f"{variable}.trend_slope" for variable in DIRECTIONAL_VARIABLES)


def feature_columns() -> tuple[str, ...]:
    names: list[str] = []
    for variable in DIRECTIONAL_VARIABLES:
        names.append(f"{variable}.level_percentile")
        names.append(f"{variable}.trend_slope")
    return tuple(names)


def load_directional_feature_library(
    library: str | Path | pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Load and validate the directional-feature library CSV."""

    if isinstance(library, pd.DataFrame):
        frame = library.copy()
    else:
        path = Path(library) if library is not None else default_library_path()
        if not path.exists():
            raise AnalogueMatcherError(
                f"Directional feature library not found at {path}; build it with "
                "the directional_features build-library command first"
            )
        frame = pd.read_csv(path)

    if "as_of" not in frame.columns:
        if isinstance(frame.index, pd.PeriodIndex):
            frame = frame.reset_index().rename(columns={"index": "as_of"})
        else:
            raise AnalogueMatcherError("directional feature library is missing as_of column")

    missing = sorted(set(feature_columns()) - set(frame.columns))
    if missing:
        raise AnalogueMatcherError(
            f"directional feature library missing feature columns: {missing}"
        )

    frame = frame.copy()
    try:
        frame["as_of"] = [str(_parse_quarter(value)) for value in frame["as_of"]]
    except Exception as exc:
        raise AnalogueMatcherError("directional feature library has invalid as_of values") from exc

    duplicate_dates = sorted(frame.loc[frame["as_of"].duplicated(), "as_of"].unique())
    if duplicate_dates:
        raise AnalogueMatcherError(
            f"directional feature library contains duplicate as_of dates: {duplicate_dates}"
        )

    for column in feature_columns():
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    non_finite_columns = [
        column
        for column in feature_columns()
        if not np.isfinite(frame[column].to_numpy(dtype=float)).all()
    ]
    if non_finite_columns:
        raise AnalogueMatcherError(
            f"directional feature library contains non-finite values in: {non_finite_columns}"
        )

    frame["_as_of_period"] = pd.PeriodIndex(frame["as_of"], freq="Q")
    frame = frame.sort_values("_as_of_period").reset_index(drop=True)
    return frame


def compute_pairwise_distances(
    library: str | Path | pd.DataFrame | None = None,
    *,
    w: float = DEFAULT_TREND_WEIGHT,
) -> pd.DataFrame:
    """Compute all pairwise level/trend/blended distances across the library."""

    weight = _validate_w(w)
    frame = load_directional_feature_library(library)
    if len(frame) < 2:
        raise AnalogueMatcherError(
            f"need at least two directional feature dates for pairwise distances; got {len(frame)}"
        )

    levels, trends = _feature_matrices(frame)
    dates = frame["as_of"].tolist()
    rows: list[dict[str, Any]] = []
    for left_idx in range(len(frame) - 1):
        level_delta = levels[left_idx + 1 :] - levels[left_idx]
        trend_delta = trends[left_idx + 1 :] - trends[left_idx]
        level_distances = np.sqrt(np.sum(level_delta * level_delta, axis=1))
        trend_distances = np.sqrt(np.sum(trend_delta * trend_delta, axis=1))
        distances = _blend_distances(level_distances, trend_distances, weight)
        for offset, distance in enumerate(distances, start=left_idx + 1):
            rows.append(
                {
                    "date_a": dates[left_idx],
                    "date_b": dates[offset],
                    "level_distance": float(level_distances[offset - left_idx - 1]),
                    "trend_distance": float(trend_distances[offset - left_idx - 1]),
                    "distance": float(distance),
                }
            )
    return pd.DataFrame(rows)


def summarize_pairwise_distances(
    pairwise: pd.DataFrame,
    *,
    w: float = DEFAULT_TREND_WEIGHT,
    bins: int = 12,
) -> PairwiseDistanceSummary:
    """Summarize the empirical distance distribution with percentiles and bins."""

    distances = _distance_array(pairwise, "pairwise distances")
    if bins <= 0:
        raise AnalogueMatcherError(f"histogram bins must be positive; got {bins}")
    counts, edges = np.histogram(distances, bins=int(bins))
    histogram = tuple(
        {
            "lower": float(edges[idx]),
            "upper": float(edges[idx + 1]),
            "count": int(count),
        }
        for idx, count in enumerate(counts)
    )
    distribution: dict[str, float] = {
        "min": float(np.min(distances)),
        **{f"p{_format_percentile_key(pct)}": float(np.percentile(distances, pct)) for pct in PAIRWISE_PERCENTILES},
        "max": float(np.max(distances)),
    }
    dates = set(pairwise["date_a"].astype(str)).union(set(pairwise["date_b"].astype(str)))
    return PairwiseDistanceSummary(
        w=_validate_w(w),
        n_dates=len(dates),
        n_pairs=int(len(pairwise)),
        distribution=distribution,
        histogram=histogram,
    )


def threshold_distance_from_percentile(
    pairwise: pd.DataFrame,
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE,
) -> float:
    pct = _validate_percentile(threshold_percentile, name="threshold_percentile")
    distances = _distance_array(pairwise, "pairwise distances")
    threshold = float(np.percentile(distances, pct))
    if not np.isfinite(threshold) or threshold <= 0:
        raise AnalogueMatcherError(
            f"invalid empirical threshold distance at percentile {pct}: {threshold}"
        )
    return threshold


def match_analogues(
    query_date: pd.Period | str,
    *,
    w: float = DEFAULT_TREND_WEIGHT,
    threshold_percentile: float = DEFAULT_THRESHOLD_PERCENTILE,
    forward_buffer_quarters: int = DEFAULT_FORWARD_BUFFER_QUARTERS,
    library: str | Path | pd.DataFrame | None = None,
) -> AnalogueMatchResult:
    """Find point-in-time historical dates similar to one query quarter."""

    weight = _validate_w(w)
    threshold_pct = _validate_percentile(
        threshold_percentile,
        name="threshold_percentile",
    )
    buffer = _validate_forward_buffer(forward_buffer_quarters)
    query_period = _parse_quarter(query_date)
    frame = load_directional_feature_library(library)

    query_rows = frame[frame["_as_of_period"] == query_period]
    if query_rows.empty:
        raise AnalogueMatcherError(
            f"query date {query_period} is not in directional feature library; "
            f"available range {frame['_as_of_period'].min()}..{frame['_as_of_period'].max()}"
        )
    query_idx = int(query_rows.index[0])
    cutoff = query_period - buffer
    candidates = frame[frame["_as_of_period"] <= cutoff].copy()
    if candidates.empty:
        raise AnalogueMatcherError(
            f"no point-in-time candidates for query {query_period}; cutoff is {cutoff} "
            f"after applying forward_buffer_quarters={buffer}"
        )

    pairwise = compute_pairwise_distances(frame, w=weight)
    threshold = threshold_distance_from_percentile(pairwise, threshold_pct)

    query_level = _level_matrix(frame.iloc[[query_idx]])[0]
    query_trend = _trend_matrix(frame.iloc[[query_idx]])[0]
    candidate_levels = _level_matrix(candidates)
    candidate_trends = _trend_matrix(candidates)
    level_distances = np.sqrt(np.sum((candidate_levels - query_level) ** 2, axis=1))
    trend_distances = np.sqrt(np.sum((candidate_trends - query_trend) ** 2, axis=1))
    distances = _blend_distances(level_distances, trend_distances, weight)
    in_threshold = distances <= threshold
    matches: list[AnalogueMatch] = []
    for row_idx, row in enumerate(candidates.itertuples(index=False)):
        if not bool(in_threshold[row_idx]):
            continue
        distance = float(distances[row_idx])
        kernel_weight = float(math.exp(-distance * distance / (2.0 * threshold * threshold)))
        matches.append(
            AnalogueMatch(
                analogue_date=str(getattr(row, "as_of")),
                distance=distance,
                level_distance=float(level_distances[row_idx]),
                trend_distance=float(trend_distances[row_idx]),
                kernel_weight=kernel_weight,
            )
        )
    matches.sort(key=lambda item: (item.distance, item.analogue_date))
    max_candidate = candidates["_as_of_period"].max()
    metadata = {
        "query_date": str(query_period),
        "w": weight,
        "distance_formula": "w * trend_distance + (1 - w) * level_distance",
        "threshold_percentile": threshold_pct,
        "threshold_distance": threshold,
        "kernel_formula": "exp(-distance^2 / (2 * threshold_distance^2))",
        "kernel_bandwidth": threshold,
        "forward_buffer_quarters": buffer,
        "candidate_cutoff": str(cutoff),
        "max_candidate_date": str(max_candidate),
        "point_in_time_ok": bool(max_candidate <= cutoff and max_candidate < query_period),
        "n_library_dates": int(len(frame)),
        "n_candidates": int(len(candidates)),
        "n_analogues_in_threshold": int(len(matches)),
        "kernel_weight_sum": float(sum(match.kernel_weight for match in matches)),
        "query_vector": _query_vector_metadata(frame.iloc[query_idx]),
    }
    return AnalogueMatchResult(
        query_date=str(query_period),
        matches=tuple(matches),
        metadata=metadata,
    )


def pre_crisis_clustering_diagnostic(
    library: str | Path | pd.DataFrame | None = None,
    *,
    w: float = DEFAULT_TREND_WEIGHT,
    k: int = 10,
    exclude_exogenous: bool = True,
    pre_crisis_ranges: Iterable[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Check whether labeled pre-crisis dates are neighbors in feature space."""

    if k <= 0:
        raise AnalogueMatcherError(f"k must be positive; got {k}")
    weight = _validate_w(w)
    frame = load_directional_feature_library(library)
    periods = list(frame["_as_of_period"])
    period_set = set(periods)
    if pre_crisis_ranges is None:
        requested = tuple(sorted(pre_crisis_quarters(exclude_exogenous=exclude_exogenous)))
    else:
        requested = _expand_pre_crisis_ranges(pre_crisis_ranges)
    present = tuple(str(period) for period in requested if period in period_set)
    omitted = tuple(str(period) for period in requested if period not in period_set)
    peak_periods = tuple(
        period
        for period in NBER_PEAKS
        if not (exclude_exogenous and period in EXOGENOUS_PEAKS)
    )
    peak_present = tuple(str(period) for period in peak_periods if period in period_set)
    peak_omitted = tuple(str(period) for period in peak_periods if period not in period_set)
    excluded_exogenous_periods = (
        tuple(sorted(exogenous_cycle_quarters())) if exclude_exogenous else tuple()
    )
    excluded_exogenous_present = tuple(
        str(period) for period in excluded_exogenous_periods if period in period_set
    )
    excluded_exogenous_set = set(excluded_exogenous_present)
    if len(present) < 2:
        raise AnalogueMatcherError(
            "pre-crisis clustering diagnostic needs at least two labeled dates "
            f"present in the library; present={list(present)}, omitted={list(omitted)}"
        )

    pairwise = compute_pairwise_distances(frame, w=weight)
    all_distances = _distance_array(pairwise, "pairwise distances")
    level_matrix, trend_matrix = _feature_matrices(frame)
    pre_set = set(present)
    peak_set = set(peak_present)
    benign_set = {
        str(period)
        for period in periods
        if str(period) not in pre_set
        and str(period) not in peak_set
        and str(period) not in excluded_exogenous_set
    }
    evaluated_label_count = len(pre_set) + len(peak_set) + len(benign_set)
    if evaluated_label_count == 0:
        raise AnalogueMatcherError("pre-crisis diagnostic has no evaluated label dates")
    base_rate = len(pre_set) / evaluated_label_count
    label_groups = {
        "pre_crisis": tuple(sorted(pre_set)),
        "peak": tuple(sorted(peak_set)),
        "excluded_exogenous": tuple(sorted(excluded_exogenous_set)),
        "benign": tuple(sorted(benign_set)),
    }
    mean_within_group_distance = {
        label: _mean_within_distance(pairwise, dates)
        for label, dates in label_groups.items()
    }
    mean_between_group_distance = {
        "pre_crisis_vs_benign": _mean_between_distance(pairwise, pre_set, benign_set),
        "pre_crisis_vs_peak": _mean_between_distance(pairwise, pre_set, peak_set),
        "peak_vs_benign": _mean_between_distance(pairwise, peak_set, benign_set),
    }
    rows: list[dict[str, Any]] = []
    for idx, period in enumerate(periods):
        date = str(period)
        if date not in pre_set:
            continue
        level_distances = np.sqrt(np.sum((level_matrix - level_matrix[idx]) ** 2, axis=1))
        trend_distances = np.sqrt(np.sum((trend_matrix - trend_matrix[idx]) ** 2, axis=1))
        distances = _blend_distances(level_distances, trend_distances, weight)
        order = np.argsort(distances)
        neighbor_indices = [int(item) for item in order if int(item) != idx][:k]
        neighbor_dates = [str(periods[item]) for item in neighbor_indices]
        pre_neighbors = [item for item in neighbor_dates if item in pre_set]
        peak_neighbors = [item for item in neighbor_dates if item in peak_set]
        benign_neighbors = [item for item in neighbor_dates if item in benign_set]
        excluded_neighbors = [
            item for item in neighbor_dates if item in excluded_exogenous_set
        ]
        counted_neighbor_count = (
            len(pre_neighbors) + len(peak_neighbors) + len(benign_neighbors)
        )
        rows.append(
            {
                "date": date,
                "k": int(min(k, len(frame) - 1)),
                "pre_crisis_neighbor_count": int(len(pre_neighbors)),
                "peak_neighbor_count": int(len(peak_neighbors)),
                "benign_neighbor_count": int(len(benign_neighbors)),
                "excluded_exogenous_neighbor_count": int(len(excluded_neighbors)),
                "pre_crisis_neighbor_fraction": (
                    float(len(pre_neighbors) / counted_neighbor_count)
                    if counted_neighbor_count
                    else 0.0
                ),
                "nearest_neighbors": neighbor_dates,
            }
        )

    threshold_rows: list[dict[str, Any]] = []
    first_separation_percentile: float | None = None
    separation_floor = max(0.25, 2.0 * base_rate)
    for pct in DIAGNOSTIC_THRESHOLD_PERCENTILES:
        threshold = float(np.percentile(all_distances, pct))
        pre_count = 0
        peak_count = 0
        benign_count = 0
        excluded_count = 0
        anchors_with_neighbors = 0
        for idx, period in enumerate(periods):
            if str(period) not in pre_set:
                continue
            level_distances = np.sqrt(np.sum((level_matrix - level_matrix[idx]) ** 2, axis=1))
            trend_distances = np.sqrt(np.sum((trend_matrix - trend_matrix[idx]) ** 2, axis=1))
            distances = _blend_distances(level_distances, trend_distances, weight)
            mask = (distances <= threshold) & (distances > 0.0)
            neighbor_dates = [str(periods[item]) for item in np.where(mask)[0]]
            if neighbor_dates:
                anchors_with_neighbors += 1
            pre_count += sum(1 for item in neighbor_dates if item in pre_set)
            peak_count += sum(1 for item in neighbor_dates if item in peak_set)
            benign_count += sum(1 for item in neighbor_dates if item in benign_set)
            excluded_count += sum(
                1 for item in neighbor_dates if item in excluded_exogenous_set
            )
        total = pre_count + peak_count + benign_count
        pre_share = float(pre_count / total) if total else 0.0
        row = {
            "threshold_percentile": float(pct),
            "threshold_distance": threshold,
            "pre_crisis_neighbors": int(pre_count),
            "peak_neighbors": int(peak_count),
            "benign_neighbors": int(benign_count),
            "excluded_exogenous_neighbors": int(excluded_count),
            "pre_crisis_neighbor_share": pre_share,
            "anchors_with_neighbors": int(anchors_with_neighbors),
        }
        threshold_rows.append(row)
        if (
            first_separation_percentile is None
            and total > 0
            and pre_share >= separation_floor
        ):
            first_separation_percentile = float(pct)

    mean_k_fraction = float(np.mean([row["pre_crisis_neighbor_fraction"] for row in rows]))
    k_fraction_floor = max(0.25, 2.0 * base_rate)
    separates = bool(
        mean_k_fraction >= k_fraction_floor
        or first_separation_percentile is not None
    )
    if separates:
        if first_separation_percentile is not None:
            verdict = (
                "pre-crisis dates form a recognizable neighborhood at threshold "
                f"percentile {first_separation_percentile:g}"
            )
        else:
            verdict = (
                "pre-crisis dates form a recognizable neighborhood in k-nearest "
                f"space (mean pre-crisis share {mean_k_fraction:.3f})"
            )
    else:
        verdict = "pre-crisis dates do NOT separate cleanly from benign in distance space"

    return {
        "w": weight,
        "k": int(k),
        "exclude_exogenous": bool(exclude_exogenous),
        "pre_crisis_dates_present": present,
        "pre_crisis_dates_omitted": omitted,
        "peak_dates_present": peak_present,
        "peak_dates_omitted": peak_omitted,
        "label_groups": label_groups,
        "group_counts": {label: len(dates) for label, dates in label_groups.items()},
        "evaluated_label_count": int(evaluated_label_count),
        "mean_within_group_distance": mean_within_group_distance,
        "mean_between_group_distance": mean_between_group_distance,
        "library_base_pre_crisis_rate": float(base_rate),
        "separation_rule": (
            "recognizable if pre-crisis neighbor share is at least max(0.25, "
            "2 * library_base_pre_crisis_rate)"
        ),
        "k_nearest": tuple(rows),
        "threshold_diagnostics": tuple(threshold_rows),
        "first_separation_threshold_percentile": first_separation_percentile,
        "mean_k_nearest_pre_crisis_fraction": mean_k_fraction,
        "summary": verdict,
    }


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
        description="Standalone point-in-time analogue matcher for directional macro features."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--library",
        default=None,
        help=f"Directional feature library CSV; defaults to classifier cache/{LIBRARY_FILENAME}.",
    )
    common.add_argument(
        "--w",
        type=float,
        default=DEFAULT_TREND_WEIGHT,
        help="Trend-distance blend weight. 0=level only, 1=trend only.",
    )

    inspect = subparsers.add_parser("inspect", parents=[common])
    inspect.add_argument("--query", required=True, help="Query quarter, e.g. 2007Q4.")
    inspect.add_argument(
        "--threshold-pct",
        type=float,
        default=DEFAULT_THRESHOLD_PERCENTILE,
        help="Empirical pairwise-distance percentile used as the cutoff.",
    )
    inspect.add_argument(
        "--forward-buffer-quarters",
        type=int,
        default=DEFAULT_FORWARD_BUFFER_QUARTERS,
        help="Exclude candidate dates after query minus this many quarters.",
    )
    inspect.add_argument("--max-results", type=int, default=20)
    inspect.set_defaults(func=_cmd_inspect)

    calibrate = subparsers.add_parser("calibrate", parents=[common])
    calibrate.add_argument("--bins", type=int, default=12)
    calibrate.add_argument("--k", type=int, default=10)
    calibrate.set_defaults(func=_cmd_calibrate)
    return parser


def _cmd_inspect(args: argparse.Namespace) -> int:
    result = match_analogues(
        args.query,
        w=args.w,
        threshold_percentile=args.threshold_pct,
        forward_buffer_quarters=args.forward_buffer_quarters,
        library=args.library,
    )
    metadata = result.metadata
    print("Directional Analogue Matches")
    print(f"query: {result.query_date}")
    print(f"library: {args.library or default_library_path()}")
    print(
        "distance: "
        f"{metadata['w']:.3f} * trend_distance + {1.0 - metadata['w']:.3f} * level_distance"
    )
    print(
        f"threshold: p{metadata['threshold_percentile']:g} = "
        f"{metadata['threshold_distance']:.6f}"
    )
    print(
        "point-in-time: "
        f"candidates <= {metadata['candidate_cutoff']} "
        f"(max candidate {metadata['max_candidate_date']}; ok={metadata['point_in_time_ok']})"
    )
    print(
        f"candidates: {metadata['n_candidates']} / library dates: {metadata['n_library_dates']} / "
        f"in threshold: {metadata['n_analogues_in_threshold']}"
    )
    print()
    print(f"{'analogue':<10} {'distance':>10} {'level':>10} {'trend':>10} {'kernel_wt':>12}")
    for match in result.matches[: max(0, int(args.max_results))]:
        print(
            f"{match.analogue_date:<10} "
            f"{match.distance:>10.4f} "
            f"{match.level_distance:>10.4f} "
            f"{match.trend_distance:>10.4f} "
            f"{match.kernel_weight:>12.6f}"
        )
    if not result.matches:
        print("(no point-in-time candidates inside threshold)")
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    pairwise = compute_pairwise_distances(args.library, w=args.w)
    summary = summarize_pairwise_distances(pairwise, w=args.w, bins=args.bins)
    headline = pre_crisis_clustering_diagnostic(
        args.library,
        w=args.w,
        k=args.k,
        exclude_exogenous=True,
    )
    reference = pre_crisis_clustering_diagnostic(
        args.library,
        w=args.w,
        k=args.k,
        exclude_exogenous=False,
    )
    print("Directional Analogue Calibration")
    print(f"library: {args.library or default_library_path()}")
    print(f"w: {summary.w:.3f}")
    print(f"dates: {summary.n_dates}, pairs: {summary.n_pairs}")
    print()
    print("Pairwise distance distribution")
    for key, value in summary.distribution.items():
        print(f"  {key:<4} {value:.6f}")
    print()
    print("Histogram")
    for row in summary.histogram:
        print(f"  [{row['lower']:.4f}, {row['upper']:.4f}] {row['count']}")
    print()
    _print_pre_crisis_diagnostic(
        "Pre-crisis clustering diagnostic (headline, exclude_exogenous=True)",
        headline,
    )
    print()
    _print_pre_crisis_diagnostic(
        "Pre-crisis clustering diagnostic (reference, exclude_exogenous=False)",
        reference,
    )
    return 0


def _print_pre_crisis_diagnostic(title: str, diagnostic: dict[str, Any]) -> None:
    print(title)
    print(f"  exclude_exogenous: {diagnostic['exclude_exogenous']}")
    print(f"  group counts: {diagnostic['group_counts']}")
    print(f"  evaluated label count: {diagnostic['evaluated_label_count']}")
    print(f"  pre-crisis present: {', '.join(diagnostic['pre_crisis_dates_present'])}")
    if diagnostic["pre_crisis_dates_omitted"]:
        print(f"  pre-crisis omitted: {', '.join(diagnostic['pre_crisis_dates_omitted'])}")
    print(f"  peak present: {', '.join(diagnostic['peak_dates_present'])}")
    if diagnostic["peak_dates_omitted"]:
        print(f"  peak omitted: {', '.join(diagnostic['peak_dates_omitted'])}")
    print("  label groups:")
    for label, dates in diagnostic["label_groups"].items():
        print(f"    {label} ({len(dates)}): {', '.join(dates)}")
    print("  mean within-group distance:")
    for label, value in diagnostic["mean_within_group_distance"].items():
        print(f"    {label}: {_format_float_or_na(value)}")
    print("  mean between-group distance:")
    for label, value in diagnostic["mean_between_group_distance"].items():
        print(f"    {label}: {_format_float_or_na(value)}")
    print(f"  base pre-crisis rate: {diagnostic['library_base_pre_crisis_rate']:.3f}")
    print(f"  mean k-nearest pre-crisis fraction: {diagnostic['mean_k_nearest_pre_crisis_fraction']:.3f}")
    print(f"  summary: {diagnostic['summary']}")
    print()
    print(
        f"{'date':<8} {'pre/k':>8} {'peak/k':>8} {'exog/k':>8} "
        f"{'benign/k':>9} {'pre_frac':>9} nearest"
    )
    for row in diagnostic["k_nearest"]:
        nearest = ", ".join(row["nearest_neighbors"][: min(5, len(row["nearest_neighbors"]))])
        print(
            f"{row['date']:<8} "
            f"{row['pre_crisis_neighbor_count']:>8} "
            f"{row['peak_neighbor_count']:>8} "
            f"{row['excluded_exogenous_neighbor_count']:>8} "
            f"{row['benign_neighbor_count']:>9} "
            f"{row['pre_crisis_neighbor_fraction']:>9.3f} "
            f"{nearest}"
        )
    print()
    print(
        f"{'pct':>6} {'threshold':>11} {'pre':>6} {'peak':>6} "
        f"{'exog':>6} {'benign':>8} {'pre_share':>10}"
    )
    for row in diagnostic["threshold_diagnostics"]:
        print(
            f"{row['threshold_percentile']:>6.1f} "
            f"{row['threshold_distance']:>11.6f} "
            f"{row['pre_crisis_neighbors']:>6} "
            f"{row['peak_neighbors']:>6} "
            f"{row['excluded_exogenous_neighbors']:>6} "
            f"{row['benign_neighbors']:>8} "
            f"{row['pre_crisis_neighbor_share']:>10.3f}"
        )


def _parse_quarter(value: pd.Period | str) -> pd.Period:
    if isinstance(value, pd.Period):
        return value.asfreq("Q")
    text = str(value).strip().upper()
    if not text:
        raise AnalogueMatcherError("empty quarter value")
    try:
        return pd.Period(text, freq="Q")
    except Exception:
        try:
            return pd.Timestamp(text).to_period("Q")
        except Exception as exc:
            raise AnalogueMatcherError(f"Could not parse quarter: {value!r}") from exc


def _validate_w(w: float) -> float:
    try:
        value = float(w)
    except (TypeError, ValueError) as exc:
        raise AnalogueMatcherError(f"w must be numeric; got {w!r}") from exc
    if not np.isfinite(value) or not 0.0 <= value <= 1.0:
        raise AnalogueMatcherError(f"w must be in [0, 1]; got {w!r}")
    return value


def _validate_percentile(value: float, *, name: str) -> float:
    try:
        pct = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueMatcherError(f"{name} must be numeric; got {value!r}") from exc
    if not np.isfinite(pct) or not 0.0 < pct <= 100.0:
        raise AnalogueMatcherError(f"{name} must be in (0, 100]; got {value!r}")
    return pct


def _validate_forward_buffer(value: int) -> int:
    try:
        buffer = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueMatcherError(
            f"forward_buffer_quarters must be an integer; got {value!r}"
        ) from exc
    if buffer < 1:
        raise AnalogueMatcherError(
            f"forward_buffer_quarters must be at least 1; got {value!r}"
        )
    return buffer


def _feature_matrices(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return _level_matrix(frame), _trend_matrix(frame)


def _level_matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame.loc[:, list(level_feature_columns())].to_numpy(dtype=float)


def _trend_matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame.loc[:, list(trend_feature_columns())].to_numpy(dtype=float)


def _blend_distances(
    level_distances: np.ndarray,
    trend_distances: np.ndarray,
    w: float,
) -> np.ndarray:
    return (w * trend_distances) + ((1.0 - w) * level_distances)


def _distance_array(frame: pd.DataFrame, label: str) -> np.ndarray:
    if "distance" not in frame.columns:
        raise AnalogueMatcherError(f"{label} frame is missing distance column")
    distances = pd.to_numeric(frame["distance"], errors="coerce").to_numpy(dtype=float)
    if len(distances) == 0:
        raise AnalogueMatcherError(f"{label} frame has no rows")
    if not np.isfinite(distances).all():
        raise AnalogueMatcherError(f"{label} contain non-finite distance values")
    return distances


def _mean_within_distance(pairwise: pd.DataFrame, dates: Iterable[str]) -> float:
    date_set = set(dates)
    if len(date_set) < 2:
        return float("nan")
    mask = pairwise["date_a"].isin(date_set) & pairwise["date_b"].isin(date_set)
    if not mask.any():
        return float("nan")
    return float(pairwise.loc[mask, "distance"].mean())


def _mean_between_distance(
    pairwise: pd.DataFrame,
    left_dates: Iterable[str],
    right_dates: Iterable[str],
) -> float:
    left = set(left_dates)
    right = set(right_dates)
    if not left or not right:
        return float("nan")
    mask = (
        pairwise["date_a"].isin(left) & pairwise["date_b"].isin(right)
    ) | (
        pairwise["date_a"].isin(right) & pairwise["date_b"].isin(left)
    )
    if not mask.any():
        return float("nan")
    return float(pairwise.loc[mask, "distance"].mean())


def _format_float_or_na(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if not np.isfinite(number):
        return "n/a"
    return f"{number:.6f}"


def _format_percentile_key(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return str(value).replace(".", "_")


def _query_vector_metadata(row: pd.Series) -> dict[str, dict[str, float]]:
    return {
        variable: {
            "level_percentile": float(row[f"{variable}.level_percentile"]),
            "trend_slope": float(row[f"{variable}.trend_slope"]),
        }
        for variable in DIRECTIONAL_VARIABLES
    }


def _expand_pre_crisis_ranges(
    ranges: Iterable[tuple[str, str]],
) -> tuple[pd.Period, ...]:
    dates: list[pd.Period] = []
    for start, end in ranges:
        start_period = _parse_quarter(start)
        end_period = _parse_quarter(end)
        if end_period < start_period:
            raise AnalogueMatcherError(
                f"pre-crisis range end {end_period} is before start {start_period}"
            )
        dates.extend(pd.period_range(start_period, end_period, freq="Q"))
    return tuple(dict.fromkeys(dates))


if __name__ == "__main__":
    raise SystemExit(main())
