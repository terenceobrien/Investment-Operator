from __future__ import annotations

import pytest

from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.paths import decision_log_path, schema_records_path
from src.agent_system.schemas.regime import RegimeState
from src.agent_system.storage import repository
from src.agent_system.storage.repository import (
    get_schema,
    list_schemas,
    load_decision_log_entries_by_cycle,
    save_decision_log_entry,
    save_schema,
)


@pytest.fixture(autouse=True)
def _use_jsonl_backend(monkeypatch):
    monkeypatch.setenv("AGENT_STORAGE_BACKEND", "jsonl")


def test_repository_uses_shared_agent_system_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    assert repository._schema_records_path() == schema_records_path()
    assert repository._decision_log_path() == decision_log_path()


def test_repository_saves_and_rehydrates_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    regime = make_stub_regime_state()

    record_id = save_schema(regime)
    loaded = get_schema(record_id, RegimeState)

    assert loaded.id == record_id
    assert loaded.regime_id == "supply_shock_inflation"
    assert list_schemas(RegimeState, limit=5)[0].id == record_id


def test_decision_log_entry_is_append_only(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    entry_id = save_decision_log_entry(
        {
            "cycle_id": "cycle-test",
            "candidate": "ETN",
            "decision": "accepted",
            "summary": "Stub accepted decision for repository test.",
        }
    )

    log_path = tmp_path / "decision_log.jsonl"
    assert entry_id
    assert log_path.exists()
    assert "ETN" in log_path.read_text(encoding="utf-8")


def test_load_decision_log_entries_by_cycle_normalizes_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_STORAGE_BACKEND", "jsonl")
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    save_decision_log_entry(
        {
            "cycle_id": "cycle-test",
            "candidate": "ZZZ",
            "decision": "rejected",
            "conviction_rating": "weak",
            "rule_applied": "late_rule",
            "summary": "Late rejected candidate.",
            "weakest_link": "fundamental",
            "trade_idea_id": "trade-late",
            "timestamp": "2026-01-02T00:00:00+00:00",
        }
    )
    save_decision_log_entry(
        {
            "cycle_id": "cycle-test",
            "candidate": "AAA",
            "decision": "accepted",
            "conviction_rating": "strong",
            "rule_applied": "early_rule",
            "summary": "Early accepted candidate.",
            "weakest_link": "none",
            "trade_idea_id": "trade-early",
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    )
    save_decision_log_entry(
        {
            "cycle_id": "other-cycle",
            "candidate": "OTHER",
            "decision": "rejected",
            "summary": "Different cycle.",
        }
    )

    entries = load_decision_log_entries_by_cycle("cycle-test")

    assert [entry.candidate for entry in entries] == ["AAA", "ZZZ"]
    assert [entry.id for entry in entries] == [2, 1]
    assert entries[0].trade_idea_id == "trade-early"
    assert entries[1].rule_applied == "late_rule"
