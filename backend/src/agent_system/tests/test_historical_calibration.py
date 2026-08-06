from __future__ import annotations

import pytest

from src.agent_system.forecasting import macro_forecast_runner as runner
from src.agent_system.forecasting.macro_forecast_runner import (
    MacroForecastRunConfig,
    MacroForecastRunnerError,
    run_macro_forecast,
)
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.macro_forecast import (
    HistoricalCalibrationConfig,
    HistoricalCalibrationResult,
)

from two_source_fixtures import patch_two_source_runner


def test_legacy_historical_calibration_config_is_not_a_runner_input(monkeypatch):
    patch_two_source_runner(monkeypatch, runner)

    with pytest.raises(MacroForecastRunnerError, match="HistoricalCalibrationConfig"):
        run_macro_forecast(
            make_stub_regime_state(),
            historical_calibration_config=HistoricalCalibrationConfig(enabled=True),
        )


def test_run_config_historical_config_helper_is_retired():
    with pytest.raises(MacroForecastRunnerError, match="two_source_v1 rewire"):
        MacroForecastRunConfig().historical_config()


def test_old_historical_calibration_results_remain_schema_readable():
    payload = {
        "enabled": True,
        "method": "rolling_composite",
        "asof_date": "2026-06-05",
        "conditions_summary": "legacy artifact",
        "n_analogues": 0,
        "confidence": 0.0,
        "warnings": ["legacy path retired from live runner"],
    }

    parsed = HistoricalCalibrationResult.model_validate(payload)

    assert parsed.enabled is True
    assert parsed.method == "rolling_composite"
    assert parsed.warnings == ["legacy path retired from live runner"]
