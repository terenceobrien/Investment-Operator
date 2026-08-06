"""CLI for the standalone FRB/US scenario path classifier."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.forecasting.scenario_classifier.classifier import (
    ScenarioClassifier,
)
from src.agent_system.forecasting.scenario_classifier.config import (
    load_classifier_config,
)
from src.agent_system.forecasting.scenario_classifier.data import (
    default_cache_dir,
    ensure_cache_available,
    refresh_fred_cache,
)
from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
)
from src.agent_system.forecasting.scenario_classifier.scaling import (
    fit_scales,
    load_scales,
)
from src.agent_system.forecasting.scenario_classifier.signatures import (
    load_latest_signatures,
)
from src.agent_system.forecasting.scenario_classifier.validation import (
    BASELINE_MODES,
    ValidationEpisode,
    classify_episode,
    load_histories_for_classifier,
    load_validation_episodes,
    print_distance_table,
    print_variable_contributions,
    run_validation,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standalone FRB/US scenario path classifier."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--handoff-dir",
        default=None,
        help="Directory containing frbus_scenario_paths_*.json handoffs.",
    )
    common.add_argument(
        "--cache-dir",
        default=None,
        help="Classifier cache directory; defaults to the resolved classifier_cache directory.",
    )
    common.add_argument(
        "--k",
        "--horizon-quarters",
        dest="horizon_quarters",
        type=int,
        default=None,
        help="Signature/path horizon in quarters.",
    )

    refresh = subparsers.add_parser("refresh-data", parents=[common])
    refresh.set_defaults(func=_cmd_refresh_data)

    fit = subparsers.add_parser("fit-scales", parents=[common])
    fit.set_defaults(func=_cmd_fit_scales)

    validate = subparsers.add_parser("validate", parents=[common])
    validate.add_argument("--robust", action="store_true", help="Validate MAD scales are usable.")
    validate.set_defaults(func=_cmd_validate)

    classify_one = subparsers.add_parser("classify-episode", parents=[common])
    _add_classification_flags(classify_one)
    classify_one.add_argument("--start", required=True, help="Episode start quarter, e.g. 2008Q1.")
    classify_one.set_defaults(func=_cmd_classify_episode)

    run_val = subparsers.add_parser("run-validation", parents=[common])
    _add_classification_flags(run_val)
    run_val.set_defaults(func=_cmd_run_validation)

    batch = subparsers.add_parser("classify-paths", parents=[common])
    _add_classification_flags(batch)
    batch.add_argument("--input", required=True, help="Input long-format parquet path.")
    batch.add_argument("--output", required=True, help="Output classification parquet path.")
    batch.set_defaults(func=_cmd_classify_paths)
    return parser


def _add_classification_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--baseline-mode",
        default=None,
        choices=sorted(BASELINE_MODES),
        help="Baseline mode; defaults to classifier_config.yaml.",
    )
    parser.add_argument(
        "--exclude-var",
        action="append",
        default=None,
        help="Exclude a signature variable. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--include-only",
        default=None,
        help="Comma-separated signature variables to include.",
    )
    parser.add_argument("--robust", action="store_true", help="Use MAD-based scaling.")
    parser.add_argument(
        "--kernel-sigma",
        type=float,
        default=None,
        help="Gaussian kernel sigma for soft scenario weights.",
    )


def _cmd_refresh_data(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    manifest = refresh_fred_cache(registry, cache_dir=args.cache_dir)
    series = manifest.get("series", {})
    print(f"Refreshed {len(series)} FRED series into {args.cache_dir or default_cache_dir()}")
    for series_id, payload in sorted(series.items()):
        print(
            f"  {series_id}: rows={payload.get('row_count')} "
            f"range={payload.get('first_date')}..{payload.get('last_date')}"
        )
    return 0


def _cmd_fit_scales(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    config = _load_config(args)
    ensure_cache_available(registry, cache_dir=args.cache_dir)
    scales = fit_scales(
        registry,
        horizon_quarters=config["horizon_quarters"],
        cache_dir=args.cache_dir,
    )
    print(f"Wrote scales: {scales.path}")
    for variable, payload in scales.variables.items():
        print(
            f"  {variable}: std={payload['std']:.6g} mad={payload['mad']:.6g} "
            f"n={payload['change_count']} "
            f"range={payload['history_start']}..{payload['history_end']}"
        )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    config = _load_config(args)
    ensure_cache_available(registry, cache_dir=args.cache_dir)
    signatures = load_latest_signatures(
        registry,
        handoff_dir=args.handoff_dir,
        horizon_quarters=config["horizon_quarters"],
    )
    scales = load_scales(
        horizon_quarters=config["horizon_quarters"],
        cache_dir=args.cache_dir,
    )
    if args.robust:
        for variable in signatures.active_variables:
            scales.scale_for(variable, robust=True)
    else:
        for variable in signatures.active_variables:
            scales.scale_for(variable, robust=False)

    print("Scenario classifier validation OK")
    print(f"  registry: {registry.source_path}")
    print(f"  cache: {args.cache_dir or default_cache_dir()}")
    print(f"  handoff: {signatures.handoff_path}")
    print(f"  baseline_fingerprint: {signatures.baseline_data_fingerprint}")
    print(f"  scales: {scales.path}")
    print(f"  K: {config['horizon_quarters']}")
    print("  active signature variables: " + ", ".join(signatures.active_variables))
    for warning in signatures.warnings:
        print(warning)
    return 0


def _cmd_classify_episode(args: argparse.Namespace) -> int:
    classifier, registry, _config = _build_classifier(args)
    histories = load_histories_for_classifier(
        registry,
        classifier,
        cache_dir=args.cache_dir,
    )
    episode = _episode_for_start(args.start)
    baseline_mode = args.baseline_mode or _config["baseline_mode"]
    result = classify_episode(
        classifier,
        histories,
        episode,
        baseline_mode=baseline_mode,
    )
    print_distance_table(result.distances, stream=sys.stdout)
    print("\nPer-variable distance contributions:")
    print_variable_contributions(result.contributions, stream=sys.stdout)
    return 0


def _cmd_run_validation(args: argparse.Namespace) -> int:
    classifier, registry, _config = _build_classifier(args)
    histories = load_histories_for_classifier(
        registry,
        classifier,
        cache_dir=args.cache_dir,
    )
    episodes = load_validation_episodes()
    baseline_mode = args.baseline_mode or _config["baseline_mode"]
    passed = run_validation(
        classifier,
        histories,
        episodes,
        baseline_modes=[baseline_mode],
        stream=sys.stdout,
    )
    return 0 if passed else 1


def _cmd_classify_paths(args: argparse.Namespace) -> int:
    classifier, _registry, _config = _build_classifier(args)
    frame = pd.read_parquet(args.input)
    paths, path_ids = _paths_from_long_frame(frame, classifier)
    result = classifier.classify(paths, path_ids=path_ids)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output)
    print(f"Wrote classifications: {output}")
    metadata = getattr(result, "metadata", None) or result.attrs.get("metadata", {})
    for warning in metadata.get("warnings", []):
        print(warning)
    return 0


def _build_classifier(
    args: argparse.Namespace,
) -> tuple[ScenarioClassifier, VariableRegistry, dict[str, Any]]:
    registry = VariableRegistry.load()
    config = _load_config(args)
    ensure_cache_available(registry, cache_dir=args.cache_dir)
    signatures = load_latest_signatures(
        registry,
        handoff_dir=args.handoff_dir,
        horizon_quarters=config["horizon_quarters"],
    )
    scales = load_scales(
        horizon_quarters=config["horizon_quarters"],
        cache_dir=args.cache_dir,
    )
    classifier = ScenarioClassifier(
        registry,
        signatures,
        scales,
        config,
        include_only=_parse_variable_list(args.include_only),
        exclude=_parse_variable_list(args.exclude_var),
        robust=bool(args.robust or config.get("scaling") == "mad"),
    )
    for warning in signatures.warnings:
        print(warning)
    return classifier, registry, config


def _load_config(args: argparse.Namespace) -> dict[str, Any]:
    return load_classifier_config(
        horizon_quarters=args.horizon_quarters,
        baseline_mode=getattr(args, "baseline_mode", None),
        kernel_sigma=getattr(args, "kernel_sigma", None),
    )


def _episode_for_start(start: str) -> ValidationEpisode:
    for episode in load_validation_episodes():
        if episode.start == start:
            return episode
    return ValidationEpisode(start=start, expected="unknown", must_pass=False, note=None)


def _parse_variable_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    values: list[str] = []
    raw_items = value if isinstance(value, list) else [value]
    for item in raw_items:
        for piece in str(item).split(","):
            clean = piece.strip()
            if clean:
                values.append(clean)
    return values or None


def _paths_from_long_frame(
    frame: pd.DataFrame,
    classifier: ScenarioClassifier,
) -> tuple[np.ndarray, list[Any]]:
    required = {"path_id", "quarter_index", *classifier.active_variables}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"classify-paths input missing columns: {missing}")
    path_arrays: list[np.ndarray] = []
    path_ids: list[Any] = []
    for path_id, group in frame.groupby("path_id", sort=True):
        ordered = group.sort_values("quarter_index")
        if len(ordered) != classifier.scales.horizon_quarters:
            raise RuntimeError(
                f"path_id {path_id} has {len(ordered)} rows; "
                f"expected {classifier.scales.horizon_quarters}"
            )
        values = ordered[classifier.active_variables].to_numpy(dtype=float)
        if not np.isfinite(values).all():
            raise RuntimeError(f"path_id {path_id} contains non-finite path values")
        path_arrays.append(values)
        path_ids.append(path_id)
    if not path_arrays:
        raise RuntimeError("classify-paths input contains no paths")
    return np.stack(path_arrays, axis=0), path_ids


if __name__ == "__main__":
    raise SystemExit(main())
