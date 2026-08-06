from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.agent_system.forecasting.current_regime_export import (
    CurrentRegimeExportError,
    build_current_regime_handoff,
    build_current_regime_handoff_from_macro_source,
    save_current_regime_yaml,
)
from src.agent_system.forecasting.macro_scenario_source import (
    MacroScenarioSourceConfig,
    get_macro_scenario_source,
)
from src.agent_system.schemas.current_regime import CurrentRegimeHandoff
from src.agent_system.schemas.macro_forecast import MacroForecastResult

from two_source_fixtures import BEHAVIORAL_IDS, behavioral_probabilities


def _write_bvar_forecast(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "forecast_2026Q2_test.json"
    probabilities = behavioral_probabilities()
    path.write_text(
        json.dumps(
            {
                "asof_quarter": "2026Q2",
                "generated_at": "2026-07-31T00:00:00Z",
                "scenario_probabilities_soft": probabilities,
                "classifier_metadata": {
                    "map_version": "behavioral-v1-test",
                    "scenario_ids": list(BEHAVIORAL_IDS),
                },
                "handoff_fingerprint": "test-fingerprint",
                "model_limitations": {"credit_tail_magnitude": "conservative"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _handoff(tmp_path: Path) -> CurrentRegimeHandoff:
    _write_bvar_forecast(tmp_path)
    source = get_macro_scenario_source(
        cycle_date="2026-06-30",
        config=MacroScenarioSourceConfig(
            macro_forecast_source="ensemble",
            bvar_cache_dir=tmp_path,
            analogue_evidence_enabled=False,
        ),
    )
    return build_current_regime_handoff_from_macro_source(source)


def test_current_regime_schema_loads_reference_yaml():
    path = Path(__file__).resolve().parents[1] / "config" / "current_regime.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    handoff = CurrentRegimeHandoff.model_validate(payload)

    assert handoff.regime_id
    assert handoff.key_drivers
    assert handoff.seed_research_priorities
    assert isinstance(handoff.seed_research_priorities[0].sub_questions, list)


def test_legacy_current_regime_builder_is_retired():
    with pytest.raises(CurrentRegimeExportError, match="two_source_v1 rewire"):
        build_current_regime_handoff(
            MacroForecastResult(
                asof_date="2026-06-05",
                horizon="3m",
                scenario_probabilities=behavioral_probabilities(),
            )
        )


def test_build_current_regime_handoff_from_macro_source_is_behavioral(tmp_path):
    handoff = _handoff(tmp_path)

    assert handoff.scenario_taxonomy == "behavioral_v1"
    assert set(handoff.scenario_probabilities) == set(BEHAVIORAL_IDS)
    assert handoff.probability_decomposition
    assert handoff.analogue_evidence["enabled"] is False
    payload = handoff.model_dump(mode="json")
    payload_text = json.dumps(payload, sort_keys=True)
    for narrative_id in (
        "reopening_soft_landing",
        "sticky_late_cycle_ai",
        "oil_inflation_tail",
        "late_cycle_risk_off",
        "ai_capex_rollover",
    ):
        assert narrative_id not in payload_text


def test_save_current_regime_yaml_uses_report_dir_and_preserves_key_order(tmp_path):
    handoff = _handoff(tmp_path / "bvar")

    path = save_current_regime_yaml(handoff, output_dir=tmp_path, asof_date="2026-06-05")

    assert path == tmp_path / "current_regime_2026-06-05.yaml"
    assert path.exists()
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert payload["scenario_taxonomy"] == "behavioral_v1"
    assert set(payload["scenario_probabilities"]) == set(BEHAVIORAL_IDS)
    first_keys = [
        line.split(":", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith(" ")
    ]
    assert first_keys[:6] == [
        "regime_id",
        "regime_label",
        "regime_call_confidence",
        "headline",
        "summary",
        "risk_summary",
    ]


def test_save_current_regime_yaml_does_not_overwrite_by_default(tmp_path):
    handoff = _handoff(tmp_path / "bvar")
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
    handoff = _handoff(tmp_path / "bvar")
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
    assert path.exists()
