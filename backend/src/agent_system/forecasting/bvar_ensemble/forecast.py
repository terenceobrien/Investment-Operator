"""End-to-end BVAR ensemble forecast orchestration."""
from __future__ import annotations

import glob
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import numpy as np
import pandas as pd

from src.agent_system.forecasting.bvar_ensemble.diagnostics import (
    compute_regime_overlay_diagnostics,
    compute_tail_diagnostics,
    compute_horizon_dispersion,
    garch_fallback_flags,
    print_tail_diagnostics,
    tail_flags,
)
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    PosteriorArtifact,
    default_bvar_cache_dir,
    load_spine_history_frame,
)
from src.agent_system.forecasting.bvar_ensemble.simulation import (
    SimulationResult,
    simulate_paths,
)
from src.agent_system.forecasting.bvar_ensemble.garch import (
    GarchArtifact,
    garch_metadata_for_forecast,
)
from src.agent_system.forecasting.bvar_ensemble.regime_params import (
    RegimeArtifact,
    regime_metadata_for_forecast,
)
from src.agent_system.forecasting.scenario_classifier.classifier import (
    ScenarioClassifier,
)
from src.agent_system.forecasting.scenario_classifier.data import (
    ensure_cache_available,
)
from src.agent_system.forecasting.scenario_classifier.deltas import (
    BASELINE_MODES,
    to_baseline_deltas,
)
from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
)
from src.agent_system.forecasting.scenario_classifier.scaling import (
    load_scales,
)
from src.agent_system.forecasting.scenario_classifier.signatures import (
    load_latest_signatures,
)


class ForecastError(RuntimeError):
    """Raised when the BVAR forecast pipeline cannot proceed."""


def build_classifier_for_forecast(
    registry: VariableRegistry,
    *,
    config: dict[str, Any],
    handoff_dir: str | Path | None,
    classifier_cache_dir: str | Path | None,
    robust: bool = False,
) -> ScenarioClassifier:
    ensure_cache_available(registry, cache_dir=classifier_cache_dir)
    signatures = load_latest_signatures(
        registry,
        handoff_dir=handoff_dir,
        horizon_quarters=int(config["horizon"]),
    )
    scales = load_scales(
        horizon_quarters=int(config["horizon"]),
        cache_dir=classifier_cache_dir,
    )
    return ScenarioClassifier(
        registry,
        signatures,
        scales,
        {"kernel_sigma": float(config.get("kernel_sigma", 1.0))},
        robust=robust,
    )


