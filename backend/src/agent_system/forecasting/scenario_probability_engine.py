"""Deterministic scenario probability update engine."""
from __future__ import annotations

import math
from collections.abc import Mapping

from src.agent_system.schemas.macro_forecast import (
    ForecastInputSet,
    InputDedupeConfig,
    MacroInputSignal,
    ProbabilityContribution,
    ScenarioContribution,
    ScenarioMathAudit,
    ScenarioProbabilityConfig,
    ScenarioProbabilityUpdate,
)


EPSILON = 1e-6


def _clamp_probability(value: float) -> float:
    return min(1.0 - EPSILON, max(EPSILON, float(value)))


def _logit(probability: float) -> float:
    p = _clamp_probability(probability)
    return math.log(p / (1.0 - p))


def _softmax_details(
    scores: Mapping[str, float],
    *,
    temperature: float = 1.0,
) -> tuple[dict[str, float], dict[str, float], float]:
    if not scores:
        return {}, {}, 0.0
    adjusted_scores = {
        key: value / max(temperature, EPSILON)
        for key, value in scores.items()
    }
    max_score = max(adjusted_scores.values())
    exp_scores = {key: math.exp(value - max_score) for key, value in adjusted_scores.items()}
    total = sum(exp_scores.values())
    if total <= 0:
        equal = 1.0 / len(exp_scores)
        return {key: equal for key in exp_scores}, exp_scores, total
    return {key: value / total for key, value in exp_scores.items()}, exp_scores, total


def _softmax(scores: Mapping[str, float], *, temperature: float = 1.0) -> dict[str, float]:
    probabilities, _, _ = _softmax_details(scores, temperature=temperature)
    return probabilities


def _as_priors(priors: Mapping[str, float] | object) -> dict[str, float]:
    if isinstance(priors, Mapping):
        return {str(key): float(value) for key, value in priors.items()}
    scenarios = getattr(priors, "scenarios", None)
    if scenarios is None:
        raise TypeError("priors must be a mapping or an object with .scenarios")
    return {scenario.id: float(scenario.probability) for scenario in scenarios}


def _top(contributions: list[ProbabilityContribution], *, positive: bool) -> list[ProbabilityContribution]:
    filtered = [
        item
        for item in contributions
        if (item.contribution > 0 if positive else item.contribution < 0)
    ]
    return sorted(filtered, key=lambda item: abs(item.contribution), reverse=True)[:5]


def _horizon_weight(input_signal: MacroInputSignal, dedupe_config: InputDedupeConfig, horizon: str) -> float:
    if input_signal.input_scope != "market_tape":
        return 1.0
    return dedupe_config.market_tape_weight_by_horizon.get(horizon.lower(), 0.25)


def _role_weight(input_signal: MacroInputSignal, dedupe_config: InputDedupeConfig) -> float:
    if input_signal.dedupe_weight is not None:
        return input_signal.dedupe_weight
    if input_signal.role == "layer_summary":
        return dedupe_config.layer_summary_base_weight
    if input_signal.role == "raw_component":
        return dedupe_config.raw_component_modifier_weight
    return 1.0


def _used_by_mode(input_signal: MacroInputSignal, dedupe_config: InputDedupeConfig) -> bool:
    if not input_signal.used_in_probability_update or input_signal.display_only:
        return False
    if input_signal.parent_layer == "volatility":
        if input_signal.role == "layer_summary" and not dedupe_config.include_volatility_layer:
            return False
        if input_signal.role == "raw_component" and not dedupe_config.include_volatility_raw_components:
            return False
    if dedupe_config.mode == "layer_only" and input_signal.role == "raw_component":
        return False
    if dedupe_config.mode == "raw_only" and input_signal.role == "layer_summary":
        return False
    return True


