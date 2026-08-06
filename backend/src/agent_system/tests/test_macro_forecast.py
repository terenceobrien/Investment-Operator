from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agent_system.forecasting import macro_forecast_runner as runner
from src.agent_system.forecasting.macro_forecast_runner import (
    MacroForecastRunnerError,
    _apply_yaml_priors_override,
    default_scenario_set,
    format_macro_forecast_report,
    load_latest_bvar_forecast,
    run_macro_forecast,
)
from src.agent_system.forecasting.theme_exposure_matrix import rank_themes
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.macro_forecast import HistoricalCalibrationConfig

from two_source_fixtures import (
    BEHAVIORAL_IDS,
    analogue_evidence_fixture,
    behavioral_probabilities,
    patch_two_source_runner,
)


def _forecast_payload(
    *,
    asof_quarter: str,
    probabilities: dict[str, float] | None = None,
    map_version: str = "behavioral-v1-test",
    scenario_ids: list[str] | None = None,
    generated_at: str = "2026-08-01T00:00:00Z",
) -> dict:
    soft = probabilities or behavioral_probabilities()
    return {
        "asof_quarter": asof_quarter,
        "generated_at": generated_at,
        "scenario_probabilities_soft": soft,
        "classifier_metadata": {
            "map_version": map_version,
            "scenario_ids": scenario_ids or list(BEHAVIORAL_IDS),
        },
        "handoff_fingerprint": "test-fingerprint",
        "model_limitations": {"credit_tail_magnitude": "conservative"},
    }


