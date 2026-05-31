"""Standalone scenario generation and scoring module."""

from src.agent_system.scenarios.generator import propose_scenarios
from src.agent_system.scenarios.loader import (
    load_current_scenarios,
    load_proposed_scenarios,
)
from src.agent_system.scenarios.scorer import score_trade_against_scenarios
from src.agent_system.scenarios.types import (
    Scenario,
    ScenarioScore,
    ScenarioSet,
    TradeScenarioAnalysis,
    compute_robustness,
)

__all__ = [
    "Scenario",
    "ScenarioScore",
    "ScenarioSet",
    "TradeScenarioAnalysis",
    "compute_robustness",
    "load_current_scenarios",
    "load_proposed_scenarios",
    "propose_scenarios",
    "score_trade_against_scenarios",
]
