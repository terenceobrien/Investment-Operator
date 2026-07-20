"""Trade expression agent for turning accepted candidates into trade components."""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.agent_system.config.trader_profile import TraderProfile
from src.agent_system.data.types import FundamentalDataBundle, MarketDataBundle
from src.agent_system.llm.client import StructuredOutputError
from src.agent_system.schemas.common import (
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
)
from src.agent_system.schemas.fundamental_screen import FundamentalScreen
from src.agent_system.schemas.regime import (
    EdgeDecayHorizon,
    RegimeState,
    ResearchPriority,
)
from src.agent_system.schemas.thematic import (
    Candidate,
    InstrumentType,
    VariantStrength,
)
from src.agent_system.schemas.trade import (
    AlternativeRejected,
    Instrument,
    ProposedSizing,
    ReviewCadence,
    TargetDerivation,
    TradeDirection,
    TradeExpression,
    TradeProvenance,
)

logger = logging.getLogger("agent_system.agents.trade_expression")

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
TENOR_RULES_PATH = CONFIG_DIR / "tenor_rules.yaml"
SIZING_RULES_PATH = CONFIG_DIR / "sizing_rules.yaml"

ExpressionStrategy = Literal[
    "long_stock",
    "long_call",
    "long_put",
    "long_call_spread",
    "long_put_spread",
    "covered_call",
    "cash_secured_put",
    "pair_trade",
]
OPTION_STRATEGIES = {
    "long_call",
    "long_put",
    "long_call_spread",
    "long_put_spread",
    "covered_call",
    "cash_secured_put",
}


class ThesisDirection(str, Enum):
    BULLISH = "bullish_contrarian"
    BEARISH = "bearish"
    RELATIVE_VALUE = "relative_value"


class PriorityThesisDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    PAIR = "pair"
    NEUTRAL = "neutral"
    AMBIGUOUS = "ambiguous"


class TenorWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    min_dte: int
    target_dte: int
    max_dte: int
    rule_key: str
    nearest_catalyst: str | None = None


class TechnicalAnchors(BaseModel):
    model_config = ConfigDict(frozen=True)

    current_price: float | None
    trend_regime: str | None
    entry_reference: str
    stop_reference: str
    target_reference: str


class _FalsifierOutput(BaseModel):
    condition: str = Field(min_length=1, max_length=1000)
    observable_in: FalsifierObservable
    check_frequency: FalsifierFrequency
    notes: str = Field(default="", max_length=2000)


class _AlternativeOutput(BaseModel):
    instrument_type: str
    instrument_description: str = Field(min_length=1, max_length=500)
    why_rejected: str = Field(min_length=15, max_length=1000)


class _TargetDerivationOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: Literal[
        "technical",
        "valuation",
        "analyst_target",
        "measured_move",
        "volatility",
        "thesis_based_no_price",
    ]
    inputs_used: list[str] = Field(min_length=1, max_length=10)
    implied_price: float | None = Field(ge=0.0)


