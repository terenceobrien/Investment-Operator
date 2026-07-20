"""Univariate GARCH(1,1) volatility artifacts for BVAR residual shocks."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import lgamma, log, pi
from pathlib import Path
from typing import Any

import numpy as np

from src.agent_system.forecasting.bvar_ensemble.estimation import (
    BVARFitError,
    PosteriorArtifact,
    default_bvar_cache_dir,
    posterior_artifact_fingerprint,
    require_posterior_residuals,
)


class GarchError(RuntimeError):
    """Raised when GARCH fitting/loading cannot proceed."""


@dataclass(frozen=True)
class GarchArtifact:
    path: Path
    variable_order: list[str]
    omega: np.ndarray
    alpha: np.ndarray
    beta: np.ndarray
    residual_correlation: np.ndarray
    terminal_conditional_volatility: np.ndarray
    conditional_volatility: np.ndarray
    next_conditional_volatility: np.ndarray
    residual_quarters: list[str]
    garch_dist: str
    garch_t_dof: int
    posterior_fingerprint: str
    fit_timestamp: str
    warnings: list[str]
    fallback_variables: list[str]
    persistence_warning_variables: list[str]

    @property
    def persistence(self) -> np.ndarray:
        return self.alpha + self.beta

    @property
    def unconditional_volatility(self) -> np.ndarray:
        denom = np.maximum(1.0 - self.persistence, 1e-12)
        return np.sqrt(self.omega / denom)


def fit_garch_artifact(
    posterior: PosteriorArtifact,
    config: dict[str, Any],
    *,
    bvar_cache_dir: str | Path | None = None,
) -> tuple[GarchArtifact, Path]:
    residuals, residual_quarters = _require_residuals(posterior)
    variable_order = list(posterior.variable_order)
    dist = str(config.get("garch_dist", "student_t"))
    if dist not in {"student_t", "gaussian"}:
        raise GarchError("garch_dist must be student_t or gaussian")
    t_dof = int(config.get("garch_t_dof", 6))
    if t_dof <= 2:
        raise GarchError("garch_t_dof must be greater than 2")
    max_iter = int(config.get("garch_max_iter", 500))
    if max_iter < 1:
        raise GarchError("garch_max_iter must be positive")
    persistence_warn = float(config.get("garch_persistence_warn", 0.99))

    n_obs, n_vars = residuals.shape
    omega = np.zeros(n_vars, dtype=float)
    alpha = np.zeros(n_vars, dtype=float)
    beta = np.zeros(n_vars, dtype=float)
    conditional_vol = np.zeros((n_obs, n_vars), dtype=float)
    next_vol = np.zeros((n_obs, n_vars), dtype=float)
    standardized = np.zeros((n_obs, n_vars), dtype=float)
    warnings: list[str] = []
    fallback_variables: list[str] = []
    optimizer_diagnostics: dict[str, Any] = {}

    for index, variable in enumerate(variable_order):
        series = residuals[:, index]
        result = _fit_one_series(
            series,
            dist=dist,
            t_dof=t_dof,
            max_iter=max_iter,
        )
        if result["fallback"]:
            fallback_variables.append(variable)
            warnings.append(
                f"WARNING: GARCH fit for {variable} fell back to constant volatility: "
                f"{result['warning']}"
            )
        optimizer_diagnostics[variable] = result.get("optimizer_diagnostics", {})
        omega[index] = float(result["omega"])
        alpha[index] = float(result["alpha"])
        beta[index] = float(result["beta"])
        conditional_vol[:, index] = result["conditional_volatility"]
        next_vol[:, index] = result["next_conditional_volatility"]
        standardized[:, index] = series / np.maximum(conditional_vol[:, index], 1e-12)

    residual_correlation = _correlation_from_standardized_residuals(standardized)
    persistence = alpha + beta
    persistence_warning_variables = [
        variable
        for variable, value in zip(variable_order, persistence)
        if float(value) > persistence_warn
    ]
    for variable in persistence_warning_variables:
        warnings.append(
            f"WARNING: GARCH persistence for {variable} exceeds "
            f"garch_persistence_warn={persistence_warn:.3f}."
        )

    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    artifact_path = target_dir / f"garch_{timestamp}.npz"
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    metadata = {
        "variable_order": variable_order,
        "residual_quarters": residual_quarters,
        "garch_dist": dist,
        "garch_t_dof": int(t_dof),
        "posterior_fingerprint": posterior_fp,
        "posterior_artifact": str(posterior.path),
        "fit_timestamp": timestamp,
        "warnings": warnings,
        "fallback_variables": fallback_variables,
        "persistence_warning_variables": persistence_warning_variables,
        "optimizer_diagnostics": optimizer_diagnostics,
    }
    np.savez_compressed(
        artifact_path,
        omega=omega,
        alpha=alpha,
        beta=beta,
        residual_correlation=residual_correlation,
        terminal_conditional_volatility=conditional_vol[-1],
        conditional_volatility=conditional_vol,
        next_conditional_volatility=next_vol,
        metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
    )
    artifact = load_garch_artifact(artifact_path)
    summary_path = target_dir / f"garch_{timestamp}_summary.json"
    summary = {
        **metadata,
        "garch_artifact": str(artifact_path),
        "persistence_warn_threshold": persistence_warn,
        "variables": {
            variable: {
                "omega": float(omega[index]),
                "alpha": float(alpha[index]),
                "beta": float(beta[index]),
                "persistence": float(persistence[index]),
                "unconditional_vol": float(artifact.unconditional_volatility[index]),
                "terminal_conditional_vol": float(conditional_vol[-1, index]),
                "terminal_vs_unconditional_vol_ratio": float(
                    conditional_vol[-1, index] / max(artifact.unconditional_volatility[index], 1e-12)
                ),
                "fallback_constant": variable in fallback_variables,
                "persistence_warning": variable in persistence_warning_variables,
                "optimizer_diagnostics": optimizer_diagnostics.get(variable, {}),
            }
            for index, variable in enumerate(variable_order)
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact, summary_path


def load_garch_artifact(path: str | Path) -> GarchArtifact:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise GarchError(f"GARCH artifact not found: {artifact_path}")
    try:
        data = np.load(artifact_path, allow_pickle=False)
        metadata = json.loads(str(data["metadata_json"]))
    except Exception as exc:
        raise GarchError(f"could not load GARCH artifact {artifact_path}: {exc}") from exc
    variable_order = list(metadata["variable_order"])
    residual_quarters = [str(value) for value in metadata["residual_quarters"]]
    conditional_volatility = np.asarray(data["conditional_volatility"], dtype=float)
    next_conditional_volatility = np.asarray(
        data["next_conditional_volatility"],
        dtype=float,
    )
    _validate_volatility_series_shape(
        conditional_volatility,
        residual_quarters=residual_quarters,
        variable_order=variable_order,
        label="conditional_volatility",
    )
    _validate_volatility_series_shape(
        next_conditional_volatility,
        residual_quarters=residual_quarters,
        variable_order=variable_order,
        label="next_conditional_volatility",
    )
    return GarchArtifact(
        path=artifact_path,
        variable_order=variable_order,
        omega=np.asarray(data["omega"], dtype=float),
        alpha=np.asarray(data["alpha"], dtype=float),
        beta=np.asarray(data["beta"], dtype=float),
        residual_correlation=np.asarray(data["residual_correlation"], dtype=float),
        terminal_conditional_volatility=np.asarray(
            data["terminal_conditional_volatility"],
            dtype=float,
        ),
        conditional_volatility=conditional_volatility,
        next_conditional_volatility=next_conditional_volatility,
        residual_quarters=residual_quarters,
        garch_dist=str(metadata["garch_dist"]),
        garch_t_dof=int(metadata["garch_t_dof"]),
        posterior_fingerprint=str(metadata["posterior_fingerprint"]),
        fit_timestamp=str(metadata["fit_timestamp"]),
        warnings=list(metadata.get("warnings", [])),
        fallback_variables=list(metadata.get("fallback_variables", [])),
        persistence_warning_variables=list(
            metadata.get("persistence_warning_variables", [])
        ),
    )


def newest_garch_artifact(
    posterior: PosteriorArtifact,
    *,
    bvar_cache_dir: str | Path | None = None,
) -> GarchArtifact:
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    if not target_dir.is_dir():
        raise GarchError(f"BVAR cache directory not found: {target_dir}; run fit-garch first.")
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    matches: list[GarchArtifact] = []
    for path in sorted(target_dir.glob("garch_*.npz"), key=lambda item: item.stat().st_mtime, reverse=True):
        artifact = load_garch_artifact(path)
        if artifact.posterior_fingerprint == posterior_fp:
            matches.append(artifact)
    if not matches:
        raise GarchError(
            f"No garch_*.npz artifact in {target_dir} matches posterior fingerprint "
            f"{posterior_fp}; run fit-garch for {posterior.path}."
        )
    return matches[0]


def validate_garch_matches_posterior(
    artifact: GarchArtifact,
    posterior: PosteriorArtifact,
) -> None:
    posterior_fp = posterior_artifact_fingerprint(posterior.path)
    if artifact.posterior_fingerprint != posterior_fp:
        raise GarchError(
            "GARCH artifact posterior fingerprint mismatch: "
            f"{artifact.posterior_fingerprint} vs active posterior {posterior_fp}. "
            "Run fit-garch against the active posterior."
        )
    if artifact.variable_order != list(posterior.variable_order):
        raise GarchError(
            "GARCH artifact variable_order does not match posterior variable_order: "
            f"{artifact.variable_order} vs {posterior.variable_order}"
        )


def initial_volatility_for_anchor(
    artifact: GarchArtifact,
    anchor_quarter: str,
) -> np.ndarray:
    index = _anchor_index(artifact, anchor_quarter)
    return artifact.conditional_volatility[index].astype(float).copy()


def _anchor_index(artifact: GarchArtifact, anchor_quarter: str) -> int:
    quarter_to_index = {
        quarter: index
        for index, quarter in enumerate(artifact.residual_quarters)
    }
    if anchor_quarter in quarter_to_index:
        return quarter_to_index[anchor_quarter]
    raise GarchError(
        f"GARCH artifact has no conditional volatility state for anchor {anchor_quarter}. "
        f"Available residual range: {artifact.residual_quarters[0] if artifact.residual_quarters else 'n/a'}.."
        f"{artifact.residual_quarters[-1] if artifact.residual_quarters else 'n/a'}"
    )


def initial_volatility_by_variable(
    artifact: GarchArtifact,
    anchor_quarter: str,
) -> dict[str, float]:
    values = initial_volatility_for_anchor(artifact, anchor_quarter)
    return {
        variable: float(values[index])
    for index, variable in enumerate(artifact.variable_order)
    }


def _validate_volatility_series_shape(
    values: np.ndarray,
    *,
    residual_quarters: list[str],
    variable_order: list[str],
    label: str,
) -> None:
    expected = (len(residual_quarters), len(variable_order))
    if values.shape != expected:
        raise GarchError(
            f"GARCH artifact {label} must have shape {expected} aligned to "
            f"residual_quarters x variable_order; got {values.shape}"
        )


def garch_metadata_for_forecast(artifact: GarchArtifact) -> dict[str, Any]:
    persistence = artifact.persistence
    unconditional = artifact.unconditional_volatility
    terminal = artifact.terminal_conditional_volatility
    return {
        "garch_artifact": str(artifact.path),
        "garch_dist": artifact.garch_dist,
        "garch_t_dof": artifact.garch_t_dof,
        "posterior_fingerprint": artifact.posterior_fingerprint,
        "fit_timestamp": artifact.fit_timestamp,
        "warnings": list(artifact.warnings),
        "fallback_variables": list(artifact.fallback_variables),
        "persistence_warning_variables": list(artifact.persistence_warning_variables),
        "variables": {
            variable: {
                "omega": float(artifact.omega[index]),
                "alpha": float(artifact.alpha[index]),
                "beta": float(artifact.beta[index]),
                "persistence": float(persistence[index]),
                "unconditional_vol": float(unconditional[index]),
                "terminal_conditional_vol": float(terminal[index]),
                "terminal_vs_unconditional_vol_ratio": float(
                    terminal[index] / max(unconditional[index], 1e-12)
                ),
                "fallback_constant": variable in artifact.fallback_variables,
            }
            for index, variable in enumerate(artifact.variable_order)
        },
    }


def _require_residuals(posterior: PosteriorArtifact) -> tuple[np.ndarray, list[str]]:
    try:
        return require_posterior_residuals(posterior)
    except BVARFitError as exc:
        raise GarchError(str(exc)) from exc


def _fit_one_series(
    eps: np.ndarray,
    *,
    dist: str,
    t_dof: int,
    max_iter: int,
) -> dict[str, Any]:
    clean = np.asarray(eps, dtype=float)
    if clean.ndim != 1 or clean.size < 20:
        return _constant_result(clean, "not enough residual observations")
    sample_var = float(np.var(clean, ddof=1))
    if sample_var <= 0 or not np.isfinite(sample_var):
        return _constant_result(clean, "non-positive residual variance")

    def objective(raw: np.ndarray) -> float:
        params = _unpack_params(raw)
        return _negative_log_likelihood(
            clean,
            omega=params[0],
            alpha=params[1],
            beta=params[2],
            dist=dist,
            t_dof=t_dof,
        )

    candidates: list[dict[str, Any]] = []
    for initial_omega, initial_alpha, initial_beta in _initial_parameter_guesses(sample_var):
        x0 = _pack_params(initial_omega, initial_alpha, initial_beta)
        best_x, best_value, converged = _coordinate_search(objective, x0, max_iter=max_iter)
        omega, alpha, beta = _unpack_params(best_x)
        stationary = (
            np.isfinite(best_value)
            and omega > 0
            and alpha >= 0
            and beta >= 0
            and alpha + beta < 0.999
        )
        candidates.append(
            {
                "omega": float(omega),
                "alpha": float(alpha),
                "beta": float(beta),
                "persistence": float(alpha + beta),
                "negative_log_likelihood": float(best_value),
                "converged": bool(converged),
                "stationary": bool(stationary),
                "start_alpha": float(initial_alpha),
                "start_beta": float(initial_beta),
                "start_omega": float(initial_omega),
            }
        )
    converged_candidates = [
        candidate
        for candidate in candidates
        if candidate["converged"] and candidate["stationary"]
    ]
    stationary_candidates = [
        candidate
        for candidate in candidates
        if candidate["stationary"]
    ]
    usable_candidates = converged_candidates or stationary_candidates
    diagnostics = {
        "starts_attempted": len(candidates),
        "converged_starts": len(converged_candidates),
        "stationary_starts": len(stationary_candidates),
        "best_attempts": sorted(
            candidates,
            key=lambda item: item["negative_log_likelihood"],
        )[:5],
    }
    if not usable_candidates:
        return _constant_result(
            clean,
            "all optimizer starts failed stationarity/positivity constraints",
            optimizer_diagnostics=diagnostics,
        )
    best = min(usable_candidates, key=lambda item: item["negative_log_likelihood"])
    omega = float(best["omega"])
    alpha = float(best["alpha"])
    beta = float(best["beta"])
    sigma2, next_sigma2 = _variance_recursions(clean, omega, alpha, beta)
    return {
        "omega": float(omega),
        "alpha": float(alpha),
        "beta": float(beta),
        "conditional_volatility": np.sqrt(sigma2),
        "next_conditional_volatility": np.sqrt(next_sigma2),
        "fallback": False,
        "warning": None,
        "optimizer_diagnostics": {
            **diagnostics,
            "selected": best,
            "selected_from_nonconverged_stationary": not bool(best["converged"]),
        },
    }


def _constant_result(
    eps: np.ndarray,
    warning: str,
    *,
    optimizer_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean = np.asarray(eps, dtype=float)
    variance = float(np.var(clean, ddof=1)) if clean.size > 1 else 1.0
    variance = variance if np.isfinite(variance) and variance > 0 else 1.0
    vol = np.full(clean.shape[0], np.sqrt(variance), dtype=float)
    return {
        "omega": variance,
        "alpha": 0.0,
        "beta": 0.0,
        "conditional_volatility": vol,
        "next_conditional_volatility": vol.copy(),
        "fallback": True,
        "warning": warning,
        "optimizer_diagnostics": optimizer_diagnostics or {},
    }


def _initial_parameter_guesses(sample_var: float) -> list[tuple[float, float, float]]:
    guesses: list[tuple[float, float, float]] = []
    for alpha in (0.05, 0.15, 0.30):
        for beta in (0.60, 0.80, 0.90):
            if alpha + beta >= 0.98:
                continue
            omega = max(sample_var * (1.0 - alpha - beta), 1e-10)
            guesses.append((omega, alpha, beta))
    if not guesses:
        guesses.append((max(sample_var * 0.06, 1e-10), 0.08, 0.86))
    return guesses


def _variance_recursions(
    eps: np.ndarray,
    omega: float,
    alpha: float,
    beta: float,
) -> tuple[np.ndarray, np.ndarray]:
    sigma2 = np.zeros_like(eps, dtype=float)
    next_sigma2 = np.zeros_like(eps, dtype=float)
    sample_var = max(float(np.var(eps, ddof=1)), 1e-12)
    sigma2[0] = sample_var
    next_sigma2[0] = omega + alpha * eps[0] ** 2 + beta * sigma2[0]
    for index in range(1, len(eps)):
        sigma2[index] = next_sigma2[index - 1]
        next_sigma2[index] = omega + alpha * eps[index] ** 2 + beta * sigma2[index]
    return np.maximum(sigma2, 1e-12), np.maximum(next_sigma2, 1e-12)


def _negative_log_likelihood(
    eps: np.ndarray,
    *,
    omega: float,
    alpha: float,
    beta: float,
    dist: str,
    t_dof: int,
) -> float:
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
        return 1e100
    sigma2, _next = _variance_recursions(eps, omega, alpha, beta)
    sigma = np.sqrt(sigma2)
    z = eps / sigma
    if not np.isfinite(z).all():
        return 1e100
    if dist == "gaussian":
        log_density = -0.5 * (log(2.0 * pi) + z * z)
    else:
        log_density = _standardized_student_t_logpdf(z, t_dof)
    value = -float(np.sum(log_density - np.log(sigma)))
    return value if np.isfinite(value) else 1e100


def _standardized_student_t_logpdf(z: np.ndarray, dof: int) -> np.ndarray:
    scale = np.sqrt((dof - 2.0) / dof)
    raw = z / scale
    constant = (
        lgamma((dof + 1.0) / 2.0)
        - lgamma(dof / 2.0)
        - 0.5 * log(dof * pi)
        - log(scale)
    )
    return constant - ((dof + 1.0) / 2.0) * np.log1p((raw * raw) / dof)


def _coordinate_search(
    objective: Any,
    x0: np.ndarray,
    *,
    max_iter: int,
) -> tuple[np.ndarray, float, bool]:
    x = np.asarray(x0, dtype=float).copy()
    best = float(objective(x))
    steps = np.array([0.8, 0.8, 0.8], dtype=float)
    for _iteration in range(max_iter):
        improved = False
        for dim in range(len(x)):
            for direction in (1.0, -1.0):
                candidate = x.copy()
                candidate[dim] += direction * steps[dim]
                value = float(objective(candidate))
                if value + 1e-9 < best:
                    x = candidate
                    best = value
                    improved = True
        if not improved:
            steps *= 0.5
            if float(np.max(steps)) < 1e-4:
                return x, best, True
    return x, best, float(np.max(steps)) < 1e-3


def _pack_params(omega: float, alpha: float, beta: float) -> np.ndarray:
    limit = 0.995
    a = max(alpha / limit, 1e-8)
    b = max(beta / limit, 1e-8)
    slack = max(1.0 - a - b, 1e-8)
    return np.asarray([log(max(omega, 1e-12)), log(a / slack), log(b / slack)], dtype=float)


def _unpack_params(raw: np.ndarray) -> tuple[float, float, float]:
    clipped = np.clip(np.asarray(raw, dtype=float), [-40.0, -25.0, -25.0], [20.0, 25.0, 25.0])
    omega = float(np.exp(clipped[0]))
    exp_a = float(np.exp(clipped[1]))
    exp_b = float(np.exp(clipped[2]))
    denom = 1.0 + exp_a + exp_b
    limit = 0.995
    alpha = limit * exp_a / denom
    beta = limit * exp_b / denom
    return omega, alpha, beta


def _correlation_from_standardized_residuals(standardized: np.ndarray) -> np.ndarray:
    corr = np.corrcoef(standardized, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    return _make_positive_definite_correlation(corr)


def _make_positive_definite_correlation(matrix: np.ndarray) -> np.ndarray:
    sym = (matrix + matrix.T) / 2.0
    jitter = 1e-10
    for _ in range(8):
        candidate = sym + np.eye(sym.shape[0]) * jitter
        try:
            np.linalg.cholesky(candidate)
            diag = np.sqrt(np.diag(candidate))
            return candidate / np.outer(diag, diag)
        except np.linalg.LinAlgError:
            jitter *= 10
    candidate = sym + np.eye(sym.shape[0]) * jitter
    diag = np.sqrt(np.maximum(np.diag(candidate), 1e-12))
    return candidate / np.outer(diag, diag)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
