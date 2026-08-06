from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from api import macro_router
from src.agent_system.paths import analogue_fans_dir, macro_json_dir


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _json_response_body(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def test_latest_macro_forecast_returns_newest_two_source_artifact(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    forecast_dir = macro_json_dir(create=True)
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
    _write_json(forecast_dir / "macro_forecast_older.json", older)
    latest_path = _write_json(forecast_dir / "macro_forecast_newer.json", newer)

    response = asyncio.run(macro_router.latest_macro_forecast(user={}))
    payload = _json_response_body(response)

    assert payload["asof_date"] == "2026-08-04"
    assert payload["probability_mode"] == "two_source_v1"
    assert payload["asof_metadata"]["artifact_path"] == str(latest_path)


def test_latest_macro_forecast_rejects_retired_probability_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    forecast_dir = macro_json_dir(create=True)
    stale_path = _write_json(
        forecast_dir / "macro_forecast_stale.json",
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
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    forecast_dir = macro_json_dir(create=True)
    fan_dir = analogue_fans_dir(create=True)
    fan_path = _write_json(
        fan_dir / "fan.json",
        {
            "query_date": "2026Q2",
            "horizon_quarters": 8,
            "variables": {},
        },
    )
    _write_json(
        forecast_dir / "macro_forecast_two_source.json",
        {
            "asof_date": "2026-08-04",
            "created_at": "2026-08-05T00:00:00Z",
            "probability_mode": "two_source_v1",
            "scenario_probabilities": {"late_cycle_expansion": 1.0},
            "mixture_report": {
                "analogue_fan_artifact_path": "agent_system/reports/macro_forecasts/analogue_fans/fan.json"
            },
        },
    )

    response = asyncio.run(macro_router.latest_analogue_fan(user={}))
    payload = _json_response_body(response)

    assert payload["query_date"] == "2026Q2"
    assert payload["asof_metadata"]["artifact_path"] == str(fan_path)


def test_latest_analogue_fan_404s_when_artifact_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    forecast_dir = macro_json_dir(create=True)
    _write_json(
        forecast_dir / "macro_forecast_two_source.json",
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
    assert "resolution_source=env:HELIX_DATA_ROOT" in str(exc.value.detail)


def test_latest_macro_forecast_404_names_resolved_json_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(macro_router.latest_macro_forecast(user={}))

    assert exc.value.status_code == 404
    assert str(macro_json_dir(create=False)) in str(exc.value.detail)
    assert "resolution_source=env:HELIX_DATA_ROOT" in str(exc.value.detail)


def test_latest_macro_forecast_falls_back_to_mtime_when_created_at_missing(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("HELIX_DATA_ROOT", str(tmp_path))
    forecast_dir = macro_json_dir(create=True)
    old_path = _write_json(
        forecast_dir / "macro_forecast_without_created_at.json",
        {
            "asof_date": "2026-07-31",
            "probability_mode": "two_source_v1",
            "scenario_probabilities": {"late_cycle_expansion": 1.0},
            "mixture_report": {"analogue_fan_artifact_path": "unused.json"},
        },
    )
    new_path = _write_json(
        forecast_dir / "macro_forecast_with_created_at.json",
        {
            "asof_date": "2026-08-04",
            "created_at": "2026-08-05T00:00:00Z",
            "probability_mode": "two_source_v1",
            "scenario_probabilities": {"late_cycle_expansion": 1.0},
            "mixture_report": {"analogue_fan_artifact_path": "unused.json"},
        },
    )
    os.utime(old_path, (1, 1))

    with caplog.at_level("WARNING"):
        response = asyncio.run(macro_router.latest_macro_forecast(user={}))

    payload = _json_response_body(response)
    assert payload["asof_metadata"]["artifact_path"] == str(new_path)
    assert any("falling back to mtime" in record.message for record in caplog.records)


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


def _history_series(column: str, values: list[tuple[str, float]], source: str = "fixture") -> dict:
    return {
        "column": column,
        "source": source,
        "points": [{"date": date, "value": value} for date, value in values],
    }


def test_macro_layers_detail_shape_sort_and_contribution(monkeypatch):
    monkeypatch.setattr(
        macro_router,
        "_load_latest_regime_state_dict",
        lambda: {
            "asof_date": "2026-02-02",
            "layer_monetary": 5.5,
            "layer_credit": 6.0,
            "layer_volatility": 6.0,
            "layer_breadth": 6.0,
            "layer_positioning": 6.0,
            "layer_statuses": {
                "monetary": "neutral",
                "credit": "bullish",
                "volatility": "bullish",
                "breadth": "neutral",
                "positioning": "neutral",
            },
            "net_liquidity_z": 1.2,
            "nfci_inverted": -0.4,
            "m2_growth_yoy": 2.0,
            "fci_z": 0.3,
        },
    )
    monkeypatch.setattr(
        macro_router,
        "_build_indicator_history_payload",
        lambda days: {
            "start_date": "2026-01-01",
            "end_date": "2026-02-02",
            "source_counts": {"regime_timeseries": 5, "backtest_master_file": 0},
            "warnings": [],
            "series": {
                "net_liquidity_z": _history_series("net_liquidity_z", [("2026-01-01", -1.0), ("2026-02-02", 1.2)]),
                "nfci_inverted": _history_series("nfci_inverted", [("2026-01-01", 0.2), ("2026-02-02", -0.4)]),
                "m2_growth_yoy": _history_series("m2_growth_yoy", [("2026-01-01", 1.7), ("2026-02-02", 2.0)]),
                "fci_z": _history_series("fci_z", [("2026-01-01", 0.1), ("2026-02-02", 0.3)]),
                "layer_monetary": _history_series("layer_monetary", [("2026-01-01", 4.5), ("2026-02-02", 5.5)]),
            },
        },
    )

    response = asyncio.run(macro_router.macro_layers_detail(user={}))
    payload = _json_response_body(response)
    monetary = next(layer for layer in payload["layers"] if layer["layer_id"] == "monetary")

    assert payload["asof"] == "2026-02-02"
    assert monetary["display_name"] == "Monetary & Liquidity"
    assert monetary["delta_1m"] == pytest.approx(1.0)
    assert monetary["components"]
    non_null_changes = [
        abs(component["change_contribution_1m"])
        for component in monetary["components"]
        if component["change_contribution_1m"] is not None
    ]
    assert non_null_changes == sorted(non_null_changes, reverse=True)
    first = monetary["components"][0]
    assert first["contribution"] == pytest.approx(first["weight"] * first["component_score"])
    assert first["change_contribution_1m"] == pytest.approx(first["weight"] * first["delta_1m"])


def test_macro_component_history_returns_raw_score_and_layer_overlay(monkeypatch):
    monkeypatch.setattr(
        macro_router,
        "_build_indicator_history_payload",
        lambda days: {
            "start_date": "2026-01-01",
            "end_date": "2026-02-02",
            "source_counts": {"regime_timeseries": 2, "backtest_master_file": 0},
            "warnings": [],
            "series": {
                "net_liquidity_z": _history_series("net_liquidity_z", [("2026-01-01", -1.0), ("2026-02-02", 1.2)]),
                "layer_monetary": _history_series("layer_monetary", [("2026-01-01", 4.5), ("2026-02-02", 5.5)]),
            },
        },
    )

    response = asyncio.run(
        macro_router.macro_layer_component_history(
            "monetary",
            "net_liquidity_z",
            window="90d",
            user={},
        )
    )
    payload = _json_response_body(response)

    assert payload["component_id"] == "net_liquidity_z"
    assert payload["series"][0]["value"] == -1.0
    assert payload["series"][0]["component_score"] is not None
    assert payload["layer_score_series"] == [
        {"date": "2026-01-01", "score": 4.5},
        {"date": "2026-02-02", "score": 5.5},
    ]


def test_macro_component_history_404s_when_history_missing(monkeypatch):
    monkeypatch.setattr(
        macro_router,
        "_build_indicator_history_payload",
        lambda days: {
            "start_date": None,
            "end_date": None,
            "source_counts": {"regime_timeseries": 0, "backtest_master_file": 0},
            "warnings": ["fixture history unavailable"],
            "series": {},
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            macro_router.macro_layer_component_history(
                "breadth",
                "sectors_green",
                window="90d",
                user={},
            )
        )

    assert exc.value.status_code == 404
    assert "No stored history" in str(exc.value.detail)
    assert "fixture history unavailable" in str(exc.value.detail)
