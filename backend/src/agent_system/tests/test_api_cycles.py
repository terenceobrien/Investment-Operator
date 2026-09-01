"""Tests for cycle status files and frontend cycle API helpers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException

from api import cycle_router
from api import research_router as research_api
from src.agent_system.api import cycle_runner
from src.agent_system.orchestration import run_research_cycle as cycle_module
from src.agent_system.orchestration.cycle_status import (
    CycleStatus,
    CycleStatusEmitter,
    StageName,
    StageState,
    StageStatus,
)
from src.agent_system.orchestration.run_research_cycle import (
    main as run_cycle_cli_main,
    run_stub_research_cycle,
)
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.paths import cycles_dir
from src.agent_system.storage.backend import get_backend


@pytest.fixture(autouse=True)
def _use_jsonl_storage(monkeypatch):
    monkeypatch.setenv("AGENT_STORAGE_BACKEND", "jsonl")
    from src.agent_system.storage import backend as storage_backend

    storage_backend._backend_singletons.clear()
    yield
    storage_backend._backend_singletons.clear()


def _write_status(cycle_id: str, *, started_at: datetime, status: StageStatus) -> None:
    path = cycles_dir() / cycle_id / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = CycleStatus(
        cycle_id=cycle_id,
        started_at=started_at,
        updated_at=started_at,
        completed_at=started_at if status in {StageStatus.COMPLETE, StageStatus.FAILED} else None,
        overall_status=status,
        stages=[StageState(stage=stage) for stage in StageName],
        user_inputs_preview=[f"{cycle_id} input"],
    )
    path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")


def test_cycle_status_emitter_writes_atomically_and_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    long_input = "Dovish pivot beneficiaries " + ("with full context " * 12)
    emitter = CycleStatusEmitter("cycle-test", user_inputs=[long_input])

    emitter.start_stage(StageName.MACRO, "starting macro")
    emitter.update_stage(StageName.MACRO, current=1, total=2)
    emitter.complete_stage(StageName.MACRO, "macro complete")

    path = tmp_path / "cycles" / "cycle-test" / "status.json"
    assert path.exists()
    status = CycleStatus.model_validate_json(path.read_text(encoding="utf-8"))
    macro = next(stage for stage in status.stages if stage.stage == StageName.MACRO)
    assert status.cycle_id == "cycle-test"
    assert status.user_inputs_preview == [long_input]
    assert macro.status == StageStatus.COMPLETE
    assert macro.progress_current == 1
    assert macro.progress_total == 2
    assert not list(path.parent.glob("*.tmp"))


def test_stub_cycle_with_emitter_completes_status(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    emitter = CycleStatusEmitter("cycle-emitted")

    summary = run_stub_research_cycle(
        skip_portfolio_construction=True,
        emitter=emitter,
    )

    status = CycleStatus.model_validate_json(
        (tmp_path / "cycles" / "cycle-emitted" / "status.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["cycle_id"] == "cycle-emitted"
    assert status.overall_status == StageStatus.COMPLETE
    assert status.summary_counters["cycle_id"] == "cycle-emitted"


def test_cli_cycle_writes_status_and_endpoint_can_read_it(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))

    run_cycle_cli_main(
        [
            "--stub",
            "--use-stub-thematic",
            "--use-stub-fundamental",
            "--use-stub-trade-expression",
            "--skip-portfolio-construction",
        ]
    )

    stdout = capsys.readouterr().out
    cycle_id_line = next(
        line for line in stdout.splitlines() if line.startswith("Cycle ID: ")
    )
    cycle_id = cycle_id_line.removeprefix("Cycle ID: ").strip()
    status_path = tmp_path / "cycles" / cycle_id / "status.json"

    assert status_path.exists()
    assert f"Frontend: http://localhost:3000/agent-system?cycle={cycle_id}" in stdout
    assert f"Status file: {status_path}" in stdout

    status = CycleStatus.model_validate_json(status_path.read_text(encoding="utf-8"))
    stages = {stage.stage: stage for stage in status.stages}
    assert status.overall_status == StageStatus.COMPLETE
    assert stages[StageName.MACRO].status == StageStatus.SKIPPED
    assert stages[StageName.THEMATIC].status == StageStatus.COMPLETE
    assert stages[StageName.SCREEN].status == StageStatus.COMPLETE
    assert stages[StageName.CONVICTION].status == StageStatus.COMPLETE
    assert stages[StageName.PORTFOLIO].status == StageStatus.SKIPPED
    assert status.updated_at > status.started_at

    endpoint_status = cycle_router.get_status_endpoint(cycle_id, user={})
    assert endpoint_status.cycle_id == cycle_id
    assert endpoint_status.overall_status == StageStatus.COMPLETE


def test_submit_cycle_returns_uuid_and_submits_worker(monkeypatch):
    submitted = []

    class FakeExecutor:
        def submit(self, fn, cycle_id, user_inputs):
            submitted.append((fn, cycle_id, user_inputs))
            return object()

    monkeypatch.setattr(cycle_runner, "_executor", FakeExecutor())

    cycle_id = cycle_runner.submit_cycle(["AI power"])

    assert UUID(cycle_id)
    assert len(submitted) == 1
    assert submitted[0][1] == cycle_id
    assert submitted[0][2] == ["AI power"]


def test_api_worker_path_persists_schema_records(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    original_run_research_cycle = cycle_module.run_research_cycle

    def _stubbed_run_cycle_with_inputs(*, user_inputs, cycle_id, emitter, **_kwargs):
        del user_inputs
        regime = make_stub_regime_state()
        return original_run_research_cycle(
            force_stub=True,
            use_stub_thematic=True,
            use_stub_fundamental=True,
            use_stub_trade_expression=True,
            skip_portfolio_construction=True,
            cycle_id=cycle_id,
            research_priorities=regime.research_priorities,
            emitter=emitter,
        )

    monkeypatch.setattr(
        cycle_module,
        "run_cycle_with_inputs",
        _stubbed_run_cycle_with_inputs,
    )

    cycle_runner._run_cycle_in_process("api-persisted", ["API persistence test thesis"])

    rows = get_backend().read_all(collection="schema_records")
    schema_types = {row["schema_type"] for row in rows}
    assert {"ResearchPriority", "ThematicMap", "Conviction", "TradeIdea"}.issubset(
        schema_types
    )
    assert (tmp_path / "decision_log.jsonl").exists()

    status = cycle_router.get_status_endpoint("api-persisted", user={})
    assert status.overall_status == StageStatus.COMPLETE


def test_submit_endpoint_validation(monkeypatch):
    monkeypatch.setattr(cycle_router, "submit_cycle", lambda _inputs: "cycle-ok")

    with pytest.raises(HTTPException) as empty:
        cycle_router.submit_cycle_endpoint(
            cycle_router.SubmitCycleRequest(user_inputs=[]),
            user={},
        )
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as too_many:
        cycle_router.submit_cycle_endpoint(
            cycle_router.SubmitCycleRequest(user_inputs=["x"] * 11),
            user={},
        )
    assert too_many.value.status_code == 400

    with pytest.raises(HTTPException) as too_long:
        cycle_router.submit_cycle_endpoint(
            cycle_router.SubmitCycleRequest(user_inputs=["x" * 501]),
            user={},
        )
    assert too_long.value.status_code == 400

    response = cycle_router.submit_cycle_endpoint(
        cycle_router.SubmitCycleRequest(user_inputs=["  AI power  "]),
        user={},
    )
    assert response.cycle_id == "cycle-ok"


def test_status_endpoint_returns_status_and_404s(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    emitter = CycleStatusEmitter("cycle-status")
    emitter.start_stage(StageName.THEMATIC, "working")

    status = cycle_router.get_status_endpoint("cycle-status", user={})

    assert status.cycle_id == "cycle-status"
    assert status.overall_status == StageStatus.RUNNING

    with pytest.raises(HTTPException) as missing:
        cycle_router.get_status_endpoint("missing", user={})
    assert missing.value.status_code == 404


def test_results_endpoint_filters_records_by_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    _write_status("cycle-a", started_at=datetime.now(timezone.utc), status=StageStatus.COMPLETE)
    get_backend().append_to_log(
        log_name="decision_log",
        record={
            "id": "decision-a",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload_json": {
                "cycle_id": "cycle-a",
                "candidate": "ETN",
                "trade_idea_id": "trade-a",
            },
        },
        indexed_fields={"cycle_id": "cycle-a", "candidate": "ETN"},
    )
    schemas = [
        {
            "id": "trade-a",
            "schema_type": "TradeIdea",
            "payload_json": {"id": "trade-a", "underlying": "ETN"},
        },
        {
            "id": "plan-a",
            "schema_type": "PortfolioPlan",
            "payload_json": {"id": "plan-a", "cycle_id": "cycle-a"},
        },
        {
            "id": "other",
            "schema_type": "TradeIdea",
            "payload_json": {"id": "other", "cycle_id": "cycle-b"},
        },
    ]
    for row in schemas:
        get_backend().write_record(
            collection="schema_records",
            record_id=str(row["id"]),
            payload=row,
            indexed_fields={"schema_type": row["schema_type"]},
        )

    result = cycle_router.get_results_endpoint("cycle-a", user={})

    assert not (tmp_path / "schema_records.jsonl").exists()
    assert set(result["records_by_type"]) == {"TradeIdea", "PortfolioPlan"}
    assert result["records_by_type"]["TradeIdea"][0]["id"] == "trade-a"
    assert result["decision_log_entries"][0]["candidate"] == "ETN"

    with pytest.raises(HTTPException) as missing:
        cycle_router.get_results_endpoint("missing", user={})
    assert missing.value.status_code == 404


def test_recent_cycles_endpoint_sorts_and_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    now = datetime.now(timezone.utc)
    _write_status("older", started_at=now - timedelta(hours=1), status=StageStatus.COMPLETE)
    _write_status("newer", started_at=now, status=StageStatus.RUNNING)

    result = cycle_router.list_recent_cycles_endpoint(limit=1, user={})

    assert len(result["cycles"]) == 1
    assert result["cycles"][0]["cycle_id"] == "newer"
    assert result["cycles"][0]["user_inputs_preview"] == ["newer input"]


def test_research_cycle_stream_emits_keepalive_when_status_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(research_api, "_STREAM_HEARTBEAT_SECONDS", 0.0)
    monkeypatch.setattr(research_api, "_STREAM_POLL_SECONDS", 0.0)
    emitter = CycleStatusEmitter("cycle-stream-heartbeat")
    emitter.start_stage(StageName.THEMATIC, "long thematic call")

    async def _read_first_two_events() -> tuple[str, str]:
        stream = research_api._status_event_stream("cycle-stream-heartbeat")
        try:
            first = await anext(stream)
            second = await anext(stream)
        finally:
            await stream.aclose()
        return first, second

    first, second = asyncio.run(_read_first_two_events())

    assert first == 'data: {"stage_index":1,"status":"running"}\n\n'
    assert second.startswith(": keepalive ")
    assert second.endswith("\n\n")
