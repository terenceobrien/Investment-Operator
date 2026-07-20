"""Build TradeOutcome records from portfolio decisions and trade ideas."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.agent_system.schemas.portfolio_plan import PortfolioTradeDecision
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.schemas.trade_outcome import TradeOutcome


def _enum_value(value, default: str | None = None) -> str | None:
    if value is None:
        return default
    raw = getattr(value, "value", value)
    return str(raw) if raw is not None else default


def _outcome_direction(value) -> str:
    raw = (_enum_value(value, "long") or "long").lower()
    if raw == "pair_long_short":
        return "pair"
    if raw in {"long", "short", "spread", "pair", "neutral"}:
        return raw
    return "long"


def _describe_instrument(expression) -> str:
    instrument = getattr(expression, "primary_instrument", None)
    if instrument is None:
        return "unknown instrument"
    description = (getattr(instrument, "description", "") or "").strip()
    if description:
        return description[:500]

    ticker = (getattr(instrument, "ticker", "") or "").strip()
    direction = _outcome_direction(getattr(instrument, "direction", "long"))
    instrument_type = _enum_value(getattr(instrument, "instrument_type", None), "")
    if instrument_type == "single_stock":
        return f"{direction} {ticker} common stock".strip()
    if instrument_type == "option_underlying":
        return f"{direction} {ticker} option strategy".strip()
    if instrument_type == "pair":
        return f"pair trade anchored on {ticker}".strip()
    return f"{direction} {ticker} {instrument_type}".strip() or "unknown instrument"


def _extract_variant_strength(trade_idea: TradeIdea) -> str | None:
    candidates = [
        getattr(trade_idea, "variant_strength", None),
        getattr(getattr(trade_idea, "fundamental", None), "variant_strength", None),
        getattr(getattr(trade_idea, "narrative", None), "variant_strength", None),
    ]
    for value in candidates:
        raw = _enum_value(value)
        if raw in {"strong", "moderate", "weak"}:
            return raw
    return None


def _extract_entry_price(expression) -> float | None:
    value = getattr(expression, "entry_trigger_price", None)
    return float(value) if isinstance(value, (int, float)) else None


def _extract_target_price(expression) -> float | None:
    target_derivation = getattr(expression, "target_derivation", None)
    value = getattr(target_derivation, "implied_price", None)
    return float(value) if isinstance(value, (int, float)) else None


def _extract_stop_price(expression) -> float | None:
    for attr in ("stop_price", "exit_stop_price"):
        value = getattr(expression, attr, None)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def build_trade_outcome(
    *,
    trade_idea: TradeIdea,
    decision: PortfolioTradeDecision,
    cycle_id: str,
    cycle_date: str,
) -> Optional[TradeOutcome]:
    """Construct a TradeOutcome from a trade idea and portfolio decision pair.

    Returns None if the decision should not generate an outcome.
    """
    if decision.decision == "rejected_portfolio" or decision.final_size_pct <= 0:
        return None
    if trade_idea.expression is None:
        return None

    expression = trade_idea.expression
    instrument = expression.primary_instrument
    now = datetime.now(timezone.utc)
    stop_price = _extract_stop_price(expression)
    if stop_price is None:
        stop_price = trade_idea.invalidation_price
    priority = trade_idea.research_priority
    priority_record_id = getattr(trade_idea.provenance, "research_priority_id", None)
    priority_id = (
        getattr(priority, "source_theme_id", None)
        or priority_record_id
        or getattr(priority, "id", None)
    )

    return TradeOutcome(
        trade_id=decision.trade_id,
        cycle_id=cycle_id,
        cycle_date=cycle_date[:10],
        underlying=decision.underlying,
        priority_theme=decision.priority_theme,
        originating_cycle_id=cycle_id,
        originating_priority_id=priority_id,
        originating_priority_label=getattr(priority, "theme", None) or decision.priority_theme,
        originating_priority_scenarios=list(getattr(priority, "source_scenario_ids", []) or []),
        direction=_outcome_direction(getattr(instrument, "direction", "long")),
        instrument_type=_enum_value(instrument.instrument_type, "unknown") or "unknown",
        instrument_description=_describe_instrument(expression),
        proposed_size_pct=decision.proposed_size_pct,
        final_size_pct=decision.final_size_pct,
        decision=decision.decision,
        variant_strength=_extract_variant_strength(trade_idea),
        conviction=_enum_value(trade_idea.combined_conviction.rating),
        robustness_score=decision.robustness_score,
        robustness_quartile=decision.robustness_quartile,
        entry_target_price=_extract_entry_price(expression),
        target_price=_extract_target_price(expression),
        stop_price=stop_price,
        invalidation_thesis=trade_idea.invalidation_thesis,
        expected_holding_period=trade_idea.expected_holding_period,
        status="proposed",
        created_at=now,
        updated_at=now,
    )
