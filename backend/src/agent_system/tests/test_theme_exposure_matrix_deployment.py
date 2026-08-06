from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest

from src.agent_system.forecasting.behavioral_scenarios_loader import (
    EXPECTED_BEHAVIORAL_SCENARIO_IDS,
)


@pytest.fixture(autouse=True)
def clear_behavioral_exposure_cache():
    yield
    from src.agent_system.forecasting import theme_exposure_matrix

    theme_exposure_matrix._behavioral_exposure_bundle.cache_clear()


def _write_fixture_returns_csv(data_root: Path) -> Path:
    path = data_root / "reference" / "scenario_theme_returns.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        "scenario_id,theme_id,expected_return",
        *[
            f"{scenario_id},fixture_theme,0.07"
            for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS
        ],
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_theme_exposure_import_succeeds_when_behavioral_csv_is_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))

    from src.agent_system.forecasting import theme_exposure_matrix

    module = importlib.reload(theme_exposure_matrix)
    assert module.SCENARIO_THEME_EXPOSURES_BEHAVIORAL is not None

    with pytest.raises(FileNotFoundError) as exc:
        module.get_scenario_theme_exposures("behavioral_v1")

    message = str(exc.value)
    assert str(tmp_path / "reference" / "scenario_theme_returns.csv") in message
    assert "resolution_source=env:HELIX_DATA_ROOT" in message


def test_lazy_behavioral_exposure_matrix_matches_fixture_build(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    _write_fixture_returns_csv(tmp_path)

    from src.agent_system.forecasting import theme_exposure_matrix

    module = importlib.reload(theme_exposure_matrix)
    expected_matrix = module._build_behavioral_exposure_matrix()[0]
    module._behavioral_exposure_bundle.cache_clear()

    lazy_matrix = module.get_scenario_theme_exposures("behavioral_v1")

    assert lazy_matrix == expected_matrix
    assert {
        scenario_id: exposures["fixture_theme"]
        for scenario_id, exposures in lazy_matrix.items()
    } == {
        scenario_id: 3.0
        for scenario_id in EXPECTED_BEHAVIORAL_SCENARIO_IDS
    }


def test_startup_health_check_logs_missing_artifacts_without_raising(tmp_path, monkeypatch, caplog):
    import api.data_artifact_health as artifact_health

    missing = tmp_path / "missing.csv"
    monkeypatch.setattr(
        artifact_health,
        "required_data_artifacts",
        lambda: [
            artifact_health.DataArtifactCheck(
                name="fixture_missing_csv",
                path=missing,
                resolution_source="test:fixture",
            )
        ],
    )

    with caplog.at_level(logging.WARNING, logger="api.main"):
        artifact_health.log_required_data_artifact_health()

    assert any(
        "startup data artifact missing" in record.message
        and "fixture_missing_csv" in record.message
        and str(missing) in record.message
        and "test:fixture" in record.message
        for record in caplog.records
    )