def _apply_hybrid_dedupe_caps(
    detailed: list[ScenarioContribution],
    dedupe_config: InputDedupeConfig,
) -> list[ScenarioContribution]:
    if dedupe_config.mode != "hybrid":
        return detailed

    by_group: dict[tuple[str, str], list[ScenarioContribution]] = {}
    for contribution in detailed:
        if not contribution.used_in_probability_update:
            continue
        if contribution.parent_layer is None or contribution.dedupe_group is None:
            continue
        key = (contribution.scenario_id, contribution.dedupe_group)
        by_group.setdefault(key, []).append(contribution)

    replacements: dict[tuple[str, str], ScenarioContribution] = {}
    for _, items in by_group.items():
        primary_abs = sum(
            abs(item.adjusted_contribution)
            for item in items
            if item.dedupe_role == "primary" or item.source_role in {"layer_summary", "composite"}
        )
        modifiers = [
            item
            for item in items
            if item.dedupe_role == "modifier" or item.source_role == "raw_component"
        ]
        modifier_abs = sum(
            abs(item.adjusted_contribution)
            for item in modifiers
        )
        if primary_abs <= 0 or modifier_abs <= 0:
            continue
        cap = primary_abs * dedupe_config.raw_component_cap_ratio
        if modifier_abs <= cap + EPSILON:
            continue
        scale = cap / modifier_abs
        for item in modifiers:
            original = item.adjusted_contribution
            final = original * scale
            replacements[(item.input_id, item.scenario_id)] = item.model_copy_validate(
                {
                    "adjusted_contribution": final,
                    "raw_contribution": final,
                    "final_contribution": final,
                    "capped_by_dedupe": True,
                    "direction": "positive" if final > 0 else "negative",
                }
            )

    if not replacements:
        return detailed
    return [
        replacements.get((item.input_id, item.scenario_id), item)
        for item in detailed
    ]


