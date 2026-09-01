"""API endpoints for submitting and inspecting agent-system cycles."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.agent_system_router import verify_agent_system_access
from src.agent_system.api.cycle_runner import submit_cycle
from src.agent_system.orchestration.cycle_status import CycleStatus
from src.agent_system.paths import cycles_dir
from src.agent_system.storage.backend import get_backend

logger = logging.getLogger("api.cycles")

cycle_router = APIRouter(prefix="/api/cycles", tags=["cycles"])


class SubmitCycleRequest(BaseModel):
    user_inputs: list[str]


class SubmitCycleResponse(BaseModel):
    cycle_id: str


def _cycle_status_path(cycle_id: str) -> Path:
    return cycles_dir() / cycle_id / "status.json"


def _load_cycle_status(cycle_id: str) -> CycleStatus:
    path = _cycle_status_path(cycle_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Cycle {cycle_id} not found")
    return CycleStatus.model_validate_json(path.read_text(encoding="utf-8"))


def _decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    wrapper = row.get("payload")
    if isinstance(wrapper, dict):
        payload = wrapper.get("payload_json")
        return payload if isinstance(payload, dict) else wrapper
    payload = row.get("payload_json")
    return payload if isinstance(payload, dict) else row


def _decision_rows_for_cycle(cycle_id: str) -> list[dict[str, Any]]:
    rows = get_backend().query_log_by_field(
        log_name="decision_log",
        field="cycle_id",
        value=cycle_id,
    )
    return [
        row
        for row in rows
        if _decision_payload(row).get("cycle_id") == cycle_id
    ]


def _trade_ids_for_cycle(cycle_id: str) -> set[str]:
    ids: set[str] = set()
    for row in _decision_rows_for_cycle(cycle_id):
        payload = _decision_payload(row)
        trade_id = payload.get("trade_idea_id")
        if trade_id:
            ids.add(str(trade_id))
    return ids


def _schema_record_matches_cycle(
    row: dict[str, Any],
    *,
    cycle_id: str,
    trade_ids: set[str],
) -> bool:
    payload = row.get("payload_json") if isinstance(row.get("payload_json"), dict) else {}
    if row.get("cycle_id") == cycle_id or payload.get("cycle_id") == cycle_id:
        return True
    record_id = row.get("id") or payload.get("id")
    return bool(record_id and str(record_id) in trade_ids)


@cycle_router.post("/submit", response_model=SubmitCycleResponse)
def submit_cycle_endpoint(
    req: SubmitCycleRequest,
    user: dict = Depends(verify_agent_system_access),
):
    """Kick off a cycle. Returns immediately with a cycle_id."""
    del user
    if not req.user_inputs:
        raise HTTPException(status_code=400, detail="At least one input required")
    if len(req.user_inputs) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 inputs per cycle")
    for item in req.user_inputs:
        if not 1 <= len(item.strip()) <= 500:
            raise HTTPException(
                status_code=400,
                detail="Each input must be 1-500 chars after trimming",
            )
    cycle_id = submit_cycle([item.strip() for item in req.user_inputs])
    return SubmitCycleResponse(cycle_id=cycle_id)


@cycle_router.get("/{cycle_id}/status", response_model=CycleStatus)
def get_status_endpoint(
    cycle_id: str,
    user: dict = Depends(verify_agent_system_access),
):
    """Return current cycle status from disk."""
    del user
    return _load_cycle_status(cycle_id)


@cycle_router.get("/{cycle_id}/results")
def get_results_endpoint(
    cycle_id: str,
    user: dict = Depends(verify_agent_system_access),
):
    """Return structured cycle results available so far."""
    del user
    _load_cycle_status(cycle_id)
    trade_ids = _trade_ids_for_cycle(cycle_id)
    records_by_type: dict[str, list[dict[str, Any]]] = {}
    for row in get_backend().read_all(collection="schema_records"):
        if not _schema_record_matches_cycle(row, cycle_id=cycle_id, trade_ids=trade_ids):
            continue
        schema_type = str(row.get("schema_type") or "Unknown")
        records_by_type.setdefault(schema_type, []).append(row)

    decision_log_entries = []
    for row in _decision_rows_for_cycle(cycle_id):
        decision_log_entries.append(_decision_payload(row))

    return {
        "cycle_id": cycle_id,
        "records_by_type": records_by_type,
        "decision_log_entries": decision_log_entries,
    }


@cycle_router.get("/recent")
def list_recent_cycles_endpoint(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    user: dict = Depends(verify_agent_system_access),
):
    """List recent cycle status records."""
    del user
    cycles: list[dict[str, Any]] = []
    for cycle_dir in cycles_dir().iterdir():
        status_file = cycle_dir / "status.json"
        if not status_file.exists():
            continue
        try:
            status = CycleStatus.model_validate_json(status_file.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Skipping malformed cycle status file: %s", status_file)
            continue
        cycles.append(
            {
                "cycle_id": status.cycle_id,
                "started_at": status.started_at.isoformat(),
                "completed_at": status.completed_at.isoformat()
                if status.completed_at
                else None,
                "overall_status": status.overall_status.value,
                "user_inputs_preview": status.user_inputs_preview,
            }
        )
    cycles.sort(key=lambda item: item["started_at"], reverse=True)
    return {"cycles": cycles[:limit]}