class _TradeExpressionLLMOutput(BaseModel):
    priority_thesis_direction: PriorityThesisDirection = PriorityThesisDirection.AMBIGUOUS
    chosen_instrument_type: str
    primary_instrument_description: str = Field(min_length=1, max_length=500)
    rationale_for_instrument: str = Field(min_length=20, max_length=2000)
    alternatives_considered: list[_AlternativeOutput] = Field(default_factory=list)
    entry_logic: str = Field(min_length=10, max_length=2000)
    target_derivation: _TargetDerivationOutput
    exit_target: str = Field(min_length=10, max_length=1000)
    exit_stop: str = Field(min_length=10, max_length=1000)
    exit_time_stop: str | None = Field(default=None, max_length=1000)
    invalidation_thesis: str = Field(min_length=20, max_length=2000)
    trade_falsifiers: list[_FalsifierOutput] = Field(default_factory=list)
    expected_holding_period: str = Field(min_length=1, max_length=200)
    thesis_review_cadence: ReviewCadence
    sizing_logic: str = Field(min_length=20, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class TradeExpressionComponents(BaseModel):
    """Components the cycle combines with conviction into a TradeIdea."""

    model_config = ConfigDict(frozen=True)

    expression: TradeExpression
    proposed_sizing: ProposedSizing
    invalidation_thesis: str
    trade_falsifiers: list[Falsifier] = Field(min_length=3, max_length=15)
    expected_holding_period: str
    thesis_review_cadence: ReviewCadence
    provenance: TradeProvenance
    selected_strategy: str
    fallback_used: bool = False
    notes: str | None = None


class TradeExpressionRejection(BaseModel):
    """Explicit sentinel for expression-stage rejection before TradeIdea assembly."""

    model_config = ConfigDict(frozen=True)

    rejection_rule_fired: Literal["direction_misaligned"] = "direction_misaligned"
    rejection_stage: Literal["construction"] = "construction"
    misalignment_reason: str
    priority_thesis_direction: PriorityThesisDirection
    effective_direction: str
    selected_strategy: str


SYSTEM_PROMPT_TEMPLATE = """You are the trade expression agent for a structured \
investment research system. Your job is to translate an already screen-passing, \
conviction-eligible candidate into a concrete trade expression. You do NOT \
decide conviction; the deterministic rules engine does that before you are \
called.

# Core instructions

Choose one eligible expression from the provided list. Option specifics belong \
inside primary_instrument_description as prose, for example "long Jul 2026 \
$250 calls" or "Jul/Sep $250/$275 call spread". Do not invent real option-chain \
availability; approximate tenor and strikes from the supplied target DTE and \
current price.

Every exit_target must cite a target_derivation method. Choose exactly one:
- technical: cite the named support/resistance level, historical context, and \
  swing points if Fibonacci or measured off a move.
- valuation: cite the multiple, reference period, and approximate price math.
- analyst_target: cite whether this is consensus bear case, lowest target, or \
  a stress-case target, plus approximate target date.
- measured_move: cite the chart pattern and measurement projected from the \
  breakdown/breakout level.
- volatility: cite ATR, IV band, sigma move, or similar metric and its current \
  value.
- thesis_based_no_price: use only when no price method genuinely fits. In that \
  case exit_target must say "thesis-based: no defined price target" and note \
  that the spread structure defines the maximum payoff zone rather than a \
  price target. Do not fabricate "technical downside targets" from strike \
  geometry.

For put/call spreads, obey the upper-strike rule. If entry_logic requires \
confirmation at a price level, treat that level as the entry trigger. For \
bearish put spreads, the upper strike must be from 10% below to 5% above the \
entry trigger. For bullish call spreads, the upper/short strike must be from \
5% below to 10% above the entry trigger. If entry is immediate with no trigger, \
the upper strike must be within 5% of current spot. If entry_logic is ambiguous, \
default to confirmation_required and infer the trigger from the most prominent \
price level in entry_logic.

The invalidation_thesis must be distinct from the price stop. A stop says when \
risk is cut; an invalidation thesis says what would prove the investment thesis \
wrong. Produce at least three distinct falsifiers: price action, fundamental or \
earnings, and regime/positioning where relevant.

Respect the trader profile. If short stock is not allowed, express bearish \
views with puts or put spreads. If options are disallowed, use stock. For weak \
or unclear variant views, avoid options and favor small stock probes.

Before choosing an instrument, determine the priority's overall thesis \
direction. This is what direction the PRIORITY is betting on, not what \
direction the individual candidate's technical context suggests.

Allowed priority_thesis_direction values:
- bullish: the priority is long the underlying assets or beneficiaries
- bearish: the priority is short/negative on the underlying assets or losers
- pair: the priority is relative value, long one set and short another
- neutral: the priority is direction-agnostic, volatility, dispersion, or \
premium collection
- ambiguous: the priority prose does not clearly imply one direction

Examples:
- "Beneficiaries of Fed dovish pivot" -> bullish
- "Supply-shock losers" -> bearish
- "Capital rotation into quality" -> pair or bullish depending on framing
- "Dry powder dynamics" -> ambiguous
- "Vol dispersion in single names" -> neutral

Priority direction dominates individual candidate technicals for direction \
selection. If a bullish priority has a candidate in a bearish technical setup, \
try to express the bullish thesis through a pullback/reversal structure rather \
than choosing puts. If you cannot find a sensible expression in the priority's \
direction, be honest; the system will reject directionally contradictory \
outputs.

# Few-shot examples

Example 1: Strong bullish-contrarian profitable single name in an uptrend.
Input anchors: current price 242, SMA50 228, SMA200 201, 52w high 265, target \
DTE 90. Eligible: long_stock, long_call, long_call_spread.
Output shape: choose long_call_spread; description "long Sep 2026 $245/$270 \
call spread"; rationale says spread captures upside to the 52w high with \
defined risk and avoids overpaying for far-tail calls. Alternative: long stock, \
rejected because options give better capital efficiency. Entry: buy on pullback \
toward SMA50 or reclaim after test. Stop: thesis/risk review if close below \
SMA200. Target: near 52w high with target_derivation.method="technical", \
inputs_used naming the 52w high and trend context, implied_price=265. \
Falsifiers: price break below SMA200, earnings guide fails to show backlog \
conversion, regime rates shock pressures duration multiples. Review cadence \
weekly or event-driven around earnings.

Example 2: Bearish thesis where short stock is not allowed.
Input anchors: current price 58, low20d 54, SMA50 62, target DTE 75. Eligible: \
long_put, long_put_spread.
Output shape: choose long_put; description "long Aug 2026 $55 puts"; rationale \
says uncapped downside is worth paying for because the catalyst can gap lower. \
Alternative: long_put_spread, rejected because premium is cheap enough that \
capping the downside payoff is unnecessary. Entry: buy on breakdown below the \
20-day low. Target: thesis-based: no defined price target, because the catalyst \
is an earnings gap and not a cited chart or valuation level; \
target_derivation.method="thesis_based_no_price", inputs_used names that thesis \
input, implied_price=null. Stop: close back above SMA50. Falsifiers: price \
recaptures SMA50, reported retention improves, forward Fed path turns \
materially dovish and rescues the long-duration basket.

Example 3: Weak or unclear variant.
Input anchors: current price 80, SMA50 76, SMA200 72, target DTE informational. \
Eligible: long_stock only.
Output shape: choose long_stock; description "small long stock probe"; rationale \
says options are avoided because the variant view is not clean enough to pay \
premium. Alternative: no entry, rejected because the theme is still researchable \
at a small size. Entry: scale in on pullback toward SMA50. Stop: below SMA200 \
or thesis deterioration. Target: exit on a 2-ATR move from entry with \
target_derivation.method="volatility", inputs_used naming ATR and current price, \
implied_price consistent with the target. Falsifiers: price breaks trend, next \
earnings fails to confirm the operating signal, consensus fully prices the \
variant before position entry.

Example 4: Direction alignment overrides bearish technicals.
Priority: "Dovish pivot beneficiaries - long rate-sensitive names"; \
priority_thesis_direction: bullish. Candidate: homebuilder XXX with weak \
near-term price trend but a plausible variant view that lower mortgage rates \
can reaccelerate orders. Input anchors: current price 90, SMA50 96, SMA200 88, \
52w high 110, target DTE 90. Eligible: long_stock, long_call_spread.
Output shape: choose long_call_spread; description "long Sep 2026 $90/$110 \
call spread"; rationale says the priority is explicitly bullish on \
rate-sensitive beneficiaries, so bearish technicals should affect entry timing \
and sizing, not flip the direction into puts. Alternative: long_put_spread, \
rejected because it would contradict the dovish-pivot beneficiary thesis. \
Entry: buy only on stabilization above SMA200 or reclaim of short-term support. \
Target: 52w high with target_derivation.method="technical", inputs_used naming \
the 52w high and SMA200 stabilization reference, implied_price=110. Stop: thesis \
review if price loses SMA200 and mortgage-rate relief fails to appear. \
Falsifiers: price loses SMA200 without reversal, orders/gross margin miss in \
earnings, Fed path reprices away from cuts.

Return only the structured object requested by the API.
"""


@lru_cache(maxsize=1)
def load_tenor_rules() -> dict:
    with TENOR_RULES_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("tenor_rules.yaml must contain a mapping")
    return raw


@lru_cache(maxsize=1)
def load_sizing_rules() -> dict:
    with SIZING_RULES_PATH.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError("sizing_rules.yaml must contain a mapping")
    return raw


def _first_priority_horizon(regime: RegimeState) -> EdgeDecayHorizon:
    if regime.research_priorities:
        return regime.research_priorities[0].expected_edge_decay
    return EdgeDecayHorizon.MONTHS


def _infer_thesis_direction(candidate: Candidate) -> ThesisDirection:
    text = " ".join(
        [
            candidate.thematic_fit,
            candidate.consensus_view,
            candidate.potential_variant_view,
        ]
    ).lower()
    if candidate.instrument_type == InstrumentType.PAIR or any(
        phrase in text for phrase in ["pair trade", "long/short", "long-short", "relative value"]
    ):
        return ThesisDirection.RELATIVE_VALUE
    bearish_terms = [
        "short",
        "downside",
        "decline",
        "overvalued",
        "bearish",
        "margin compression",
        "credit stress",
        "deteriorat",
        "mispriced downside",
    ]
    if any(term in text for term in bearish_terms):
        return ThesisDirection.BEARISH
    return ThesisDirection.BULLISH


def _priority_text(priority: ResearchPriority | None) -> str:
    if priority is None:
        return ""
    return " ".join(
        [
            priority.theme,
            priority.rationale,
            priority.edge_hypothesis,
            " ".join(priority.sub_questions),
        ]
    )


def _infer_priority_direction(
    priority: ResearchPriority | None,
    candidate: Candidate,
) -> PriorityThesisDirection:
    """
    Lightweight pre-call direction hint used to constrain eligible structures.

    The structured LLM output is still asked to classify the priority direction
    explicitly; this helper only prevents the prompt from offering obviously
    contradictory instruments when the priority prose is clear.
    """
    if priority is None:
        candidate_direction = _infer_thesis_direction(candidate)
        if candidate_direction == ThesisDirection.BEARISH:
            return PriorityThesisDirection.BEARISH
        if candidate_direction == ThesisDirection.RELATIVE_VALUE:
            return PriorityThesisDirection.PAIR
        return PriorityThesisDirection.BULLISH

    text = _priority_text(priority).lower()
    if not text:
        return PriorityThesisDirection.AMBIGUOUS

    if any(
        phrase in text
        for phrase in [
            "pair trade",
            "long/short",
            "long-short",
            "relative value",
        ]
    ):
        return PriorityThesisDirection.PAIR
    if any(
        phrase in text
        for phrase in [
            "vol dispersion",
            "volatility",
            "dispersion",
            "premium collection",
            "direction-agnostic",
        ]
    ):
        return PriorityThesisDirection.NEUTRAL
    if any(
        phrase in text
        for phrase in [
            "dry powder",
            "capital deployment",
            "where does capital",
            "positioning dynamics",
        ]
    ):
        return PriorityThesisDirection.AMBIGUOUS
    if any(
        phrase in text
        for phrase in [
            "beneficiaries",
            "benefit",
            "winners",
            "convexity",
            "dovish pivot",
            "fed-pivot",
            "rate-sensitive laggards",
            "long ",
            "upside",
            "re-rate",
        ]
    ):
        return PriorityThesisDirection.BULLISH
    if any(
        phrase in text
        for phrase in [
            "losers",
            "short ",
            "downside",
            "breaks",
            "fragility",
            "stress",
            "vulnerable",
            "bearish",
            "hedge",
        ]
    ):
        return PriorityThesisDirection.BEARISH
    return PriorityThesisDirection.AMBIGUOUS


def _priority_direction_to_thesis_direction(
    priority_direction: PriorityThesisDirection,
    candidate: Candidate,
) -> ThesisDirection:
    if priority_direction == PriorityThesisDirection.BULLISH:
        return ThesisDirection.BULLISH
    if priority_direction == PriorityThesisDirection.BEARISH:
        return ThesisDirection.BEARISH
    if priority_direction == PriorityThesisDirection.PAIR:
        return ThesisDirection.RELATIVE_VALUE
    return _infer_thesis_direction(candidate)


def _allowed_strategies(profile: TraderProfile) -> list[str]:
    allowed = profile.instruments_allowed
    return [
        name
        for name in [
            "long_stock",
            "short_stock",
            "long_call",
            "long_put",
            "covered_call",
            "cash_secured_put",
            "long_call_spread",
            "long_put_spread",
            "pair_trade",
        ]
        if bool(getattr(allowed, name))
    ]


def _eligible_strategies(
    *,
    candidate: Candidate,
    direction: ThesisDirection,
    profile: TraderProfile,
) -> list[str]:
    strategies = _allowed_strategies(profile)

    if candidate.variant_strength in (VariantStrength.WEAK, VariantStrength.UNCLEAR):
        return ["long_stock"] if "long_stock" in strategies else strategies[:1]

    if direction == ThesisDirection.RELATIVE_VALUE:
        if "pair_trade" in strategies:
            return ["pair_trade"]
        return ["long_stock"] if "long_stock" in strategies else strategies[:1]

    if direction == ThesisDirection.BEARISH:
        bearish = [s for s in ["long_put", "long_put_spread"] if s in strategies]
        bearish.extend(
            [s for s in ["covered_call", "cash_secured_put"] if s in strategies]
        )
        if bearish:
            return bearish
        if "short_stock" in strategies:
            return ["short_stock"]
        return ["long_stock"] if "long_stock" in strategies else strategies[:1]

    bullish = [
        s
        for s in strategies
        if s
        in {
            "long_stock",
            "long_call",
            "long_call_spread",
            "covered_call",
            "cash_secured_put",
        }
    ]
    if not bullish and "long_stock" in strategies:
        bullish = ["long_stock"]
    return bullish or strategies[:1] or ["long_stock"]


def _nearest_forward_catalyst(
    regime: RegimeState,
    *,
    today: date | None = None,
) -> tuple[int | None, str | None]:
    if regime.forward_context is None:
        return None, None
    today = today or date.today()
    nearest_days = None
    nearest_name = None
    for event in regime.forward_context.upcoming_catalysts:
        try:
            event_date = date.fromisoformat(event.date)
        except ValueError:
            continue
        days = (event_date - today).days
        if days < 0:
            continue
        if nearest_days is None or days < nearest_days:
            nearest_days = days
            nearest_name = f"{event.name} ({event.date})"
    return nearest_days, nearest_name


def compute_tenor_window(
    *,
    edge_decay: EdgeDecayHorizon,
    regime: RegimeState,
    trader_profile: TraderProfile,
    today: date | None = None,
) -> TenorWindow:
    rules = load_tenor_rules()
    tenor_rules = rules["tenor_rules"]
    catalyst_buffer = int(rules["catalyst_buffer_days"])
    days_to_catalyst, catalyst_name = _nearest_forward_catalyst(regime, today=today)

    if edge_decay in (EdgeDecayHorizon.DAYS, EdgeDecayHorizon.WEEKS):
        bucket = "weeks"
        key = (
            "catalyst_within_30d"
            if days_to_catalyst is not None and days_to_catalyst <= 30
            else "no_near_catalyst"
        )
    elif edge_decay == EdgeDecayHorizon.MONTHS:
        bucket = "months"
        key = (
            "catalyst_within_60d"
            if days_to_catalyst is not None and days_to_catalyst <= 60
            else "no_near_catalyst"
        )
    else:
        bucket = "quarters"
        key = "any"

    config = tenor_rules[bucket][key]
    min_dte = int(config["min_dte"])
    target_dte = int(config["target_dte"])
    max_dte = int(config["max_dte"])
    if days_to_catalyst is not None:
        target_dte = max(target_dte, days_to_catalyst + catalyst_buffer)

    floor = trader_profile.constraints.min_option_dte
    ceiling = trader_profile.constraints.max_option_dte
    min_dte = max(floor, min(min_dte, ceiling))
    max_dte = max(min_dte, min(max_dte, ceiling))
    target_dte = max(min_dte, min(target_dte, max_dte))
    return TenorWindow(
        min_dte=min_dte,
        target_dte=target_dte,
        max_dte=max_dte,
        rule_key=f"{bucket}.{key}",
        nearest_catalyst=catalyst_name,
    )


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.2f}"