def run_simulation_only(
    registry: VariableRegistry,
    posterior: PosteriorArtifact,
    config: dict[str, Any],
    *,
    classifier_cache_dir: str | Path | None,
    bvar_cache_dir: str | Path | None,
    asof_quarter: str | None,
    n_paths: int,
    horizon: int,
    seed: int,
    shock_dist: str,
    t_dof: int,
    draw_coefficients: bool,
    vol_model: str = "constant",
    garch_artifact: GarchArtifact | None = None,
    regime_model: str = "none",
    regime_artifact: RegimeArtifact | None = None,
) -> tuple[Path, Path, SimulationResult, dict[str, Any]]:
    history = load_spine_history_frame(
        registry,
        estimation_start=posterior.sample_start,
        min_sample_quarters=posterior.lags + 1,
        cache_dir=classifier_cache_dir,
    )
    sim = simulate_paths(
        registry,
        posterior,
        history,
        n_paths=n_paths,
        horizon=horizon,
        asof_quarter=asof_quarter,
        seed=seed,
        shock_dist=shock_dist,
        t_dof=t_dof,
        draw_coefficients=draw_coefficients,
        max_redraws_per_path=int(config["max_redraws_per_path"]),
        rejection_warn_pct=float(config["rejection_warn_pct"]),
        vol_model=vol_model,
        garch_artifact=garch_artifact,
        regime_model=regime_model,
        regime_artifact=regime_artifact,
    )
    diagnostics = compute_tail_diagnostics(
        sim.paths,
        variable_order=sim.variable_order,
        anchor_values=sim.anchor_values,
        historical_sample=history,
        horizon=horizon,
    )
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    asof = sim.anchor_quarter
    paths_path = target_dir / f"simulation_{asof}_{timestamp}_paths.parquet"
    metadata_path = target_dir / f"simulation_{asof}_{timestamp}_metadata.json"
    _write_spine_paths_long(sim, paths_path)
    metadata = {
        **sim.metadata,
        "posterior_artifact": str(posterior.path),
        "tail_diagnostics": diagnostics,
        "horizon_dispersion": compute_horizon_dispersion(
            sim.paths,
            variable_order=sim.variable_order,
        ),
        "garch_diagnostics": (
            garch_metadata_for_forecast(garch_artifact)
            if garch_artifact is not None
            else None
        ),
        "regime_diagnostics": compute_regime_overlay_diagnostics(
            sim.paths,
            variable_order=sim.variable_order,
            ever_stress=sim.regime_ever_stress,
            entered_stress=sim.regime_entered_stress,
            stress_quarters=sim.regime_stress_quarters,
        ),
        "regime_artifact_metadata": regime_metadata_for_forecast(regime_artifact),
        "tail_flags": tail_flags(diagnostics),
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths_path, metadata_path, sim, diagnostics


def run_forecast(
    registry: VariableRegistry,
    posterior: PosteriorArtifact,
    config: dict[str, Any],
    *,
    classifier_cache_dir: str | Path | None,
    bvar_cache_dir: str | Path | None,
    handoff_dir: str | Path | None,
    asof_quarter: str | None,
    n_paths: int,
    horizon: int,
    seed: int,
    shock_dist: str,
    t_dof: int,
    draw_coefficients: bool,
    baseline_mode: str,
    vol_model: str = "constant",
    garch_artifact: GarchArtifact | None = None,
    regime_model: str = "none",
    regime_artifact: RegimeArtifact | None = None,
    robust_classifier: bool = False,
) -> tuple[Path, Path, dict[str, Any], pd.DataFrame]:
    if baseline_mode not in BASELINE_MODES:
        raise ForecastError(
            f"unknown baseline_mode '{baseline_mode}'. Valid modes: {sorted(BASELINE_MODES)}"
        )
    if int(horizon) != int(config["horizon"]):
        config = dict(config)
        config["horizon"] = int(horizon)
    classifier = build_classifier_for_forecast(
        registry,
        config=config,
        handoff_dir=handoff_dir,
        classifier_cache_dir=classifier_cache_dir,
        robust=robust_classifier,
    )
    history = load_spine_history_frame(
        registry,
        estimation_start=posterior.sample_start,
        min_sample_quarters=posterior.lags + 1,
        cache_dir=classifier_cache_dir,
    )
    sim = simulate_paths(
        registry,
        posterior,
        history,
        n_paths=n_paths,
        horizon=horizon,
        asof_quarter=asof_quarter,
        seed=seed,
        shock_dist=shock_dist,
        t_dof=t_dof,
        draw_coefficients=draw_coefficients,
        max_redraws_per_path=int(config["max_redraws_per_path"]),
        rejection_warn_pct=float(config["rejection_warn_pct"]),
        vol_model=vol_model,
        garch_artifact=garch_artifact,
        regime_model=regime_model,
        regime_artifact=regime_artifact,
    )
    classifier_paths = _classifier_paths_from_simulation(
        sim,
        classifier,
        history=history,
        baseline_mode=baseline_mode,
    )
    path_ids = list(range(n_paths))
    classifications = classifier.classify(classifier_paths, path_ids=path_ids)
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    asof = sim.anchor_quarter
    paths_path = target_dir / f"forecast_{asof}_{timestamp}_paths.parquet"
    spine_paths_path = target_dir / f"forecast_{asof}_{timestamp}_spine_paths.parquet"
    forecast_path = target_dir / f"forecast_{asof}_{timestamp}.json"
    _write_classifier_paths_long(
        classifier_paths,
        path_ids=path_ids,
        variables=classifier.full_variable_order,
        output_path=paths_path,
    )
    _write_spine_paths_long(sim, spine_paths_path)
    diagnostics = compute_tail_diagnostics(
        sim.paths,
        variable_order=sim.variable_order,
        anchor_values=sim.anchor_values,
        historical_sample=history,
        horizon=horizon,
    )
    horizon_dispersion = compute_horizon_dispersion(
        sim.paths,
        variable_order=sim.variable_order,
    )
    garch_diagnostics = (
        garch_metadata_for_forecast(garch_artifact)
        if garch_artifact is not None
        else None
    )
    regime_diagnostics = compute_regime_overlay_diagnostics(
        sim.paths,
        variable_order=sim.variable_order,
        ever_stress=sim.regime_ever_stress,
        entered_stress=sim.regime_entered_stress,
        stress_quarters=sim.regime_stress_quarters,
    )
    regime_artifact_metadata = regime_metadata_for_forecast(regime_artifact)
    hard_probs = _hard_probabilities(classifications, classifier.scenario_ids)
    soft_probs = _soft_probabilities(classifications, classifier.scenario_ids)
    margins = classifications["margin"].to_numpy(dtype=float)
    metadata = getattr(classifications, "metadata", None) or classifications.attrs.get("metadata", {})
    forecast = {
        "asof_quarter": asof,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "n_paths": int(n_paths),
        "horizon_quarters": int(horizon),
        "scenario_probabilities": hard_probs,
        "scenario_probabilities_soft": soft_probs,
        "margin_stats": {
            "mean": float(np.mean(margins)),
            "p25": float(np.percentile(margins, 25)),
            "share_low_margin": float(
                np.mean(margins < float(config["low_margin_threshold"]))
            ),
        },
        "anchor_values": sim.anchor_values,
        "posterior_artifact": str(posterior.path),
        "handoff_fingerprint": metadata.get("baseline_data_fingerprint"),
        "handoff_file": metadata.get("handoff_file"),
        "baseline_mode": baseline_mode,
        "shock_dist": shock_dist,
        "vol_model": vol_model,
        "regime_model": regime_model,
        "seed": int(seed),
        "garch_init_vol_by_variable": sim.metadata.get("garch_init_vol_by_variable"),
        "regime_artifact": sim.metadata.get("regime_artifact"),
        "regime_anchor_label": sim.metadata.get("regime_anchor_label"),
        "regime_anchor_p_enter": sim.metadata.get("regime_anchor_p_enter"),
        "regime_fraction_entered_stress": sim.metadata.get("regime_fraction_entered_stress"),
        "regime_fraction_ever_stress": sim.metadata.get("regime_fraction_ever_stress"),
        "regime_avg_quarters_in_stress": sim.metadata.get("regime_avg_quarters_in_stress"),
        "validity": sim.validity,
        "tail_diagnostics": diagnostics,
        "horizon_dispersion": horizon_dispersion,
        "garch_diagnostics": garch_diagnostics,
        "regime_diagnostics": regime_diagnostics,
        "regime_artifact_metadata": regime_artifact_metadata,
        "volatility_diagnostics": {
            "vol_model": vol_model,
            "garch_init_vol_by_variable": sim.metadata.get("garch_init_vol_by_variable"),
            "garch_fallback_variables": garch_fallback_flags(garch_diagnostics),
            "horizon_dispersion": horizon_dispersion,
        },
        "tail_flags": tail_flags(diagnostics),
        "paths_parquet": str(paths_path),
        "classifier_paths_parquet": str(paths_path),
        "simulation_paths_parquet": str(spine_paths_path),
        "classifier_metadata": metadata,
        "posterior_artifact_fingerprint": _file_fingerprint(posterior.path),
        "posterior_hyperparameters": posterior.hyperparameters,
        "config": _json_safe_config(config),
    }
    forecast_path.write_text(
        json.dumps(forecast, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return forecast_path, paths_path, forecast, classifications


def print_forecast_summary(
    forecast: dict[str, Any],
    *,
    stream: TextIO,
) -> None:
    print(f"BVAR forecast as of {forecast['asof_quarter']}", file=stream)
    print(f"Baseline mode: {forecast.get('baseline_mode', 'unknown')}", file=stream)
    print(f"Vol model: {forecast.get('vol_model', 'constant')}", file=stream)
    print(f"Regime model: {forecast.get('regime_model', 'none')}", file=stream)
    print("Scenario probabilities (hard primary, soft secondary):", file=stream)
    hard = forecast["scenario_probabilities"]
    soft = forecast["scenario_probabilities_soft"]
    for scenario, probability in sorted(hard.items(), key=lambda item: item[1], reverse=True):
        print(f"  {scenario:<32} hard={probability:.3f} soft={soft[scenario]:.3f}", file=stream)
    validity = forecast["validity"]
    print(
        "Validity: "
        f"rejections={validity['rejections']} redraws={validity['redraws']} "
        f"clips={validity['clips']} rejection_rate={validity['rejection_rate_pct']:.2f}%",
        file=stream,
    )
    if validity.get("warning"):
        print(validity["warning"], file=stream)
    flags = forecast.get("tail_flags", [])
    print(f"Tail flags: {', '.join(flags) if flags else 'none'}", file=stream)
    fallback = (forecast.get("garch_diagnostics") or {}).get("fallback_variables") or []
    if fallback:
        print(f"GARCH fallback variables: {', '.join(fallback)}", file=stream)
    init_vols = forecast.get("garch_init_vol_by_variable") or {}
    garch_variables = (forecast.get("garch_diagnostics") or {}).get("variables") or {}
    if init_vols:
        print(
            f"GARCH init vol at anchor {forecast.get('asof_quarter')}:",
            file=stream,
        )
        for variable, init_vol in init_vols.items():
            unconditional = (garch_variables.get(variable) or {}).get("unconditional_vol")
            if unconditional is None:
                print(f"  {variable:<16} init={float(init_vol):.4f}", file=stream)
            else:
                print(
                    f"  {variable:<16} init={float(init_vol):.4f} "
                    f"uncond={float(unconditional):.4f}",
                    file=stream,
                )
    if str(forecast.get("regime_model") or "none") == "markov":
        print(
            "Regime overlay: "
            f"anchor_label={forecast.get('regime_anchor_label')} "
            f"anchor_p_enter={float(forecast.get('regime_anchor_p_enter') or 0.0):.3f} "
            f"entered_stress={float(forecast.get('regime_fraction_entered_stress') or 0.0):.3f} "
            f"avg_stress_q={float(forecast.get('regime_avg_quarters_in_stress') or 0.0):.2f}",
            file=stream,
        )


def compare_forecasts(pattern: str) -> pd.DataFrame:
    paths = sorted(glob.glob(pattern))
    if not paths:
        raise ForecastError(f"no forecast JSON files match pattern: {pattern}")
    rows: list[dict[str, Any]] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        row: dict[str, Any] = {
            "forecast": path,
            "asof_quarter": payload.get("asof_quarter"),
            "seed": payload.get("seed"),
            "shock_dist": payload.get("shock_dist"),
            "vol_model": payload.get("vol_model"),
            "regime_model": payload.get("regime_model"),
            "baseline_mode": payload.get("baseline_mode"),
        }
        probs = payload.get("scenario_probabilities", {})
        if isinstance(probs, dict):
            row.update({f"p_{key}": value for key, value in probs.items()})
        rows.append(row)
    return pd.DataFrame(rows)


def _classifier_paths_from_simulation(
    sim: SimulationResult,
    classifier: ScenarioClassifier,
    *,
    history: pd.DataFrame,
    baseline_mode: str,
) -> np.ndarray:
    variable_to_index = {variable: index for index, variable in enumerate(sim.variable_order)}
    missing = [
        variable
        for variable in classifier.full_variable_order
        if variable not in variable_to_index
    ]
    if missing:
        raise ForecastError(f"simulation missing classifier variables: {missing}")
    path_values = np.zeros(
        (sim.paths.shape[0], sim.paths.shape[1], len(classifier.full_variable_order)),
        dtype=float,
    )
    for variable_index, variable in enumerate(classifier.full_variable_order):
        source_index = variable_to_index[variable]
        path_values[:, :, variable_index] = sim.paths[:, :, source_index]
    return to_baseline_deltas(
        path_values,
        variables=classifier.full_variable_order,
        anchor_history=history,
        anchor_quarter=sim.anchor_quarter,
        baseline_mode=baseline_mode,
    )


def _write_classifier_paths_long(
    paths: np.ndarray,
    *,
    path_ids: list[int],
    variables: list[str],
    output_path: Path,
) -> None:
    rows: list[dict[str, Any]] = []
    for path_index, path_id in enumerate(path_ids):
        for quarter_index in range(paths.shape[1]):
            row: dict[str, Any] = {
                "path_id": path_id,
                "quarter_index": quarter_index + 1,
            }
            for variable_index, variable in enumerate(variables):
                row[variable] = float(paths[path_index, quarter_index, variable_index])
            rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(output_path)


def _write_spine_paths_long(sim: SimulationResult, output_path: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path_index in range(sim.paths.shape[0]):
        for quarter_index in range(sim.paths.shape[1]):
            row: dict[str, Any] = {
                "path_id": path_index,
                "quarter_index": quarter_index + 1,
            }
            for variable_index, variable in enumerate(sim.variable_order):
                row[variable] = float(sim.paths[path_index, quarter_index, variable_index])
            rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(output_path)


def _hard_probabilities(
    classifications: pd.DataFrame,
    scenario_ids: list[str],
) -> dict[str, float]:
    total = max(1, len(classifications))
    counts = classifications["assigned"].value_counts()
    return {
        scenario: float(counts.get(scenario, 0) / total)
        for scenario in scenario_ids
    }


def _soft_probabilities(
    classifications: pd.DataFrame,
    scenario_ids: list[str],
) -> dict[str, float]:
    return {
        scenario: float(classifications[f"soft_{scenario}"].mean())
        for scenario in scenario_ids
    }


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _file_fingerprint(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _json_safe_config(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in config.items():
        if isinstance(value, Path):
            out[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, dict):
            out[key] = {
                str(nested_key): (
                    nested_value
                    if isinstance(nested_value, (str, int, float, bool)) or nested_value is None
                    else str(nested_value)
                )
                for nested_key, nested_value in value.items()
            }
        else:
            out[key] = str(value)
    return out
