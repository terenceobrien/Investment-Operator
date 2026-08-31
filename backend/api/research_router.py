"""Research-priority and full-cycle orchestration endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.agent_system_router import verify_agent_system_access
from src.agent_system.evals.generate_priorities_from_text import (
    ManualPriorityAppendError,
    PriorityGenerationError,
    convert_text_to_priority,
    replace_manual_priority,
)
from src.agent_system.forecasting.macro_scenario_source import (
    MacroScenarioSourceError,
    load_manual_research_priorities,
)
from src.agent_system.orchestration.cycle_status import (
    CycleStatus,
    CycleStatusEmitter,
    StageName,
    StageStatus,
)
from src.agent_system.paths import cycles_dir, deep_fundamental_reports_dir_info, resolved_path_message
from src.agent_system.schemas.regime import ResearchPriority


logger = logging.getLogger("api.research")
research_router = APIRouter(prefix="/api/research", tags=["research"])
priorities_router = APIRouter(prefix="/api/priorities", tags=["priorities"])

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent

load_dotenv()
load_dotenv(REPO_ROOT / ".env.local")
load_dotenv(BACKEND_ROOT / ".env")

_executor: ProcessPoolExecutor | None = None
_executor_lock = Lock()
_active_jobs_by_user: dict[str, str] = {}
_job_users: dict[str, str] = {}

_STAGE_INDEX: dict[StageName, int] = {
    StageName.MACRO: 0,
    StageName.THEMATIC: 1,
    StageName.SCREEN: 2,
    StageName.CONVICTION: 3,
    StageName.TRADE_EXPRESSION: 4,
    StageName.SCENARIO_SCORING: 5,
    StageName.PORTFOLIO: 6,
}
_DONE_STATUSES = {StageStatus.COMPLETE, StageStatus.SKIPPED, StageStatus.FAILED}
_TICKER_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class GeneratePrioritiesRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class GeneratePriorityRequest(BaseModel):
    thesis_text: str = Field(min_length=1, max_length=5000)


class CommitPriorityRequest(BaseModel):
    priority: dict[str, Any]


class ApprovePriorityRequest(BaseModel):
    priority: ResearchPriority
    source_thesis_text: str = Field(min_length=1, max_length=10000)


class RunCycleResponse(BaseModel):
    job_id: str


class RunCycleRequest(BaseModel):
    priority_source: Literal["macro", "manual", "both"] = "macro"


def _deep_fundamental_candidates() -> list[Path]:
    env_root = os.getenv("DEEP_FUNDAMENTAL_DIR")
    paths: list[Path] = []
    if env_root:
        paths.append(Path(env_root))
    report_info = deep_fundamental_reports_dir_info(create=False)
    paths.append(report_info.path / "standalone")
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = str(path.expanduser())
        if expanded not in seen:
            seen.add(expanded)
            unique.append(Path(expanded))
    return unique


def _deep_fundamental_root() -> Path:
    for path in _deep_fundamental_candidates():
        if path.is_dir():
            return path
    return _deep_fundamental_candidates()[0]


def _deep_fundamental_missing_detail() -> str:
    report_info = deep_fundamental_reports_dir_info(create=False)
    checked = ", ".join(str(path) for path in _deep_fundamental_candidates())
    return (
        "Deep fundamental report directory not found. "
        "Set DEEP_FUNDAMENTAL_DIR to the standalone reports directory. "
        f"{resolved_path_message('Default deep fundamental reports root', report_info)}. "
        f"Checked: {checked}"
    )


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"report JSON is invalid: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"report JSON must contain an object: {path}")
    return payload


def _latest_report_file(ticker_dir: Path) -> tuple[Path, dict[str, Any]]:
    candidates = sorted(ticker_dir.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No report JSON files found in {ticker_dir}")
    best: tuple[str, str, Path, dict[str, Any]] | None = None
    for path in candidates:
        payload = _load_json_file(path)
        as_of = str(payload.get("as_of_date") or path.stem)
        key = (as_of, path.stem, path, payload)
        if best is None or key[:2] > best[:2]:
            best = key
    assert best is not None
    return best[2], best[3]


def _ticker_dir(ticker: str) -> Path:
    normalized = ticker.strip().upper()
    if not normalized or not _TICKER_RE.fullmatch(normalized):
        raise ValueError("ticker must contain only letters, numbers, '.', '_' or '-'")
    return _deep_fundamental_root() / normalized


def _run_research_cycle_process(cycle_id: str, priority_source: str = "macro") -> None:
    """Worker-process entry point. Durable progress is written by the emitter."""
    from src.agent_system.orchestration.run_research_cycle import run_research_cycle

    emitter = CycleStatusEmitter(cycle_id)
    try:
        run_research_cycle(
            cycle_id=cycle_id,
            emitter=emitter,
            priority_source=priority_source,
        )
    except Exception:
        emitter.fail_cycle(traceback.format_exc())


def _get_executor() -> ProcessPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ProcessPoolExecutor(max_workers=1)
        return _executor


def _user_id(user: dict[str, Any]) -> str:
    return str(
        user.get("sub")
        or user.get("id")
        or user.get("email")
        or user.get("user_id")
        or "local-dev-agent-system"
    )


def _cycle_status_path(cycle_id: str) -> Path:
    return cycles_dir() / cycle_id / "status.json"


def _load_cycle_status(cycle_id: str) -> CycleStatus:
    path = _cycle_status_path(cycle_id)
    if not path.exists():
        raise FileNotFoundError(f"Cycle {cycle_id} status file is not available yet")
    return CycleStatus.model_validate_json(path.read_text(encoding="utf-8"))


def _cycle_done(cycle_id: str) -> bool:
    try:
        status = _load_cycle_status(cycle_id)
    except FileNotFoundError:
        return False
    return status.overall_status in _DONE_STATUSES


def _active_job_for_user(user_id: str) -> str | None:
    existing = _active_jobs_by_user.get(user_id)
    if not existing:
        return None
    if _cycle_done(existing):
        _active_jobs_by_user.pop(user_id, None)
        return None
    return existing


def _priority_payload(priority: Any) -> dict[str, Any]:
    payload = priority.model_dump(mode="json")
    if not payload.get("source_theme_id"):
        payload["source_theme_id"] = "free_text"
    return payload


def _priority_generation_error_detail(exc: PriorityGenerationError) -> dict[str, Any]:
    return {
        "error": str(exc),
        "raw_llm_output": exc.raw_output,
        "validation_error": exc.validation_error,
    }


async def _generate_priority_from_text(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="thesis_text must not be blank")
    try:
        priority = await convert_text_to_priority(cleaned)
    except PriorityGenerationError as exc:
        logger.warning("Priority generation failed validation: %s", exc)
        raise HTTPException(
            status_code=422,
            detail=_priority_generation_error_detail(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": str(exc),
                "raw_llm_output": None,
                "validation_error": str(exc),
            },
        ) from exc
    except Exception as exc:
        logger.exception("Priority generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"priority": _priority_payload(priority), "raw_llm_output": None}


def _approve_priority(
    priority: ResearchPriority,
    source_thesis_text: str,
    approved_by: str | None,
) -> dict[str, Any]:
    try:
        priorities = replace_manual_priority(
            priority,
            source_thesis_text,
            approved_by=approved_by,
        )
    except (ManualPriorityAppendError, MacroScenarioSourceError, ValueError) as exc:
        logger.exception("Manual priority approval failed")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"success": True, "manual_priorities_count": len(priorities)}


@research_router.get("/fundamental/coverage")
def fundamental_coverage(
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """List tickers with standalone deep fundamental reports."""
    del user
    root = _deep_fundamental_root()
    if not root.is_dir():
        raise HTTPException(
            status_code=404,
            detail=_deep_fundamental_missing_detail(),
        )
    coverage: list[dict[str, Any]] = []
    for ticker_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        try:
            latest_path, payload = _latest_report_file(ticker_dir)
        except Exception as exc:
            logger.warning("Skipping malformed fundamental coverage entry %s: %s", ticker_dir, exc)
            continue
        profile = payload.get("company_profile") if isinstance(payload.get("company_profile"), dict) else {}
        coverage.append(
            {
                "ticker": str(payload.get("ticker") or ticker_dir.name).upper(),
                "name": profile.get("company_name") or payload.get("company_name") or ticker_dir.name,
                "as_of_date": payload.get("as_of_date") or latest_path.stem,
            }
        )
    coverage.sort(key=lambda item: item["ticker"])
    return {"coverage": coverage}


@research_router.get("/fundamental/{ticker}")
def latest_fundamental_report(
    ticker: str,
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Return the latest standalone deep fundamental report JSON for a ticker."""
    del user
    try:
        ticker_dir = _ticker_dir(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ticker_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No deep fundamental report directory found for {ticker.upper()} "
                f"under {_deep_fundamental_root()}"
            ),
        )
    try:
        _path, payload = _latest_report_file(ticker_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return payload


@research_router.post("/priorities/generate")
async def generate_priorities(
    req: GeneratePrioritiesRequest,
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Compatibility route for the old research-page generate endpoint."""
    del user
    result = await _generate_priority_from_text(req.text)
    return {"priorities": [result["priority"]], **result}


@research_router.post("/priorities/commit")
def commit_priority(
    req: CommitPriorityRequest,
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Retired current_regime.yaml commit path."""
    del user
    del req
    raise HTTPException(
        status_code=410,
        detail=(
            "The current_regime.yaml priority commit path is retired. "
            "Use POST /api/priorities/approve to append to manual_research_priorities.yaml."
        ),
    )


@priorities_router.post("/generate")
async def generate_manual_priority(
    req: GeneratePriorityRequest,
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Generate one structured ResearchPriority for operator review only."""

    del user
    return await _generate_priority_from_text(req.thesis_text)


@priorities_router.post("/approve")
def approve_manual_priority(
    req: ApprovePriorityRequest,
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Replace the manual queue with one operator-approved ResearchPriority."""

    return _approve_priority(
        req.priority,
        req.source_thesis_text,
        approved_by=_user_id(user),
    )


@priorities_router.get("/manual")
def list_manual_priorities(
    user: dict = Depends(verify_agent_system_access),
) -> dict[str, Any]:
    """Return the current manual operator priority queue."""

    del user
    try:
        priorities = load_manual_research_priorities()
    except MacroScenarioSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = [_priority_payload(priority) for priority in priorities]
    return {
        "manual_priorities_count": len(payload),
        "priorities": payload,
    }


@research_router.post("/cycle/run", response_model=RunCycleResponse)
def run_cycle(
    req: RunCycleRequest | None = None,
    user: dict = Depends(verify_agent_system_access),
) -> RunCycleResponse:
    """Start a full research cycle unless this user already has one active."""
    request = req or RunCycleRequest()
    user_id = _user_id(user)
    existing = _active_job_for_user(user_id)
    if existing:
        return RunCycleResponse(job_id=existing)

    cycle_id = str(uuid4())
    _active_jobs_by_user[user_id] = cycle_id
    _job_users[cycle_id] = user_id
    _get_executor().submit(_run_research_cycle_process, cycle_id, request.priority_source)
    return RunCycleResponse(job_id=cycle_id)


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _stage_event(status: CycleStatus) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for stage in status.stages:
        idx = _STAGE_INDEX.get(stage.stage)
        if idx is None:
            continue
        if stage.status == StageStatus.RUNNING:
            events.append({"stage_index": idx, "status": "running"})
        elif stage.status in _DONE_STATUSES:
            events.append({"stage_index": idx, "status": "done"})
    return events


async def _status_event_stream(cycle_id: str) -> AsyncIterator[str]:
    last_sent: dict[int, str] = {}
    while True:
        try:
            status = _load_cycle_status(cycle_id)
        except FileNotFoundError:
            await asyncio.sleep(0.75)
            continue

        for event in _stage_event(status):
            idx = int(event["stage_index"])
            state = str(event["status"])
            if last_sent.get(idx) == state:
                continue
            last_sent[idx] = state
            yield _sse(event)

        if status.overall_status in _DONE_STATUSES:
            for idx in range(7):
                if last_sent.get(idx) != "done":
                    last_sent[idx] = "done"
                    yield _sse({"stage_index": idx, "status": "done"})
            final: dict[str, Any] = {"done": True}
            if status.fatal_error:
                final["error"] = status.fatal_error
            yield _sse(final)
            break

        await asyncio.sleep(0.75)


@research_router.get("/cycle/{job_id}/stream")
async def stream_cycle(
    job_id: str,
    user: dict = Depends(verify_agent_system_access),
) -> StreamingResponse:
    """Stream stage state updates as Server-Sent Events."""
    user_id = _user_id(user)
    owner = _job_users.get(job_id)
    if owner is not None and owner != user_id:
        raise HTTPException(status_code=403, detail="Cycle belongs to another user")
    if owner is None and not _cycle_status_path(job_id).exists():
        raise HTTPException(status_code=404, detail=f"Cycle {job_id} not found")

    return StreamingResponse(
        _status_event_stream(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