def compute_technical_anchors(
    *,
    market: MarketDataBundle,
    direction: ThesisDirection,
) -> TechnicalAnchors:
    price = market.current_price
    tech = market.technicals
    if tech is None or price is None:
        return TechnicalAnchors(
            current_price=price,
            trend_regime=None,
            entry_reference="Scale in only after confirming liquid market data.",
            stop_reference="Use a conservative stop until technical data is available.",
            target_reference="Target a 2:1 reward/risk setup after market data refresh.",
        )

    atr = tech.atr_14 or (price * 0.05)
    trend = tech.trend_regime
    if direction == ThesisDirection.BEARISH:
        entry = tech.low_20d or price
        stop = tech.sma_50 or (price + 2 * atr)
        target = max(0.01, entry - 2 * abs(stop - entry))
        return TechnicalAnchors(
            current_price=price,
            trend_regime=trend,
            entry_reference=(
                f"Enter on close below 20-day low near {_money(entry)}."
            ),
            stop_reference=f"Risk stop on close back above {_money(stop)}.",
            target_reference=f"Initial downside target near {_money(target)}.",
        )

    entry = tech.sma_50 if trend == "uptrend" and tech.sma_50 else price
    stop_base = entry - 2 * atr
    if tech.sma_200 is not None:
        stop_base = min(stop_base, tech.sma_200)
    reward_target = entry + 2 * abs(entry - stop_base)
    if tech.high_52w is not None and tech.high_52w > entry:
        target = min(tech.high_52w, reward_target)
    else:
        target = reward_target
    entry_text = (
        f"Enter on pullback toward SMA50 near {_money(entry)}."
        if trend == "uptrend"
        else f"Scale in around current price near {_money(price)}."
    )
    return TechnicalAnchors(
        current_price=price,
        trend_regime=trend,
        entry_reference=entry_text,
        stop_reference=f"Risk stop below {_money(stop_base)}.",
        target_reference=f"Initial upside target near {_money(target)}.",
    )


