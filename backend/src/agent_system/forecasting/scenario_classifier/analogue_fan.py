"""Empirical analogue fan charts from directional analogue match sets.

The fan is a reporting diagnostic only. It uses the existing directional
analogue matcher and transformed classifier-cache spine histories, re-anchoring
historical forward deltas to the query quarter so the paths are in the same
transformed-cache units as the BVAR signature space.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    DEFAULT_FORWARD_BUFFER_QUARTERS,
    DEFAULT_THRESHOLD_PERCENTILE,
    DEFAULT_TREND_WEIGHT,
    AnalogueMatch,
    AnalogueMatcherError,
    default_library_path,
    load_directional_feature_library,
    match_analogues,
)
from src.agent_system.forecasting.scenario_classifier.data import default_cache_dir
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    DIRECTIONAL_VARIABLES,
    load_directional_feature_cache,
)
from src.agent_system.forecasting.scenario_classifier.forward_outcomes import (
    DEFAULT_HORIZON_QUARTERS,
)
from src.agent_system.forecasting.scenario_classifier.nber_dates import (
    parse_quarter,
    recession_within,
)


FAN_OUTPUT_TEMPLATE = "analogue_fan_{query_date}.json"
PERCENTILES: tuple[int, ...] = (10, 25, 50, 75, 90)
UNITS_NOTE = "transformed-cache units, same as BVAR signature space"
SUBSET_EFFECTIVE_N_MIN = 3.0


class AnalogueFanError(RuntimeError):
    """Raised when analogue fan computation would hide missing data."""


@dataclass(frozen=True)
class FanVariableResult:
    variable: str
    query_anchor_value: float
    units_note: str
    percentiles: dict[str, tuple[float | None, ...]]
    effective_n: tuple[float, ...]
    median_recession_bound: tuple[float | None, ...] | None
    median_benign: tuple[float | None, ...] | None
    subset_notes: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FanResult:
    query_date: str
    horizon_quarters: int
    variables: dict[str, FanVariableResult]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_date": self.query_date,
            "horizon_quarters": self.horizon_quarters,
            "variables": {
                variable: result.to_dict()
                for variable, result in self.variables.items()
            },
            "metadata": self.metadata,
        }


def default_fan_output_path(
    query_date: pd.Period | str,
    *,
    output_dir: str | Path | None = None,
) -> Path:
    target_dir = Path(output_dir) if output_dir is not None else default_cache_dir()
    return target_dir / FAN_OUTPUT_TEMPLATE.format(query_date=str(parse_quarter(query_date)))


def compute_analogue_fan(
    query_date: pd.Period | str | None = None,
    *,
    horizon_quarters: int = DEFAULT_HORIZON_QUARTERS,
    library: str | Path | pd.DataFrame | None = None,
    histories: Mapping[str, pd.Series] | None = None,
) -> FanResult:
    """Compute weighted empirical forward-path fans for the query's analogue set."""

    horizon = _positive_int(horizon_quarters, "horizon_quarters")
    frame = load_directional_feature_library(library)
    query = max(frame["_as_of_period"]) if query_date is None else parse_quarter(query_date)
    if query not in set(frame["_as_of_period"]):
        raise AnalogueFanError(
            f"query date {query} is not in directional feature library; "
            f"available range {frame['_as_of_period'].min()}..{frame['_as_of_period'].max()}"
        )
    match_result = match_analogues(
        query,
        w=DEFAULT_TREND_WEIGHT,
        threshold_percentile=DEFAULT_THRESHOLD_PERCENTILE,
        forward_buffer_quarters=DEFAULT_FORWARD_BUFFER_QUARTERS,
        library=frame,
    )
    if not match_result.matches:
        raise AnalogueFanError(f"{query} has no analogue matches for fan computation")

    series_by_variable = _load_histories(histories)
    max_known = max(
        series.index.max()
        for variable, series in series_by_variable.items()
        if variable in DIRECTIONAL_VARIABLES
    )
    variables: dict[str, FanVariableResult] = {}
    for variable in DIRECTIONAL_VARIABLES:
        series = series_by_variable.get(variable)
        if series is None:
            raise AnalogueFanError(f"missing transformed history for {variable}")
        variables[variable] = _compute_variable_fan(
            variable,
            _quarterly_series(series, variable),
            query=query,
            matches=match_result.matches,
            horizon=horizon,
            max_known=max_known,
        )

    metadata = {
        "query_date": str(query),
        "horizon_quarters": int(horizon),
        "match_count": int(len(match_result.matches)),
        "match_kernel_weight_sum": float(sum(match.kernel_weight for match in match_result.matches)),
        "matcher": match_result.metadata,
        "units_note": UNITS_NOTE,
    }
    return FanResult(
        query_date=str(query),
        horizon_quarters=int(horizon),
        variables=variables,
        metadata=metadata,
    )


