"""Minnesota-prior VAR estimation for the standalone BVAR ensemble."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.agent_system.forecasting.scenario_classifier.data import (
    ClassifierDataError,
    default_cache_dir as classifier_cache_dir,
    ensure_cache_available,
    load_transformed_history,
)
from src.agent_system.forecasting.scenario_classifier.registry import (
    VariableRegistry,
    VariableSpec,
)
from src.agent_system.paths import agent_system_data_root


class BVARFitError(RuntimeError):
    """Raised when BVAR estimation cannot proceed."""


@dataclass(frozen=True)
class PosteriorArtifact:
    path: Path
    coefficient_mean: np.ndarray
    residual_cov: np.ndarray
    residuals: np.ndarray | None
    residual_quarters: list[str]
    beta_cov_by_eq: np.ndarray
    niw_scale: np.ndarray
    niw_nu: float
    variable_order: list[str]
    transforms: dict[str, str]
    lags: int
    sample_start: str
    sample_end: str
    hyperparameters: dict[str, float]
    classifier_cache_manifest_fingerprint: str
    r2_by_equation: dict[str, float]
    companion_max_eigenvalue_modulus: float


def default_bvar_cache_dir() -> Path:
    return agent_system_data_root() / "bvar_cache"


def artifact_candidate_paths(
    pattern: str,
    *,
    bvar_cache_dir: str | Path | None = None,
) -> list[Path]:
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    if not target_dir.is_dir():
        return []
    candidates = list(target_dir.glob(pattern))
    archive_dir = target_dir / "archive"
    if archive_dir.is_dir():
        candidates.extend(archive_dir.glob(pattern))
    return sorted(candidates, key=_artifact_sort_key, reverse=True)


def print_archive_resolution_note(
    artifact_label: str,
    path: str | Path,
    *,
    bvar_cache_dir: str | Path | None = None,
) -> None:
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    archive_dir = target_dir / "archive"
    artifact_path = Path(path)
    if artifact_path.parent == archive_dir:
        print(f"resolved {artifact_label} from archive/: {artifact_path.name}")


def default_bvar_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "bvar_config.yaml"


def load_bvar_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else default_bvar_config_path()
    if not config_path.is_file():
        raise BVARFitError(f"BVAR config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    if not isinstance(payload, dict):
        raise BVARFitError(f"BVAR config must be a YAML mapping: {config_path}")
    config = {
        "estimation_start": str(payload.get("estimation_start")),
        "min_sample_quarters": int(payload.get("min_sample_quarters")),
        "lags": int(payload.get("lags")),
        "lambda1": float(payload.get("lambda1")),
        "lambda2": float(payload.get("lambda2")),
        "lambda3": float(payload.get("lambda3")),
        "lambda4": float(payload.get("lambda4")),
        "n_paths": int(payload.get("n_paths")),
        "horizon": int(payload.get("horizon")),
        "seed": int(payload.get("seed")),
        "shock_dist": str(payload.get("shock_dist")),
        "t_dof": int(payload.get("t_dof")),
        "vol_model": str(payload.get("vol_model", "garch")),
        "regime_model": str(payload.get("regime_model", "markov")),
        "garch_dist": str(payload.get("garch_dist", "student_t")),
        "garch_t_dof": int(payload.get("garch_t_dof", 6)),
        "garch_max_iter": int(payload.get("garch_max_iter", 500)),
        "garch_persistence_warn": float(payload.get("garch_persistence_warn", 0.99)),
        "spread_level_pctile": float(payload.get("spread_level_pctile", 90.0)),
        "spread_change_threshold": float(payload.get("spread_change_threshold", 0.50)),
        "nfci_threshold": float(payload.get("nfci_threshold", 0.5)),
        "stress_min_conditions": int(payload.get("stress_min_conditions", 2)),
        "regime_min_stress_quarters": int(payload.get("regime_min_stress_quarters", 8)),
        "crisis_correlation_target": float(payload.get("crisis_correlation_target", 0.8)),
        "stress_correlation_impose_weight": float(
            payload.get("stress_correlation_impose_weight", 1.0)
        ),
        "psd_repair_warn_delta": float(payload.get("psd_repair_warn_delta", 0.1)),
        "regime_proxy_weights": dict(payload.get("regime_proxy_weights") or {}),
        "max_redraws_per_path": int(payload.get("max_redraws_per_path")),
        "rejection_warn_pct": float(payload.get("rejection_warn_pct")),
        "low_margin_threshold": float(payload.get("low_margin_threshold")),
        "report_output_dir": str(
            payload.get("report_output_dir")
            or (default_bvar_cache_dir() / "reports")
        ),
    }
    _validate_config(config)
    return config


def apply_config_overrides(config: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    updated = dict(config)
    for key, value in overrides.items():
        if value is not None:
            updated[key] = value
    _validate_config(updated)
    return updated


def fit_bvar(
    registry: VariableRegistry,
    config: dict[str, Any],
    *,
    cache_dir: str | Path | None = None,
    bvar_cache_dir: str | Path | None = None,
) -> tuple[PosteriorArtifact, Path]:
    ensure_cache_available(registry, cache_dir=cache_dir)
    manifest_fingerprint = classifier_cache_manifest_fingerprint(cache_dir=cache_dir)
    sample = load_spine_history_frame(
        registry,
        estimation_start=config["estimation_start"],
        min_sample_quarters=config["min_sample_quarters"],
        cache_dir=cache_dir,
    )
    variable_order = list(sample.columns)
    specs = [registry.get(name) for name in variable_order]
    y, x, residual_quarters = _lagged_design(sample, int(config["lags"]))
    coefficients, residual_cov, beta_cov_by_eq, residuals = _fit_minnesota_ridge(
        y,
        x,
        specs,
        lags=int(config["lags"]),
        lambda1=float(config["lambda1"]),
        lambda2=float(config["lambda2"]),
        lambda3=float(config["lambda3"]),
        lambda4=float(config["lambda4"]),
    )
    predictions = x @ coefficients
    r2 = _r2_by_equation(y, predictions, variable_order)
    companion_eigen = _companion_max_eigenvalue(coefficients, len(variable_order), int(config["lags"]))
    resid_df = max(1, residuals.shape[0] - x.shape[1])
    niw_scale = residual_cov * resid_df
    metadata = {
        "variable_order": variable_order,
        "transforms": {spec.name: spec.transform for spec in specs},
        "lags": int(config["lags"]),
        "sample_start": str(sample.index.min()),
        "sample_end": str(sample.index.max()),
        "sample_observations": int(len(sample)),
        "usable_regression_observations": int(y.shape[0]),
        "hyperparameters": {
            "lambda1": float(config["lambda1"]),
            "lambda2": float(config["lambda2"]),
            "lambda3": float(config["lambda3"]),
            "lambda4": float(config["lambda4"]),
        },
        "classifier_cache_manifest_fingerprint": manifest_fingerprint,
        "r2_by_equation": r2,
        "companion_max_eigenvalue_modulus": companion_eigen,
    }
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _utc_timestamp()
    artifact_path = target_dir / f"posterior_{timestamp}.npz"
    np.savez_compressed(
        artifact_path,
        coefficient_mean=coefficients,
        residual_cov=residual_cov,
        beta_cov_by_eq=beta_cov_by_eq,
        niw_scale=niw_scale,
        niw_nu=np.asarray(float(resid_df)),
        residuals=residuals,
        residual_quarters=np.asarray(residual_quarters),
        metadata_json=np.asarray(json.dumps(metadata, sort_keys=True)),
    )
    summary_path = target_dir / f"posterior_{timestamp}_summary.json"
    summary = {
        **metadata,
        "posterior_artifact": str(artifact_path),
        "residual_correlation": _correlation_matrix(residual_cov, variable_order),
        "explosive_dynamics_warning": (
            "Largest companion-matrix eigenvalue modulus is >= 1.0."
            if companion_eigen >= 1.0
            else None
        ),
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return load_posterior_artifact(artifact_path), summary_path


def load_spine_history_frame(
    registry: VariableRegistry,
    *,
    estimation_start: str | None = None,
    min_sample_quarters: int = 0,
    cache_dir: str | Path | None = None,
) -> pd.DataFrame:
    spine_specs = registry.spine_variables()
    if not spine_specs:
        raise BVARFitError("state vector registry has no spine-role variables")
    histories: dict[str, pd.Series] = {}
    availability: dict[str, dict[str, Any]] = {}
    for spec in spine_specs:
        try:
            series = load_transformed_history(registry, spec, cache_dir=cache_dir)
        except ClassifierDataError as exc:
            raise BVARFitError(str(exc)) from exc
        if not isinstance(series.index, pd.PeriodIndex):
            series = series.copy()
            series.index = pd.PeriodIndex(series.index, freq="Q")
        histories[spec.name] = series
        availability[spec.name] = {
            "start": str(series.index.min()) if not series.empty else None,
            "end": str(series.index.max()) if not series.empty else None,
            "count": int(series.dropna().shape[0]),
        }
    frame = pd.concat(histories, axis=1, join="inner").dropna()
    if estimation_start:
        start = _parse_quarter(estimation_start)
        frame = frame[frame.index >= start]
    if len(frame) < min_sample_quarters:
        raise BVARFitError(
            "Insufficient intersected spine history for BVAR estimation: "
            f"{len(frame)} quarters available, need {min_sample_quarters}. "
            f"Per-series availability: {availability}"
        )
    return frame.sort_index()


def load_posterior_artifact(path: str | Path) -> PosteriorArtifact:
    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise BVARFitError(f"posterior artifact not found: {artifact_path}")
    try:
        data = np.load(artifact_path, allow_pickle=False)
        metadata = json.loads(str(data["metadata_json"]))
    except Exception as exc:
        raise BVARFitError(f"could not load posterior artifact {artifact_path}: {exc}") from exc
    return PosteriorArtifact(
        path=artifact_path,
        coefficient_mean=np.asarray(data["coefficient_mean"], dtype=float),
        residual_cov=np.asarray(data["residual_cov"], dtype=float),
        beta_cov_by_eq=np.asarray(data["beta_cov_by_eq"], dtype=float),
        niw_scale=np.asarray(data["niw_scale"], dtype=float),
        niw_nu=float(np.asarray(data["niw_nu"])),
        residuals=(
            np.asarray(data["residuals"], dtype=float)
            if "residuals" in data.files
            else None
        ),
        residual_quarters=(
            [str(value) for value in np.asarray(data["residual_quarters"]).tolist()]
            if "residual_quarters" in data.files
            else []
        ),
        variable_order=list(metadata["variable_order"]),
        transforms=dict(metadata["transforms"]),
        lags=int(metadata["lags"]),
        sample_start=str(metadata["sample_start"]),
        sample_end=str(metadata["sample_end"]),
        hyperparameters=dict(metadata["hyperparameters"]),
        classifier_cache_manifest_fingerprint=str(
            metadata["classifier_cache_manifest_fingerprint"]
        ),
        r2_by_equation={k: float(v) for k, v in metadata["r2_by_equation"].items()},
        companion_max_eigenvalue_modulus=float(
            metadata["companion_max_eigenvalue_modulus"]
        ),
    )


def newest_posterior_artifact(
    *,
    bvar_cache_dir: str | Path | None = None,
) -> PosteriorArtifact:
    target_dir = Path(bvar_cache_dir) if bvar_cache_dir is not None else default_bvar_cache_dir()
    if not target_dir.is_dir():
        raise BVARFitError(f"BVAR cache directory not found: {target_dir}; run fit first.")
    candidates = artifact_candidate_paths("posterior_*.npz", bvar_cache_dir=bvar_cache_dir)
    if not candidates:
        raise BVARFitError(
            f"No posterior_*.npz found in {target_dir} or {target_dir / 'archive'}; "
            "run fit first or pass --posterior."
        )
    print_archive_resolution_note("posterior", candidates[0], bvar_cache_dir=bvar_cache_dir)
    return load_posterior_artifact(candidates[0])


def classifier_cache_manifest_fingerprint(
    *,
    cache_dir: str | Path | None = None,
) -> str:
    target_dir = Path(cache_dir) if cache_dir is not None else classifier_cache_dir()
    manifest_path = target_dir / "cache_manifest.json"
    if not manifest_path.is_file():
        raise BVARFitError(
            f"classifier cache manifest missing at {manifest_path}; run refresh-data first."
        )
    data = manifest_path.read_bytes()
    return hashlib.sha256(data).hexdigest()[:16]


def validate_posterior_cache_fingerprint(
    posterior: PosteriorArtifact,
    *,
    cache_dir: str | Path | None = None,
) -> None:
    current = classifier_cache_manifest_fingerprint(cache_dir=cache_dir)
    if current != posterior.classifier_cache_manifest_fingerprint:
        raise BVARFitError(
            "posterior artifact was fit against classifier cache fingerprint "
            f"{posterior.classifier_cache_manifest_fingerprint}, but current cache "
            f"fingerprint is {current}. Refit the posterior or restore the matching "
            "classifier cache."
        )


def posterior_artifact_fingerprint(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def require_posterior_residuals(posterior: PosteriorArtifact) -> tuple[np.ndarray, list[str]]:
    if posterior.residuals is None or not posterior.residual_quarters:
        raise BVARFitError(
            f"posterior artifact {posterior.path} does not contain stored VAR residuals. "
            "Run bvar_ensemble.cli fit with the Stage 6 schema, then rerun fit-garch."
        )
    residuals = np.asarray(posterior.residuals, dtype=float)
    if residuals.ndim != 2:
        raise BVARFitError(f"posterior residuals must be 2D; got shape {residuals.shape}")
    if residuals.shape[1] != len(posterior.variable_order):
        raise BVARFitError(
            "posterior residual variable dimension does not match variable_order: "
            f"{residuals.shape[1]} vs {len(posterior.variable_order)}"
        )
    if residuals.shape[0] != len(posterior.residual_quarters):
        raise BVARFitError(
            "posterior residual row count does not match residual_quarters: "
            f"{residuals.shape[0]} vs {len(posterior.residual_quarters)}"
        )
    if not np.isfinite(residuals).all():
        raise BVARFitError("posterior residuals contain non-finite values")
    return residuals, list(posterior.residual_quarters)


def _fit_minnesota_ridge(
    y: np.ndarray,
    x: np.ndarray,
    specs: list[VariableSpec],
    *,
    lags: int,
    lambda1: float,
    lambda2: float,
    lambda3: float,
    lambda4: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_obs, n_vars = y.shape
    n_coeff = x.shape[1]
    xtx = x.T @ x
    xty = x.T @ y
    coefficients = np.zeros((n_coeff, n_vars), dtype=float)
    inv_precision_by_eq = np.zeros((n_vars, n_coeff, n_coeff), dtype=float)
    for eq_index, spec in enumerate(specs):
        prior_mean, prior_precision = _minnesota_prior_for_equation(
            eq_index,
            specs,
            lags=lags,
            lambda1=lambda1,
            lambda2=lambda2,
            lambda3=lambda3,
            lambda4=lambda4,
        )
        precision = xtx + prior_precision
        rhs = xty[:, eq_index] + prior_precision @ prior_mean
        coefficients[:, eq_index] = np.linalg.solve(precision, rhs)
        inv_precision_by_eq[eq_index] = np.linalg.inv(precision)

    residuals = y - x @ coefficients
    denom = max(1, n_obs - n_coeff)
    residual_cov = (residuals.T @ residuals) / denom
    residual_cov = _make_positive_definite(residual_cov)
    beta_cov_by_eq = np.zeros_like(inv_precision_by_eq)
    for eq_index in range(n_vars):
        beta_cov_by_eq[eq_index] = inv_precision_by_eq[eq_index] * residual_cov[eq_index, eq_index]
        beta_cov_by_eq[eq_index] = _make_positive_definite(beta_cov_by_eq[eq_index])
    return coefficients, residual_cov, beta_cov_by_eq, residuals


def _minnesota_prior_for_equation(
    eq_index: int,
    specs: list[VariableSpec],
    *,
    lags: int,
    lambda1: float,
    lambda2: float,
    lambda3: float,
    lambda4: float,
) -> tuple[np.ndarray, np.ndarray]:
    n_vars = len(specs)
    n_coeff = 1 + n_vars * lags
    prior_mean = np.zeros(n_coeff, dtype=float)
    prior_variance = np.zeros(n_coeff, dtype=float)
    prior_variance[0] = lambda4 ** 2
    for lag in range(1, lags + 1):
        for variable_index, _spec in enumerate(specs):
            row = 1 + (lag - 1) * n_vars + variable_index
            shrink = lambda1 / (lag ** lambda3)
            if variable_index != eq_index:
                shrink *= lambda2
            prior_variance[row] = shrink ** 2
            if variable_index == eq_index and lag == 1:
                prior_mean[row] = 1.0 if specs[eq_index].transform == "level" else 0.0
    if np.any(prior_variance <= 0):
        raise BVARFitError("Minnesota prior variance contains non-positive values")
    prior_precision = np.diag(1.0 / prior_variance)
    return prior_mean, prior_precision


def _lagged_design(frame: pd.DataFrame, lags: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(frame) <= lags:
        raise BVARFitError(f"need more than {lags} rows to fit VAR")
    values = frame.to_numpy(dtype=float)
    y_rows: list[np.ndarray] = []
    x_rows: list[np.ndarray] = []
    quarters: list[str] = []
    for row_index in range(lags, len(values)):
        lagged = [values[row_index - lag] for lag in range(1, lags + 1)]
        x_rows.append(np.concatenate([np.ones(1), *lagged]))
        y_rows.append(values[row_index])
        quarters.append(str(frame.index[row_index]))
    return np.vstack(y_rows), np.vstack(x_rows), quarters


def _r2_by_equation(
    y: np.ndarray,
    predictions: np.ndarray,
    variable_order: list[str],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for index, name in enumerate(variable_order):
        actual = y[:, index]
        resid = actual - predictions[:, index]
        tss = float(np.sum((actual - actual.mean()) ** 2))
        rss = float(np.sum(resid ** 2))
        out[name] = float(1.0 - rss / tss) if tss > 0 else 0.0
    return out


def _companion_max_eigenvalue(
    coefficients: np.ndarray,
    n_vars: int,
    lags: int,
) -> float:
    companion = np.zeros((n_vars * lags, n_vars * lags), dtype=float)
    for lag in range(lags):
        block = coefficients[1 + lag * n_vars : 1 + (lag + 1) * n_vars, :]
        companion[:n_vars, lag * n_vars : (lag + 1) * n_vars] = block.T
    if lags > 1:
        companion[n_vars:, :-n_vars] = np.eye(n_vars * (lags - 1))
    eigenvalues = np.linalg.eigvals(companion)
    return float(np.max(np.abs(eigenvalues)))


def _correlation_matrix(covariance: np.ndarray, variable_order: list[str]) -> dict[str, dict[str, float]]:
    diag = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    corr = covariance / np.outer(diag, diag)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    return {
        left: {
            right: float(corr[left_index, right_index])
            for right_index, right in enumerate(variable_order)
        }
        for left_index, left in enumerate(variable_order)
    }


def _make_positive_definite(matrix: np.ndarray) -> np.ndarray:
    sym = (matrix + matrix.T) / 2.0
    jitter = 1e-10
    for _ in range(8):
        try:
            np.linalg.cholesky(sym + np.eye(sym.shape[0]) * jitter)
            return sym + np.eye(sym.shape[0]) * jitter
        except np.linalg.LinAlgError:
            jitter *= 10
    return sym + np.eye(sym.shape[0]) * jitter


def _validate_config(config: dict[str, Any]) -> None:
    positive_ints = [
        "min_sample_quarters",
        "lags",
        "n_paths",
        "horizon",
        "t_dof",
        "garch_t_dof",
        "garch_max_iter",
        "max_redraws_per_path",
    ]
    for key in positive_ints:
        if int(config[key]) < 1:
            raise BVARFitError(f"bvar_config {key} must be positive")
    for key in ["lambda1", "lambda2", "lambda3", "lambda4", "rejection_warn_pct"]:
        if float(config[key]) <= 0:
            raise BVARFitError(f"bvar_config {key} must be positive")
    if str(config["shock_dist"]) not in {"gaussian", "student_t"}:
        raise BVARFitError("bvar_config shock_dist must be gaussian or student_t")
    if str(config["vol_model"]) not in {"constant", "garch"}:
        raise BVARFitError("bvar_config vol_model must be constant or garch")
    if str(config["regime_model"]) not in {"none", "markov"}:
        raise BVARFitError("bvar_config regime_model must be none or markov")
    if str(config["garch_dist"]) not in {"gaussian", "student_t"}:
        raise BVARFitError("bvar_config garch_dist must be gaussian or student_t")
    if int(config["garch_t_dof"]) <= 2:
        raise BVARFitError("bvar_config garch_t_dof must be greater than 2")
    if float(config["garch_persistence_warn"]) <= 0:
        raise BVARFitError("bvar_config garch_persistence_warn must be positive")
    if str(config["estimation_start"]) == "None":
        raise BVARFitError("bvar_config estimation_start is required")
    if not str(config.get("report_output_dir", "")).strip():
        raise BVARFitError("bvar_config report_output_dir must be non-empty")
    if not 0.0 < float(config["spread_level_pctile"]) < 100.0:
        raise BVARFitError("bvar_config spread_level_pctile must be between 0 and 100")
    if not 1 <= int(config["stress_min_conditions"]) <= 3:
        raise BVARFitError("bvar_config stress_min_conditions must be between 1 and 3")
    if int(config["regime_min_stress_quarters"]) < 1:
        raise BVARFitError("bvar_config regime_min_stress_quarters must be positive")
    if not 0.0 < float(config["crisis_correlation_target"]) < 1.0:
        raise BVARFitError("bvar_config crisis_correlation_target must be between 0 and 1")
    if not 0.0 <= float(config["stress_correlation_impose_weight"]) <= 1.0:
        raise BVARFitError(
            "bvar_config stress_correlation_impose_weight must be between 0 and 1"
        )
    if float(config["psd_repair_warn_delta"]) < 0.0:
        raise BVARFitError("bvar_config psd_repair_warn_delta must be non-negative")
    weights = config.get("regime_proxy_weights")
    if not isinstance(weights, dict):
        raise BVARFitError("bvar_config regime_proxy_weights must be a mapping")
    allowed_weights = {"credit_spread_level", "credit_spread_change_4q", "nfci"}
    unknown_weights = sorted(set(weights) - allowed_weights)
    if unknown_weights:
        raise BVARFitError(
            f"bvar_config regime_proxy_weights contains unknown keys {unknown_weights}"
        )
    if not weights:
        config["regime_proxy_weights"] = {
            "credit_spread_level": 1.0,
            "credit_spread_change_4q": 1.0,
            "nfci": 1.0,
        }
    else:
        total_weight = 0.0
        cleaned: dict[str, float] = {}
        for key in allowed_weights:
            cleaned[key] = float(weights.get(key, 1.0))
            total_weight += abs(cleaned[key])
        if total_weight <= 0:
            raise BVARFitError("bvar_config regime_proxy_weights must not all be zero")
        config["regime_proxy_weights"] = cleaned
    _parse_quarter(str(config["estimation_start"]))


def _parse_quarter(value: str) -> pd.Period:
    try:
        return pd.Period(value, freq="Q")
    except Exception as exc:
        raise BVARFitError(f"invalid quarter '{value}'") from exc


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _artifact_sort_key(path: Path) -> tuple[str, float, str]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (path.name, mtime, str(path))