def _conviction_factor_key(candidate: Candidate, screen: FundamentalScreen) -> str:
    if screen.crowding_flag or screen.data_quality_flag:
        return "weak_or_flagged"
    if (
        candidate.variant_strength == VariantStrength.STRONG
        and candidate.fit_strength >= 0.80
    ):
        return "strong_clean"
    if candidate.variant_strength == VariantStrength.STRONG or (
        candidate.variant_strength == VariantStrength.MODERATE
        and candidate.fit_strength >= 0.80
    ):
        return "strong_or_high_fit"
    if candidate.variant_strength == VariantStrength.MODERATE:
        return "moderate_default"
    return "weak_or_flagged"


def compute_base_sizing(
    *,
    candidate: Candidate,
    screen: FundamentalScreen,
    trader_profile: TraderProfile,
) -> tuple[float, str]:
    sizing = load_sizing_rules()["sizing_rules"]
    key = _conviction_factor_key(candidate, screen)
    factor = float(sizing["conviction_factors"][key])
    return trader_profile.constraints.max_position_pct * factor, key


def max_loss_for_strategy(base_size_pct: float, strategy: str) -> float:
    estimates = load_sizing_rules()["sizing_rules"]["max_loss_estimates"]
    return base_size_pct * float(estimates.get(strategy, estimates["long_stock"]))


