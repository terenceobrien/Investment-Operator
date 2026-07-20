"""Build TradeOutcome records for system-rejected candidates."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.schemas.trade_outcome import TradeOutcome
from src.agent_system.services.trade_outcome_builder import (
    _describe_instrument,
    _enum_value,
    _extract_stop_price,
    _extract_target_price,
    _extract_variant_strength,
    _outcome_direction,
)


def _entry_value(entry: dict[str, Any] | object, field: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(field, default)
    return getattr(entry, field, default)


def _rejection_reason(entry: dict[str, Any] | object) -> str:
    rule_applied = _entry_value(entry, "rule_applied", "unknown") or "unknown"
    summary = _entry_value(entry, "summary", "") or ""
    return f"{rule_applied}: {str(summary)[:200]}"


def build_shadow_outcome(
    *,
    trade_idea: TradeIdea,
    decision_log_entry: dict[str, Any] | object,
    cycle_id: str,
    cycle_date: str,
) -> TradeOutcome | None:
    """Create a shadow TradeOutcome for a conviction-gate rejection."""

    if not trade_idea.id:
        return None

    expression = trade_idea.expression
    instrument = expression.primary_instrument if expression is not None else None
    priority = trade_idea.research_priority
    priority_record_id = getattr(trade_idea.provenance, "research_priority_id", None)
    priority_id = (
        getattr(priority, "source_theme_id", None)
        or priority_record_id
        or getattr(priority, "id", None)
    )
    now = datetime.now(timezone.utc)
    description = (
        _describe_instrument(expression)
        if expression is not None
        else f"shadow tracking of {trade_idea.underlying}"
    )
    instrument_type = (
        _enum_value(getattr(instrument, "instrument_type", None), "single_stock")
        or "single_stock"
    )
    direction = (
        _outcome_direction(getattr(instrument, "direction", "long"))
        if instrument is not None
        else "long"
    )
    stop_price = _extract_stop_price(expression) if expression is not None else None
    if stop_price is None:
        stop_price = trade_idea.invalidation_price

    return TradeOutcome(
        trade_id=trade_idea.id,
        cycle_id=cycle_id,
        cycle_date=cycle_date[:10],
        underlying=trade_idea.underlying,
        priority_theme=getattr(priority, "theme", None),
        originating_cycle_id=cycle_id,
        originating_priority_id=priority_id,
        originating_priority_label=getattr(priority, "theme", None),
        originating_priority_scenarios=list(
            getattr(priority, "source_scenario_ids", []) or []
        ),
        direction=direction,
        instrument_type=instrument_type,
        instrument_description=description,
        proposed_size_pct=0.0,
        final_size_pct=0.0,
        decision="shadow_rejected",
        variant_strength=_extract_variant_strength(trade_idea),
        conviction=_enum_value(trade_idea.combined_conviction.rating),
        entry_target_price=None,
        target_price=_extract_target_price(expression) if expression is not None else None,
        stop_price=stop_price,
        invalidation_thesis=trade_idea.invalidation_thesis,
        expected_holding_period=trade_idea.expected_holding_period,
        status="shadow_rejected",
        user_decision=None,
        user_decision_reason=None,
        entry_triggered=False,
        entry_date=None,
        entry_underlying_price=None,
        audit_notes=f"SYSTEM REJECTED: {_rejection_reason(decision_log_entry)}",
        created_at=now,
        updated_at=now,
    )