def write_fan_result(
    fan_result: FanResult,
    path: str | Path | None = None,
) -> Path:
    """Write a fan result JSON artifact."""

    output_path = Path(path) if path is not None else default_fan_output_path(fan_result.query_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(fan_result.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output_path


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
        description="Empirical fan diagnostics from directional analogue matches."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--date", default=None, help="Query quarter, e.g. 2026Q2.")
    run.add_argument("--horizon", type=int, default=DEFAULT_HORIZON_QUARTERS)
    run.add_argument(
        "--library",
        default=None,
        help=f"Directional feature library CSV; defaults to {default_library_path()}.",
    )
    run.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path.",
    )
    run.set_defaults(func=_cmd_run)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    fan = compute_analogue_fan(
        query_date=args.date,
        horizon_quarters=args.horizon,
        library=args.library,
    )
    output_path = write_fan_result(fan, args.output)
    _print_fan(fan)
    print(f"wrote: {output_path}")
    return 0


def _compute_variable_fan(
    variable: str,
    series: pd.Series,
    *,
    query: pd.Period,
    matches: tuple[AnalogueMatch, ...],
    horizon: int,
    max_known: pd.Period,
) -> FanVariableResult:
    if query not in series.index:
        raise AnalogueFanError(
            f"{variable} lacks query anchor value at {query}; available range "
            f"{series.index.min()}..{series.index.max()}"
        )
    query_anchor = _finite_float(series.loc[query], f"{variable}.{query}")
    percentile_paths: dict[str, list[float | None]] = {
        f"p{percentile}": []
        for percentile in PERCENTILES
    }
    effective_n: list[float] = []
    subset_cache = _resolved_subset_labels(matches, query=query, horizon=horizon, max_known=max_known)
    rec_medians, rec_note = _subset_median_path(
        series,
        query_anchor=query_anchor,
        matches=[item for item in subset_cache if item["recession_bound"] is True],
        horizon=horizon,
    )
    benign_medians, benign_note = _subset_median_path(
        series,
        query_anchor=query_anchor,
        matches=[item for item in subset_cache if item["recession_bound"] is False],
        horizon=horizon,
    )

    for step in range(1, horizon + 1):
        values, weights = _reanchored_values_at_horizon(
            series,
            query_anchor=query_anchor,
            matches=matches,
            step=step,
            variable=variable,
        )
        weight_sum = float(np.sum(weights))
        effective_n.append(weight_sum)
        if step == 1 and weight_sum <= 0.0:
            raise AnalogueFanError(f"{variable} has zero effective_n at h=1")
        for percentile in PERCENTILES:
            percentile_paths[f"p{percentile}"].append(
                _weighted_percentile(values, weights, percentile)
                if weight_sum > 0.0
                else None
            )

    return FanVariableResult(
        variable=variable,
        query_anchor_value=query_anchor,
        units_note=UNITS_NOTE,
        percentiles={
            name: tuple(path)
            for name, path in percentile_paths.items()
        },
        effective_n=tuple(effective_n),
        median_recession_bound=rec_medians,
        median_benign=benign_medians,
        subset_notes={
            "recession_bound": rec_note,
            "benign": benign_note,
        },
    )


def _reanchored_values_at_horizon(
    series: pd.Series,
    *,
    query_anchor: float,
    matches: tuple[AnalogueMatch, ...] | list[AnalogueMatch],
    step: int,
    variable: str,
) -> tuple[np.ndarray, np.ndarray]:
    values: list[float] = []
    weights: list[float] = []
    for match in matches:
        neighbor = parse_quarter(match.analogue_date)
        if neighbor not in series.index:
            raise AnalogueFanError(
                f"{variable} missing match anchor {neighbor}; cannot compute deltas"
            )
        forward = neighbor + step
        if forward not in series.index:
            continue
        delta = _finite_float(series.loc[forward], f"{variable}.{forward}") - _finite_float(
            series.loc[neighbor],
            f"{variable}.{neighbor}",
        )
        values.append(float(query_anchor + delta))
        weights.append(_nonnegative_float(match.kernel_weight, "kernel_weight"))
    return np.asarray(values, dtype=float), np.asarray(weights, dtype=float)


def _resolved_subset_labels(
    matches: tuple[AnalogueMatch, ...],
    *,
    query: pd.Period,
    horizon: int,
    max_known: pd.Period,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in matches:
        neighbor = parse_quarter(match.analogue_date)
        if neighbor + horizon > query:
            continue
        if neighbor + horizon > max_known:
            raise AnalogueFanError(
                f"resolved subset label for {neighbor} extends beyond known history "
                f"{max_known}"
            )
        rows.append(
            {
                "match": match,
                "recession_bound": bool(
                    recession_within(
                        neighbor,
                        horizon,
                        max_known_quarter=max_known,
                    )
                ),
            }
        )
    return rows


def _subset_median_path(
    series: pd.Series,
    *,
    query_anchor: float,
    matches: list[dict[str, Any]],
    horizon: int,
) -> tuple[tuple[float | None, ...] | None, str]:
    if not matches:
        return None, "skipped: no resolved neighbors in subset"
    raw_matches = [item["match"] for item in matches]
    values_h1, weights_h1 = _reanchored_values_at_horizon(
        series,
        query_anchor=query_anchor,
        matches=raw_matches,
        step=1,
        variable=series.name or "series",
    )
    eff_h1 = float(np.sum(weights_h1))
    if eff_h1 < SUBSET_EFFECTIVE_N_MIN:
        return None, f"skipped: h1 effective_n {eff_h1:.6f} < {SUBSET_EFFECTIVE_N_MIN:g}"
    medians: list[float | None] = []
    for step in range(1, horizon + 1):
        values, weights = _reanchored_values_at_horizon(
            series,
            query_anchor=query_anchor,
            matches=raw_matches,
            step=step,
            variable=series.name or "series",
        )
        medians.append(
            _weighted_percentile(values, weights, 50)
            if float(np.sum(weights)) > 0.0
            else None
        )
    return tuple(medians), "ok"


def _weighted_percentile(
    values: np.ndarray,
    weights: np.ndarray,
    percentile: float,
) -> float:
    if len(values) == 0:
        raise AnalogueFanError("weighted percentile received no values")
    if len(values) != len(weights):
        raise AnalogueFanError("weighted percentile values/weights length mismatch")
    clean_mask = np.isfinite(values) & np.isfinite(weights) & (weights >= 0.0)
    clean_values = values[clean_mask]
    clean_weights = weights[clean_mask]
    total = float(np.sum(clean_weights))
    if len(clean_values) == 0 or total <= 0.0:
        raise AnalogueFanError("weighted percentile has no positive finite weight")
    order = np.argsort(clean_values)
    sorted_values = clean_values[order]
    sorted_weights = clean_weights[order]
    cutoff = float(percentile) / 100.0 * total
    cumulative = np.cumsum(sorted_weights)
    idx = int(np.searchsorted(cumulative, cutoff, side="left"))
    idx = min(max(idx, 0), len(sorted_values) - 1)
    return float(sorted_values[idx])


def _load_histories(
    histories: Mapping[str, pd.Series] | None,
) -> dict[str, pd.Series]:
    if histories is not None:
        loaded = {
            str(variable): _quarterly_series(series, str(variable))
            for variable, series in histories.items()
        }
    else:
        cache = load_directional_feature_cache()
        loaded = {
            variable: _quarterly_series(series, variable)
            for variable, series in cache.histories.items()
        }
    missing = sorted(set(DIRECTIONAL_VARIABLES) - set(loaded))
    if missing:
        raise AnalogueFanError(f"missing transformed histories for fan variables: {missing}")
    return loaded


def _quarterly_series(series: pd.Series, variable: str) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        raise AnalogueFanError(f"transformed history for {variable} is empty")
    if not isinstance(clean.index, pd.PeriodIndex):
        clean = clean.copy()
        clean.index = pd.PeriodIndex(clean.index, freq="Q")
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    clean.name = variable
    return clean


def _positive_int(value: Any, name: str) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueFanError(f"{name} must be an integer; got {value!r}") from exc
    if integer < 1:
        raise AnalogueFanError(f"{name} must be at least 1; got {value!r}")
    return integer


def _finite_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise AnalogueFanError(f"{name} must be numeric; got {value!r}") from exc
    if not np.isfinite(number):
        raise AnalogueFanError(f"{name} must be finite; got {value!r}")
    return number


def _nonnegative_float(value: Any, name: str) -> float:
    number = _finite_float(value, name)
    if number < 0.0:
        raise AnalogueFanError(f"{name} must be non-negative; got {value!r}")
    return number


def _print_fan(fan: FanResult) -> None:
    print("Analogue Fan")
    print(f"query_date: {fan.query_date}")
    print(f"horizon_quarters: {fan.horizon_quarters}")
    print(f"match_count: {fan.metadata.get('match_count')}")
    print(f"units: {fan.metadata.get('units_note')}")
    quarters = [str(parse_quarter(fan.query_date) + step) for step in range(1, fan.horizon_quarters + 1)]
    for variable, result in fan.variables.items():
        print()
        print(f"{variable} (anchor={result.query_anchor_value:.6f})")
        print(f"  {'h':<8} {'p10':>10} {'p50':>10} {'p90':>10} {'eff_n':>10}")
        p10 = result.percentiles["p10"]
        p50 = result.percentiles["p50"]
        p90 = result.percentiles["p90"]
        for idx, quarter in enumerate(quarters):
            print(
                f"  {quarter:<8} {_fmt(p10[idx]):>10} {_fmt(p50[idx]):>10} "
                f"{_fmt(p90[idx]):>10} {result.effective_n[idx]:>10.6f}"
            )
        for subset, note in result.subset_notes.items():
            if note != "ok":
                print(f"  {subset}: {note}")


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