def _schema_instrument_type(strategy: str, candidate: Candidate) -> InstrumentType:
    if strategy == "pair_trade":
        return InstrumentType.PAIR
    if strategy in OPTION_STRATEGIES:
        return InstrumentType.OPTION_UNDERLYING
    return candidate.instrument_type


def _direction_for_strategy(strategy: str, thesis_direction: ThesisDirection) -> TradeDirection:
    if strategy == "pair_trade":
        return TradeDirection.PAIR_LONG_SHORT
    if strategy in {"long_call_spread", "long_put_spread"}:
        return TradeDirection.SPREAD
    if strategy in {"long_put", "long_put_spread"} or thesis_direction == ThesisDirection.BEARISH:
        return TradeDirection.SHORT
    return TradeDirection.LONG


def _effective_direction(instrument_type: str, direction: TradeDirection) -> str:
    """
    Map a chosen instrument to its effective directional exposure.

    Returns one of: bullish, bearish, pair, neutral.
    """
    if direction == TradeDirection.PAIR_LONG_SHORT:
        return "pair"
    if direction == TradeDirection.NEUTRAL:
        return "neutral"
    if instrument_type in {"covered_call", "cash_secured_put"}:
        return "neutral"
    if instrument_type == "iron_condor":
        return "neutral"
    if instrument_type in {"long_stock", "long_call", "long_call_spread"}:
        return "bullish"
    if instrument_type in {"long_put", "long_put_spread"}:
        return "bearish"
    if direction == TradeDirection.SHORT:
        return "bearish"
    return "neutral"


def _check_direction_alignment(
    priority_direction: str,
    effective_direction: str,
) -> tuple[bool, str | None]:
    """Return whether the priority direction and trade exposure align."""
    if effective_direction in ("pair", "neutral"):
        return True, None
    if priority_direction == "ambiguous":
        return True, None
    if priority_direction == "neutral":
        return True, None
    if priority_direction == "pair":
        return True, None
    if priority_direction == "bullish" and effective_direction == "bearish":
        return (
            False,
            "Priority thesis is bullish but chosen instrument expresses bearish exposure",
        )
    if priority_direction == "bearish" and effective_direction == "bullish":
        return (
            False,
            "Priority thesis is bearish but chosen instrument expresses bullish exposure",
        )
    return True, None


class StrikeRuleViolation(ValueError):
    """Raised when a spread's stated upper strike violates entry-reference rules."""


def _target_derivation_from_output(output: _TargetDerivationOutput) -> TargetDerivation:
    return TargetDerivation(
        method=output.method,
        inputs_used=output.inputs_used,
        implied_price=output.implied_price,
    )


def _extract_dollar_prices(text: str) -> list[float]:
    return [
        float(match)
        for match in re.findall(r"\$\s*(\d+(?:\.\d+)?)", text or "")
    ]


def _infer_entry_metadata(entry_logic: str) -> tuple[str, float | None]:
    text = entry_logic.lower()
    prices = _extract_dollar_prices(entry_logic)
    trigger_price = prices[0] if prices else None
    immediate_markers = [
        "immediate",
        "buy now",
        "open now",
        "starter position near current",
        "around current price",
        "scale in around current price",
    ]
    confirmation_markers = [
        "enter on",
        "enter only",
        "buy after",
        "wait for",
        "confirmation",
        "confirmed",
        "close below",
        "close above",
        "breakdown",
        "breakout",
        "trigger",
        "pullback toward",
        "reclaim",
    ]
    if any(marker in text for marker in immediate_markers) and not any(
        marker in text for marker in confirmation_markers
    ):
        return "immediate", None
    if trigger_price is not None or any(marker in text for marker in confirmation_markers):
        return "confirmation_required", trigger_price
    return "immediate", None


def _append_note(existing: str | None, note: str) -> str:
    return f"{existing}\n{note}" if existing else note


