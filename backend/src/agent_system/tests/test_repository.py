from __future__ import annotations

from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.regime import RegimeState
from src.agent_system.storage.repository import (
    get_schema,
    list_schemas,
    save_decision_log_entry,
    save_schema,
)


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
