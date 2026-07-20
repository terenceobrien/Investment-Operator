"""Forward simulation for fitted BVAR posterior artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.forecasting.bvar_ensemble.bounds import (
    ValidityStats,
    add_violations,
    bounds_for_variables,
    clip_path_to_bounds,
    find_violations,
)
from src.agent_system.forecasting.bvar_ensemble.estimation import PosteriorArtifact
from src.agent_system.forecasting.bvar_ensemble.garch import (
    GarchArtifact,
    initial_volatility_by_variable,
    initial_volatility_for_anchor,
    validate_garch_matches_posterior,
)
from src.agent_system.forecasting.bvar_ensemble.regime_params import (
    RegimeArtifact,
    label_for_anchor,
    p_enter_for_anchor,
    validate_regime_matches_posterior,
)
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry


class SimulationError(RuntimeError):
    """Raised when BVAR simulation inputs are inconsistent."""


@dataclass(frozen=True)
class SimulationResult:
    paths: np.ndarray
    variable_order: list[str]
    anchor_quarter: str
    anchor_values: dict[str, float]
    validity: dict[str, Any]
    metadata: dict[str, Any]
    regime_entered_stress: np.ndarray | None = None
    regime_ever_stress: np.ndarray | None = None
    regime_stress_quarters: np.ndarray | None = None


def simulate_paths(
    registry: VariableRegistry,
    posterior: PosteriorArtifact,
    history: pd.DataFrame,
    *,
    n_paths: int,
    horizon: int,
    asof_quarter: str | None,
    seed: int,
    shock_dist: str,
    t_dof: int,
    draw_coefficients: bool,
    max_redraws_per_path: int,
    rejection_warn_pct: float,
    vol_model: str = "constant",
    garch_artifact: GarchArtifact | None = None,
    regime_model: str = "none",
    regime_artifact: RegimeArtifact | None = None,
) -> SimulationResult:
    if n_paths < 1:
        raise SimulationError("n_paths must be positive")
    if horizon < 1:
        raise SimulationError("horizon must be positive")
    if shock_dist not in {"gaussian", "student_t"}:
        raise SimulationError("shock_dist must be gaussian or student_t")
    if t_dof <= 2:
        raise SimulationError("t_dof must be greater than 2 for covariance-rescaled Student-t shocks")
    if max_redraws_per_path < 0:
        raise SimulationError("max_redraws_per_path cannot be negative")
    if vol_model not in {"constant", "garch"}:
        raise SimulationError("vol_model must be constant or garch")
    if regime_model not in {"none", "markov"}:
        raise SimulationError("regime_model must be none or markov")
    if vol_model == "garch":
        if garch_artifact is None:
            raise SimulationError("vol_model=garch requires a GARCH artifact")
        validate_garch_matches_posterior(garch_artifact, posterior)
    if regime_model == "markov":
        if vol_model != "garch":
            raise SimulationError("regime_model=markov requires vol_model=garch")
        if regime_artifact is None:
            raise SimulationError("regime_model=markov requires a regime artifact")
        validate_regime_matches_posterior(regime_artifact, posterior)

    variable_order = list(posterior.variable_order)
    missing = [variable for variable in variable_order if variable not in history.columns]
    if missing:
        raise SimulationError(f"history frame missing posterior variables: {missing}")
    history = history[variable_order].dropna().sort_index()
    anchor_window, anchor_quarter = _anchor_window(
        history,
        lags=posterior.lags,
        asof_quarter=asof_quarter,
    )
    regime_history_window = (
        _regime_history_window(history, anchor_quarter=anchor_quarter, lookback=5)
        if regime_model == "markov"
        else None
    )
    anchor_values_array = anchor_window.iloc[-1].to_numpy(dtype=float)
    anchor_values = {
        variable: float(anchor_values_array[index])
        for index, variable in enumerate(variable_order)
    }
    bounds = bounds_for_variables(registry, variable_order)
    rng = np.random.default_rng(int(seed))
    constant_chol = _cholesky(posterior.residual_cov)
    if vol_model == "garch":
        assert garch_artifact is not None
        garch_chol = _cholesky(garch_artifact.residual_correlation)
        garch_initial_vol = initial_volatility_for_anchor(
            garch_artifact,
            str(anchor_quarter),
        )
        garch_init_vol_by_variable = initial_volatility_by_variable(
            garch_artifact,
            str(anchor_quarter),
        )
    else:
        garch_chol = None
        garch_initial_vol = None
        garch_init_vol_by_variable = None
    if regime_model == "markov":
        assert regime_artifact is not None
        regime_calm_chol = _cholesky(regime_artifact.calm_correlation)
        regime_stress_chol = _cholesky(regime_artifact.stress_correlation)
        regime_anchor_label_int = label_for_anchor(regime_artifact, str(anchor_quarter))
        regime_anchor_label = "stress" if regime_anchor_label_int == 1 else "calm"
        regime_anchor_p_enter = p_enter_for_anchor(regime_artifact, str(anchor_quarter))
        regime_entered_stress = np.zeros(n_paths, dtype=bool)
        regime_ever_stress = np.zeros(n_paths, dtype=bool)
        regime_stress_quarters = np.zeros(n_paths, dtype=int)
    else:
        regime_calm_chol = None
        regime_stress_chol = None
        regime_anchor_label_int = 0
        regime_anchor_label = None
        regime_anchor_p_enter = None
        regime_entered_stress = None
        regime_ever_stress = None
        regime_stress_quarters = None
    paths = np.zeros((n_paths, horizon, len(variable_order)), dtype=float)
    validity = ValidityStats()
    for path_index in range(n_paths):
        attempt = 0
        while True:
            coefficients = (
                _draw_coefficients(posterior, rng)
                if draw_coefficients
                else posterior.coefficient_mean
            )
            candidate = _simulate_single_path(
                coefficients,
                anchor_window.to_numpy(dtype=float),
                horizon=horizon,
                shock_dist=shock_dist,
                t_dof=t_dof,
                chol=constant_chol,
                rng=rng,
                vol_model=vol_model,
                garch_artifact=garch_artifact,
                garch_chol=garch_chol,
                garch_initial_vol=garch_initial_vol,
                regime_model=regime_model,
                regime_artifact=regime_artifact,
                regime_calm_chol=regime_calm_chol,
                regime_stress_chol=regime_stress_chol,
                regime_initial_state=regime_anchor_label_int,
                regime_history_window=(
                    regime_history_window.to_numpy(dtype=float)
                    if regime_history_window is not None
                    else None
                ),
            )
            if isinstance(candidate, tuple):
                candidate_path, path_regime_stats = candidate
            else:
                candidate_path = candidate
                path_regime_stats = None
            violations = find_violations(candidate_path, variable_order, bounds)
            if not violations:
                paths[path_index] = candidate_path
                _record_regime_path_stats(
                    path_index,
                    path_regime_stats,
                    regime_entered_stress,
                    regime_ever_stress,
                    regime_stress_quarters,
                )
                break
            if attempt < max_redraws_per_path:
                validity.rejections += 1
                validity.redraws += 1
                add_violations(validity, violations)
                attempt += 1
                continue
            validity.clips += 1
            add_violations(validity, violations)
            paths[path_index] = clip_path_to_bounds(candidate_path, variable_order, bounds)
            _record_regime_path_stats(
                path_index,
                path_regime_stats,
                regime_entered_stress,
                regime_ever_stress,
                regime_stress_quarters,
            )
            break

    rejection_rate_pct = (validity.rejections / max(1, n_paths)) * 100.0
    warning = (
        "WARNING: BVAR simulation rejection rate exceeds configured threshold; "
        "the residual covariance and registry bounds may disagree."
        if rejection_rate_pct > rejection_warn_pct
        else None
    )
    validity_dict = validity.as_dict()
    validity_dict["rejection_rate_pct"] = rejection_rate_pct
    validity_dict["rejection_warn_pct"] = rejection_warn_pct
    validity_dict["warning"] = warning
    metadata = {
        "n_paths": int(n_paths),
        "horizon": int(horizon),
        "seed": int(seed),
        "shock_dist": shock_dist,
        "t_dof": int(t_dof),
        "vol_model": vol_model,
        "regime_model": regime_model,
        "garch_artifact": str(garch_artifact.path) if garch_artifact else None,
        "garch_init_vol_by_variable": garch_init_vol_by_variable,
        "regime_artifact": str(regime_artifact.path) if regime_artifact else None,
        "regime_anchor_label": regime_anchor_label,
        "regime_anchor_p_enter": (
            float(regime_anchor_p_enter)
            if regime_anchor_p_enter is not None
            else None
        ),
        "regime_fraction_entered_stress": (
            float(np.mean(regime_entered_stress))
            if regime_entered_stress is not None
            else None
        ),
        "regime_fraction_ever_stress": (
            float(np.mean(regime_ever_stress))
            if regime_ever_stress is not None
            else None
        ),
        "regime_avg_quarters_in_stress": (
            float(np.mean(regime_stress_quarters))
            if regime_stress_quarters is not None
            else None
        ),
        "draw_coefficients": bool(draw_coefficients),
        "max_redraws_per_path": int(max_redraws_per_path),
        "anchor_quarter": str(anchor_quarter),
        "anchor_values": anchor_values,
        "validity": validity_dict,
    }
    return SimulationResult(
        paths=paths,
        variable_order=variable_order,
        anchor_quarter=str(anchor_quarter),
        anchor_values=anchor_values,
        validity=validity_dict,
        metadata=metadata,
        regime_entered_stress=regime_entered_stress,
        regime_ever_stress=regime_ever_stress,
        regime_stress_quarters=regime_stress_quarters,
    )


def _simulate_single_path(
    coefficients: np.ndarray,
    anchor_window: np.ndarray,
    *,
    horizon: int,
    shock_dist: str,
    t_dof: int,
    chol: np.ndarray,
    rng: np.random.Generator,
    vol_model: str,
    garch_artifact: GarchArtifact | None,
    garch_chol: np.ndarray | None,
    garch_initial_vol: np.ndarray | None,
    regime_model: str,
    regime_artifact: RegimeArtifact | None,
    regime_calm_chol: np.ndarray | None,
    regime_stress_chol: np.ndarray | None,
    regime_initial_state: int,
    regime_history_window: np.ndarray | None,
) -> np.ndarray | tuple[np.ndarray, dict[str, Any]]:
    n_vars = anchor_window.shape[1]
    lags = (coefficients.shape[0] - 1) // n_vars
    lag_states = [anchor_window[-lag].copy() for lag in range(1, lags + 1)]
    out = np.zeros((horizon, n_vars), dtype=float)
    current_sigma2 = (
        np.asarray(garch_initial_vol, dtype=float) ** 2
        if vol_model == "garch"
        else None
    )
    regime_state = int(regime_initial_state)
    regime_entered_stress = False
    regime_ever_stress = bool(regime_state == 1)
    regime_stress_quarters = 0
    regime_history = (
        [row.copy() for row in np.asarray(regime_history_window, dtype=float)]
        if regime_model == "markov" and regime_history_window is not None
        else None
    )
    for step in range(horizon):
        x = np.concatenate([np.ones(1), *lag_states])
        mean = x @ coefficients
        if vol_model == "garch":
            if garch_artifact is None or garch_chol is None or current_sigma2 is None:
                raise SimulationError("GARCH simulation missing volatility state")
            if regime_model == "markov":
                if (
                    regime_artifact is None
                    or regime_calm_chol is None
                    or regime_stress_chol is None
                    or regime_history is None
                    or len(regime_history) < 5
                ):
                    raise SimulationError("Markov regime simulation missing regime state")
                current_state = regime_history[-1]
                lag4_state = regime_history[-5]
                proxy_value = regime_artifact.proxy_for_state(current_state, lag4_state)
                if regime_state == 1:
                    regime_state = 1 if rng.random() < regime_artifact.p_stay else 0
                else:
                    p_enter = regime_artifact.p_enter_for_proxy(proxy_value)
                    if rng.random() < p_enter:
                        regime_state = 1
                        regime_entered_stress = True
                if regime_state == 1:
                    regime_ever_stress = True
                    regime_stress_quarters += 1
                    shock = _draw_garch_shock(
                        regime_stress_chol,
                        np.sqrt(current_sigma2) * regime_artifact.stress_vol_multiplier,
                        rng,
                        dist=garch_artifact.garch_dist,
                        t_dof=garch_artifact.garch_t_dof,
                    )
                else:
                    shock = _draw_garch_shock(
                        regime_calm_chol,
                        np.sqrt(current_sigma2),
                        rng,
                        dist=garch_artifact.garch_dist,
                        t_dof=garch_artifact.garch_t_dof,
                    )
            else:
                shock = _draw_garch_shock(
                    garch_chol,
                    np.sqrt(current_sigma2),
                    rng,
                    dist=garch_artifact.garch_dist,
                    t_dof=garch_artifact.garch_t_dof,
                )
            current_sigma2 = (
                garch_artifact.omega
                + garch_artifact.alpha * shock * shock
                + garch_artifact.beta * current_sigma2
            )
            current_sigma2 = np.maximum(current_sigma2, 1e-12)
        else:
            shock = _draw_shock(chol, rng, shock_dist=shock_dist, t_dof=t_dof)
        next_state = mean + shock
        out[step] = next_state
        if regime_history is not None:
            regime_history.append(next_state.copy())
            if len(regime_history) > 5:
                regime_history = regime_history[-5:]
        lag_states = [next_state, *lag_states[:-1]]
    if regime_model == "markov":
        return out, {
            "entered_stress": bool(regime_entered_stress),
            "ever_stress": bool(regime_ever_stress),
            "stress_quarters": int(regime_stress_quarters),
        }
    return out


def _draw_shock(
    chol: np.ndarray,
    rng: np.random.Generator,
    *,
    shock_dist: str,
    t_dof: int,
) -> np.ndarray:
    n_vars = chol.shape[0]
    if shock_dist == "gaussian":
        z = rng.standard_normal(n_vars)
    else:
        z = rng.standard_t(t_dof, size=n_vars) * np.sqrt((t_dof - 2.0) / t_dof)
    return z @ chol.T


def _draw_garch_shock(
    correlation_chol: np.ndarray,
    sigma: np.ndarray,
    rng: np.random.Generator,
    *,
    dist: str,
    t_dof: int,
) -> np.ndarray:
    n_vars = correlation_chol.shape[0]
    if dist == "gaussian":
        z = rng.standard_normal(n_vars)
    elif dist == "student_t":
        z = rng.standard_t(t_dof, size=n_vars) * np.sqrt((t_dof - 2.0) / t_dof)
    else:
        raise SimulationError(f"unsupported GARCH shock distribution: {dist}")
    correlated = z @ correlation_chol.T
    return correlated * sigma


def _draw_coefficients(
    posterior: PosteriorArtifact,
    rng: np.random.Generator,
) -> np.ndarray:
    coef = np.zeros_like(posterior.coefficient_mean)
    for equation_index in range(posterior.coefficient_mean.shape[1]):
        coef[:, equation_index] = rng.multivariate_normal(
            posterior.coefficient_mean[:, equation_index],
            _make_positive_definite(posterior.beta_cov_by_eq[equation_index]),
        )
    return coef


def _anchor_window(
    history: pd.DataFrame,
    *,
    lags: int,
    asof_quarter: str | None,
) -> tuple[pd.DataFrame, pd.Period]:
    if not isinstance(history.index, pd.PeriodIndex):
        history = history.copy()
        history.index = pd.PeriodIndex(history.index, freq="Q")
    if asof_quarter is None:
        anchor = history.index.max()
    else:
        try:
            anchor = pd.Period(asof_quarter, freq="Q")
        except Exception as exc:
            raise SimulationError(f"invalid asof quarter '{asof_quarter}'") from exc
        if anchor not in history.index:
            raise SimulationError(f"asof quarter {anchor} is not present in complete spine history")
    window = history[history.index <= anchor].tail(lags)
    if len(window) < lags:
        raise SimulationError(
            f"need {lags} complete quarters through {anchor}; only {len(window)} available"
        )
    return window, anchor


def _regime_history_window(
    history: pd.DataFrame,
    *,
    anchor_quarter: pd.Period,
    lookback: int,
) -> pd.DataFrame:
    window = history[history.index <= anchor_quarter].tail(lookback)
    if len(window) < lookback:
        raise SimulationError(
            f"need {lookback} complete quarters through {anchor_quarter} for "
            f"regime proxy history; only {len(window)} available"
        )
    return window


def _record_regime_path_stats(
    path_index: int,
    path_regime_stats: dict[str, Any] | None,
    regime_entered_stress: np.ndarray | None,
    regime_ever_stress: np.ndarray | None,
    regime_stress_quarters: np.ndarray | None,
) -> None:
    if path_regime_stats is None:
        return
    if (
        regime_entered_stress is None
        or regime_ever_stress is None
        or regime_stress_quarters is None
    ):
        raise SimulationError("received regime path stats without output arrays")
    regime_entered_stress[path_index] = bool(path_regime_stats["entered_stress"])
    regime_ever_stress[path_index] = bool(path_regime_stats["ever_stress"])
    regime_stress_quarters[path_index] = int(path_regime_stats["stress_quarters"])


def _cholesky(covariance: np.ndarray) -> np.ndarray:
    return np.linalg.cholesky(_make_positive_definite(covariance))


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
