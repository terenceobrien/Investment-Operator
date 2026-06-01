"""File-backed status reporting for long-running research cycles."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from src.agent_system.paths import cycles_dir


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StageName(str, Enum):
    MACRO = "macro_agent"
    THEMATIC = "thematic_agent"
    SCREEN = "fundamental_screen"
    CONVICTION = "conviction_gate"
    TRADE_EXPRESSION = "trade_expression"
    SCENARIO_SCORING = "scenario_scoring"
    PORTFOLIO = "portfolio_construction"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


class StageState(BaseModel):
    model_config = ConfigDict(frozen=False)

    stage: StageName
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    message: str = ""
    progress_current: int | None = None
    progress_total: int | None = None
    error: str | None = None


class CycleStatus(BaseModel):
    model_config = ConfigDict(frozen=False)

    cycle_id: str
    started_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    overall_status: StageStatus = StageStatus.RUNNING
    stages: list[StageState]
    summary_counters: dict = Field(default_factory=dict)
    fatal_error: str | None = None
    user_inputs_preview: list[str] = Field(default_factory=list)


class CycleStatusEmitter:
    """Writes cycle status to a file as the cycle progresses."""

    def __init__(
        self,
        cycle_id: str,
        *,
        user_inputs: list[str] | None = None,
    ):
        self.cycle_id = cycle_id
        self.path = cycles_dir() / cycle_id / "status.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        preview = list(user_inputs or [])
        now = _utcnow()
        self.state = CycleStatus(
            cycle_id=cycle_id,
            started_at=now,
            updated_at=now,
            stages=[StageState(stage=stage) for stage in StageName],
            user_inputs_preview=preview,
        )
        self._write()

    def start_stage(self, stage: StageName, message: str = "") -> None:
        item = self._stage(stage)
        item.status = StageStatus.RUNNING
        item.started_at = item.started_at or _utcnow()
        item.completed_at = None
        item.message = message
        item.error = None
        self._touch()

    def update_stage(
        self,
        stage: StageName,
        *,
        message: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        item = self._stage(stage)
        if item.status == StageStatus.PENDING:
            item.status = StageStatus.RUNNING
            item.started_at = _utcnow()
        if message is not None:
            item.message = message
        if current is not None:
            item.progress_current = current
        if total is not None:
            item.progress_total = total
        self._touch()

    def complete_stage(self, stage: StageName, message: str = "") -> None:
        item = self._stage(stage)
        item.status = StageStatus.COMPLETE
        item.started_at = item.started_at or _utcnow()
        item.completed_at = _utcnow()
        if message:
            item.message = message
        self._touch()

    def fail_stage(self, stage: StageName, error: str) -> None:
        item = self._stage(stage)
        item.status = StageStatus.FAILED
        item.started_at = item.started_at or _utcnow()
        item.completed_at = _utcnow()
        item.error = error
        item.message = error
        self._touch()

    def skip_stage(self, stage: StageName, reason: str = "") -> None:
        item = self._stage(stage)
        item.status = StageStatus.SKIPPED
        item.started_at = item.started_at or _utcnow()
        item.completed_at = _utcnow()
        item.message = reason
        self._touch()

    def set_summary(self, summary: dict) -> None:
        self.state.summary_counters = dict(summary)
        self._touch()

    def complete_cycle(self) -> None:
        self.state.overall_status = StageStatus.COMPLETE
        self.state.completed_at = _utcnow()
        self._touch()

    def fail_cycle(self, error: str) -> None:
        self.state.overall_status = StageStatus.FAILED
        self.state.completed_at = _utcnow()
        self.state.fatal_error = error
        self._touch()

    def _stage(self, stage: StageName) -> StageState:
        for item in self.state.stages:
            if item.stage == stage:
                return item
        raise KeyError(f"Unknown stage {stage!r}")

    def _touch(self) -> None:
        self.state.updated_at = _utcnow()
        self._write()

    def _write(self) -> None:
        """Write current state to status.json atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path: Path = self.path.parent / f".{self.path.name}.{uuid4().hex}.tmp"
        tmp_path.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)
