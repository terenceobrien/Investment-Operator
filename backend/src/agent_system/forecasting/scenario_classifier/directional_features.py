"""Directional macro-state features from the scenario-classifier spine cache.

This module intentionally does not call the analogue matcher, scenario mapping,
BVAR forecast, or macro-forecast blend. It computes a standalone level+trend
feature vector over the classifier spine variables using the existing quarterly
classifier cache at data/agent_system/classifier_cache/.

curve_slope is derived from the transformed spine series as ten_year - fed_funds.
It is first-class in the directional vector because curve shape is a core
recession lead indicator. A future refinement can swap this proxy for an
explicit 10y-2y slope if a 2y series is added to the spine registry.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.data import (
    default_cache_dir,
    ensure_cache_available,
    load_transformed_history,
)
from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
)


SPINE_VARIABLES: tuple[str, ...] = (
    "activity",
    "lur",
    "core_pce",
    "credit_spread",
    "fed_funds",
    "ten_year",
    "nfci",
)
DERIVED_VARIABLES: tuple[str, ...] = ("curve_slope",)
DIRECTIONAL_VARIABLES: tuple[str, ...] = SPINE_VARIABLES + DERIVED_VARIABLES
FEATURE_COMPONENTS: tuple[str, ...] = ("level_percentile", "trend_slope")
TRAILING_WINDOW_QUARTERS = 4
# Avoid producing noisy early-sample percentiles before the quarterly spine has
# an established empirical distribution; this also keeps early NFCI history
# fail-loud instead of silently filling the vector.
MIN_LEVEL_HISTORY_QUARTERS = 16
LIBRARY_FILENAME = "directional_feature_library.csv"


class DirectionalFeatureError(RuntimeError):
    """Raised when directional features cannot be computed without imputation."""


@dataclass(frozen=True)
class VariableDirectionalFeatures:
    variable: str
    level_percentile: float
    trend_slope: float
    current_value: float
    raw_ols_slope_per_year: float
    trend_normalizer_12m_change_std: float
    history_start: str
    history_end: str
    history_count: int
    observations_available_through_as_of: int
    source: str
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DirectionalFeatureVector:
    as_of: str
    variables: tuple[str, ...]
    features: dict[str, VariableDirectionalFeatures]
    flat_feature_names: tuple[str, ...]
    flat_vector: tuple[float, ...]
    window_quarters_used: tuple[str, ...]
    metadata: dict[str, Any]

    def to_flat_dict(self) -> dict[str, float]:
        return dict(zip(self.flat_feature_names, self.flat_vector))

    def to_record(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "window_start": self.window_quarters_used[0],
            "window_end": self.window_quarters_used[-1],
            **self.to_flat_dict(),
        }


@dataclass(frozen=True)
class DirectionalFeatureCache:
    cache_dir: Path
    registry_path: Path
    histories: dict[str, pd.Series]


def load_directional_feature_cache(
    *,
    cache_dir: str | Path | None = None,
    registry: VariableRegistry | None = None,
) -> DirectionalFeatureCache:
    """Load transformed spine histories from the existing classifier cache."""

    loaded_registry = registry or VariableRegistry.load()
    target_cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    ensure_cache_available(loaded_registry, cache_dir=target_cache_dir)

    histories: dict[str, pd.Series] = {}
    for variable_name in SPINE_VARIABLES:
        spec = loaded_registry.get(variable_name)
        if not spec.is_spine:
            raise DirectionalFeatureError(
                f"state_vector variable {variable_name} is not marked as spine"
            )
        series = load_transformed_history(
            loaded_registry,
            spec,
            cache_dir=target_cache_dir,
        )
        histories[variable_name] = _quarterly_series(series, variable_name)

    histories["curve_slope"] = _derive_curve_slope(histories)
    return DirectionalFeatureCache(
        cache_dir=target_cache_dir,
        registry_path=loaded_registry.source_path,
        histories=histories,
    )


def compute_directional_features(
    as_of: pd.Period | str,
    cache: DirectionalFeatureCache | str | Path | None = None,
) -> DirectionalFeatureVector:
    """Compute the 16-dimensional level+trend vector for one quarter."""

    feature_cache = _coerce_cache(cache)
    quarter = _parse_quarter(as_of)
    window = _window_quarters(quarter)
    features: dict[str, VariableDirectionalFeatures] = {}
    flat_names: list[str] = []
    flat_values: list[float] = []

    for variable_name in DIRECTIONAL_VARIABLES:
        series = feature_cache.histories.get(variable_name)
        if series is None:
            raise DirectionalFeatureError(
                f"Missing transformed history for {variable_name} at {quarter}"
            )
        feature = _compute_variable_features(variable_name, series, quarter, window)
        features[variable_name] = feature
        flat_names.append(f"{variable_name}.level_percentile")
        flat_values.append(feature.level_percentile)
        flat_names.append(f"{variable_name}.trend_slope")
        flat_values.append(feature.trend_slope)

    metadata = {
        "as_of": str(quarter),
        "cache_dir": str(feature_cache.cache_dir),
        "registry_path": str(feature_cache.registry_path),
        "frequency": "quarterly",
        "spine_variables": list(SPINE_VARIABLES),
        "derived_variables": list(DERIVED_VARIABLES),
        "derived_feature_notes": {
            "curve_slope": (
                "Derived from transformed spine series as ten_year - fed_funds; "
                "future refinement can use an explicit 10y-2y slope if a 2y "
                "series is added to the spine."
            ),
        },
        "level_method": "empirical percentile against full available transformed series",
        "trend_method": (
            "OLS slope over four quarterly observations ending at as_of, with "
            "time measured in years and normalized by full-history std of "
            "four-quarter changes"
        ),
        "trailing_window_quarters": TRAILING_WINDOW_QUARTERS,
        "minimum_level_history_quarters_through_as_of": MIN_LEVEL_HISTORY_QUARTERS,
        "insufficient_history": [],
    }
    return DirectionalFeatureVector(
        as_of=str(quarter),
        variables=DIRECTIONAL_VARIABLES,
        features=features,
        flat_feature_names=tuple(flat_names),
        flat_vector=tuple(float(value) for value in flat_values),
        window_quarters_used=tuple(str(item) for item in window),
        metadata=metadata,
    )


def compute_directional_features_batch(
    dates: Iterable[pd.Period | str],
    cache: DirectionalFeatureCache | str | Path | None = None,
) -> list[DirectionalFeatureVector]:
    """Compute directional feature vectors for a batch of dates."""

    feature_cache = _coerce_cache(cache)
    return [
        compute_directional_features(as_of, cache=feature_cache)
        for as_of in dates
    ]


def build_directional_feature_library(
    *,
    start: pd.Period | str,
    end: pd.Period | str,
    cache: DirectionalFeatureCache | str | Path | None = None,
    output_path: str | Path | None = None,
) -> tuple[pd.DataFrame, Path]:
    """Build and write a historical directional-feature library CSV."""

    feature_cache = _coerce_cache(cache)
    start_q = _parse_quarter(start)
    end_q = _parse_quarter(end)
    if end_q < start_q:
        raise DirectionalFeatureError(f"end {end_q} is before start {start_q}")
    dates = pd.period_range(start_q, end_q, freq="Q")
    vectors = compute_directional_features_batch(dates, cache=feature_cache)
    frame = pd.DataFrame([vector.to_record() for vector in vectors])
    feature_columns = [name for name in frame.columns if name not in {"as_of", "window_start", "window_end"}]
    if frame[feature_columns].isna().any().any():
        missing = frame.columns[frame.isna().any()].tolist()
        raise DirectionalFeatureError(
            f"Directional feature library contains missing values in columns: {missing}"
        )

    path = Path(output_path) if output_path is not None else feature_cache.cache_dir / LIBRARY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame, path


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
        description="Standalone directional macro-state feature builder."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--cache-dir",
        default=None,
        help="Classifier cache directory; defaults to the resolved classifier_cache directory.",
    )

    inspect = subparsers.add_parser("inspect", parents=[common])
    inspect.add_argument("--dates", nargs="+", required=True, help="Quarter(s), e.g. 2007Q4.")
    inspect.set_defaults(func=_cmd_inspect)

    build = subparsers.add_parser("build-library", parents=[common])
    build.add_argument("--start", required=True, help="Start quarter, e.g. 1975Q1.")
    build.add_argument("--end", required=True, help="End quarter, e.g. 2026Q2.")
    build.add_argument(
        "--output",
        default=None,
        help=f"Output CSV path; defaults to classifier cache/{LIBRARY_FILENAME}.",
    )
    build.set_defaults(func=_cmd_build_library)
    return parser


def _cmd_inspect(args: argparse.Namespace) -> int:
    cache = load_directional_feature_cache(cache_dir=args.cache_dir)
    vectors = compute_directional_features_batch(args.dates, cache=cache)
    print("Directional Macro-State Features")
    print(f"cache: {cache.cache_dir}")
    print(f"registry: {cache.registry_path}")
    print(
        "curve_slope: derived as transformed ten_year - transformed fed_funds "
        "(future refinement: explicit 10y-2y if 2y enters the spine)"
    )
    for vector in vectors:
        _print_vector(vector)
    if len(vectors) >= 2:
        _print_comparison(vectors)
    return 0


def _cmd_build_library(args: argparse.Namespace) -> int:
    cache = load_directional_feature_cache(cache_dir=args.cache_dir)
    frame, path = build_directional_feature_library(
        start=args.start,
        end=args.end,
        cache=cache,
        output_path=args.output,
    )
    print(f"Wrote directional feature library: {path}")
    print(f"rows: {len(frame)}")
    print(f"range: {frame['as_of'].iloc[0]}..{frame['as_of'].iloc[-1]}")
    print(f"features: {len([column for column in frame.columns if '.' in column])}")
    return 0


def _coerce_cache(cache: DirectionalFeatureCache | str | Path | None) -> DirectionalFeatureCache:
    if isinstance(cache, DirectionalFeatureCache):
        return cache
    return load_directional_feature_cache(cache_dir=cache)


def _quarterly_series(series: pd.Series, variable_name: str) -> pd.Series:
    clean = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if clean.empty:
        raise DirectionalFeatureError(f"Transformed history for {variable_name} is empty")
    if not isinstance(clean.index, pd.PeriodIndex):
        clean = clean.copy()
        clean.index = pd.PeriodIndex(clean.index, freq="Q")
    clean = clean[~clean.index.duplicated(keep="last")]
    clean.name = variable_name
    return clean.sort_index()


def _derive_curve_slope(histories: dict[str, pd.Series]) -> pd.Series:
    required = ["ten_year", "fed_funds"]
    missing = [variable for variable in required if variable not in histories]
    if missing:
        raise DirectionalFeatureError(
            f"Cannot derive curve_slope; missing transformed series: {missing}"
        )
    aligned = pd.concat(
        [histories["ten_year"].rename("ten_year"), histories["fed_funds"].rename("fed_funds")],
        axis=1,
        join="inner",
    ).dropna()
    if aligned.empty:
        raise DirectionalFeatureError(
            "Cannot derive curve_slope; ten_year and fed_funds have no overlapping history"
        )
    curve = aligned["ten_year"] - aligned["fed_funds"]
    curve.name = "curve_slope"
    return _quarterly_series(curve, "curve_slope")


def _parse_quarter(value: pd.Period | str) -> pd.Period:
    if isinstance(value, pd.Period):
        return value.asfreq("Q")
    text = str(value).strip().upper()
    if not text:
        raise DirectionalFeatureError("empty quarter value")
    try:
        return pd.Period(text, freq="Q")
    except Exception:
        try:
            return pd.Timestamp(text).to_period("Q")
        except Exception as exc:
            raise DirectionalFeatureError(f"Could not parse quarter: {value!r}") from exc


def _window_quarters(as_of: pd.Period) -> pd.PeriodIndex:
    return pd.period_range(as_of - (TRAILING_WINDOW_QUARTERS - 1), as_of, freq="Q")


def _compute_variable_features(
    variable_name: str,
    series: pd.Series,
    as_of: pd.Period,
    window: pd.PeriodIndex,
) -> VariableDirectionalFeatures:
    clean = _quarterly_series(series, variable_name)
    if as_of not in clean.index:
        raise DirectionalFeatureError(
            f"{variable_name} lacks value at {as_of}; available range "
            f"{clean.index.min()}..{clean.index.max()}"
        )
    history_through_as_of = clean[clean.index <= as_of]
    if len(history_through_as_of) < MIN_LEVEL_HISTORY_QUARTERS:
        raise DirectionalFeatureError(
            f"{variable_name} has insufficient percentile history at {as_of}: "
            f"{len(history_through_as_of)} quarter(s) available through as_of, "
            f"need at least {MIN_LEVEL_HISTORY_QUARTERS}"
        )

    window_values = clean.reindex(window)
    missing_window = [str(item) for item, value in window_values.items() if pd.isna(value)]
    if missing_window:
        raise DirectionalFeatureError(
            f"{variable_name} has insufficient trailing 12-month window at {as_of}; "
            f"missing quarter(s): {', '.join(missing_window)}"
        )
    current_value = _finite_float(clean.loc[as_of], variable_name, as_of)
    level_percentile = _level_percentile(clean, current_value, variable_name, as_of)
    raw_slope = _ols_slope_per_year(window_values.to_numpy(dtype=float), variable_name, as_of)
    normalizer = _trend_normalizer(clean, variable_name, as_of)
    trend_slope = raw_slope / normalizer
    if not np.isfinite(trend_slope):
        raise DirectionalFeatureError(
            f"{variable_name} trend_slope is non-finite at {as_of}"
        )

    source = "derived" if variable_name in DERIVED_VARIABLES else "spine"
    note = None
    if variable_name == "curve_slope":
        note = (
            "Derived from transformed ten_year - transformed fed_funds; future "
            "refinement can use explicit 10y-2y if a 2y series enters the spine."
        )
    return VariableDirectionalFeatures(
        variable=variable_name,
        level_percentile=float(level_percentile),
        trend_slope=float(trend_slope),
        current_value=float(current_value),
        raw_ols_slope_per_year=float(raw_slope),
        trend_normalizer_12m_change_std=float(normalizer),
        history_start=str(clean.index.min()),
        history_end=str(clean.index.max()),
        history_count=int(len(clean)),
        observations_available_through_as_of=int(len(history_through_as_of)),
        source=source,
        note=note,
    )


def _finite_float(value: Any, variable_name: str, as_of: pd.Period) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise DirectionalFeatureError(
            f"{variable_name} has non-numeric value at {as_of}: {value!r}"
        ) from exc
    if not np.isfinite(out):
        raise DirectionalFeatureError(
            f"{variable_name} has non-finite value at {as_of}: {value!r}"
        )
    return out


def _level_percentile(
    series: pd.Series,
    current_value: float,
    variable_name: str,
    as_of: pd.Period,
) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(dtype=float)
    if len(values) == 0:
        raise DirectionalFeatureError(
            f"{variable_name} has no full-history values for percentile at {as_of}"
        )
    percentile = float(np.count_nonzero(values <= current_value) / len(values))
    if not 0.0 <= percentile <= 1.0:
        raise DirectionalFeatureError(
            f"{variable_name} percentile is out of range at {as_of}: {percentile}"
        )
    return percentile


def _ols_slope_per_year(
    values: np.ndarray,
    variable_name: str,
    as_of: pd.Period,
) -> float:
    if len(values) != TRAILING_WINDOW_QUARTERS:
        raise DirectionalFeatureError(
            f"{variable_name} OLS window at {as_of} has {len(values)} points; "
            f"need {TRAILING_WINDOW_QUARTERS}"
        )
    if not np.isfinite(values).all():
        raise DirectionalFeatureError(
            f"{variable_name} OLS window contains non-finite values at {as_of}"
        )
    x_years = np.arange(TRAILING_WINDOW_QUARTERS, dtype=float) / 4.0
    slope, _intercept = np.polyfit(x_years, values, 1)
    return float(slope)


def _trend_normalizer(series: pd.Series, variable_name: str, as_of: pd.Period) -> float:
    changes = pd.to_numeric(series, errors="coerce").dropna().diff(4).dropna()
    if len(changes) < 2:
        raise DirectionalFeatureError(
            f"{variable_name} has insufficient full-history 12-month changes "
            f"for trend normalization at {as_of}"
        )
    normalizer = float(changes.std(ddof=0))
    if not np.isfinite(normalizer) or normalizer <= 0:
        raise DirectionalFeatureError(
            f"{variable_name} has invalid 12-month change std for trend "
            f"normalization at {as_of}: {normalizer}"
        )
    return normalizer


def _print_vector(vector: DirectionalFeatureVector) -> None:
    print()
    print(f"{vector.as_of}  window={vector.window_quarters_used[0]}..{vector.window_quarters_used[-1]}")
    print(f"{'variable':<18} {'level_percentile':>16} {'trend_slope':>13} {'value':>12}")
    for variable_name in vector.variables:
        feature = vector.features[variable_name]
        print(
            f"{variable_name:<18} "
            f"{feature.level_percentile:>16.3f} "
            f"{feature.trend_slope:>+13.3f} "
            f"{feature.current_value:>12.3f}"
        )


def _print_comparison(vectors: list[DirectionalFeatureVector]) -> None:
    left, right = _comparison_pair(vectors)
    print()
    print(f"Side-by-side divergence: {left.as_of} vs {right.as_of}")
    print(f"{'feature':<34} {left.as_of:>10} {right.as_of:>10} {'diff':>10}")
    focus_names = [
        "credit_spread.level_percentile",
        "credit_spread.trend_slope",
        "curve_slope.level_percentile",
        "curve_slope.trend_slope",
        "activity.trend_slope",
    ]
    left_flat = left.to_flat_dict()
    right_flat = right.to_flat_dict()
    printed: set[str] = set()
    for name in focus_names:
        if name in left_flat and name in right_flat:
            _print_feature_diff(name, left_flat[name], right_flat[name])
            printed.add(name)

    diffs = sorted(
        (
            (name, left_flat[name], right_flat[name], abs(left_flat[name] - right_flat[name]))
            for name in left.flat_feature_names
            if name in right_flat and name not in printed
        ),
        key=lambda item: item[3],
        reverse=True,
    )
    if diffs:
        print("Top remaining differences:")
        for name, left_value, right_value, _abs_diff in diffs[:8]:
            _print_feature_diff(name, left_value, right_value)


def _comparison_pair(
    vectors: list[DirectionalFeatureVector],
) -> tuple[DirectionalFeatureVector, DirectionalFeatureVector]:
    by_date = {vector.as_of: vector for vector in vectors}
    if "2007Q4" in by_date and "2017Q1" in by_date:
        return by_date["2007Q4"], by_date["2017Q1"]
    return vectors[0], vectors[1]


def _print_feature_diff(name: str, left_value: float, right_value: float) -> None:
    print(
        f"{name:<34} "
        f"{left_value:>+10.3f} "
        f"{right_value:>+10.3f} "
        f"{left_value - right_value:>+10.3f}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
