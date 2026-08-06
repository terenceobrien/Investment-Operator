from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import macro_router
from src.agent_system.paths import analogue_fans_dir, macro_json_dir


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _forecast(path_value: str) -> dict:
    return {
        "asof_date": "2026-08-04",
        "created_at": "2026-08-05T00:00:00Z",
        "probability_mode": "two_source_v1",
        "scenario_probabilities": {"late_cycle_expansion": 1.0},
        "mixture_report": {"analogue_fan_artifact_path": path_value},
    }


def _body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_latest_analogue_fan_resolves_data_root_relative_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    fan_path = _write_json(
        analogue_fans_dir(create=True) / "analogue_fan_2026Q2.json",
        {"query_date": "2026Q2", "horizon_quarters": 8, "variables": {}},
    )
    _write_json(
        macro_json_dir(create=True) / "macro_forecast_two_source.json",
        _forecast("agent_system/reports/macro_forecasts/analogue_fans/analogue_fan_2026Q2.json"),
    )

    response = asyncio.run(macro_router.latest_analogue_fan(user={}))
    payload = _body(response)

    assert payload["query_date"] == "2026Q2"
    assert payload["asof_metadata"]["artifact_path"] == str(fan_path)


def test_latest_analogue_fan_resolves_legacy_absolute_path_by_basename(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    fan_path = _write_json(
        analogue_fans_dir(create=True) / "analogue_fan_2026Q2.json",
        {"query_date": "2026Q2", "horizon_quarters": 8, "variables": {}},
    )
    legacy_path = "/Users/someone/local/backend/data/agent_system/reports/macro_forecasts/analogue_fans/analogue_fan_2026Q2.json"
    _write_json(
        macro_json_dir(create=True) / "macro_forecast_two_source.json",
        _forecast(legacy_path),
    )

    with caplog.at_level("INFO"):
        response = asyncio.run(macro_router.latest_analogue_fan(user={}))
    payload = _body(response)

    assert payload["asof_metadata"]["artifact_path"] == str(fan_path)
    assert any("legacy absolute analogue fan artifact path" in record.message for record in caplog.records)


def test_latest_analogue_fan_missing_artifact_404_names_candidate_source_and_command(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    _write_json(
        macro_json_dir(create=True) / "macro_forecast_two_source.json",
        _forecast("agent_system/reports/macro_forecasts/analogue_fans/missing_fan.json"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(macro_router.latest_analogue_fan(user={}))

    detail = str(exc.value.detail)
    assert exc.value.status_code == 404
    assert str(analogue_fans_dir(create=False) / "missing_fan.json") in detail
    assert "resolution_source=env:HELIX_DATA_ROOT" in detail
    assert "macro_forecast_runner" in detail
