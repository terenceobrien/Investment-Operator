"""Current-regime YAML handoff export for the thematic agent."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.agent_system.schemas.current_regime import (
    CurrentRegimeFalsifier,
    CurrentRegimeHandoff,
    CurrentRegimeKeyDriver,
    CurrentRegimeSeedResearchPriority,
)
from src.agent_system.schemas.macro_forecast import MacroForecastResult, MacroInputSignal


def _clamp(value: float | None, default: float = 0.50) -> float:
    if value is None:
        value = default
    return max(0.0, min(1.0, float(value)))


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "macro_forecast_regime"


def _scenario_name(scenario_id: str) -> str:
    labels = {
        "reopening_soft_landing": "Reopening / Soft Landing",
        "sticky_late_cycle_ai": "Sticky Late Cycle AI",
        "oil_inflation_tail": "Oil Inflation Tail",
        "late_cycle_risk_off": "Late Cycle Risk-Off",
        "ai_capex_rollover": "AI Capex Rollover",
    }
    return labels.get(scenario_id, scenario_id.replace("_", " ").title())


def _dominant_and_runner_up(result: MacroForecastResult) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    ordered = sorted(result.scenario_probabilities.items(), key=lambda item: item[1], reverse=True)
    dominant = ordered[0] if ordered else None
    runner_up = ordered[1] if len(ordered) > 1 else None
    return dominant, runner_up


def _probability_text(item: tuple[str, float] | None) -> str:
    if item is None:
        return "n/a"
    return f"{_scenario_name(item[0])} ({item[1]:.0%})"


def _regime_id(result: MacroForecastResult) -> str:
    active_ids: list[str] = []
    input_set = result.forecast_input_set
    if input_set is not None:
        for signal in input_set.all_signals:
            active_ids.extend(signal.active_only_in_regime_ids)
    active_ids = [item for item in active_ids if item]
    if active_ids:
        return _slugify(active_ids[0])
    dominant, _ = _dominant_and_runner_up(result)
    if dominant is not None:
        return _slugify(dominant[0])
    return "macro_forecast_regime"


def _regime_label(result: MacroForecastResult) -> str:
    interpretation = result.forecast_interpretation
    if interpretation is not None and interpretation.regime_read:
        return interpretation.regime_read[:220]
    dominant, _ = _dominant_and_runner_up(result)
    if dominant is not None:
        return _scenario_name(dominant[0])
    return "Macro forecast regime"


def _confidence(result: MacroForecastResult) -> float:
    calibration = result.historical_calibration
    if calibration is not None:
        return _clamp(calibration.confidence)
    interpretation = result.forecast_interpretation
    if interpretation is not None:
        mapping = {"low": 0.40, "medium": 0.60, "high": 0.75}
        return _clamp(mapping.get(interpretation.confidence_level, 0.50))
    dominant, runner_up = _dominant_and_runner_up(result)
    if dominant is not None:
        gap = dominant[1] - (runner_up[1] if runner_up is not None else 0.0)
        return _clamp(0.45 + gap)
    return 0.50


def _summary(result: MacroForecastResult) -> str:
    interpretation = result.forecast_interpretation
    dominant, runner_up = _dominant_and_runner_up(result)
    base = interpretation.summary if interpretation is not None else "Macro forecast produced a deterministic regime read."
    tension = ""
    if interpretation is not None and interpretation.key_tensions:
        tension = f" Key macro tension: {interpretation.key_tensions[0]}"
    return (
        f"{base} Dominant scenario: {_probability_text(dominant)}; "
        f"runner-up scenario: {_probability_text(runner_up)}. "
        f"Probability mode: {result.probability_mode}.{tension}"
    )


def _risk_summary(result: MacroForecastResult) -> str:
    interpretation = result.forecast_interpretation
    parts: list[str] = []
    if interpretation is not None:
        parts.extend(interpretation.key_tensions[:2])
    for shifter in result.probability_shifters[:2]:
        if shifter.would_decrease_probability_if:
            parts.append(f"{_scenario_name(shifter.scenario_id)} could fade if {shifter.would_decrease_probability_if[0]}")
        elif shifter.would_increase_probability_if:
            parts.append(f"{_scenario_name(shifter.scenario_id)} could rise if {shifter.would_increase_probability_if[0]}")
    risk_off = result.scenario_probabilities.get("late_cycle_risk_off")
    capex = result.scenario_probabilities.get("ai_capex_rollover")
    if risk_off is not None or capex is not None:
        tail_values = []
        if risk_off is not None:
            tail_values.append(f"risk-off {risk_off:.0%}")
        if capex is not None:
            tail_values.append(f"AI capex rollover {capex:.0%}")
        parts.append(f"Tail probabilities remain visible: {', '.join(tail_values)}.")
    return " ".join(parts) if parts else "Monitor breadth, credit, volatility, Fed path, and AI capex guidance for regime breaks."


def _signals_by_id(result: MacroForecastResult) -> dict[str, MacroInputSignal]:
    return {signal.input_id: signal for signal in result.input_signals}


def _signal_status(signal: MacroInputSignal | None) -> str:
    if signal is None:
        return "unavailable"
    return f"{signal.signal}/{signal.trend}"


def _signal_explanation(signal: MacroInputSignal | None, fallback: str) -> str:
    if signal is None:
        return fallback
    return signal.notes or fallback


def _key_drivers(result: MacroForecastResult) -> list[CurrentRegimeKeyDriver]:
    signals = _signals_by_id(result)
    driver_specs = [
        ("AI earnings resilience", signals.get("ai_earnings_resilience"), "AI earnings resilience remains a key determinant of leadership durability."),
        ("Breadth / participation", signals.get("market_breadth"), "Breadth determines whether leadership can broaden beyond mega-cap growth."),
        ("Credit conditions", signals.get("credit_conditions"), "Credit health governs the risk-off tail and beta tolerance."),
        ("Fed path / monetary policy", signals.get("monetary_policy_composite") or signals.get("fed_path"), "Fed path and liquidity shape duration and quality leadership."),
        ("Oil shock and reopening optionality", signals.get("oil_reopening_optionality"), "Oil can pressure inflation or unwind if reopening/de-escalation improves."),
        ("Volatility / hedging", signals.get("volatility_layer_summary") or signals.get("put_call_ratio"), "Volatility and hedging conditions determine fragility and need for liquidity."),
    ]
    rows: list[CurrentRegimeKeyDriver] = []
    for name, signal, fallback in driver_specs:
        rows.append(
            CurrentRegimeKeyDriver(
                name=name,
                status=_signal_status(signal),
                explanation=_signal_explanation(signal, fallback),
            )
        )
    return rows


def _readable_items(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        label = str(value).replace("_", " ").replace("/", " / ").strip()
        if label:
            out.append(label[:1].upper() + label[1:])
    return list(dict.fromkeys(out))


def _portfolio_implications(result: MacroForecastResult) -> list[str]:
    interpretation = result.forecast_interpretation
    preferred = _readable_items(interpretation.preferred_exposures if interpretation is not None else [])
    avoid = _readable_items(interpretation.exposures_to_avoid if interpretation is not None else [])
    implications = [
        "Favor themes with positive macro support across the highest-probability scenarios.",
        "Maintain hedges or cash-like exposure while risk-off analogue probability remains elevated.",
        "Distinguish quality AI and grid beneficiaries from high-beta crowded semiconductor beta.",
    ]
    if preferred:
        implications.append(f"Best supported exposures include {', '.join(preferred[:4])}.")
    if avoid:
        implications.append(f"Be cautious with {', '.join(avoid[:4])}.")
    if result.scenario_probabilities.get("oil_inflation_tail", 0.0) > 0.10:
        implications.append("Treat oil and energy exposure as tactical because oil-shock risk remains two-sided.")
    return implications[:6]


def _best_positioned(result: MacroForecastResult) -> list[str]:
    interpretation = result.forecast_interpretation
    values = _readable_items(interpretation.preferred_exposures if interpretation is not None else [])
    values.extend(theme.label for theme in result.theme_rankings[:5])
    return list(dict.fromkeys(item for item in values if item))[:8]


def _most_vulnerable(result: MacroForecastResult) -> list[str]:
    interpretation = result.forecast_interpretation
    values = _readable_items(interpretation.exposures_to_avoid if interpretation is not None else [])
    bottom_themes = sorted(result.theme_rankings, key=lambda item: item.macro_support_score)[:4]
    values.extend(theme.label for theme in bottom_themes)
    defaults = [
        "Small caps",
        "Long-duration growth",
        "High-beta AI semiconductors",
        "Weak balance sheets",
        "Crowded capex beta if capex rollover risk rises",
    ]
    values.extend(defaults)
    return list(dict.fromkeys(item for item in values if item))[:10]


def _observable_for_condition(condition: str) -> str:
    text = condition.lower()
    if any(word in text for word in ["vix", "rsp", "iwm", "spread", "oil", "price", "breadth"]):
        return "price_action"
    if any(word in text for word in ["fed", "cpi", "inflation", "cut", "hike"]):
        return "data_series"
    if any(word in text for word in ["capex", "earnings", "guidance"]):
        return "earnings"
    return "data_series"


def _check_frequency(condition: str) -> str:
    text = condition.lower()
    if any(word in text for word in ["earnings", "guidance", "capex"]):
        return "event_driven"
    if any(word in text for word in ["fed", "cpi", "inflation"]):
        return "weekly"
    return "daily"


def _falsifiers(result: MacroForecastResult) -> list[CurrentRegimeFalsifier]:
    conditions: list[str] = []
    input_set = result.forecast_input_set
    if input_set is not None:
        for signal in input_set.scenario_falsifier_signals:
            if signal.notes:
                conditions.append(signal.notes)
    for shifter in result.probability_shifters:
        conditions.extend(shifter.would_decrease_probability_if[:2])
        conditions.extend(shifter.would_increase_probability_if[:1])
    conditions.extend(
        [
            "Breadth broadens materially with RSP and IWM outperforming SPY.",
            "Fed cut probabilities rise materially.",
            "HY spreads widen materially.",
            "VIX spikes while breadth deteriorates.",
            "AI capex guidance weakens.",
            "Oil risk premium compresses or energy leadership breaks.",
        ]
    )
    unique = list(dict.fromkeys(item for item in conditions if item))
    return [
        CurrentRegimeFalsifier(
            condition=condition,
            observable_in=_observable_for_condition(condition),
            check_frequency=_check_frequency(condition),
        )
        for condition in unique[:10]
    ]


def _priority_from_theme(theme, rank: int) -> CurrentRegimeSeedResearchPriority:
    label = theme.label or theme.theme_id or f"Theme {rank}"
    return CurrentRegimeSeedResearchPriority(
        theme=label,
        rationale=f"{label} ranks highly on macro support in the current forecast.",
        edge_hypothesis=(
            f"The potential edge is that macro scenario support for {label} is stronger than broad market pricing implies, "
            "creating a candidate pool for bottom-up validation."
        ),
        sub_questions=[
            f"Which companies have the cleanest revenue exposure to {label}?",
            "Which names have positive revisions and balance-sheet quality?",
            "Where is crowding low relative to macro support?",
        ],
        priority_rank=rank,
        expected_edge_decay="quarters",
        source_theme_id=theme.theme_id,
        source_scenario_ids=list(theme.best_scenarios[:3]),
    )


def _seed_research_priorities(
    result: MacroForecastResult,
    max_seed_priorities: int,
) -> list[CurrentRegimeSeedResearchPriority]:
    priorities: list[CurrentRegimeSeedResearchPriority] = []
    for index, item in enumerate(result.recommended_research_priorities[:max_seed_priorities], 1):
        priorities.append(
            CurrentRegimeSeedResearchPriority(
                theme=item.theme,
                rationale=item.rationale,
                edge_hypothesis=item.edge_hypothesis,
                sub_questions=list(item.sub_questions),
                priority_rank=item.priority_rank or index,
                expected_edge_decay=getattr(item.expected_edge_decay, "value", str(item.expected_edge_decay)),
                source_theme_id=item.source_theme_id,
                source_scenario_ids=list(item.source_scenario_ids),
                source_macro_forecast_id=item.source_macro_forecast_id,
            )
        )
    if priorities:
        return priorities
    return [
        _priority_from_theme(theme, index)
        for index, theme in enumerate(result.theme_rankings[:max_seed_priorities], 1)
    ]


def build_current_regime_handoff(
    forecast_result: MacroForecastResult,
    max_seed_priorities: int = 5,
) -> CurrentRegimeHandoff:
    """Convert a finalized MacroForecastResult into thematic-agent YAML content."""

    interpretation = forecast_result.forecast_interpretation
    headline = interpretation.headline if interpretation is not None else "Macro forecast regime handoff"
    return CurrentRegimeHandoff(
        regime_id=_regime_id(forecast_result),
        regime_label=_regime_label(forecast_result),
        regime_call_confidence=_confidence(forecast_result),
        headline=headline,
        summary=_summary(forecast_result),
        risk_summary=_risk_summary(forecast_result),
        scenario_probabilities=dict(forecast_result.scenario_probabilities),
        key_drivers=_key_drivers(forecast_result),
        portfolio_implications=_portfolio_implications(forecast_result),
        best_positioned=_best_positioned(forecast_result),
        most_vulnerable=_most_vulnerable(forecast_result),
        falsifiers=_falsifiers(forecast_result),
        seed_research_priorities=_seed_research_priorities(forecast_result, max_seed_priorities),
    )


def _fallback_yaml(value: Any, indent: int = 0) -> str:
    spaces = " " * indent
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{spaces}{key}:")
                lines.append(_fallback_yaml(item, indent + 2))
            else:
                lines.append(f"{spaces}{key}: {_fallback_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                first = True
                for key, nested in item.items():
                    prefix = f"{spaces}- " if first else f"{spaces}  "
                    if isinstance(nested, (dict, list)):
                        lines.append(f"{prefix}{key}:")
                        lines.append(_fallback_yaml(nested, indent + 2))
                    else:
                        lines.append(f"{prefix}{key}: {_fallback_scalar(nested)}")
                    first = False
            else:
                lines.append(f"{spaces}- {_fallback_scalar(item)}")
        return "\n".join(lines)
    return f"{spaces}{_fallback_scalar(value)}"


def _fallback_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if "\n" in text or len(text) > 90:
        return "|\n" + "\n".join(f"  {line}" for line in text.splitlines())
    escaped = text.replace('"', '\\"')
    return f'"{escaped}"'


def _yaml_text(payload: dict[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=100,
        )
    except Exception:
        return _fallback_yaml(payload) + "\n"


def _collision_safe_path(path: Path, *, overwrite: bool, timestamp: str | None) -> Path:
    if overwrite or not path.exists():
        return path
    stamp = timestamp or datetime.now().strftime("%H%M%S")
    candidate = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{stamp}_{counter}{path.suffix}")
        counter += 1
    return candidate


def save_current_regime_yaml(
    handoff: CurrentRegimeHandoff,
    output_dir: str | Path,
    asof_date: str,
    timestamp: str | None = None,
    overwrite: bool = False,
    output_path: str | Path | None = None,
) -> Path:
    """Save a thematic-agent-compatible current-regime YAML handoff."""

    path = Path(output_path) if output_path is not None else Path(output_dir) / f"current_regime_{asof_date}.yaml"
    path = _collision_safe_path(path, overwrite=overwrite, timestamp=timestamp)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = handoff.model_dump(mode="json")
    path.write_text(_yaml_text(payload), encoding="utf-8")
    return path
