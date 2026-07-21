"""Markov financial-stress regime artifact for the BVAR simulator.

This is the Phase 1 regime interface: hard historical labels plus a
state-dependent calm-to-stress transition. Phase 2 can replace the estimation
method with latent-regime inference while keeping this artifact contract stable
for simulation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    BVARFitError,
    PosteriorArtifact,
    artifact_candidate_paths,
    default_bvar_cache_dir,
    load_spine_history_frame,
    posterior_artifact_fingerprint,
    print_archive_resolution_note,
    require_posterior_residuals,
)
from src.agent_system.forecasting.bvar_ensemble.regime_labeling import (
    label_regimes,
    proxy_for_state,
    proxy_scalers,
    proxy_weights_from_config,
)
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry


class RegimeParamsError(RuntimeError):
    """Raised when regime parameters cannot be estimated or loaded."""


@dataclass(frozen=True)
class RegimeArtifact:
    path: Path
    variable_order: list[str]
    residual_quarters: list[str]
    labels: np.ndarray
    proxy: np.ndarray
    proxy_means: dict[str, float]
    proxy_stds: dict[str, float]
    proxy_weights: dict[str, float]
    thresholds: dict[str, float]
    stress_episodes: list[dict[str, str]]
    logistic_intercept: float
    logistic_slope: float
    binned_transition_table: list[dict[str, Any]]
    p_stay: float
    expected_stress_duration: float
    stress_vol_multiplier: np.ndarray
    average_stress_vol_multiplier: float
    calm_correlation: np.ndarray
    stress_correlation: np.ndarray
    empirical_stress_correlation: np.ndarray
    imposed_stress_correlation: np.ndarray
    pre_repair_stress_correlation: np.ndarray
    calm_avg_offdiag_correlation: float
    stress_avg_offdiag_correlation: float
    empirical_stress_avg_offdiag_correlation: float
    stress_avg_offdiag_magnitude: float
    posterior_fingerprint: str
    fit_timestamp: str
    summary: dict[str, Any]

    def p_enter_for_proxy(self, proxy_value: float) -> float:
        return _sigmoid(self.logistic_intercept + self.logistic_slope * float(proxy_value))

    def proxy_for_state(
        self,
        current_state: np.ndarray,
        lag4_state: np.ndarray,
    ) -> float:
        return proxy_for_state(
            current_state,
            lag4_state,
            variable_order=self.variable_order,
            proxy_means=self.proxy_means,
            proxy_stds=self.proxy_stds,
            weights=self.proxy_weights,
        )


def fit_regime_artifact(
    registry: VariableRegistry,
    posterior: PosteriorArtifact,
    config: dict[str, Any],
    *,
    cache_dir: str | Path | None = None,
    bvar_cache_dir: str | Path | None = None,
) -> tuple[RegimeArtifact, Path]:
    residuals, residual_quarters = _require_residuals(posterior)
    history = load_spine_history_frame(
        registry,
        estimation_start=posterior.sample_start,
        min_sample_quarters=posterior.lags + 1,
        cache_dir=cache_dir,
    )
    labels = label_regimes(
        history,
        residual_quarters=residual_quarters,
        config=config,
    )
    if residuals.shape[0] != len(labels.labels):
        raise RegimeParamsError(
            "residual row count does not match regime labels: "
            f"{residuals.shape[0]} vs {len(labels.labels)}"
        )
    intercept, slope, logistic_diagnostics = _fit_entry_logistic(
        labels.proxy,
        labels.labels,
    )
    if slope <= 0:
        raise RegimeParamsError(
            "regime transition proxy has non-positive fitted logistic slope; "
            f"intercept={intercept:.6f}, slope={slope:.6f}. "
            "Do not use a forecast-useless transition predictor."
        )

    p_stay, expected_duration = _stress_persistence(labels.labels)
    calm_mask = labels.labels == 0
    stress_mask = labels.labels == 1
    if int(np.sum(calm_mask)) < 2 or int(np.sum(stress_mask)) < 2:
        raise RegimeParamsError("need at least two calm and two stress residual quarters")

    calm_residuals = residuals[calm_mask]
    stress_residuals = residuals[stress_mask]
    multipliers = _stress_vol_multipliers(
        calm_residuals,
        stress_residuals,
        variable_order=posterior.variable_order,
    )
    calm_corr = _correlation_from_residuals(calm_residuals)
    empirical_stress_corr = _correlation_from_residuals(stress_residuals)
    correlation_build = _build_active_stress_correlation(
        calm_corr,
        empirical_stress_corr,
        variable_order=list(posterior.variable_order),
        config=config,
    )
    stress_corr = correlation_build["stress_correlation"]
    imposed_stress_corr = correlation_build["imposed_correlation"]
    pre_repair_stress_corr = correlation_build["pre_repair_correlation"]
    calm_offdiag = _avg_offdiag_correlation(calm_corr)
    empirical_stress_offdiag = _avg_offdiag_correlation(empirical_stress_corr)
    stress_offdiag = _avg_offdiag_correlation(stress_corr)
    empirical_stress_magnitude = _avg_offdiag_magnitude(empirical_stress_corr)
    stress_magnitude = _avg_offdiag_magnitude(stress_corr)
    avg_multiplier = float(np.mean(multipliers))

    proxy_means, proxy_stds = proxy_scalers(history)
    proxy_weights = proxy_weights_from_config(config)

    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    artifact_path = target_dir / f"regime_{timestamp}.npz"
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    metadata = {
        "variable_order": list(posterior.variable_order),
        "residual_quarters": residual_quarters,
        "posterior_fingerprint": posterior_fp,
        "posterior_artifact": str(posterior.path),
        "fit_timestamp": timestamp,
        "proxy_means": proxy_means,
        "proxy_stds": proxy_stds,
        "proxy_weights": proxy_weights,
        "thresholds": labels.thresholds,
        "stress_episodes": labels.stress_episodes,
        "logistic_intercept": float(intercept),
        "logistic_slope": float(slope),
        "binned_transition_table": _binned_transition_table(labels.proxy, labels.labels),
        "logistic_diagnostics": logistic_diagnostics,
        "p_stay": float(p_stay),
        "expected_stress_duration": float(expected_duration),
        "average_stress_vol_multiplier": float(avg_multiplier),
        "calm_avg_offdiag_correlation": float(calm_offdiag),
        "empirical_stress_avg_offdiag_correlation": float(empirical_stress_offdiag),
        "empirical_stress_avg_offdiag_magnitude": float(empirical_stress_magnitude),
        "stress_avg_offdiag_correlation": float(stress_offdiag),
        "stress_avg_offdiag_magnitude": float(stress_magnitude),
        "crisis_correlation_target": float(correlation_build["target_magnitude"]),
        "stress_correlation_impose_weight": float(correlation_build["blend_weight"]),
        "psd_repair_warn_delta": float(correlation_build["repair_warn_delta"]),
        "pre_repair_stress_avg_offdiag_magnitude": float(
            correlation_build["pre_repair_avg_offdiag_magnitude"]
        ),
        "post_repair_stress_avg_offdiag_magnitude": float(
            correlation_build["post_repair_avg_offdiag_magnitude"]
        ),
        "stress_correlation_psd_repaired": bool(correlation_build["psd_repaired"]),
        "stress_correlation_psd_repair_delta": float(correlation_build["repair_delta"]),
        "stress_correlation_min_eigenvalue_pre_repair": float(
            correlation_build["min_eigenvalue_pre_repair"]
        ),
        "stress_correlation_min_eigenvalue_post_repair": float(
            correlation_build["min_eigenvalue_post_repair"]
        ),
        "stress_correlation_warnings": list(correlation_build["warnings"]),
        "stress_count": int(labels.stress_count),
        "stress_fraction": float(labels.stress_fraction),
    }
    np.savez_compressed(
        artifact_path,
        labels=labels.labels.astype(int),
        proxy=labels.proxy.astype(float),
        stress_vol_multiplier=multipliers.astype(float),
        calm_correlation=calm_corr.astype(float),
        stress_correlation=stress_corr.astype(float),
        empirical_stress_correlation=empirical_stress_corr.astype(float),
        imposed_stress_correlation=imposed_stress_corr.astype(float),
        pre_repair_stress_correlation=pre_repair_stress_corr.astype(float),
        metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
    )
    artifact = load_regime_artifact(artifact_path)
    summary_path = target_dir / f"regime_{timestamp}_summary.json"
    summary = {
        **metadata,
        "regime_artifact": str(artifact_path),
        "stress_vol_multiplier_by_variable": {
            variable: float(multipliers[index])
            for index, variable in enumerate(posterior.variable_order)
        },
        "stress_regime_concentration_effect": {
            "average_stress_vol_multiplier": float(avg_multiplier),
            "avg_offdiag_correlation_delta": float(stress_offdiag - calm_offdiag),
            "empirical_stress_avg_offdiag_correlation": float(empirical_stress_offdiag),
            "post_repair_stress_avg_offdiag_magnitude": float(stress_magnitude),
        },
        "calm_correlation": _matrix_to_nested(calm_corr, posterior.variable_order),
        "empirical_stress_correlation": _matrix_to_nested(
            empirical_stress_corr,
            posterior.variable_order,
        ),
        "imposed_stress_correlation": _matrix_to_nested(
            imposed_stress_corr,
            posterior.variable_order,
        ),
        "pre_repair_stress_correlation": _matrix_to_nested(
            pre_repair_stress_corr,
            posterior.variable_order,
        ),
        "stress_correlation": _matrix_to_nested(stress_corr, posterior.variable_order),
        "notes": [
            "Phase 1 regime estimation uses hard labels plus a lagged proxy logistic transition.",
            "Stress-regime correlation is imposed from calm signs plus documented economic fallback signs, then PSD-repaired before simulation.",
            "Simulation consumes only the stable artifact interface so Phase 2 latent-regime inference can swap in later.",
            *correlation_build["warnings"],
            *(
                [
                    "WARNING: count-estimated stress persistence implies roughly one-quarter stress duration; this is a method limitation, not a fitted floor."
                ]
                if np.isfinite(expected_duration) and expected_duration <= 1.25
                else []
            ),
        ],
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact, summary_path


def load_regime_artifact(path: str | Path) -> RegimeArtifact:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise RegimeParamsError(f"regime artifact not found: {artifact_path}")
    try:
        data = np.load(artifact_path, allow_pickle=False)
        metadata = json.loads(str(data["metadata_json"]))
    except Exception as exc:
        raise RegimeParamsError(f"could not load regime artifact {artifact_path}: {exc}") from exc

    variable_order = list(metadata["variable_order"])
    residual_quarters = [str(value) for value in metadata["residual_quarters"]]
    labels = np.asarray(data["labels"], dtype=int)
    proxy = np.asarray(data["proxy"], dtype=float)
    stress_vol_multiplier = np.asarray(data["stress_vol_multiplier"], dtype=float)
    calm_correlation = np.asarray(data["calm_correlation"], dtype=float)
    stress_correlation = np.asarray(data["stress_correlation"], dtype=float)
    empirical_stress_correlation = np.asarray(
        data["empirical_stress_correlation"]
        if "empirical_stress_correlation" in data.files
        else data["stress_correlation"],
        dtype=float,
    )
    imposed_stress_correlation = np.asarray(
        data["imposed_stress_correlation"]
        if "imposed_stress_correlation" in data.files
        else data["stress_correlation"],
        dtype=float,
    )
    pre_repair_stress_correlation = np.asarray(
        data["pre_repair_stress_correlation"]
        if "pre_repair_stress_correlation" in data.files
        else data["stress_correlation"],
        dtype=float,
    )
    n_obs = len(residual_quarters)
    n_vars = len(variable_order)
    if labels.shape != (n_obs,):
        raise RegimeParamsError(
            f"regime labels must have shape {(n_obs,)} aligned to residual_quarters; got {labels.shape}"
        )
    if proxy.shape != (n_obs,):
        raise RegimeParamsError(
            f"regime proxy must have shape {(n_obs,)} aligned to residual_quarters; got {proxy.shape}"
        )
    if stress_vol_multiplier.shape != (n_vars,):
        raise RegimeParamsError(
            f"stress_vol_multiplier must have shape {(n_vars,)}; got {stress_vol_multiplier.shape}"
        )
    for label, matrix in [
        ("calm_correlation", calm_correlation),
        ("stress_correlation", stress_correlation),
        ("empirical_stress_correlation", empirical_stress_correlation),
        ("imposed_stress_correlation", imposed_stress_correlation),
        ("pre_repair_stress_correlation", pre_repair_stress_correlation),
    ]:
        if matrix.shape != (n_vars, n_vars):
            raise RegimeParamsError(f"{label} must have shape {(n_vars, n_vars)}; got {matrix.shape}")
    return RegimeArtifact(
        path=artifact_path,
        variable_order=variable_order,
        residual_quarters=residual_quarters,
        labels=labels,
        proxy=proxy,
        proxy_means={k: float(v) for k, v in metadata["proxy_means"].items()},
        proxy_stds={k: float(v) for k, v in metadata["proxy_stds"].items()},
        proxy_weights={k: float(v) for k, v in metadata["proxy_weights"].items()},
        thresholds={k: float(v) for k, v in metadata["thresholds"].items()},
        stress_episodes=list(metadata.get("stress_episodes", [])),
        logistic_intercept=float(metadata["logistic_intercept"]),
        logistic_slope=float(metadata["logistic_slope"]),
        binned_transition_table=list(metadata.get("binned_transition_table", [])),
        p_stay=float(metadata["p_stay"]),
        expected_stress_duration=float(metadata["expected_stress_duration"]),
        stress_vol_multiplier=stress_vol_multiplier,
        average_stress_vol_multiplier=float(
            metadata.get("average_stress_vol_multiplier", np.mean(stress_vol_multiplier))
        ),
        calm_correlation=calm_correlation,
        stress_correlation=stress_correlation,
        empirical_stress_correlation=empirical_stress_correlation,
        imposed_stress_correlation=imposed_stress_correlation,
        pre_repair_stress_correlation=pre_repair_stress_correlation,
        calm_avg_offdiag_correlation=float(metadata["calm_avg_offdiag_correlation"]),
        stress_avg_offdiag_correlation=float(metadata["stress_avg_offdiag_correlation"]),
        empirical_stress_avg_offdiag_correlation=float(
            metadata.get(
                "empirical_stress_avg_offdiag_correlation",
                _avg_offdiag_correlation(empirical_stress_correlation),
            )
        ),
        stress_avg_offdiag_magnitude=float(
            metadata.get(
                "stress_avg_offdiag_magnitude",
                _avg_offdiag_magnitude(stress_correlation),
            )
        ),
        posterior_fingerprint=str(metadata["posterior_fingerprint"]),
        fit_timestamp=str(metadata["fit_timestamp"]),
        summary=metadata,
    )


def newest_regime_artifact(
    posterior: PosteriorArtifact,
    *,
    bvar_cache_dir: str | Path | None = None,
) -> RegimeArtifact:
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    if not target_dir.is_dir():
        raise RegimeParamsError(f"BVAR cache directory not found: {target_dir}; run fit-regime first.")
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    for path in artifact_candidate_paths("regime_*.npz", bvar_cache_dir=bvar_cache_dir):
        artifact = load_regime_artifact(path)
        if artifact.posterior_fingerprint == posterior_fp:
            print_archive_resolution_note("regime", artifact.path, bvar_cache_dir=bvar_cache_dir)
            return artifact
    raise RegimeParamsError(
        f"No regime_*.npz artifact in {target_dir} or {target_dir / 'archive'} "
        f"matches posterior fingerprint {posterior_fp}; run fit-regime for "
        f"{posterior.path} or pass --regime."
    )


def validate_regime_matches_posterior(
    artifact: RegimeArtifact,
    posterior: PosteriorArtifact,
) -> None:
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    if artifact.posterior_fingerprint != posterior_fp:
        raise RegimeParamsError(
            "regime artifact posterior fingerprint mismatch: "
            f"{artifact.posterior_fingerprint} vs active posterior {posterior_fp}. "
            "Run fit-regime against the active posterior."
        )
    if artifact.variable_order != list(posterior.variable_order):
        raise RegimeParamsError(
            "regime artifact variable_order does not match posterior variable_order: "
            f"{artifact.variable_order} vs {posterior.variable_order}"
        )


def regime_metadata_for_forecast(artifact: RegimeArtifact | None) -> dict[str, Any] | None:
    if artifact is None:
        return None
    return {
        "regime_artifact": str(artifact.path),
        "posterior_fingerprint": artifact.posterior_fingerprint,
        "fit_timestamp": artifact.fit_timestamp,
        "logistic_intercept": artifact.logistic_intercept,
        "logistic_slope": artifact.logistic_slope,
        "p_stay": artifact.p_stay,
        "expected_stress_duration": artifact.expected_stress_duration,
        "thresholds": artifact.thresholds,
        "stress_count": int(np.sum(artifact.labels == 1)),
        "stress_fraction": float(np.mean(artifact.labels == 1)),
        "stress_episodes": artifact.stress_episodes,
        "binned_transition_table": artifact.binned_transition_table,
        "calm_avg_offdiag_correlation": artifact.calm_avg_offdiag_correlation,
        "empirical_stress_avg_offdiag_correlation": artifact.empirical_stress_avg_offdiag_correlation,
        "stress_avg_offdiag_correlation": artifact.stress_avg_offdiag_correlation,
        "stress_avg_offdiag_magnitude": artifact.stress_avg_offdiag_magnitude,
        "crisis_correlation_target": artifact.summary.get("crisis_correlation_target"),
        "stress_correlation_impose_weight": artifact.summary.get(
            "stress_correlation_impose_weight"
        ),
        "stress_correlation_psd_repaired": artifact.summary.get(
            "stress_correlation_psd_repaired"
        ),
        "stress_correlation_psd_repair_delta": artifact.summary.get(
            "stress_correlation_psd_repair_delta"
        ),
        "average_stress_vol_multiplier": artifact.average_stress_vol_multiplier,
        "stress_vol_multiplier_by_variable": {
            variable: float(artifact.stress_vol_multiplier[index])
            for index, variable in enumerate(artifact.variable_order)
        },
    }


def label_for_anchor(artifact: RegimeArtifact, anchor_quarter: str) -> int:
    index = _anchor_index(artifact, anchor_quarter)
    return int(artifact.labels[index])


def proxy_for_anchor(artifact: RegimeArtifact, anchor_quarter: str) -> float:
    index = _anchor_index(artifact, anchor_quarter)
    return float(artifact.proxy[index])


def p_enter_for_anchor(artifact: RegimeArtifact, anchor_quarter: str) -> float:
    return artifact.p_enter_for_proxy(proxy_for_anchor(artifact, anchor_quarter))


def _anchor_index(artifact: RegimeArtifact, anchor_quarter: str) -> int:
    quarter_to_index = {
        quarter: index
        for index, quarter in enumerate(artifact.residual_quarters)
    }
    if anchor_quarter in quarter_to_index:
        return quarter_to_index[anchor_quarter]
    raise RegimeParamsError(
        f"regime artifact has no state for anchor {anchor_quarter}. "
        f"Available residual range: {artifact.residual_quarters[0] if artifact.residual_quarters else 'n/a'}.."
        f"{artifact.residual_quarters[-1] if artifact.residual_quarters else 'n/a'}"
    )


def _fit_entry_logistic(
    proxy: np.ndarray,
    labels: np.ndarray,
) -> tuple[float, float, dict[str, Any]]:
    x_values: list[float] = []
    y_values: list[float] = []
    for index in range(len(labels) - 1):
        if int(labels[index]) == 0:
            x_values.append(float(proxy[index]))
            y_values.append(1.0 if int(labels[index + 1]) == 1 else 0.0)
    if len(x_values) < 10:
        raise RegimeParamsError(
            f"not enough calm-quarter transitions to fit entry logistic: {len(x_values)}"
        )
    x = np.column_stack([np.ones(len(x_values)), np.asarray(x_values, dtype=float)])
    y = np.asarray(y_values, dtype=float)
    if float(np.sum(y)) < 1:
        raise RegimeParamsError("no calm-to-stress transitions in hard labels")

    beta = np.asarray([
        np.log((np.mean(y) + 1e-6) / (1.0 - np.mean(y) + 1e-6)),
        0.1,
    ], dtype=float)
    converged = False
    ridge = 1e-6
    last_ll = _logistic_log_likelihood(x, y, beta)
    for iteration in range(100):
        p = _sigmoid_array(x @ beta)
        grad = x.T @ (y - p)
        weights = np.maximum(p * (1.0 - p), 1e-8)
        hessian = -(x.T * weights) @ x - np.eye(2) * ridge
        try:
            step = np.linalg.solve(hessian, grad)
        except np.linalg.LinAlgError as exc:
            raise RegimeParamsError("entry logistic Hessian is singular") from exc
        step_scale = 1.0
        accepted = False
        for _ in range(20):
            candidate = beta - step_scale * step
            candidate_ll = _logistic_log_likelihood(x, y, candidate)
            if candidate_ll >= last_ll - 1e-10:
                beta = candidate
                last_ll = candidate_ll
                accepted = True
                break
            step_scale *= 0.5
        if not accepted:
            raise RegimeParamsError("entry logistic Newton updates failed line search")
        if float(np.max(np.abs(step_scale * step))) < 1e-7:
            converged = True
            break
    if not converged:
        raise RegimeParamsError(
            f"entry logistic did not converge; intercept={beta[0]:.6f}, slope={beta[1]:.6f}"
        )
    return float(beta[0]), float(beta[1]), {
        "n_calm_transitions": int(len(y)),
        "transition_count": int(np.sum(y)),
        "transition_rate": float(np.mean(y)),
        "iterations": int(iteration + 1),
        "log_likelihood": float(last_ll),
    }


def _binned_transition_table(
    proxy: np.ndarray,
    labels: np.ndarray,
) -> list[dict[str, Any]]:
    x_values: list[float] = []
    y_values: list[int] = []
    for index in range(len(labels) - 1):
        if int(labels[index]) == 0:
            x_values.append(float(proxy[index]))
            y_values.append(1 if int(labels[index + 1]) == 1 else 0)
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=int)
    if x.size == 0:
        return []
    quantiles = np.percentile(x, [0, 25, 50, 75, 100])
    out: list[dict[str, Any]] = []
    for bucket in range(4):
        lo = float(quantiles[bucket])
        hi = float(quantiles[bucket + 1])
        if bucket == 3:
            mask = (x >= lo) & (x <= hi)
        else:
            mask = (x >= lo) & (x < hi)
        count = int(np.sum(mask))
        transitions = int(np.sum(y[mask])) if count else 0
        out.append(
            {
                "quartile": bucket + 1,
                "proxy_min": lo,
                "proxy_max": hi,
                "observations": count,
                "transitions": transitions,
                "transition_rate": float(transitions / count) if count else None,
            }
        )
    return out


def _build_active_stress_correlation(
    calm_corr: np.ndarray,
    empirical_stress_corr: np.ndarray,
    *,
    variable_order: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    target_magnitude = float(config.get("crisis_correlation_target", 0.8))
    blend_weight = float(config.get("stress_correlation_impose_weight", 1.0))
    repair_warn_delta = float(config.get("psd_repair_warn_delta", 0.1))
    if not 0.0 < target_magnitude < 1.0:
        raise RegimeParamsError("crisis_correlation_target must be between 0 and 1")
    if not 0.0 <= blend_weight <= 1.0:
        raise RegimeParamsError("stress_correlation_impose_weight must be between 0 and 1")
    if repair_warn_delta < 0.0:
        raise RegimeParamsError("psd_repair_warn_delta must be non-negative")

    imposed = _imposed_stress_correlation(
        calm_corr,
        variable_order=variable_order,
        target_magnitude=target_magnitude,
    )
    pre_repair = (1.0 - blend_weight) * empirical_stress_corr + blend_weight * imposed
    pre_repair = _normalize_correlation_shell(pre_repair)
    pre_repair_magnitude = _avg_offdiag_magnitude(pre_repair)
    min_eigen_pre = _min_eigenvalue(pre_repair)
    psd_repaired = not _is_valid_correlation(pre_repair)
    if psd_repaired:
        stress_corr = _nearest_psd_correlation(pre_repair)
    else:
        stress_corr = pre_repair.copy()
    stress_corr = _normalize_correlation_shell(stress_corr)
    min_eigen_post = _min_eigenvalue(stress_corr)
    if not _is_valid_correlation(stress_corr):
        raise RegimeParamsError(
            "imposed stress correlation could not be repaired to a valid PSD "
            f"correlation matrix; min_eigen_post={min_eigen_post:.6g}"
        )
    post_magnitude = _avg_offdiag_magnitude(stress_corr)
    repair_delta = abs(post_magnitude - pre_repair_magnitude)
    warnings: list[str] = []
    if psd_repaired and repair_delta > repair_warn_delta:
        warnings.append(
            "WARNING: PSD repair changed stress correlation average off-diagonal "
            f"magnitude by {repair_delta:.3f}, above psd_repair_warn_delta="
            f"{repair_warn_delta:.3f}; crisis_correlation_target={target_magnitude:.3f} "
            "may be too aggressive for the variable set."
        )
    return {
        "stress_correlation": stress_corr,
        "imposed_correlation": imposed,
        "pre_repair_correlation": pre_repair,
        "target_magnitude": target_magnitude,
        "blend_weight": blend_weight,
        "repair_warn_delta": repair_warn_delta,
        "pre_repair_avg_offdiag_magnitude": pre_repair_magnitude,
        "post_repair_avg_offdiag_magnitude": post_magnitude,
        "psd_repaired": psd_repaired,
        "repair_delta": repair_delta,
        "min_eigenvalue_pre_repair": min_eigen_pre,
        "min_eigenvalue_post_repair": min_eigen_post,
        "warnings": warnings,
    }


def _imposed_stress_correlation(
    calm_corr: np.ndarray,
    *,
    variable_order: list[str],
    target_magnitude: float,
) -> np.ndarray:
    n_vars = len(variable_order)
    imposed = np.eye(n_vars, dtype=float)
    for left_index in range(n_vars):
        for right_index in range(left_index + 1, n_vars):
            calm_value = float(calm_corr[left_index, right_index])
            sign = _stress_correlation_sign(
                variable_order[left_index],
                variable_order[right_index],
                calm_value,
            )
            if sign == 0:
                value = calm_value
            else:
                value = float(sign) * target_magnitude
            imposed[left_index, right_index] = value
            imposed[right_index, left_index] = value
    return _normalize_correlation_shell(imposed)


def _stress_correlation_sign(left: str, right: str, calm_value: float) -> int:
    prior_sign = _ECONOMIC_STRESS_SIGN_PRIOR.get(tuple(sorted((left, right))))
    if prior_sign is not None:
        calm_sign = 1 if calm_value > 0 else -1 if calm_value < 0 else 0
        if abs(calm_value) < 0.02 or calm_sign != prior_sign:
            return prior_sign
    if abs(calm_value) >= 0.02:
        return 1 if calm_value > 0 else -1
    return prior_sign or 0


# Economic sign prior for known spine-variable pairs. It is used when the calm
# residual correlation is near zero, and also when a calm sign conflicts with
# recessionary crisis economics for a documented pair. Pairs outside this map
# preserve the calm sign, or remain near zero if calm has no clear sign.
_ECONOMIC_STRESS_SIGN_PRIOR: dict[tuple[str, str], int] = {
    ("activity", "core_pce"): 1,
    ("activity", "credit_spread"): -1,
    ("activity", "fed_funds"): 1,
    ("activity", "lur"): -1,
    ("activity", "nfci"): -1,
    ("activity", "ten_year"): 1,
    ("core_pce", "credit_spread"): -1,
    ("core_pce", "fed_funds"): 1,
    ("core_pce", "lur"): -1,
    ("core_pce", "nfci"): -1,
    ("core_pce", "ten_year"): 1,
    ("credit_spread", "fed_funds"): -1,
    ("credit_spread", "lur"): 1,
    ("credit_spread", "nfci"): 1,
    ("credit_spread", "ten_year"): -1,
    ("fed_funds", "lur"): -1,
    ("fed_funds", "nfci"): -1,
    ("fed_funds", "ten_year"): 1,
    ("lur", "nfci"): 1,
    ("lur", "ten_year"): -1,
    ("nfci", "ten_year"): -1,
}


def _stress_persistence(labels: np.ndarray) -> tuple[float, float]:
    prev_stress = labels[:-1] == 1
    denominator = int(np.sum(prev_stress))
    if denominator == 0:
        raise RegimeParamsError("cannot estimate p_stay with no stress quarters before final observation")
    stays = int(np.sum((labels[:-1] == 1) & (labels[1:] == 1)))
    p_stay = float(stays / denominator)
    expected = float("inf") if p_stay >= 1.0 else float(1.0 / (1.0 - p_stay))
    return p_stay, expected


def _stress_vol_multipliers(
    calm_residuals: np.ndarray,
    stress_residuals: np.ndarray,
    *,
    variable_order: list[str],
) -> np.ndarray:
    calm_std = np.std(calm_residuals, axis=0, ddof=1)
    stress_std = np.std(stress_residuals, axis=0, ddof=1)
    if np.any(~np.isfinite(calm_std)) or np.any(calm_std <= 0):
        bad = [
            variable
            for variable, value in zip(variable_order, calm_std)
            if (not np.isfinite(value)) or value <= 0
        ]
        raise RegimeParamsError(f"non-positive calm residual std for variables: {bad}")
    multipliers = stress_std / calm_std
    multipliers = np.nan_to_num(multipliers, nan=1.0, posinf=1.0, neginf=1.0)
    return np.maximum(multipliers, 1e-6)


def _correlation_from_residuals(residuals: np.ndarray) -> np.ndarray:
    corr = np.corrcoef(residuals, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    return _make_positive_definite_correlation(corr)


def _normalize_correlation_shell(matrix: np.ndarray) -> np.ndarray:
    candidate = np.asarray(matrix, dtype=float)
    if candidate.ndim != 2 or candidate.shape[0] != candidate.shape[1]:
        raise RegimeParamsError(f"correlation matrix must be square; got {candidate.shape}")
    candidate = np.nan_to_num(candidate, nan=0.0, posinf=0.0, neginf=0.0)
    candidate = (candidate + candidate.T) / 2.0
    np.fill_diagonal(candidate, 1.0)
    return candidate


def _nearest_psd_correlation(matrix: np.ndarray) -> np.ndarray:
    sym = _normalize_correlation_shell(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(sym)
    clipped = np.maximum(eigenvalues, 1e-8)
    repaired = (eigenvectors * clipped) @ eigenvectors.T
    repaired = (repaired + repaired.T) / 2.0
    diagonal = np.sqrt(np.maximum(np.diag(repaired), 1e-12))
    repaired = repaired / np.outer(diagonal, diagonal)
    return _normalize_correlation_shell(repaired)


def _is_valid_correlation(matrix: np.ndarray, *, epsilon: float = 1e-8) -> bool:
    candidate = _normalize_correlation_shell(matrix)
    if not np.isfinite(candidate).all():
        return False
    if not np.allclose(np.diag(candidate), 1.0, atol=1e-8):
        return False
    offdiag = candidate[~np.eye(candidate.shape[0], dtype=bool)]
    if np.any(offdiag < -1.0 - epsilon) or np.any(offdiag > 1.0 + epsilon):
        return False
    return _min_eigenvalue(candidate) >= -epsilon


def _min_eigenvalue(matrix: np.ndarray) -> float:
    candidate = _normalize_correlation_shell(matrix)
    return float(np.min(np.linalg.eigvalsh(candidate)))


def _make_positive_definite_correlation(matrix: np.ndarray) -> np.ndarray:
    sym = (matrix + matrix.T) / 2.0
    jitter = 1e-10
    for _ in range(8):
        candidate = sym + np.eye(sym.shape[0]) * jitter
        try:
            np.linalg.cholesky(candidate)
            diag = np.sqrt(np.maximum(np.diag(candidate), 1e-12))
            return candidate / np.outer(diag, diag)
        except np.linalg.LinAlgError:
            jitter *= 10
    candidate = sym + np.eye(sym.shape[0]) * jitter
    diag = np.sqrt(np.maximum(np.diag(candidate), 1e-12))
    return candidate / np.outer(diag, diag)


def _avg_offdiag_correlation(matrix: np.ndarray) -> float:
    if matrix.shape[0] < 2:
        return 0.0
    mask = ~np.eye(matrix.shape[0], dtype=bool)
    return float(np.mean(matrix[mask]))


def _avg_offdiag_magnitude(matrix: np.ndarray) -> float:
    if matrix.shape[0] < 2:
        return 0.0
    mask = ~np.eye(matrix.shape[0], dtype=bool)
    return float(np.mean(np.abs(matrix[mask])))


def _matrix_to_nested(matrix: np.ndarray, variable_order: list[str]) -> dict[str, dict[str, float]]:
    return {
        left: {
            right: float(matrix[left_index, right_index])
            for right_index, right in enumerate(variable_order)
        }
        for left_index, left in enumerate(variable_order)
    }


def _logistic_log_likelihood(
    x: np.ndarray,
    y: np.ndarray,
    beta: np.ndarray,
) -> float:
    eta = np.clip(x @ beta, -40.0, 40.0)
    return float(np.sum(y * eta - np.logaddexp(0.0, eta)))


def _sigmoid(value: float) -> float:
    clipped = float(np.clip(value, -40.0, 40.0))
    return float(1.0 / (1.0 + np.exp(-clipped)))


def _sigmoid_array(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _require_residuals(posterior: PosteriorArtifact) -> tuple[np.ndarray, list[str]]:
    try:
        return require_posterior_residuals(posterior)
    except BVARFitError as exc:
        raise RegimeParamsError(str(exc)) from exc


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
