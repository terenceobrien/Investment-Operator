"""
Tests for ForwardContextBuilder.

The builder should be forgiving: each source can fail independently and the
caller still receives a valid ForwardContext with data quality notes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.agent_system.builders.forward_context import ForwardContextBuilder
from src.agent_system.schemas.forward import ForwardContext


FED_PATH_YAML = """
source_note: "CME FedWatch readings as of 2026-05-19"
meetings:
  - meeting_date: "2026-06-17"
    prob_cut_50: 0.02
    prob_cut_25: 0.18
    prob_hold: 0.70
    prob_hike_25: 0.09
    prob_hike_50: 0.01
"""


FORWARD_CALENDAR_YAML = """
events:
  - name: "FOMC June Meeting"
    date: "2026-06-17"
    category: "fed"
    significance: "high"
    notes: "Market pricing 70% hold."
"""


def _write_config(config_dir: Path, *, fed: str | None, calendar: str | None) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    if fed is not None:
        (config_dir / "fed_path.yaml").write_text(fed, encoding="utf-8")
    if calendar is not None:
        (config_dir / "forward_calendar.yaml").write_text(
            calendar, encoding="utf-8"
        )


def _fake_fred_fetcher(series_id: str) -> float:
    return {
        "T2YIE": 2.60,
        "T5YIE": 2.45,
        "T10YIE": 2.35,
        "T5YIFR": 2.25,
    }[series_id]


def test_builder_returns_valid_forward_context_when_all_sources_succeed(tmp_path):
    _write_config(tmp_path, fed=FED_PATH_YAML, calendar=FORWARD_CALENDAR_YAML)
    context = ForwardContextBuilder(
        fred_fetcher=_fake_fred_fetcher,
        config_dir=tmp_path,
    ).build()

    assert isinstance(context, ForwardContext)
    assert len(context.fed_path) == 1
    assert context.inflation_expectations is not None
    assert context.inflation_expectations.breakeven_5y == 2.45
    assert len(context.upcoming_catalysts) == 1
    assert context.prediction_market_signals == []


def test_builder_handles_missing_fed_path_yaml(tmp_path):
    _write_config(tmp_path, fed=None, calendar=FORWARD_CALENDAR_YAML)
    context = ForwardContextBuilder(
        fred_fetcher=_fake_fred_fetcher,
        config_dir=tmp_path,
    ).build()

    assert context.fed_path == []
    assert "Fed path:" in context.data_quality_notes
    assert "fed_path.yaml unavailable" in context.data_quality_notes


def test_builder_returns_valid_context_when_fred_fetcher_is_none(tmp_path):
    _write_config(tmp_path, fed=FED_PATH_YAML, calendar=FORWARD_CALENDAR_YAML)
    context = ForwardContextBuilder(config_dir=tmp_path).build()

    assert context.inflation_expectations is None
    assert "fred_fetcher not provided" in context.data_quality_notes


def test_builder_handles_malformed_yaml_gracefully(tmp_path):
    _write_config(
        tmp_path,
        fed="meetings: [",
        calendar=FORWARD_CALENDAR_YAML,
    )
    context = ForwardContextBuilder(
        fred_fetcher=_fake_fred_fetcher,
        config_dir=tmp_path,
    ).build()

    assert context.fed_path == []
    assert len(context.upcoming_catalysts) == 1
    assert "Fed path:" in context.data_quality_notes


def test_prediction_markets_are_empty_for_v1(tmp_path):
    _write_config(tmp_path, fed=FED_PATH_YAML, calendar=FORWARD_CALENDAR_YAML)
    context = ForwardContextBuilder(
        fred_fetcher=_fake_fred_fetcher,
        config_dir=tmp_path,
    ).build()

    assert context.prediction_market_signals == []


def test_as_of_is_recent_utc_datetime(tmp_path):
    _write_config(tmp_path, fed=FED_PATH_YAML, calendar=FORWARD_CALENDAR_YAML)
    before = datetime.now(timezone.utc)
    context = ForwardContextBuilder(
        fred_fetcher=_fake_fred_fetcher,
        config_dir=tmp_path,
    ).build()
    after = datetime.now(timezone.utc)

    assert context.as_of.tzinfo is not None
    assert before <= context.as_of <= after