def _write_forecast(tmp_path: Path, payload: dict, name: str = "forecast_test.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_run_macro_forecast_uses_two_source_mixture(monkeypatch):
    patch_two_source_runner(monkeypatch, runner)

    result = run_macro_forecast(make_stub_regime_state())

    assert result.probability_mode == "two_source_v1"
    assert result.scenario_updates == []
    assert set(result.scenario_probabilities) == set(BEHAVIORAL_IDS)
    assert sum(result.scenario_probabilities.values()) == pytest.approx(1.0)
    assert result.mixture_report["combination"] == "linear_mixture"
    assert "analogue_fan" in result.mixture_report
    assert result.outputs["analogue_fan_json_path"].endswith("analogue_fan_2026Q2.json")
    assert result.outputs["analogue_fan_grid_png_path"].endswith("analogue_fan_2026Q2_grid.png")
    assert result.outputs["analogue_fan_credit_spread_png_path"].endswith("analogue_fan_2026Q2_credit_spread.png")
    assert result.bvar_provenance["model_limitations"]["credit_tail_magnitude"] == "conservative"
    assert result.theme_rankings
    assert result.sector_rankings
    assert result.factor_rankings
    assert result.recommended_research_priorities
    assert all(signal.display_only for signal in result.input_signals)
    assert all(not signal.used_in_probability_update for signal in result.input_signals)


def test_report_shows_mixture_and_monitoring_only_sections(monkeypatch):
    patch_two_source_runner(
        monkeypatch,
        runner,
        evidence=analogue_evidence_fixture(trailing_max=0.42, stress_advisory=True),
    )
    result = run_macro_forecast(make_stub_regime_state())

    report = format_macro_forecast_report(result)

    assert "BVAR Soft | Analogue Implied | Mixed Pre-Floor | Final" in report
    assert "Probability mode: two_source_v1" in report
    assert "Monitoring — no probability impact" in report
    assert "credit_tail_magnitude: conservative" in report
    assert "Legacy rolling historical calibration is retired" in report


def test_fan_chart_render_failure_warns_but_keeps_json(monkeypatch):
    patch_two_source_runner(monkeypatch, runner)

    def fail_render(_fan, _output_dir):
        raise RuntimeError("matplotlib cache unavailable")

    monkeypatch.setattr(runner, "render_fan_charts", fail_render)

    result = run_macro_forecast(make_stub_regime_state())

    assert "analogue_fan_json_path" in result.outputs
    assert "analogue_fan_grid_png_path" not in result.outputs
    assert any(
        "Analogue fan chart rendering failed" in warning
        for warning in result.bvar_provenance["warnings"]
    )


def test_bvar_loader_selects_newest_by_generated_at_and_allows_stale(tmp_path):
    old = _forecast_payload(
        asof_quarter="2026Q1",
        generated_at="2026-01-01T00:00:00Z",
    )
    newest = _forecast_payload(
        asof_quarter="2026Q2",
        generated_at="2026-07-31T00:00:00Z",
    )
    _write_forecast(tmp_path, old, "forecast_2026Q1_old.json")
    newest_path = _write_forecast(tmp_path, newest, "forecast_2026Q2_new.json")

    artifact = load_latest_bvar_forecast(tmp_path, allow_stale=True)

    assert artifact.path == newest_path
    assert artifact.asof_quarter == "2026Q2"
    assert artifact.soft_probabilities == pytest.approx(newest["scenario_probabilities_soft"])
    assert artifact.provenance["warnings"]


def test_bvar_loader_validation_errors_are_fail_loud(tmp_path):
    current_quarter = runner._current_calendar_quarter_text()

    missing_soft = _forecast_payload(asof_quarter=current_quarter)
    missing_soft.pop("scenario_probabilities_soft")
    _write_forecast(tmp_path, missing_soft, "forecast_missing_soft.json")
    with pytest.raises(MacroForecastRunnerError, match="scenario_probabilities_soft"):
        load_latest_bvar_forecast(tmp_path)

    wrong_set_dir = tmp_path / "wrong_set"
    wrong_set_dir.mkdir()
    wrong_set = _forecast_payload(asof_quarter=current_quarter)
    wrong_set["scenario_probabilities_soft"] = {"credit_led_recession": 1.0}
    _write_forecast(wrong_set_dir, wrong_set)
    with pytest.raises(MacroForecastRunnerError, match="scenario set mismatch"):
        load_latest_bvar_forecast(wrong_set_dir)

    bad_version_dir = tmp_path / "bad_version"
    bad_version_dir.mkdir()
    bad_version = _forecast_payload(asof_quarter=current_quarter, map_version="narrative-v0")
    _write_forecast(bad_version_dir, bad_version)
    with pytest.raises(MacroForecastRunnerError, match="map_version mismatch"):
        load_latest_bvar_forecast(bad_version_dir)

    stale_dir = tmp_path / "stale"
    stale_dir.mkdir()
    _write_forecast(stale_dir, _forecast_payload(asof_quarter="2026Q1"))
    with pytest.raises(MacroForecastRunnerError, match="STALE BVAR forecast"):
        load_latest_bvar_forecast(stale_dir, allow_stale=False)


def test_theme_ranking_defaults_to_behavioral_taxonomy_and_fails_on_narrative_ids():
    rankings = rank_themes(behavioral_probabilities(), [])

    assert rankings
    assert all(
        contribution.scenario_id in BEHAVIORAL_IDS
        for ranking in rankings
        for contribution in ranking.scenario_contributions
    )
    with pytest.raises(ValueError, match="missing from behavioral_v1 exposure matrix"):
        rank_themes({"reopening_soft_landing": 1.0}, [])


def test_retired_probability_paths_fail_loud(monkeypatch):
    patch_two_source_runner(monkeypatch, runner)
    result = run_macro_forecast(make_stub_regime_state())

    with pytest.raises(MacroForecastRunnerError, match="two_source_v1 rewire"):
        default_scenario_set()
    with pytest.raises(MacroForecastRunnerError, match="two_source_v1 rewire"):
        _apply_yaml_priors_override(result, None, make_stub_regime_state())  # type: ignore[arg-type]
    with pytest.raises(MacroForecastRunnerError, match="HistoricalCalibrationConfig"):
        run_macro_forecast(
            make_stub_regime_state(),
            historical_calibration_config=HistoricalCalibrationConfig(enabled=True),
        )
