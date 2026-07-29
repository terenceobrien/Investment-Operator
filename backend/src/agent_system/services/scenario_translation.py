"""Translation from legacy narrative scenario IDs to behavioral macro scenario IDs.

Used at the Monte Carlo boundary while the macro forecast layer continues to
emit the legacy scenario IDs. Eventually the macro forecast will produce
behavioral scenario IDs directly and this translation layer will be removed.
"""
from __future__ import annotations

import logging


SCENARIO_TRANSLATION: dict[str, dict[str, float]] = {
    "reopening_soft_landing": {"expansion_disinflation": 1.0},
    "sticky_late_cycle_ai": {"late_cycle_expansion": 1.0},
    "oil_inflation_tail": {"inflation_shock": 0.7, "stagflation": 0.3},
    "late_cycle_risk_off": {
        "growth_scare_no_credit": 0.5,
        "credit_led_recession": 0.5,
    },
    "ai_capex_rollover": {
        "growth_scare_no_credit": 0.75,
        "credit_led_recession": 0.25,
    },
}

BEHAVIORAL_SCENARIO_IDS: list[str] = [
    "expansion_disinflation",
    "late_cycle_expansion",
    "inflation_shock",
    "stagflation",
    "growth_scare_no_credit",
    "credit_led_recession",
]


def translate_narrative_to_behavioral(
    legacy_probabilities: dict[str, float],
) -> dict[str, float]:
    """Translate legacy narrative scenario probabilities to behavioral scenario probabilities.

    Each legacy scenario contributes its probability to one or more behavioral scenarios
    according to SCENARIO_TRANSLATION weights. Unrecognized scenario IDs are passed through
    unchanged with a warning.
    """
    result: dict[str, float] = {sid: 0.0 for sid in BEHAVIORAL_SCENARIO_IDS}
    unrecognized: dict[str, float] = {}

    for legacy_id, probability in legacy_probabilities.items():
        if legacy_id in SCENARIO_TRANSLATION:
            translation_map = SCENARIO_TRANSLATION[legacy_id]
            for behavioral_id, weight in translation_map.items():
                result[behavioral_id] = (
                    result.get(behavioral_id, 0.0) + probability * weight
                )
            continue
        if legacy_id in BEHAVIORAL_SCENARIO_IDS:
            result[legacy_id] = result.get(legacy_id, 0.0) + probability
            continue
        unrecognized[legacy_id] = probability

    if unrecognized:
        logging.getLogger(__name__).warning(
            "Unrecognized scenario IDs in translation: %s. Passed through unchanged.",
            list(unrecognized.keys()),
        )
        for sid, prob in unrecognized.items():
            result[sid] = prob

    # Normalize to handle floating point drift.
    total = sum(result.values())
    if total > 0:
        result = {k: v / total for k, v in result.items()}

    return result


def translate_scenario_probabilities(
    legacy_probabilities: dict[str, float],
) -> dict[str, float]:
    """Backward-compatible wrapper for the narrative->behavioral bridge.

    Temporary shadow-period scaffolding: this retires when the macro forecast
    layer emits behavioral scenario IDs directly.
    """

    return translate_narrative_to_behavioral(legacy_probabilities)
