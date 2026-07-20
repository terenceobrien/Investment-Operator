from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.agent_system.forecasting.bvar_ensemble.bounds import validate_registry_bounds
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    PosteriorArtifact,
    _fit_minnesota_ridge,
    _lagged_design,
)
from src.agent_system.forecasting.bvar_ensemble.simulation import simulate_paths
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry


def test_registry_bounds_cover_spine_variables():
    registry = VariableRegistry.load()
    bounds = validate_registry_bounds(registry)

    assert set(bounds) == set(registry.spine_variable_names())
    assert bounds["credit_spread"] == (0.2, 10.0)


def test_minnesota_fit_returns_expected_shapes():
    registry = VariableRegistry.load()
    specs = registry.spine_variables()[:3]
    index = pd.period_range("2000Q1", periods=40, freq="Q")
    frame = pd.DataFrame(
        {
            spec.name: np.linspace(index_pos, index_pos + 1.0, len(index))
            for index_pos, spec in enumerate(specs)
        },
        index=index,
    )
    y, x = _lagged_design(frame, lags=2)

    coefficients, residual_cov, beta_cov_by_eq, residuals = _fit_minnesota_ridge(
        y,
        x,
        specs,
        lags=2,
        lambda1=0.2,
        lambda2=0.5,
        lambda3=1.0,
        lambda4=100.0,
    )

    assert coefficients.shape == (1 + 2 * len(specs), len(specs))
    assert residual_cov.shape == (len(specs), len(specs))
    assert beta_cov_by_eq.shape == (len(specs), 1 + 2 * len(specs), 1 + 2 * len(specs))
    assert residuals.shape == y.shape


def test_simulation_is_deterministic_given_seed(tmp_path):
    registry = VariableRegistry.load()
    variable_order = registry.spine_variable_names()
    n_vars = len(variable_order)
    lags = 1
    coefficients = np.zeros((1 + n_vars * lags, n_vars), dtype=float)
    for index in range(n_vars):
        coefficients[1 + index, index] = 0.95
    residual_cov = np.eye(n_vars) * 0.01
    posterior = PosteriorArtifact(
        path=tmp_path / "posterior.npz",
        coefficient_mean=coefficients,
        residual_cov=residual_cov,
        beta_cov_by_eq=np.repeat(
            np.eye(1 + n_vars * lags)[None, :, :] * 0.001,
            n_vars,
            axis=0,
        ),
        niw_scale=residual_cov,
        niw_nu=30.0,
        variable_order=variable_order,
        transforms={name: registry.get(name).transform for name in variable_order},
        lags=lags,
        sample_start="2000Q1",
        sample_end="2005Q4",
        hyperparameters={},
        classifier_cache_manifest_fingerprint="abc123",
        r2_by_equation={name: 0.5 for name in variable_order},
        companion_max_eigenvalue_modulus=0.95,
    )
    anchor = {
        "activity": 2.0,
        "lur": 4.5,
        "core_pce": 2.5,
        "credit_spread": 2.0,
        "fed_funds": 4.0,
        "ten_year": 4.0,
        "nfci": 0.0,
    }
    history = pd.DataFrame(
        [anchor],
        index=pd.period_range("2024Q4", periods=1, freq="Q"),
    )[variable_order]

    first = simulate_paths(
        registry,
        posterior,
        history,
        n_paths=20,
        horizon=4,
        asof_quarter="2024Q4",
        seed=42,
        shock_dist="gaussian",
        t_dof=6,
        draw_coefficients=False,
        max_redraws_per_path=5,
        rejection_warn_pct=5.0,
    )
    second = simulate_paths(
        registry,
        posterior,
        history,
        n_paths=20,
        horizon=4,
        asof_quarter="2024Q4",
        seed=42,
        shock_dist="gaussian",
        t_dof=6,
        draw_coefficients=False,
        max_redraws_per_path=5,
        rejection_warn_pct=5.0,
    )

    assert np.array_equal(first.paths, second.paths)
    assert first.validity["rejections"] == second.validity["rejections"]
