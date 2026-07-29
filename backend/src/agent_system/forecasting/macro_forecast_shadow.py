"""Shadow-mode BVAR ensemble macro forecast runner.

This module is deliberately observation-only. It may write shadow artifacts, but
it never feeds the live narrative forecast path or downstream agents.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    load_behavioral_scenarios,
    scenario_metadata,
)
from src.agent_system.forecasting.bvar_ensemble.bounds import validate_registry_bounds
from src.agent_system.forecasting.bvar_ensemble.estimation import (
    apply_config_overrides,
    load_bvar_config,
    newest_posterior_artifact,
    posterior_artifact_fingerprint,
    validate_posterior_cache_fingerprint,
)
from src.agent_system.forecasting.bvar_ensemble.forecast import run_forecast
from src.agent_system.forecasting.bvar_ensemble.garch import (
    newest_garch_artifact,
    validate_garch_matches_posterior,
)
from src.agent_system.forecasting.bvar_ensemble.regime_params import (
    newest_regime_artifact,
    validate_regime_matches_posterior,
)
from src.agent_system.forecasting.scenario_classifier.config import load_classifier_config
from src.agent_system.forecasting.scenario_classifier.registry import VariableRegistry
from src.agent_system.paths import agent_system_data_root


logger = logging.getLogger(__name__)


class ShadowForecastResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_path: str
    cycle_id: str
    cycle_date: str
    asof_quarter: str
    generated_at: str
    scenario_probabilities: dict[str, float]
    scenario_probabilities_soft: dict[str, float] = Field(default_factory=dict)
    regime_stress_gauge: dict[str, Any] = Field(default_factory=dict)
    margin_stats: dict[str, Any] = Field(default_factory=dict)
    model_limitations: dict[str, Any] = Field(default_factory=dict)
    scenario_metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    ensemble_config: dict[str, Any] = Field(default_factory=dict)
    source_forecast: dict[str, Any] = Field(default_factory=dict)


def shadow_forecast_dir() -> Path:
    path = agent_system_data_root() / "shadow_forecasts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cycle_date_to_asof_quarter(cycle_date: str | date | datetime) -> str:
    """Map a cycle date to the most recent complete calendar quarter."""

    if isinstance(cycle_date, datetime):
        dt = cycle_date.date()
    elif isinstance(cycle_date, date):
        dt = cycle_date
    else:
        try:
            dt = date.fromisoformat(str(cycle_date)[:10])
        except ValueError as exc:
            raise ValueError(f"cycle_date must be YYYY-MM-DD; got {cycle_date!r}") from exc

    quarter = ((dt.month - 1) // 3) + 1
    quarter_end_month = quarter * 3
    if dt.month == quarter_end_month:
        if quarter_end_month == 3:
            quarter_end_day = 31
        elif quarter_end_month == 6:
            quarter_end_day = 30
        elif quarter_end_month == 9:
            quarter_end_day = 30
        else:
            quarter_end_day = 31
        current_quarter_complete = dt.day >= quarter_end_day
    else:
        current_quarter_complete = dt.month > quarter_end_month

    if current_quarter_complete:
        return f"{dt.year}Q{quarter}"
    if quarter == 1:
        return f"{dt.year - 1}Q4"
    return f"{dt.year}Q{quarter - 1}"


def run_shadow_forecast(
    cycle_id: str,
    cycle_date: str,
    asof_quarter: str,
    *,
    classifier_cache_dir: str | Path | None = None,
    bvar_cache_dir: str | Path | None = None,
    handoff_dir: str | Path | None = None,
) -> ShadowForecastResult | None:
    """Run the frozen BVAR ensemble in shadow mode.

    Critical isolation guarantee: all failures are logged and swallowed. The
    caller receives None and the live research cycle remains unaffected.
    """

    try:
        return _run_shadow_forecast(
            cycle_id=cycle_id,
            cycle_date=cycle_date,
            asof_quarter=asof_quarter,
            classifier_cache_dir=classifier_cache_dir,
            bvar_cache_dir=bvar_cache_dir,
            handoff_dir=handoff_dir,
        )
    except Exception as exc:
        logger.warning(
            "SHADOW MODE: BVAR ensemble shadow forecast failed "
            "(non-fatal, live path unaffected): %s",
            exc,
            exc_info=True,
        )
        return None


def _run_shadow_forecast(
    *,
    cycle_id: str,
    cycle_date: str,
    asof_quarter: str,
    classifier_cache_dir: str | Path | None,
    bvar_cache_dir: str | Path | None,
    handoff_dir: str | Path | None,
) -> ShadowForecastResult:
    registry = VariableRegistry.load()
    validate_registry_bounds(registry)
    config = load_bvar_config()
    # Shadow mode freezes the validated ensemble configuration, independent of
    # any diagnostic CLI overrides used elsewhere.
    config = apply_config_overrides(
        config,
        vol_model="garch",
        regime_model="markov",
        shock_dist="student_t",
    )
    classifier_config = load_classifier_config(
        horizon_quarters=int(config["horizon"]),
        baseline_mode=None,
    )
    runtime_config = dict(config)
    runtime_config["kernel_sigma"] = float(classifier_config["kernel_sigma"])

    posterior = newest_posterior_artifact(bvar_cache_dir=bvar_cache_dir)
    validate_posterior_cache_fingerprint(
        posterior,
        cache_dir=classifier_cache_dir,
    )
    garch_artifact = newest_garch_artifact(posterior, bvar_cache_dir=bvar_cache_dir)
    validate_garch_matches_posterior(garch_artifact, posterior)
    regime_artifact = newest_regime_artifact(posterior, bvar_cache_dir=bvar_cache_dir)
    validate_regime_matches_posterior(regime_artifact, posterior)

    forecast_path, paths_path, forecast, _classifications = run_forecast(
        registry,
        posterior,
        runtime_config,
        classifier_cache_dir=classifier_cache_dir,
        bvar_cache_dir=bvar_cache_dir,
        handoff_dir=handoff_dir,
        asof_quarter=asof_quarter,
        n_paths=int(config["n_paths"]),
        horizon=int(config["horizon"]),
        seed=int(config["seed"]),
        shock_dist=str(config["shock_dist"]),
        t_dof=int(config["t_dof"]),
        draw_coefficients=False,
        baseline_mode=str(classifier_config["baseline_mode"]),
        vol_model="garch",
        garch_artifact=garch_artifact,
        regime_model="markov",
        regime_artifact=regime_artifact,
    )

    scenarios = load_behavioral_scenarios()
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = shadow_forecast_dir() / f"shadow_forecast_{cycle_date}_{timestamp}.json"
    result_payload: dict[str, Any] = {
        "mode": "SHADOW_MODE",
        "consumed_by_live_pipeline": False,
        "cycle_id": cycle_id,
        "cycle_date": cycle_date,
        "asof_quarter": forecast.get("asof_quarter", asof_quarter),
        "generated_at": generated_at,
        "scenario_probabilities": forecast.get("scenario_probabilities") or {},
        "scenario_probabilities_soft": forecast.get("scenario_probabilities_soft") or {},
        "regime_stress_gauge": {
            "anchor_label": forecast.get("regime_anchor_label"),
            "anchor_p_enter": forecast.get("regime_anchor_p_enter"),
            "fraction_entered_stress": forecast.get("regime_fraction_entered_stress"),
            "fraction_ever_stress": forecast.get("regime_fraction_ever_stress"),
            "avg_quarters_in_stress": forecast.get("regime_avg_quarters_in_stress"),
        },
        "margin_stats": forecast.get("margin_stats") or {},
        "model_limitations": forecast.get("model_limitations") or {},
        "scenario_metadata": scenario_metadata(scenarios),
        "provenance": {
            "cycle_id": cycle_id,
            "bvar_forecast_artifact": str(forecast_path),
            "classifier_paths_parquet": str(paths_path),
            "simulation_paths_parquet": forecast.get("simulation_paths_parquet"),
            "posterior_artifact": forecast.get("posterior_artifact"),
            "posterior_artifact_fingerprint": forecast.get("posterior_artifact_fingerprint")
            or posterior_artifact_fingerprint(posterior.path),
            "garch_artifact": (forecast.get("garch_diagnostics") or {}).get("garch_artifact"),
            "garch_posterior_fingerprint": (forecast.get("garch_diagnostics") or {}).get("posterior_fingerprint"),
            "regime_artifact": (forecast.get("regime_artifact_metadata") or {}).get("regime_artifact"),
            "regime_posterior_fingerprint": (forecast.get("regime_artifact_metadata") or {}).get("posterior_fingerprint"),
            "handoff_fingerprint": forecast.get("handoff_fingerprint"),
            "handoff_file": forecast.get("handoff_file"),
        },
        "ensemble_config": {
            "horizon_quarters": forecast.get("horizon_quarters"),
            "baseline_mode": forecast.get("baseline_mode"),
            "shock_dist": forecast.get("shock_dist"),
            "vol_model": forecast.get("vol_model"),
            "regime_model": forecast.get("regime_model"),
            "seed": forecast.get("seed"),
            "n_paths": forecast.get("n_paths"),
            "config": forecast.get("config") or {},
        },
        "source_forecast": {
            "asof_quarter": forecast.get("asof_quarter"),
            "generated_at": forecast.get("generated_at"),
            "paths_parquet": forecast.get("paths_parquet"),
        },
    }
    result_payload["artifact_path"] = str(output_path)
    output_path.write_text(
        json.dumps(result_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("SHADOW MODE: wrote BVAR shadow forecast artifact %s", output_path)
    return ShadowForecastResult.model_validate(result_payload)