def _strike_rule_note(
    *,
    strategy: str,
    expression: TradeExpression,
    reference_price: float | None,
) -> str | None:
    if strategy not in {"long_put_spread", "long_call_spread"}:
        return None

    strikes = _extract_dollar_prices(expression.primary_instrument.description)
    if len(strikes) < 2:
        return (
            "strike_rule_warning: spread description did not include two dollar "
            "strikes, so upper-strike geometry could not be validated."
        )

    upper_strike = max(strikes)
    is_triggered = expression.entry_mode == "confirmation_required"
    reference = expression.entry_trigger_price if is_triggered else reference_price
    if reference is None or reference <= 0:
        return (
            "strike_rule_warning: entry reference price was unavailable, so "
            "upper-strike geometry could not be validated."
        )

    if is_triggered and strategy == "long_put_spread":
        lower_bound = reference * 0.90
        upper_bound = reference * 1.05
    elif is_triggered and strategy == "long_call_spread":
        lower_bound = reference * 0.95
        upper_bound = reference * 1.10
    else:
        lower_bound = reference * 0.95
        upper_bound = reference * 1.05

    tolerance = reference * 0.02
    if upper_strike < lower_bound - tolerance or upper_strike > upper_bound + tolerance:
        return (
            "strike_rule_warning: upper strike "
            f"{_money(upper_strike)} violates {expression.entry_mode} rule "
            f"around reference {_money(reference)}; allowed range "
            f"{_money(lower_bound)}-{_money(upper_bound)} before 2% tolerance."
        )
    return (
        "strike_rule_validated: upper strike "
        f"{_money(upper_strike)} conforms to {expression.entry_mode} rule "
        f"around reference {_money(reference)}."
    )


def _enforce_strike_rule(
    *,
    strategy: str,
    expression: TradeExpression,
    reference_price: float | None,
) -> str | None:
    note = _strike_rule_note(
        strategy=strategy,
        expression=expression,
        reference_price=reference_price,
    )
    if note and note.startswith("strike_rule_warning"):
        raise StrikeRuleViolation(note)
    return note


def _instrument_from_strategy(
    *,
    candidate: Candidate,
    strategy: str,
    description: str,
    thesis_direction: ThesisDirection,
) -> Instrument:
    return Instrument(
        ticker=candidate.ticker,
        instrument_type=_schema_instrument_type(strategy, candidate),
        direction=_direction_for_strategy(strategy, thesis_direction),
        description=description,
    )


def _falsifier_from_output(output: _FalsifierOutput) -> Falsifier:
    return Falsifier(
        condition=output.condition,
        observable_in=output.observable_in,
        check_frequency=output.check_frequency,
        notes=output.notes,
    )


def _fallback_components(
    *,
    candidate: Candidate,
    screen: FundamentalScreen,
    market: MarketDataBundle,
    regime: RegimeState,
    trader_profile: TraderProfile,
    reason: str,
) -> TradeExpressionComponents:
    base_size = min(trader_profile.constraints.max_position_pct * 0.20, 0.01)
    price = market.current_price
    stop_text = (
        f"Cut the fallback probe if {candidate.ticker} closes materially below recent support."
    )
    target_text = (
        "Take profits or re-underwrite when the variant view is reflected in consensus commentary."
    )
    expression = TradeExpression(
        primary_instrument=_instrument_from_strategy(
            candidate=candidate,
            strategy="long_stock",
            description=f"Small long {candidate.ticker} stock probe",
            thesis_direction=ThesisDirection.BULLISH,
        ),
        rationale_for_instrument=(
            "Fallback expression uses common equity because the agent could not "
            "safely validate a more complex instrument and the position is sized conservatively."
        ),
        alternatives_considered=[
            AlternativeRejected(
                instrument=_instrument_from_strategy(
                    candidate=candidate,
                    strategy="long_call",
                    description="Fallback-rejected long call",
                    thesis_direction=ThesisDirection.BULLISH,
                ),
                why_rejected=(
                    "Options were rejected because the expression agent fell back "
                    "and should not invent option specifics."
                ),
            )
        ],
        entry_logic=(
            f"Open only a small starter position near current price {_money(price)} "
            "and require manual review before adding."
        ),
        entry_mode="immediate",
        entry_trigger_price=None,
        target_derivation=TargetDerivation(
            method="thesis_based_no_price",
            inputs_used=[
                "Fallback path uses thesis review rather than a defined price target.",
                "No validated technical, valuation, analyst, measured-move, or volatility target was available.",
            ],
            implied_price=None,
        ),
        exit_target=target_text,
        exit_stop=stop_text,
        exit_time_stop="Review after 30 trading days if the thesis has not started to play out.",
        hedges=[],
    )
    falsifiers = [
        Falsifier(
            condition=f"{candidate.ticker} breaks below recent technical support and fails to reclaim it within five trading days.",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        ),
        Falsifier(
            condition=f"{candidate.ticker} next earnings update contradicts the candidate's variant view.",
            observable_in=FalsifierObservable.EARNINGS,
            check_frequency=FalsifierFrequency.EVENT_DRIVEN,
        ),
        Falsifier(
            condition="Regime forward context moves materially against the thesis and removes the expected catalyst path.",
            observable_in=FalsifierObservable.DATA_SERIES,
            check_frequency=FalsifierFrequency.WEEKLY,
        ),
    ]
    return TradeExpressionComponents(
        expression=expression,
        proposed_sizing=ProposedSizing(
            base_size_pct=base_size,
            sizing_logic=(
                "Fallback sizing uses 20% of the configured max position because "
                "the expression agent could not validate a tailored structure."
            ),
            kelly_implied=None,
            max_loss_estimate_pct=max_loss_for_strategy(base_size, "long_stock"),
        ),
        invalidation_thesis=(
            "The thesis is invalidated if the candidate's specific variant view "
            "is contradicted by earnings, company guidance, or the relevant regime context."
        ),
        trade_falsifiers=falsifiers,
        expected_holding_period="Manual review within 30 trading days",
        thesis_review_cadence=ReviewCadence.WEEKLY,
        provenance=TradeProvenance(
            fundamental_analysis_id=screen.id,
            regime_state_id=regime.id,
        ),
        selected_strategy="long_stock",
        fallback_used=True,
        notes=f"fallback_used: {reason}",
    )