def _normalize(probabilities: Mapping[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in probabilities.values())
    if total <= 0:
        equal = 1.0 / len(probabilities) if probabilities else 0.0
        return {key: equal for key in probabilities}
    return {key: max(0.0, value) / total for key, value in probabilities.items()}


def _apply_floors(
    probabilities: Mapping[str, float],
    config: ScenarioProbabilityConfig,
) -> tuple[dict[str, float], dict[str, bool]]:
    if not config.use_probability_floors:
        return dict(probabilities), {scenario_id: False for scenario_id in probabilities}

    floors = {
        scenario_id: max(0.0, float(floor))
        for scenario_id, floor in config.scenario_probability_floors.items()
        if scenario_id in probabilities and floor > 0
    }
    floor_applied = {
        scenario_id: probabilities.get(scenario_id, 0.0) < floor - EPSILON
        for scenario_id, floor in floors.items()
    }
    floor_applied.update(
        {
            scenario_id: False
            for scenario_id in probabilities
            if scenario_id not in floor_applied
        }
    )
    floored = {
        scenario_id: floors[scenario_id]
        for scenario_id, applied in floor_applied.items()
        if applied
    }
    if not floored:
        return dict(probabilities), floor_applied

    total_floor = sum(floored.values())
    if total_floor >= 1.0:
        normalized_floors = _normalize(floors)
        return {
            scenario_id: normalized_floors.get(scenario_id, 0.0)
            for scenario_id in probabilities
        }, floor_applied

    remaining = [
        scenario_id
        for scenario_id in probabilities
        if scenario_id not in floored
    ]
    remaining_raw = sum(probabilities[scenario_id] for scenario_id in remaining)
    final = dict(floored)
    if remaining and remaining_raw > 0:
        remaining_mass = 1.0 - total_floor
        for scenario_id in remaining:
            final[scenario_id] = probabilities[scenario_id] / remaining_raw * remaining_mass
    elif remaining:
        equal = (1.0 - total_floor) / len(remaining)
        for scenario_id in remaining:
            final[scenario_id] = equal
    return final, floor_applied


def _apply_cap(
    probabilities: Mapping[str, float],
    max_probability: float | None,
) -> tuple[dict[str, float], dict[str, bool]]:
    cap_applied = {scenario_id: False for scenario_id in probabilities}
    if max_probability is None:
        return dict(probabilities), cap_applied

    cap = max(0.0, min(1.0, max_probability))
    final = dict(probabilities)
    for _ in range(max(1, len(final) + 1)):
        over_cap = [
            scenario_id
            for scenario_id, probability in final.items()
            if probability > cap + EPSILON
        ]
        if not over_cap:
            break
        excess = sum(final[scenario_id] - cap for scenario_id in over_cap)
        for scenario_id in over_cap:
            final[scenario_id] = cap
            cap_applied[scenario_id] = True

        recipients = [
            scenario_id
            for scenario_id in final
            if scenario_id not in over_cap and final[scenario_id] < cap - EPSILON
        ]
        if not recipients or excess <= 0:
            break
        recipient_total = sum(final[scenario_id] for scenario_id in recipients)
        if recipient_total <= 0:
            equal = excess / len(recipients)
            for scenario_id in recipients:
                final[scenario_id] += equal
        else:
            for scenario_id in recipients:
                final[scenario_id] += excess * (final[scenario_id] / recipient_total)

    return _normalize(final), cap_applied


def _apply_probability_constraints(
    probabilities: Mapping[str, float],
    config: ScenarioProbabilityConfig,
) -> tuple[dict[str, float], dict[str, bool], dict[str, bool]]:
    floored, floor_applied = _apply_floors(probabilities, config)
    capped, cap_applied = _apply_cap(floored, config.max_single_scenario_probability)
    return capped, floor_applied, cap_applied


def update_scenario_probabilities(
    priors: Mapping[str, float] | object,
    input_signals: list[MacroInputSignal] | ForecastInputSet,
    config: ScenarioProbabilityConfig | None = None,
    dedupe_config: InputDedupeConfig | None = None,
    horizon: str = "3m",
) -> list[ScenarioProbabilityUpdate]:
    """Update scenario probabilities from input-level signal impacts."""

    config = config or ScenarioProbabilityConfig()
    dedupe_config = dedupe_config or InputDedupeConfig()
    if isinstance(input_signals, ForecastInputSet):
        signal_list = list(input_signals.all_signals)
    else:
        signal_list = list(input_signals)
    prior_map = _as_priors(priors)
    if not prior_map:
        return []

    raw_scores = {
        scenario_id: _logit(probability)
        for scenario_id, probability in prior_map.items()
    }
    base_scores = dict(raw_scores)
    contributions: dict[str, list[ProbabilityContribution]] = {
        scenario_id: [] for scenario_id in prior_map
    }
    detailed_contributions: dict[str, list[ScenarioContribution]] = {
        scenario_id: [] for scenario_id in prior_map
    }
    all_detailed_contributions: dict[str, list[ScenarioContribution]] = {
        scenario_id: [] for scenario_id in prior_map
    }

    staged_detailed: dict[str, list[ScenarioContribution]] = {
        scenario_id: [] for scenario_id in prior_map
    }

    for input_signal in signal_list:
        for impact in input_signal.affected_scenarios:
            if impact.scenario_id not in prior_map:
                continue
            sign = 1.0 if impact.direction == "increases" else -1.0
            signal_multiplier = _horizon_weight(input_signal, dedupe_config, horizon)
            adjusted_strength = impact.strength * signal_multiplier
            pre_dedupe = sign * adjusted_strength * input_signal.confidence
            contribution = pre_dedupe * _role_weight(input_signal, dedupe_config)
            used = _used_by_mode(input_signal, dedupe_config)
            detailed = ScenarioContribution(
                input_id=input_signal.input_id,
                input_name=input_signal.name,
                scenario_id=impact.scenario_id,
                direction="positive" if contribution > 0 else "negative",
                scenario_impact_direction=impact.direction,
                base_strength=impact.strength,
                input_confidence=input_signal.confidence,
                signal_multiplier=signal_multiplier,
                adjusted_strength=adjusted_strength,
                raw_contribution=contribution,
                adjusted_contribution=contribution,
                strength=impact.strength,
                confidence=input_signal.confidence,
                rationale=impact.rationale,
                used_in_probability_update=used,
                source_role=input_signal.role,
                parent_layer=input_signal.parent_layer,
                dedupe_group=input_signal.dedupe_group,
                dedupe_role=input_signal.dedupe_role,
                capped_by_dedupe=False,
                pre_dedupe_contribution=pre_dedupe,
                final_contribution=contribution,
            )
            all_detailed_contributions[impact.scenario_id].append(detailed)
            if used:
                staged_detailed[impact.scenario_id].append(detailed)

    for scenario_id, items in staged_detailed.items():
        final_items = _apply_hybrid_dedupe_caps(items, dedupe_config)
        for detailed in final_items:
            if scenario_id not in raw_scores:
                continue
            contribution = detailed.adjusted_contribution
            raw_scores[scenario_id] += contribution
            contributions[scenario_id].append(
                ProbabilityContribution(
                    input_id=detailed.input_id,
                    name=detailed.input_name,
                    contribution=contribution,
                    rationale=detailed.rationale,
                )
            )
            detailed_contributions[scenario_id].append(detailed)
            for index, math_item in enumerate(all_detailed_contributions[scenario_id]):
                if math_item.input_id == detailed.input_id and math_item.scenario_id == detailed.scenario_id:
                    all_detailed_contributions[scenario_id][index] = detailed
                    break

    raw_component_signals_available = sum(
        1
        for input_signal in signal_list
        if input_signal.role == "raw_component"
        and input_signal.used_in_probability_update
        and not input_signal.display_only
    )
    raw_component_contribution_count = sum(
        1
        for items in detailed_contributions.values()
        for item in items
        if item.source_role == "raw_component"
        and abs(float(item.final_contribution or item.adjusted_contribution or 0.0)) > EPSILON
    )
    deterministic_warnings: list[str] = []
    if raw_component_signals_available == 0:
        deterministic_warnings.append("No raw component signals available for deterministic scenario math.")
    elif raw_component_contribution_count == 0:
        deterministic_warnings.append(
            "Raw component signals were available but produced no deterministic scenario contributions. "
            "Check scenario_impacts or dedupe config."
        )

    pre_floor_posteriors, exp_scores, softmax_denominator = _softmax_details(
        raw_scores,
        temperature=config.softmax_temperature,
    )
    posteriors, floor_applied, cap_applied = _apply_probability_constraints(
        pre_floor_posteriors,
        config,
    )
    updates: list[ScenarioProbabilityUpdate] = []
    for scenario_id in prior_map:
        posterior = posteriors.get(scenario_id, 0.0)
        pre_floor_posterior = pre_floor_posteriors.get(scenario_id, 0.0)
        prior = _clamp_probability(prior_map[scenario_id])
        scenario_contributions = contributions.get(scenario_id, [])
        detailed = sorted(
            detailed_contributions.get(scenario_id, []),
            key=lambda item: abs(item.adjusted_contribution),
            reverse=True,
        )
        positive = _top(scenario_contributions, positive=True)
        negative = _top(scenario_contributions, positive=False)
        total_positive = sum(item.adjusted_contribution for item in detailed if item.adjusted_contribution > 0)
        total_negative = sum(item.adjusted_contribution for item in detailed if item.adjusted_contribution < 0)
        configured_floor = config.scenario_probability_floors.get(scenario_id)
        floor_value = (
            max(0.0, min(1.0, float(configured_floor)))
            if configured_floor is not None
            else None
        )
        cap_value = config.max_single_scenario_probability
        math_contributions = sorted(
            all_detailed_contributions.get(scenario_id, []),
            key=lambda item: (
                not item.used_in_probability_update,
                -abs(item.adjusted_contribution),
                item.input_id,
            ),
        )
        math_audit = ScenarioMathAudit(
            scenario_id=scenario_id,
            prior_probability=prior,
            prior_logit_or_log_score=base_scores[scenario_id],
            base_score=base_scores[scenario_id],
            total_positive_contribution=total_positive,
            total_negative_contribution=total_negative,
            net_contribution=total_positive + total_negative,
            raw_score_before_softmax=raw_scores[scenario_id],
            exp_score=exp_scores.get(scenario_id),
            softmax_denominator=softmax_denominator,
            pre_floor_posterior_probability=pre_floor_posterior,
            floor_value=floor_value if floor_value is not None else None,
            floor_applied=floor_applied.get(scenario_id, False),
            cap_value=cap_value if cap_applied.get(scenario_id, False) else None,
            cap_applied=cap_applied.get(scenario_id, False),
            final_posterior_probability=posterior,
            final_probability_change=posterior - prior,
            formula_notes=[
                "raw_score = prior_log_score + sum(used input_contributions)",
                "input_contribution = direction_sign x base_strength x input_confidence x signal_multiplier",
                "hybrid input mode applies role weights and caps raw component modifiers within parent layers",
                "pre_floor_posterior = stabilized softmax(raw_score across scenarios)",
                "final_posterior = apply probability floors/caps after softmax and renormalize",
                "display-only component signals are recorded but excluded from used contribution totals",
            ],
            contributions=math_contributions,
        )
        updates.append(
            ScenarioProbabilityUpdate(
                scenario_id=scenario_id,
                prior_probability=prior,
                pre_floor_posterior_probability=pre_floor_posterior,
                posterior_probability=posterior,
                probability_change=posterior - prior,
                raw_score=raw_scores[scenario_id],
                floor_applied=floor_applied.get(scenario_id, False),
                floor_value=floor_value if floor_value is not None else None,
                cap_applied=cap_applied.get(scenario_id, False),
                cap_value=cap_value if cap_applied.get(scenario_id, False) else None,
                top_positive_contributors=positive,
                top_negative_contributors=negative,
                contributions=detailed,
                total_positive_contribution=total_positive,
                total_negative_contribution=total_negative,
                net_contribution=total_positive + total_negative,
                math_audit=math_audit,
                warnings=deterministic_warnings,
                explanation=(
                    f"{scenario_id} moved from {prior:.1%} to {posterior:.1%} "
                    f"(pre-floor {pre_floor_posterior:.1%}) after "
                    f"{len(scenario_contributions)} input contribution(s)."
                ),
            )
        )

    return sorted(updates, key=lambda item: item.posterior_probability, reverse=True)
