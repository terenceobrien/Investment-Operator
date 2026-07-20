"""Schema for thematic-agent current-regime YAML handoff files."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CurrentRegimeKeyDriver(BaseModel):
    name: str
    status: str
    explanation: str


class CurrentRegimeFalsifier(BaseModel):
    condition: str
    observable_in: str
    check_frequency: str


class CurrentRegimeSeedResearchPriority(BaseModel):
    theme: str
    rationale: str
    edge_hypothesis: str
    sub_questions: list[str] = Field(default_factory=list)
    priority_rank: int
    expected_edge_decay: str
    source_theme_id: str | None = None
    source_scenario_ids: list[str] = Field(default_factory=list)
    source_macro_forecast_id: str | None = None


class CurrentRegimeHandoff(BaseModel):
    regime_id: str
    regime_label: str
    regime_call_confidence: float
    headline: str
    summary: str
    risk_summary: str
    scenario_probabilities: dict[str, float] = Field(default_factory=dict)
    key_drivers: list[CurrentRegimeKeyDriver] = Field(default_factory=list)
    portfolio_implications: list[str] = Field(default_factory=list)
    best_positioned: list[str] = Field(default_factory=list)
    most_vulnerable: list[str] = Field(default_factory=list)
    falsifiers: list[CurrentRegimeFalsifier] = Field(default_factory=list)
    seed_research_priorities: list[CurrentRegimeSeedResearchPriority] = Field(default_factory=list)
