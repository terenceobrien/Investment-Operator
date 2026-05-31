"""Typed loader for the trade expression agent's trader profile."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class InstrumentsAllowed(BaseModel):
    model_config = ConfigDict(frozen=True)

    long_stock: bool
    short_stock: bool
    long_call: bool
    long_put: bool
    short_call: bool
    covered_call: bool
    cash_secured_put: bool
    long_call_spread: bool
    long_put_spread: bool
    iron_condor: bool
    pair_trade: bool


class MarginProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    max_leverage: float = Field(gt=0)
    use_for_sizing: bool


class TraderConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_position_pct: float = Field(ge=0, le=1)
    max_options_pct: float = Field(ge=0, le=1)
    min_option_dte: int = Field(ge=0)
    max_option_dte: int = Field(ge=1)


class PortfolioConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_priority_pct: float = Field(default=0.15, ge=0, le=1)
    max_total_new_deployment_pct: float = Field(default=0.50, ge=0, le=1)
    min_tradeable_size_pct: float = Field(default=0.005, ge=0, le=1)


class RobustnessProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    demotion_quartile_threshold: float = Field(default=0.25, ge=0, le=1)
    demotion_factor: float = Field(default=0.5, ge=0, le=1)


class TraderPreferences(BaseModel):
    model_config = ConfigDict(frozen=True)

    prefer_options_for_strong_variants: bool
    prefer_stock_for_weak_variants: bool
    avoid_earnings_options: bool


class TraderProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    instruments_allowed: InstrumentsAllowed
    margin: MarginProfile
    constraints: TraderConstraints
    portfolio_constraints: PortfolioConstraints = Field(default_factory=PortfolioConstraints)
    robustness: RobustnessProfile = Field(default_factory=RobustnessProfile)
    preferences: TraderPreferences
    account_type: str


DEFAULT_TRADER_PROFILE_PATH = Path(__file__).resolve().parent / "trader_profile.yaml"


@lru_cache(maxsize=8)
def _load_trader_profile_cached(path: str) -> TraderProfile:
    with Path(path).open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("trader_profile.yaml must contain a mapping")
    return TraderProfile.model_validate(raw)


def load_trader_profile(path: Path | None = None) -> TraderProfile:
    """Load and cache the configured trader profile."""

    return _load_trader_profile_cached(str(path or DEFAULT_TRADER_PROFILE_PATH))
