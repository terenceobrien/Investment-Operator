"""Scenario schemas and deterministic metric helpers."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FactorImplications(BaseModel):
    """Structured directional implications across key macro factors."""

    model_config = ConfigDict(frozen=True)

    rates: str = Field(
        min_length=5,
        max_length=300,
        description=(
            "Directional implication for interest rates, e.g. "
            "'10y settles 3.5-3.8%'."
        ),
    )
    equities: str = Field(
        min_length=5,
        max_length=300,
        description="Directional implication for broad equity markets and leadership.",
    )
    dollar: str = Field(
        min_length=5,
        max_length=300,
        description="Directional implication for the US dollar (DXY or vs major crosses).",
    )
    credit: str = Field(
        min_length=5,
        max_length=300,
        description="Directional implication for credit spreads (IG/HY).",
    )
    commodities: str = Field(
        min_length=5,
        max_length=300,
        description=(
            "Directional implication for major commodity complexes "
            "(energy, metals)."
        ),
    )


class Scenario(BaseModel):
    """A single forward scenario with structured factor implications."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=5, max_length=200)
    probability: float = Field(ge=0.0, le=1.0)
    description: str = Field(min_length=50, max_length=2000)
    factor_implications: FactorImplications
    catalysts_that_confirm: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Observable events that would increase the scenario's probability.",
    )
    catalysts_that_invalidate: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Observable events that would decrease or kill the scenario.",
    )

class ScenarioSet(BaseModel):
    """The full set of scenarios for a given horizon and regime basis."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    generated_at: datetime
    regime_id_basis: str | None = None
    horizon_months: int = Field(ge=1, le=24)
    scenarios: list[Scenario] = Field(min_length=3, max_length=5)

    def model_post_init(self, __context) -> None:
        total = sum(s.probability for s in self.scenarios)
        if not (0.95 <= total <= 1.05):
            raise ValueError(
                f"Scenario probabilities must sum to ~1.0 (got {total:.3f}). "
                "Adjust probabilities to sum within [0.95, 1.05]."
            )
        ids = [s.id for s in self.scenarios]
        if len(set(ids)) != len(ids):
            raise ValueError(f"Scenario IDs must be unique. Got: {ids}")


class ScenarioScore(BaseModel):
    """LLM's payoff estimate for one trade in one scenario."""

    model_config = ConfigDict(frozen=True)

    scenario_id: str
    expected_pnl_pct: float = Field(
        description=(
            "Expected percentage return on the trade in this scenario. "
            "Positive = profitable, negative = loss. Express as decimal "
            "(0.15 = +15%, -0.30 = -30%). Bounded approximately -1.0 to +3.0."
        ),
        ge=-1.0,
        le=3.0,
    )
    confidence: str = Field(
        description="LLM's self-rated confidence in this estimate.",
        pattern="^(high|medium|low)$",
    )
    reasoning: str = Field(min_length=20, max_length=1000)


class TradeScenarioAnalysis(BaseModel):
    """The complete scenario analysis for one TradeIdea."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    created_at: datetime
    id: str | None = None
    trade_id: str
    scenario_set_horizon_months: int
    scenario_scores: list[ScenarioScore]
    expected_return: float
    worst_case_pnl_pct: float
    best_case_pnl_pct: float
    robustness_score: float
    scenarios_positive: int
    fallback_used: bool = False


def compute_robustness(expected_return: float, worst_case: float) -> float:
    """
    Reward expected return; penalize asymmetric downside.

    Returns approximately 0 for fragile trades and 1+ for very robust trades.
    """
    return (expected_return - 2.0 * max(0.0, -worst_case)) / (
        1.0 + max(0.0, -worst_case)
    )


def compute_trade_scenario_metrics(
    scores: list[ScenarioScore],
    scenario_set: ScenarioSet,
) -> dict:
    """Compute deterministic metrics from scenario scores and probabilities."""
    probabilities = {scenario.id: scenario.probability for scenario in scenario_set.scenarios}
    expected_return = sum(
        score.expected_pnl_pct * probabilities.get(score.scenario_id, 0.0)
        for score in scores
    )
    pnl_values = [score.expected_pnl_pct for score in scores]
    worst_case = min(pnl_values) if pnl_values else 0.0
    best_case = max(pnl_values) if pnl_values else 0.0
    return {
        "expected_return": expected_return,
        "worst_case_pnl_pct": worst_case,
        "best_case_pnl_pct": best_case,
        "robustness_score": compute_robustness(expected_return, worst_case),
        "scenarios_positive": sum(1 for score in scores if score.expected_pnl_pct > 0),
    }
