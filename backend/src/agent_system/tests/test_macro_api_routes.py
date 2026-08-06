from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import macro_router


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _json_response_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_latest_macro_forecast_returns_newest_two_source_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_FORECAST_DIR", str(tmp_path))
    older = {
        "asof_date": "2026-07-31",
        "created_at": "2026-08-03T00:00:00Z",
        "probability_mode": "two_source_v1",
        "scenario_probabilities": {"late_cycle_expansion": 1.0},
        "mixture_report": {"analogue_fan_artifact_path": "unused.json"},
    }
    newer = {
        "asof_date": "2026-08-04",
        "created_at": "2026-08-05T00:00:00Z",
        "probability_mode": "two_source_v1",
        "scenario_probabilities": {"late_cycle_expansion": 1.0},
        "mixture_report": {"analogue_fan_artifact_path": "unused.json"},
    }
    _write_json(tmp_path / "macro_forecast_older.json", older)
    latest_path = _write_json(tmp_path / "macro_forecast_newer.json", newer)

    response = asyncio.run(macro_router.latest_macro_forecast(user={}))
    payload = _json_response_body(response)

    assert payload["asof_date"] == "2026-08-04"
    assert payload["probability_mode"] == "two_source_v1"
    assert payload["asof_metadata"]["artifact_path"] == str(latest_path)


def test_latest_macro_forecast_rejects_retired_probability_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_FORECAST_DIR", str(tmp_path))
    stale_path = _write_json(
        tmp_path / "macro_forecast_stale.json",
        {
            "asof_date": "2026-06-05",
            "created_at": "2026-08-05T00:00:00Z",
            "probability_mode": "historically_calibrated",
            "scenario_probabilities": {"reopening_soft_landing": 1.0},
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(macro_router.latest_macro_forecast(user={}))

    assert exc.value.status_code == 409
    assert str(stale_path) in str(exc.value.detail)
    assert "two_source_v1" in str(exc.value.detail)
    assert "macro_forecast_runner" in str(exc.value.detail)


def test_latest_analogue_fan_returns_referenced_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_FORECAST_DIR", str(tmp_path))
    fan_path = _write_json(
        tmp_path / "fan.json",
        {
            "query_date": "2026Q2",
            "horizon_quarters": 8,
            "variables": {},
        },
    )
    _write_json(
        tmp_path / "macro_forecast_two_source.json",
        {
            "asof_date": "2026-08-04",
            "created_at": "2026-08-05T00:00:00Z",
            "probability_mode": "two_source_v1",
            "scenario_probabilities": {"late_cycle_expansion": 1.0},
            "mixture_report": {"analogue_fan_artifact_path": str(fan_path)},
        },
    )

    response = asyncio.run(macro_router.latest_analogue_fan(user={}))
    payload = _json_response_body(response)

    assert payload["query_date"] == "2026Q2"
    assert payload["asof_metadata"]["artifact_path"] == str(fan_path)


def test_latest_analogue_fan_404s_when_artifact_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MACRO_FORECAST_DIR", str(tmp_path))
    _write_json(
        tmp_path / "macro_forecast_two_source.json",
        {
            "asof_date": "2026-08-04",
            "created_at": "2026-08-05T00:00:00Z",
            "probability_mode": "two_source_v1",
            "scenario_probabilities": {"late_cycle_expansion": 1.0},
            "mixture_report": {"analogue_fan_artifact_path": str(tmp_path / "missing.json")},
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(macro_router.latest_analogue_fan(user={}))

    assert exc.value.status_code == 404
    assert "Analogue fan artifact not found" in str(exc.value.detail)
    assert "macro_forecast_runner" in str(exc.value.detail)


def test_macro_scenario_meta_uses_behavioral_taxonomy():
    macro_router._behavioral_scenario_meta.cache_clear()

    response = asyncio.run(macro_router.macro_scenario_meta(user={}))
    payload = _json_response_body(response)

    assert set(payload) == {
        "expansion_disinflation",
        "late_cycle_expansion",
        "inflation_shock",
        "stagflation",
        "growth_scare_no_credit",
        "credit_led_recession",
    }
    assert payload["credit_led_recession"]["display_name"]
    assert payload["credit_led_recession"]["short_description"]
