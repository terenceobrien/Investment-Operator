"""Deterministic financial-health screen output schema."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Archetype(str, Enum):
    ESTABLISHED = "established"
    GROWTH = "growth"
    DISTRESSED = "distressed"


class ScreenVerdict(str, Enum):
    PASS = "pass"
    ELIMINATE = "eliminate"


class FundamentalScreen(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    created_at: datetime
    id: str | None = None

    ticker: str
    archetype: Archetype
    verdict: ScreenVerdict
    reason: str

    crowding_flag: bool = False
    crowding_detail: str | None = None

    data_quality_flag: bool = False
    data_quality_detail: str | None = None

    metrics_used: dict = Field(default_factory=dict)

    data_was_sufficient: bool = True
    notes: str | None = None
