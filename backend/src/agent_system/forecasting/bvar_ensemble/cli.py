"""CLI for the standalone BVAR ensemble simulator."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from src.agent_system.forecasting.bvar_ensemble.bounds import validate_registry_bounds
from src.agent_system.forecasting.bvar_ensemble.diagnostics import print_tail_diagnostics
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    apply_config_overrides,
    default_bvar_cache_dir,
    fit_bvar,
    load_bvar_config,
    load_posterior_artifact,
    load_spine_history_frame,
    newest_posterior_artifact,
    validate_posterior_cache_fingerprint,
)
from src.agent_system.forecasting.bvar_ensemble.forecast import (
    build_classifier_for_forecast,
    compare_forecasts,
    print_forecast_summary,
    run_forecast,
    run_simulation_only,
)
from src.agent_system.forecasting.bvar_ensemble.garch import (
    fit_garch_artifact,
    load_garch_artifact,
    newest_garch_artifact,
    validate_garch_matches_posterior,
)
from src.agent_system.forecasting.bvar_ensemble.regime_labeling import (
    label_regimes,
)
from src.agent_system.forecasting.bvar_ensemble.regime_params import (
    fit_regime_artifact,
    load_regime_artifact,
    newest_regime_artifact,
    p_enter_for_anchor,
    validate_regime_matches_posterior,
)
from src.agent_system.forecasting.bvar_ensemble.report import (
    generate_forecast_report,
    resolve_report_output_dir,
)
from src.agent_system.forecasting.scenario_classifier.data import default_cache_dir
from src.agent_system.forecasting.scenario_classifier.config import load_classifier_config
from src.agent_system.forecasting.scenario_classifier.deltas import BASELINE_MODES
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone BVAR ensemble simulator.")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--classifier-cache-dir", default=None)
    common.add_argument("--bvar-cache-dir", default=None)
    common.add_argument("--handoff-dir", default=None)

    fit = subparsers.add_parser("fit", parents=[common])
    fit.set_defaults(func=_cmd_fit)

    fit_garch = subparsers.add_parser("fit-garch", parents=[common])
    _add_artifact_flags(fit_garch, garch=False, regime=False)
    fit_garch.set_defaults(func=_cmd_fit_garch)

    label_regimes_cmd = subparsers.add_parser("label-regimes", parents=[common])
    _add_artifact_flags(label_regimes_cmd, garch=False, regime=False)
    label_regimes_cmd.set_defaults(func=_cmd_label_regimes)

    fit_regime = subparsers.add_parser("fit-regime", parents=[common])
    _add_artifact_flags(fit_regime, garch=False, regime=False)
    fit_regime.set_defaults(func=_cmd_fit_regime)

    validate = subparsers.add_parser("validate", parents=[common])
    _add_artifact_flags(validate)
    validate.add_argument("--horizon", type=int, default=None)
    validate.set_defaults(func=_cmd_validate)

    simulate = subparsers.add_parser("simulate", parents=[common])
    _add_simulation_flags(simulate)
    simulate.set_defaults(func=_cmd_simulate)

    forecast = subparsers.add_parser("forecast", parents=[common])
    _add_simulation_flags(forecast)
    forecast.add_argument(
        "--baseline-mode",
        choices=sorted(BASELINE_MODES),
        default=None,
        help="Classifier delta baseline mode; defaults to classifier_config.yaml.",
    )
    forecast.add_argument("--robust-classifier", action="store_true")
    forecast.set_defaults(func=_cmd_forecast)

    garch_validation = subparsers.add_parser("garch-validation", parents=[common])
    _add_simulation_flags(garch_validation)
    garch_validation.add_argument(
        "--baseline-mode",
        choices=sorted(BASELINE_MODES),
        default=None,
        help="Classifier delta baseline mode; defaults to classifier_config.yaml.",
    )
    garch_validation.set_defaults(func=_cmd_garch_validation)

    regime_validation = subparsers.add_parser("regime-validation", parents=[common])
    _add_simulation_flags(regime_validation)
    regime_validation.add_argument(
        "--baseline-mode",
        choices=sorted(BASELINE_MODES),
        default=None,
        help="Classifier delta baseline mode; defaults to classifier_config.yaml.",
    )
    regime_validation.set_defaults(func=_cmd_regime_validation)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--forecasts", required=True, help="Glob for forecast_*.json files.")
    compare.set_defaults(func=_cmd_compare)

    report = subparsers.add_parser("report", parents=[common])
    _add_artifact_flags(report)
    report.add_argument(
        "--forecast",
        default=None,
        help="Forecast JSON to render; defaults to newest forecast_*.json in bvar_cache.",
    )
    report.add_argument(
        "--compare",
        default=None,
        help="Optional comparison forecast JSON for side-by-side report mode.",
    )
    report.set_defaults(func=_cmd_report)

    shadow_compare = subparsers.add_parser("shadow-compare", parents=[common])
    shadow_compare.add_argument("--cycle-date", required=True, help="Cycle date, YYYY-MM-DD.")
    shadow_compare.add_argument(
        "--narrative-forecast",
        default=None,
        help="Existing narrative macro forecast JSON; defaults to newest macro_forecast_*.json.",
    )
    shadow_compare.add_argument(
        "--asof-quarter",
        default=None,
        help="Optional BVAR anchor quarter override, e.g. 2026Q1.",
    )
    shadow_compare.set_defaults(func=_cmd_shadow_compare)
    return parser


def _add_artifact_flags(
    parser: argparse.ArgumentParser,
    *,
    posterior: bool = True,
    garch: bool = True,
    regime: bool = True,
) -> None:
    if posterior:
        parser.add_argument("--posterior", default=None)
    if garch:
        parser.add_argument("--garch", "--garch-artifact", dest="garch_artifact", default=None)
    if regime:
        parser.add_argument("--regime", "--regime-artifact", dest="regime_artifact", default=None)


def _add_simulation_flags(parser: argparse.ArgumentParser) -> None:
    _add_artifact_flags(parser)
    parser.add_argument("--n-paths", type=int, default=None)
    parser.add_argument("--horizon", type=int, default=None)
    parser.add_argument("--asof", default=None, help="Anchor quarter, e.g. 2007Q4.")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--shock-dist", choices=["gaussian", "student_t"], default=None)
    parser.add_argument("--t-dof", type=int, default=None)
    parser.add_argument("--vol-model", choices=["constant", "garch"], default=None)
    parser.add_argument("--regime-model", choices=["none", "markov"], default=None)
    parser.add_argument("--draw-coefficients", action="store_true")


def _cmd_fit(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    config = load_bvar_config()
    posterior, summary_path = fit_bvar(
        registry,
        config,
        cache_dir=args.classifier_cache_dir,
        bvar_cache_dir=args.bvar_cache_dir,
    )
    print(f"Wrote posterior: {posterior.path}")
    print(f"Wrote summary: {summary_path}")
    print(
        "Largest companion eigenvalue modulus: "
        f"{posterior.companion_max_eigenvalue_modulus:.4f}"
    )
    if posterior.companion_max_eigenvalue_modulus >= 1.0:
        print("WARNING: fitted VAR companion dynamics are explosive (eigenvalue >= 1.0).")
    return 0


def _cmd_fit_garch(args: argparse.Namespace) -> int:
    config = load_bvar_config()
    posterior = _load_posterior(args)
    artifact, summary_path = fit_garch_artifact(
        posterior,
        config,
        bvar_cache_dir=args.bvar_cache_dir,
    )
    print(f"Wrote GARCH artifact: {artifact.path}")
    print(f"Wrote GARCH summary: {summary_path}")
    print(f"Posterior fingerprint: {artifact.posterior_fingerprint}")
    for variable, omega, alpha, beta in zip(
        artifact.variable_order,
        artifact.omega,
        artifact.alpha,
        artifact.beta,
    ):
        print(
            f"  {variable:<16} omega={omega:.6g} alpha={alpha:.4f} "
            f"beta={beta:.4f} persistence={alpha + beta:.4f}"
        )
    for warning in artifact.warnings:
        print(warning)
    return 0


def _cmd_label_regimes(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    config = load_bvar_config()
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    history = load_spine_history_frame(
        registry,
        estimation_start=posterior.sample_start,
        min_sample_quarters=posterior.lags + 1,
        cache_dir=args.classifier_cache_dir,
    )
    labels = label_regimes(
        history,
        residual_quarters=posterior.residual_quarters,
        config=config,
    )
    print("Regime labels:")
    print(f"  stress quarters: {labels.stress_count}/{len(labels.labels)} ({labels.stress_fraction:.1%})")
    print("  thresholds:")
    for key, value in labels.thresholds.items():
        if key == "stress_min_conditions":
            print(f"    {key}: {int(value)}")
        else:
            print(f"    {key}: {value:.4f}")
    print("  contiguous stress episodes:")
    for episode in labels.stress_episodes:
        print(f"    {episode['start']}..{episode['end']}")
    return 0


def _cmd_fit_regime(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    config = load_bvar_config()
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    artifact, summary_path = fit_regime_artifact(
        registry,
        posterior,
        config,
        cache_dir=args.classifier_cache_dir,
        bvar_cache_dir=args.bvar_cache_dir,
    )
    print(f"Wrote regime artifact: {artifact.path}")
    print(f"Wrote regime summary: {summary_path}")
    print(f"Posterior fingerprint: {artifact.posterior_fingerprint}")
    print(
        f"Entry logistic: intercept={artifact.logistic_intercept:.4f} "
        f"slope={artifact.logistic_slope:.4f}"
    )
    print(
        f"Stress persistence: p_stay={artifact.p_stay:.3f} "
        f"expected_duration={artifact.expected_stress_duration:.2f}q"
    )
    print(
        "Average off-diagonal correlation: "
        f"calm={artifact.calm_avg_offdiag_correlation:.3f} "
        f"empirical_stress={artifact.empirical_stress_avg_offdiag_correlation:.3f} "
        f"final_stress={artifact.stress_avg_offdiag_correlation:.3f}"
    )
    print(
        "Stress correlation imposition: "
        f"target={float(artifact.summary.get('crisis_correlation_target', 0.0)):.3f} "
        f"weight={float(artifact.summary.get('stress_correlation_impose_weight', 0.0)):.3f} "
        f"pre_repair_abs={float(artifact.summary.get('pre_repair_stress_avg_offdiag_magnitude', 0.0)):.3f} "
        f"post_repair_abs={artifact.stress_avg_offdiag_magnitude:.3f} "
        f"repaired={bool(artifact.summary.get('stress_correlation_psd_repaired', False))}"
    )
    print(
        "Stress concentration effect: "
        f"avg_vol_multiplier={artifact.average_stress_vol_multiplier:.3f} "
        f"avg_corr_delta={artifact.stress_avg_offdiag_correlation - artifact.calm_avg_offdiag_correlation:+.3f}"
    )
    for warning in artifact.summary.get("stress_correlation_warnings", []):
        print(warning)
    if artifact.expected_stress_duration <= 1.25:
        print(
            "WARNING: count-estimated stress persistence implies roughly one-quarter "
            "stress duration; this is a method limitation, not a fitted floor."
        )
    print("Imposed stress correlation matrix:")
    _print_correlation_matrix(artifact.variable_order, artifact.imposed_stress_correlation)
    print("Final PSD-repaired stress correlation matrix:")
    _print_correlation_matrix(artifact.variable_order, artifact.stress_correlation)
    print("Binned calm->stress transition rates:")
    for row in artifact.binned_transition_table:
        rate = row.get("transition_rate")
        rate_text = "n/a" if rate is None else f"{float(rate):.1%}"
        print(
            f"  Q{row['quartile']}: n={row['observations']} "
            f"transitions={row['transitions']} rate={rate_text} "
            f"proxy=[{row['proxy_min']:.3f}, {row['proxy_max']:.3f}]"
        )
    print("Stress vol multipliers:")
    for variable, multiplier in zip(artifact.variable_order, artifact.stress_vol_multiplier):
        print(f"  {variable:<16} {float(multiplier):.3f}")
    print("Stress episodes:")
    for episode in artifact.stress_episodes:
        print(f"  {episode['start']}..{episode['end']}")
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    bounds = validate_registry_bounds(registry)
    config = _config_from_args(args)
    classifier_config = _classifier_config_for_bvar(args, config)
    classifier_runtime_config = _merge_classifier_runtime_config(config, classifier_config)
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    garch_artifact = _load_garch_for_args(args, posterior, config=config)
    regime_artifact = _load_regime_for_args(args, posterior, config=config)
    classifier = build_classifier_for_forecast(
        registry,
        config=classifier_runtime_config,
        handoff_dir=args.handoff_dir,
        classifier_cache_dir=args.classifier_cache_dir,
    )
    print("BVAR ensemble validation OK")
    print(f"  posterior: {posterior.path}")
    print(f"  BVAR cache: {args.bvar_cache_dir or default_bvar_cache_dir()}")
    print(f"  classifier cache: {args.classifier_cache_dir or default_cache_dir()}")
    print(f"  active classifier variables: {', '.join(classifier.active_variables)}")
    print(f"  classifier baseline_mode: {classifier_config['baseline_mode']}")
    print(f"  vol_model: {config['vol_model']}")
    print(f"  regime_model: {config['regime_model']}")
    if garch_artifact is not None:
        print(f"  GARCH artifact: {garch_artifact.path}")
    if regime_artifact is not None:
        print(f"  regime artifact: {regime_artifact.path}")
        print(f"  regime stress episodes: {len(regime_artifact.stress_episodes)}")
    print(f"  spine bounds: {bounds}")
    metadata = classifier.signatures.metadata
    for warning in metadata.get("warnings", []):
        print(warning)
    return 0


def _cmd_simulate(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    config = _config_from_args(args)
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    garch_artifact = _load_garch_for_args(args, posterior, config=config)
    regime_artifact = _load_regime_for_args(args, posterior, config=config)
    paths_path, metadata_path, _sim, diagnostics = run_simulation_only(
        registry,
        posterior,
        config,
        classifier_cache_dir=args.classifier_cache_dir,
        bvar_cache_dir=args.bvar_cache_dir,
        asof_quarter=args.asof,
        n_paths=int(config["n_paths"]),
        horizon=int(config["horizon"]),
        seed=int(config["seed"]),
        shock_dist=str(config["shock_dist"]),
        t_dof=int(config["t_dof"]),
        draw_coefficients=bool(args.draw_coefficients),
        vol_model=str(config["vol_model"]),
        garch_artifact=garch_artifact,
        regime_model=str(config["regime_model"]),
        regime_artifact=regime_artifact,
    )
    print(f"Wrote simulated paths: {paths_path}")
    print(f"Wrote simulation metadata: {metadata_path}")
    print_tail_diagnostics(diagnostics, stream=sys.stdout)
    return 0


def _cmd_forecast(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    config = _config_from_args(args)
    classifier_config = _classifier_config_for_bvar(args, config)
    classifier_runtime_config = _merge_classifier_runtime_config(config, classifier_config)
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    garch_artifact = _load_garch_for_args(args, posterior, config=config)
    regime_artifact = _load_regime_for_args(args, posterior, config=config)
    forecast_path, paths_path, forecast, _classifications = run_forecast(
        registry,
        posterior,
        classifier_runtime_config,
        classifier_cache_dir=args.classifier_cache_dir,
        bvar_cache_dir=args.bvar_cache_dir,
        handoff_dir=args.handoff_dir,
        asof_quarter=args.asof,
        n_paths=int(config["n_paths"]),
        horizon=int(config["horizon"]),
        seed=int(config["seed"]),
        shock_dist=str(config["shock_dist"]),
        t_dof=int(config["t_dof"]),
        draw_coefficients=bool(args.draw_coefficients),
        baseline_mode=str(classifier_config["baseline_mode"]),
        vol_model=str(config["vol_model"]),
        garch_artifact=garch_artifact,
        regime_model=str(config["regime_model"]),
        regime_artifact=regime_artifact,
        robust_classifier=bool(args.robust_classifier),
    )
    print(f"Wrote forecast: {forecast_path}")
    print(f"Wrote classifier paths: {paths_path}")
    print(f"Wrote simulated spine paths: {forecast.get('simulation_paths_parquet')}")
    print_forecast_summary(forecast, stream=sys.stdout)
    metadata = forecast.get("classifier_metadata", {})
    for warning in metadata.get("warnings", []):
        print(warning)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    frame = compare_forecasts(args.forecasts)
    print(frame.to_string(index=False))
    return 0


def _cmd_garch_validation(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    base_config = _config_from_args(args)
    base_config["regime_model"] = "none"
    classifier_config = _classifier_config_for_bvar(args, base_config)
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    garch_artifact = _load_garch_for_args(
        args,
        posterior,
        config={**base_config, "vol_model": "garch"},
    )
    anchors = [
        ("2007Q4", "GFC onset", "stress"),
        ("1990Q2", "S&L / credit crunch", "stress"),
        ("2000Q4", "dot-com spread widen", "stress"),
        ("2015Q4", "energy-credit stress", "stress"),
        ("2026Q1", "current calm", "calm"),
        ("2017Q1", "synchronized calm", "calm"),
    ]
    rows: list[dict[str, Any]] = []
    scenarios: list[str] | None = None
    for anchor, label, bucket in anchors:
        for vol_model in ["constant", "garch"]:
            config = dict(base_config)
            config["vol_model"] = vol_model
            runtime_config = _merge_classifier_runtime_config(config, classifier_config)
            _forecast_path, _paths_path, forecast, _classifications = run_forecast(
                registry,
                posterior,
                runtime_config,
                classifier_cache_dir=args.classifier_cache_dir,
                bvar_cache_dir=args.bvar_cache_dir,
                handoff_dir=args.handoff_dir,
                asof_quarter=anchor,
                n_paths=int(config["n_paths"]),
                horizon=int(config["horizon"]),
                seed=int(config["seed"]),
                shock_dist=str(config["shock_dist"]),
                t_dof=int(config["t_dof"]),
                draw_coefficients=bool(args.draw_coefficients),
                baseline_mode=str(classifier_config["baseline_mode"]),
                vol_model=vol_model,
                garch_artifact=garch_artifact if vol_model == "garch" else None,
                regime_model="none",
                regime_artifact=None,
            )
            probs = forecast["scenario_probabilities"]
            scenarios = scenarios or list(probs.keys())
            rows.append(
                {
                    "anchor": anchor,
                    "label": label,
                    "bucket": bucket,
                    "vol_model": vol_model,
                    "share_low_margin": forecast["margin_stats"]["share_low_margin"],
                    **{f"p_{scenario}": probs[scenario] for scenario in probs},
                }
            )
    print("GARCH validation scenario probabilities:")
    assert scenarios is not None
    for anchor, label, bucket in anchors:
        constant = next(row for row in rows if row["anchor"] == anchor and row["vol_model"] == "constant")
        garch = next(row for row in rows if row["anchor"] == anchor and row["vol_model"] == "garch")
        print(f"\n{anchor}  {label}  [{bucket}]")
        for scenario in scenarios:
            marker = "*** " if scenario == "credit_led_recession" else "    "
            c = float(constant[f"p_{scenario}"])
            g = float(garch[f"p_{scenario}"])
            print(f"{marker}{scenario:<32} constant={c:.3f} garch={g:.3f} delta={g - c:+.3f}")
        print(
            "    share_low_margin"
            f"{'':<17} constant={constant['share_low_margin']:.3f} "
            f"garch={garch['share_low_margin']:.3f} "
            f"delta={garch['share_low_margin'] - constant['share_low_margin']:+.3f}"
        )

    stress_credit = [
        float(row["p_credit_led_recession"])
        for row in rows
        if row["vol_model"] == "garch" and row["bucket"] == "stress"
    ]
    calm_credit = [
        float(row["p_credit_led_recession"])
        for row in rows
        if row["vol_model"] == "garch" and row["bucket"] == "calm"
    ]
    stress_mean = sum(stress_credit) / len(stress_credit)
    calm_mean = sum(calm_credit) / len(calm_credit)
    gap = stress_mean - calm_mean
    calm_constant_credit = [
        float(row["p_credit_led_recession"])
        for row in rows
        if row["vol_model"] == "constant" and row["bucket"] == "calm"
    ]
    ordering_ok = gap > 0.01 and stress_mean > calm_mean * 1.5
    calm_ok = max(calm_credit) <= max(0.05, max(calm_constant_credit) + 0.02)
    margin_ok = True
    for anchor, _label, bucket in anchors:
        if bucket != "calm":
            continue
        constant = next(row for row in rows if row["anchor"] == anchor and row["vol_model"] == "constant")
        garch = next(row for row in rows if row["anchor"] == anchor and row["vol_model"] == "garch")
        if float(garch["share_low_margin"]) > float(constant["share_low_margin"]) + 1e-12:
            margin_ok = False
    print("\nOrdering check:")
    print(f"  stress mean credit_led_recession (garch): {stress_mean:.3f}")
    print(f"  calm mean credit_led_recession (garch):   {calm_mean:.3f}")
    print(f"  stress-calm gap:                         {gap:+.3f}")
    print(f"  ordering_ok={ordering_ok} calm_credit_ok={calm_ok} calm_margin_ok={margin_ok}")
    passed = ordering_ok and calm_ok and margin_ok
    print(f"\nFINAL VERDICT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def _cmd_regime_validation(args: argparse.Namespace) -> int:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    base_config = _config_from_args(args)
    base_config["vol_model"] = "garch"
    classifier_config = _classifier_config_for_bvar(args, base_config)
    posterior = _load_posterior(args)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=args.classifier_cache_dir,
    )
    garch_artifact = _load_garch_for_args(
        args,
        posterior,
        config={**base_config, "vol_model": "garch"},
    )
    regime_artifact = _load_regime_for_args(
        args,
        posterior,
        config={**base_config, "regime_model": "markov", "vol_model": "garch"},
    )
    anchors = [
        ("2007Q4", "GFC onset", "stress"),
        ("1990Q2", "S&L / credit crunch", "stress"),
        ("2000Q4", "dot-com spread widen", "stress"),
        ("2015Q4", "energy-credit stress", "stress"),
        ("2026Q1", "current calm", "calm"),
        ("2017Q1", "synchronized calm", "calm"),
    ]
    rows: list[dict[str, Any]] = []
    scenarios: list[str] | None = None
    for anchor, label, bucket in anchors:
        for regime_model in ["none", "markov"]:
            config = dict(base_config)
            config["regime_model"] = regime_model
            runtime_config = _merge_classifier_runtime_config(config, classifier_config)
            _forecast_path, _paths_path, forecast, _classifications = run_forecast(
                registry,
                posterior,
                runtime_config,
                classifier_cache_dir=args.classifier_cache_dir,
                bvar_cache_dir=args.bvar_cache_dir,
                handoff_dir=args.handoff_dir,
                asof_quarter=anchor,
                n_paths=int(config["n_paths"]),
                horizon=int(config["horizon"]),
                seed=int(config["seed"]),
                shock_dist=str(config["shock_dist"]),
                t_dof=int(config["t_dof"]),
                draw_coefficients=bool(args.draw_coefficients),
                baseline_mode=str(classifier_config["baseline_mode"]),
                vol_model="garch",
                garch_artifact=garch_artifact,
                regime_model=regime_model,
                regime_artifact=regime_artifact if regime_model == "markov" else None,
            )
            probs = forecast["scenario_probabilities"]
            scenarios = scenarios or list(probs.keys())
            rows.append(
                {
                    "anchor": anchor,
                    "label": label,
                    "bucket": bucket,
                    "regime_model": regime_model,
                    "p_enter": forecast.get("regime_anchor_p_enter"),
                    "share_low_margin": forecast["margin_stats"]["share_low_margin"],
                    **{f"p_{scenario}": probs[scenario] for scenario in probs},
                }
            )
    assert scenarios is not None
    print("Regime validation scenario probabilities:")
    for anchor, label, bucket in anchors:
        none = next(row for row in rows if row["anchor"] == anchor and row["regime_model"] == "none")
        markov = next(row for row in rows if row["anchor"] == anchor and row["regime_model"] == "markov")
        print(f"\n{anchor}  {label}  [{bucket}]  anchor_p_enter={float(markov['p_enter'] or 0.0):.3f}")
        for scenario in scenarios:
            marker = "*** " if scenario == "credit_led_recession" else "    "
            n = float(none[f"p_{scenario}"])
            m = float(markov[f"p_{scenario}"])
            print(f"{marker}{scenario:<32} none={n:.3f} markov={m:.3f} delta={m - n:+.3f}")
        print(
            "    share_low_margin"
            f"{'':<17} none={none['share_low_margin']:.3f} "
            f"markov={markov['share_low_margin']:.3f} "
            f"delta={markov['share_low_margin'] - none['share_low_margin']:+.3f}"
        )

    print("\nRun-up p_enter generalization check:")
    runup_quarters = [
        "2006Q4", "2007Q1", "2007Q2", "2007Q3", "2007Q4",
        "1989Q1", "1989Q2", "1989Q3", "1989Q4", "1990Q1", "1990Q2",
        "1999Q1", "1999Q2", "1999Q3", "1999Q4", "2000Q1", "2000Q2", "2000Q3", "2000Q4",
        "2019Q3", "2019Q4", "2020Q1",
    ]
    for quarter in runup_quarters:
        try:
            print(f"  {quarter}: p_enter={p_enter_for_anchor(regime_artifact, quarter):.3f}")
        except Exception as exc:
            print(f"  {quarter}: unavailable ({exc})")

    row_2007_none = next(row for row in rows if row["anchor"] == "2007Q4" and row["regime_model"] == "none")
    row_2007_markov = next(row for row in rows if row["anchor"] == "2007Q4" and row["regime_model"] == "markov")
    calm_markov = [
        row for row in rows
        if row["bucket"] == "calm" and row["regime_model"] == "markov"
    ]
    calm_none = [
        row for row in rows
        if row["bucket"] == "calm" and row["regime_model"] == "none"
    ]
    p2007 = float(row_2007_markov["p_enter"] or 0.0)
    calm_p_enter = [float(row["p_enter"] or 0.0) for row in calm_markov]
    penter_ok = p2007 > max(calm_p_enter) + 0.02 and p2007 > max(calm_p_enter) * 1.5
    credit_2007_markov = float(row_2007_markov["p_credit_led_recession"])
    credit_2007_none = float(row_2007_none["p_credit_led_recession"])
    calm_credit_markov = [float(row["p_credit_led_recession"]) for row in calm_markov]
    calm_credit_none = [float(row["p_credit_led_recession"]) for row in calm_none]
    credit_lift_ok = (
        credit_2007_markov > credit_2007_none + 0.01
        and credit_2007_markov > max(calm_credit_markov) + 0.01
    )
    calm_lift_ok = max(calm_credit_markov) <= max(max(calm_credit_none) + 0.05, 0.10)
    print("\nDifferentiation checks:")
    print(f"  2007Q4 p_enter:                 {p2007:.3f}")
    print(f"  max calm-anchor p_enter:         {max(calm_p_enter):.3f}")
    print(f"  2007Q4 credit none/markov:       {credit_2007_none:.3f}/{credit_2007_markov:.3f}")
    print(f"  max calm credit markov:          {max(calm_credit_markov):.3f}")
    print(f"  penter_ok={penter_ok} credit_lift_ok={credit_lift_ok} calm_lift_ok={calm_lift_ok}")
    passed = penter_ok and credit_lift_ok and calm_lift_ok
    print(f"\nFINAL VERDICT: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def _cmd_report(args: argparse.Namespace) -> int:
    config = load_bvar_config()
    output_dir = resolve_report_output_dir(
        config,
        bvar_cache_dir=args.bvar_cache_dir,
    )
    report_path = generate_forecast_report(
        args.forecast,
        compare_forecast_path=args.compare,
        output_dir=output_dir,
        bvar_cache_dir=args.bvar_cache_dir,
    )
    print(f"Wrote BVAR report: {report_path}")
    return 0


def _cmd_shadow_compare(args: argparse.Namespace) -> int:
    from src.agent_system.forecasting.macro_forecast_comparison import (
        build_forecast_comparison,
    )
    from src.agent_system.forecasting.macro_forecast_shadow import (
        cycle_date_to_asof_quarter,
        run_shadow_forecast,
        shadow_forecast_dir,
    )

    cycle_date = str(args.cycle_date)
    asof_quarter = args.asof_quarter or cycle_date_to_asof_quarter(cycle_date)
    cycle_id = f"manual-shadow-{cycle_date}"
    shadow = run_shadow_forecast(
        cycle_id,
        cycle_date,
        asof_quarter,
        classifier_cache_dir=args.classifier_cache_dir,
        bvar_cache_dir=args.bvar_cache_dir,
        handoff_dir=args.handoff_dir,
    )
    if shadow is None:
        print("Shadow forecast failed or was skipped; no comparison written.")
        return 0
    narrative_path = Path(args.narrative_forecast) if args.narrative_forecast else _latest_narrative_forecast_path()
    build_forecast_comparison(
        narrative_path,
        shadow,
        cycle_id,
        cycle_date,
    )
    print(f"Wrote shadow forecast: {shadow.artifact_path}")
    print(f"Wrote shadow comparison artifacts under: {shadow_forecast_dir()}")
    return 0


def _config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    config = load_bvar_config()
    return apply_config_overrides(
        config,
        n_paths=getattr(args, "n_paths", None),
        horizon=getattr(args, "horizon", None),
        seed=getattr(args, "seed", None),
        shock_dist=getattr(args, "shock_dist", None),
        t_dof=getattr(args, "t_dof", None),
        vol_model=getattr(args, "vol_model", None),
        regime_model=getattr(args, "regime_model", None),
    )


def _classifier_config_for_bvar(
    args: argparse.Namespace,
    bvar_config: dict[str, Any],
) -> dict[str, Any]:
    return load_classifier_config(
        horizon_quarters=int(bvar_config["horizon"]),
        baseline_mode=getattr(args, "baseline_mode", None),
    )


def _merge_classifier_runtime_config(
    bvar_config: dict[str, Any],
    classifier_config: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(bvar_config)
    merged["kernel_sigma"] = float(classifier_config["kernel_sigma"])
    return merged


def _load_posterior(args: argparse.Namespace):
    posterior_path = getattr(args, "posterior", None)
    if posterior_path:
        return load_posterior_artifact(Path(posterior_path))
    return newest_posterior_artifact(bvar_cache_dir=args.bvar_cache_dir)


def _load_garch_for_args(
    args: argparse.Namespace,
    posterior,
    *,
    config: dict[str, Any],
):
    if str(config.get("vol_model", "constant")) != "garch":
        return None
    artifact_path = getattr(args, "garch_artifact", None)
    artifact = (
        load_garch_artifact(Path(artifact_path))
        if artifact_path
        else newest_garch_artifact(posterior, bvar_cache_dir=args.bvar_cache_dir)
    )
    validate_garch_matches_posterior(artifact, posterior)
    return artifact


def _load_regime_for_args(
    args: argparse.Namespace,
    posterior,
    *,
    config: dict[str, Any],
):
    if str(config.get("regime_model", "none")) != "markov":
        return None
    artifact_path = getattr(args, "regime_artifact", None)
    artifact = (
        load_regime_artifact(Path(artifact_path))
        if artifact_path
        else newest_regime_artifact(posterior, bvar_cache_dir=args.bvar_cache_dir)
    )
    validate_regime_matches_posterior(artifact, posterior)
    return artifact


def _print_correlation_matrix(variable_order: list[str], matrix) -> None:
    labels = [variable[:10] for variable in variable_order]
    print(" " * 13 + " ".join(f"{label:>10}" for label in labels))
    for row_label, row in zip(labels, matrix):
        values = " ".join(f"{float(value):>10.3f}" for value in row)
        print(f"  {row_label:<10} {values}")


def _latest_narrative_forecast_path() -> Path:
    roots = [
        Path("data/agent_system/reports/macro_forecasts"),
        Path("backend/data/agent_system/reports/macro_forecasts"),
    ]
    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        candidates.extend(root.glob("macro_forecast_*.json"))
        current_dir = root / "current"
        if current_dir.is_dir():
            candidates.extend(current_dir.glob("macro_forecast_*.json"))
    if not candidates:
        raise FileNotFoundError(
            "No narrative macro forecast JSON found; pass --narrative-forecast."
        )
    # Prefer files that parse as JSON macro artifacts, then newest modified time.
    valid: list[Path] = []
    for path in candidates:
        try:
            json.loads(path.read_text(encoding="utf-8"))
            valid.append(path)
        except Exception:
            continue
    if not valid:
        raise FileNotFoundError(
            "No readable narrative macro forecast JSON found; pass --narrative-forecast."
        )
    return sorted(valid, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)[0]


if __name__ == "__main__":
    raise SystemExit(main())
