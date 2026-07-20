from __future__ import annotations

from pathlib import Path

import yaml

from src.agent_system.forecasting.current_regime_export import (
    build_current_regime_handoff,
    save_current_regime_yaml,
)
from src.agent_system.forecasting.macro_forecast_runner import run_macro_forecast
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.current_regime import CurrentRegimeHandoff
from src.agent_system.schemas.macro_forecast import HistoricalCalibrationConfig


def _forecast_result():
    return run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(enabled=False),
    )


def test_current_regime_schema_loads_reference_yaml():
    path = Path("backend/src/agent_system/config/current_regime.yaml")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    handoff = CurrentRegimeHandoff.model_validate(payload)

    assert handoff.regime_id == "two_sided_oil_shock_late_cycle_ai"
    assert handoff.key_drivers
    assert handoff.seed_research_priorities
    assert isinstance(handoff.seed_research_priorities[0].sub_questions, list)


def test_build_current_regime_handoff_from_forecast_result():
    result = _forecast_result()

    handoff = build_current_regime_handoff(result)

    assert handoff.regime_id
    assert handoff.regime_label
    assert 0.0 <= handoff.regime_call_confidence <= 1.0
    assert handoff.headline == result.forecast_interpretation.headline
    assert "Dominant scenario:" in handoff.summary
    assert handoff.scenario_probabilities == result.scenario_probabilities
    assert handoff.key_drivers
    assert handoff.portfolio_implications
    assert handoff.best_positioned
    assert handoff.most_vulnerable
    assert handoff.falsifiers
    assert handoff.seed_research_priorities


def test_save_current_regime_yaml_uses_report_dir_and_preserves_key_order(tmp_path):
    handoff = build_current_regime_handoff(_forecast_result())

    path = save_current_regime_yaml(handoff, output_dir=tmp_path, asof_date="2026-06-05")

    assert path == tmp_path / "current_regime_2026-06-05.yaml"
    assert path.exists()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["regime_id"] == handoff.regime_id
    first_keys = [line.split(":", 1)[0] for line in path.read_text(encoding="utf-8").splitlines() if line and not line.startswith(" ")]
    assert first_keys[:6] == [
        "regime_id",
        "regime_label",
        "regime_call_confidence",
        "headline",
        "summary",
        "risk_summary",
    ]


def test_save_current_regime_yaml_does_not_overwrite_by_default(tmp_path):
    handoff = build_current_regime_handoff(_forecast_result())
    first = save_current_regime_yaml(handoff, output_dir=tmp_path, asof_date="2026-06-05")
    first.write_text("sentinel: true\n", encoding="utf-8")

    second = save_current_regime_yaml(
        handoff,
        output_dir=tmp_path,
        asof_date="2026-06-05",
        timestamp="050316",
    )

    assert second == tmp_path / "current_regime_2026-06-05_050316.yaml"
    assert first.read_text(encoding="utf-8") == "sentinel: true\n"
    assert second.exists()


def test_save_current_regime_yaml_manual_output_path_collision(tmp_path):
    handoff = build_current_regime_handoff(_forecast_result())
    requested = tmp_path / "handoff.yaml"
    requested.write_text("sentinel: true\n", encoding="utf-8")

    path = save_current_regime_yaml(
        handoff,
        output_dir=tmp_path,
        asof_date="2026-06-05",
        output_path=requested,
        timestamp="101112",
    )

    assert path == tmp_path / "handoff_101112.yaml"
    assert requested.read_text(encoding="utf-8") == "sentinel: true\n"