def _review_cadence_for_horizon(
    edge_decay: EdgeDecayHorizon,
    tenor: TenorWindow,
) -> ReviewCadence:
    if tenor.nearest_catalyst:
        return ReviewCadence.EVENT_DRIVEN
    if edge_decay in (EdgeDecayHorizon.DAYS, EdgeDecayHorizon.WEEKS, EdgeDecayHorizon.MONTHS):
        return ReviewCadence.WEEKLY
    return ReviewCadence.MONTHLY


def _prompt_user_message(
    *,
    priority: ResearchPriority | None,
    candidate: Candidate,
    screen: FundamentalScreen,
    fundamentals: FundamentalDataBundle,
    market: MarketDataBundle,
    regime: RegimeState,
    priority_direction_hint: PriorityThesisDirection,
    direction: ThesisDirection,
    eligible: list[str],
    tenor: TenorWindow,
    anchors: TechnicalAnchors,
    base_size_pct: float,
    sizing_key: str,
) -> str:
    forward = regime.forward_context
    catalysts = []
    if forward is not None:
        catalysts = [
            f"{event.name} on {event.date} ({event.category}, {event.significance})"
            for event in forward.upcoming_catalysts[:3]
        ]
    return (
        "Priority context:\n"
        f"Priority theme: {priority.theme if priority else '(not supplied)'}\n"
        f"Priority rationale: {priority.rationale if priority else '(not supplied)'}\n"
        f"Priority edge hypothesis: {priority.edge_hypothesis if priority else '(not supplied)'}\n"
        f"Priority direction hint: {priority_direction_hint.value}\n\n"
        f"Candidate: {candidate.ticker} ({candidate.name})\n"
        f"Thematic fit: {candidate.thematic_fit}\n"
        f"Consensus view: {candidate.consensus_view}\n"
        f"Potential variant view: {candidate.potential_variant_view}\n"
        f"Variant strength: {candidate.variant_strength.value}\n"
        f"Fit strength: {candidate.fit_strength:.2f}\n"
        f"Screen: {screen.verdict.value} / {screen.archetype.value}: {screen.reason}\n"
        f"Crowding flag: {screen.crowding_flag}; data quality flag: {screen.data_quality_flag}\n"
        f"Current price: {fundamentals.current_price or market.current_price}\n"
        f"Candidate-derived expression direction: {direction.value}\n"
        f"Eligible instruments: {eligible}\n"
        f"Tenor window: min {tenor.min_dte}, target {tenor.target_dte}, max {tenor.max_dte}; "
        f"rule {tenor.rule_key}; nearest catalyst {tenor.nearest_catalyst}\n"
        f"Technical anchors: entry={anchors.entry_reference}; stop={anchors.stop_reference}; "
        f"target={anchors.target_reference}; trend={anchors.trend_regime}\n"
        f"Base size pct already computed: {base_size_pct:.4f}; sizing factor key {sizing_key}\n"
        f"Forward catalysts: {catalysts}\n"
        f"Regime headline: {regime.headline}\n"
    )


def _components_from_llm(
    *,
    output: _TradeExpressionLLMOutput,
    candidate: Candidate,
    screen: FundamentalScreen,
    regime: RegimeState,
    direction: ThesisDirection,
    eligible: list[str],
    base_size_pct: float,
    reference_price: float | None,
    allow_strike_warning: bool = False,
) -> TradeExpressionComponents | TradeExpressionRejection:
    strategy = output.chosen_instrument_type
    if strategy not in eligible:
        raise ValueError(
            f"LLM chose ineligible strategy {strategy!r}; eligible={eligible!r}"
        )
    if len(output.trade_falsifiers) < 3:
        raise ValueError("LLM returned fewer than 3 trade_falsifiers")
    if not output.alternatives_considered:
        raise ValueError("LLM returned no alternatives_considered")

    priority_direction = output.priority_thesis_direction
    if "priority_thesis_direction" not in output.model_fields_set:
        logger.warning(
            "trade expression output missing priority_thesis_direction for %s; "
            "treating as ambiguous",
            candidate.ticker,
        )
        priority_direction = PriorityThesisDirection.AMBIGUOUS

    instrument_direction = _direction_for_strategy(strategy, direction)
    effective_direction = _effective_direction(strategy, instrument_direction)
    aligned, misalignment_reason = _check_direction_alignment(
        priority_direction.value,
        effective_direction,
    )
    if not aligned:
        assert misalignment_reason is not None
        return TradeExpressionRejection(
            misalignment_reason=misalignment_reason,
            priority_thesis_direction=priority_direction,
            effective_direction=effective_direction,
            selected_strategy=strategy,
        )

    primary = _instrument_from_strategy(
        candidate=candidate,
        strategy=strategy,
        description=output.primary_instrument_description,
        thesis_direction=direction,
    )
    alternatives = [
        AlternativeRejected(
            instrument=_instrument_from_strategy(
                candidate=candidate,
                strategy=alt.instrument_type,
                description=alt.instrument_description,
                thesis_direction=direction,
            ),
            why_rejected=alt.why_rejected,
        )
        for alt in output.alternatives_considered
    ]
    entry_mode, entry_trigger_price = _infer_entry_metadata(output.entry_logic)
    expression = TradeExpression(
        primary_instrument=primary,
        rationale_for_instrument=output.rationale_for_instrument,
        alternatives_considered=alternatives,
        entry_logic=output.entry_logic,
        entry_mode=entry_mode,
        entry_trigger_price=entry_trigger_price,
        target_derivation=_target_derivation_from_output(output.target_derivation),
        exit_target=output.exit_target,
        exit_stop=output.exit_stop,
        exit_time_stop=output.exit_time_stop,
        hedges=[],
    )
    if allow_strike_warning:
        strike_note = _strike_rule_note(
            strategy=strategy,
            expression=expression,
            reference_price=reference_price,
        )
    else:
        strike_note = _enforce_strike_rule(
            strategy=strategy,
            expression=expression,
            reference_price=reference_price,
        )
    return TradeExpressionComponents(
        expression=expression,
        proposed_sizing=ProposedSizing(
            base_size_pct=base_size_pct,
            sizing_logic=output.sizing_logic,
            kelly_implied=None,
            max_loss_estimate_pct=max_loss_for_strategy(base_size_pct, strategy),
        ),
        invalidation_thesis=output.invalidation_thesis,
        trade_falsifiers=[_falsifier_from_output(f) for f in output.trade_falsifiers],
        expected_holding_period=output.expected_holding_period,
        thesis_review_cadence=output.thesis_review_cadence,
        provenance=TradeProvenance(
            fundamental_analysis_id=screen.id,
            regime_state_id=regime.id,
        ),
        selected_strategy=strategy,
        fallback_used=False,
        notes=_append_note(output.notes, strike_note) if strike_note else output.notes,
    )


