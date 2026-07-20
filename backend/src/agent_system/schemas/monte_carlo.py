"""Monte Carlo exposure schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from src.agent_system.schemas.common import BaseSchema, UnitInterval


class TradeExposure(BaseSchema):
    """Standalone post-acceptance exposure artifact for portfolio simulation."""

    trade_idea_id: str = Field(min_length=1)
    underlying: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    instrument_type: str = Field(min_length=1)
    position_size_pct: UnitInterval
    delta: UnitInterval
    market_beta: float
    market_beta_source: Literal[
        "yfinance_live",
        "yfinance_cached",
        "damodaran_sector",
        "sector_proxy",
        "manual_estimate",
    ]
    sector: str = Field(min_length=1)
    sector_beta: float
    sector_beta_source: Literal[
        "yfinance_live",
        "yfinance_cached",
        "damodaran_sector",
        "sector_proxy",
        "manual_estimate",
    ]
    theme_exposure: UnitInterval
    theme_exposure_source: Literal["theme_matrix", "conviction_derived", "manual_estimate"]
    theme_beta: float
    theme_beta_source: Literal["theme_betas_file", "manual_estimate"]
    scenario_exposures: dict[str, float]
    scenario_exposure_source: Literal[
        "derived_from_scenario_pnl",
        "manual_estimate",
    ]
    idiosyncratic_volatility: float = Field(ge=0.0)
    idiosyncratic_vol_source: Literal[
        "scenario_pnl_range",
        "manual_estimate",
    ]
    fundamental_conviction: str
    narrative_conviction: str | None
    overall_confidence: Literal["high", "medium", "low"]


class BucketReturnAssumption(BaseSchema):
    expected_return: float
    volatility: float = Field(ge=0.0)


class ScenarioReturnAssumption(BaseSchema):
    scenario_id: str
    market: dict[str, BucketReturnAssumption]
    themes: dict[str, BucketReturnAssumption]


class ScenarioReturnAssumptions(BaseSchema):
    metadata: dict[str, Any]
    scenarios: dict[str, ScenarioReturnAssumption]

    @model_validator(mode="before")
    @classmethod
    def _fill_scenario_ids(cls, data):
        if not isinstance(data, dict):
            return data
        values = dict(data)
        scenarios = values.get("scenarios")
        if not isinstance(scenarios, dict):
            return values
        labelled = {}
        for scenario_id, payload in scenarios.items():
            if isinstance(payload, dict) and payload.get("scenario_id") is None:
                item = dict(payload)
                item["scenario_id"] = str(scenario_id)
                labelled[str(scenario_id)] = item
            else:
                labelled[str(scenario_id)] = payload
        values["scenarios"] = labelled
        return values


class MonteCarloConfig(BaseSchema):
    n_paths: int = Field(default=10_000, ge=100, le=100_000)
    horizon_days: int = Field(default=63, ge=1)
    random_seed: Optional[int] = None
    use_scenario_pnl_override: bool = Field(
        default=True,
        description=(
            "If True, log a warning when factor model return diverges from "
            "scenario_pnl by more than divergence_warning_threshold"
        ),
    )
    divergence_warning_threshold: float = Field(default=0.15, ge=0.0)
    correlation_structure: Literal["independent", "factor_only"] = "independent"
    assumption_source_label: str = "manual_estimate"


class MonteCarloPathResult(BaseSchema):
    """Summary statistics extracted from raw path simulation. Raw paths are not stored."""

    n_paths: int
    n_trades: int
    scenarios_sampled: dict[str, int]
    portfolio_expected_return: float
    portfolio_median_return: float
    portfolio_p10: float
    portfolio_p25: float
    portfolio_p75: float
    portfolio_p90: float
    portfolio_prob_loss: float
    portfolio_prob_loss_5pct: float
    portfolio_prob_loss_10pct: float
    portfolio_expected_shortfall_5pct: float
    portfolio_best_scenario: str
    portfolio_worst_scenario: str
    per_scenario_mean_return: dict[str, float]
    ticker_median_returns: dict[str, float]
    ticker_p10: dict[str, float]
    ticker_p90: dict[str, float]
    ticker_prob_loss: dict[str, float]
    ticker_worst_scenario: dict[str, str]
    ticker_best_scenario: dict[str, str]
    ticker_portfolio_contribution: dict[str, float]
    ticker_tail_contribution: dict[str, float]
    theme_concentration: dict[str, float]
    divergence_warnings: list[str]
    assumption_confidence: Literal["high", "medium", "low"]
    correlation_structure_used: str
    ran_at: datetime