async def express_trade(
    candidate: Candidate,
    screen: FundamentalScreen,
    fundamentals: FundamentalDataBundle,
    market: MarketDataBundle,
    regime: RegimeState,
    trader_profile: TraderProfile,
    priority: ResearchPriority | None = None,
) -> TradeExpressionComponents | TradeExpressionRejection:
    """
    Produce the components needed to build a TradeIdea.

    This function never raises to callers. If the structured LLM call fails or
    produces invalid components, a conservative long-stock fallback is returned
    with fallback_used=True in the component notes.
    """

    priority_direction_hint = _infer_priority_direction(priority, candidate)
    direction = _priority_direction_to_thesis_direction(
        priority_direction_hint,
        candidate,
    )
    if (
        priority is not None
        and priority_direction_hint != PriorityThesisDirection.PAIR
        and candidate.variant_strength
        not in (VariantStrength.WEAK, VariantStrength.UNCLEAR)
    ):
        eligible = [
            strategy
            for strategy in _allowed_strategies(trader_profile)
            if strategy != "pair_trade"
        ]
    else:
        eligible = _eligible_strategies(
            candidate=candidate,
            direction=direction,
            profile=trader_profile,
        )
    if not eligible:
        eligible = ["long_stock"]
    edge_decay = _first_priority_horizon(regime)
    tenor = compute_tenor_window(
        edge_decay=edge_decay,
        regime=regime,
        trader_profile=trader_profile,
    )
    anchors = compute_technical_anchors(market=market, direction=direction)
    base_size_pct, sizing_key = compute_base_sizing(
        candidate=candidate,
        screen=screen,
        trader_profile=trader_profile,
    )

    try:
        from src.agent_system.llm.client import parse_structured
        from src.agent_system.llm.config import TRADE_EXPRESSION_AGENT_MODEL

        user_message = _prompt_user_message(
            priority=priority,
            candidate=candidate,
            screen=screen,
            fundamentals=fundamentals,
            market=market,
            regime=regime,
            priority_direction_hint=priority_direction_hint,
            direction=direction,
            eligible=eligible,
            tenor=tenor,
            anchors=anchors,
            base_size_pct=base_size_pct,
            sizing_key=sizing_key,
        )
        reference_price = fundamentals.current_price or market.current_price
        strike_retry_reason: str | None = None
        for attempt in range(2):
            retry_suffix = ""
            if strike_retry_reason is not None:
                retry_suffix = (
                    "\n\nPrevious output violated the spread upper-strike rule. "
                    f"Fix the instrument description and entry metadata implication: {strike_retry_reason}"
                )
            output = parse_structured(
                system=SYSTEM_PROMPT_TEMPLATE,
                user=user_message + retry_suffix,
                model=TRADE_EXPRESSION_AGENT_MODEL,
                response_schema=_TradeExpressionLLMOutput,
                purpose=f"trade expression agent express_trade: {candidate.ticker}",
                temperature=0.3,
            )
            try:
                return _components_from_llm(
                    output=output,
                    candidate=candidate,
                    screen=screen,
                    regime=regime,
                    direction=direction,
                    eligible=eligible,
                    base_size_pct=base_size_pct,
                    reference_price=reference_price,
                    allow_strike_warning=attempt == 1,
                )
            except StrikeRuleViolation as exc:
                strike_retry_reason = str(exc)
                logger.warning(
                    "trade expression strike-rule retry for %s: %s",
                    candidate.ticker,
                    strike_retry_reason,
                )
                continue

        raise StrikeRuleViolation(strike_retry_reason or "spread strike validation failed")
    except (StructuredOutputError, ValidationError, ValueError, Exception) as exc:
        logger.warning("trade expression fallback for %s: %s", candidate.ticker, exc)
        return _fallback_components(
            candidate=candidate,
            screen=screen,
            market=market,
            regime=regime,
            trader_profile=trader_profile,
            reason=f"{type(exc).__name__}: {exc}",
        )
