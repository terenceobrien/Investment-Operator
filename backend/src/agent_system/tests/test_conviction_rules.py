from __future__ import annotations

from src.agent_system.orchestration.stub_agents import (
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.schemas.common import ConvictionRating
from src.agent_system.schemas.narrative import NarrativeAge
from src.agent_system.schemas.thematic import VariantStrength


def _candidate(ticker: str):
    regime = make_stub_regime_state()
    thematic_map = make_stub_thematic_map(regime)
    return regime, next(c for c in thematic_map.candidates if c.ticker == ticker)


def _etn_setup(
    *,
    variant_strength: VariantStrength,
    fundamental_rating: ConvictionRating,
    narrative_rating: ConvictionRating,
):
    regime, candidate = _candidate("ETN")
    candidate = candidate.model_copy_validate({"variant_strength": variant_strength})
    fundamental = make_stub_fundamental_analysis(candidate)
    fundamental = fundamental.model_copy_validate(
        {
            "conviction": fundamental.conviction.model_copy_validate(
                {"rating": fundamental_rating}
            )
        }
    )
    narrative = make_stub_narrative_analysis(candidate)
    narrative = narrative.model_copy_validate(
        {
            "coverage_quality": "high",
            "conviction": narrative.conviction.model_copy_validate(
                {"rating": narrative_rating}
            )
        }
    )
    return regime, candidate, fundamental, narrative


def _with_active_narrative(narrative, rating: ConvictionRating):
    return narrative.model_copy_validate(
        {
            "coverage_quality": "high",
            "conviction": narrative.conviction.model_copy_validate({"rating": rating}),
        }
    )


def test_unclear_variant_view_passes_at_thematic_layer():
    regime, candidate = _candidate("SMH")
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.PASS
    assert conviction.rule_applied == "no_variant_view_pass"
    assert conviction.weakest_link == "thematic"


def test_missing_fundamental_analysis_passes():
    regime, candidate = _candidate("ETN")
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=None,
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.PASS
    assert conviction.rule_applied == "missing_fundamental_analysis_pass"


def test_no_fundamental_variant_view_passes():
    regime, candidate = _candidate("VST")
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.PASS
    assert conviction.rule_applied == "no_fundamental_variant_view_pass"


def test_crowded_mature_narrative_is_weak_without_strong_variant():
    regime, candidate = _candidate("NVDA")
    narrative = make_stub_narrative_analysis(candidate)
    narrative = _with_active_narrative(narrative, ConvictionRating.MODERATE)
    narrative = narrative.model_copy_validate(
        {
            "current_narrative": narrative.current_narrative.model_copy_validate(
                {
                    "narrative_age": NarrativeAge.MATURE,
                    "narrative_strength": 9.0,
                }
            )
        }
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=narrative,
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.WEAK
    assert conviction.rule_applied == "crowded_mature_narrative_weak"


def test_strong_multi_layer_alignment_accepts_etn():
    regime, candidate = _candidate("ETN")
    narrative = _with_active_narrative(
        make_stub_narrative_analysis(candidate),
        ConvictionRating.STRONG,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=narrative,
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.STRONG
    assert conviction.rule_applied == "strong_multi_layer_alignment"


def test_absent_narrative_coverage_is_neutral_not_negative():
    regime, candidate = _candidate("ETN")
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.MODERATE
    assert conviction.rule_applied == "moderate_fundamental_variant_no_narrative_signal"


def test_strong_variant_moderate_layers_still_use_existing_moderate_rule():
    regime, candidate, fundamental, narrative = _etn_setup(
        variant_strength=VariantStrength.STRONG,
        fundamental_rating=ConvictionRating.MODERATE,
        narrative_rating=ConvictionRating.MODERATE,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )

    assert conviction.rating == ConvictionRating.MODERATE
    assert conviction.rule_applied == "moderate_multi_layer_alignment"


def test_moderate_variant_with_moderate_layers_is_tradeable():
    regime, candidate, fundamental, narrative = _etn_setup(
        variant_strength=VariantStrength.MODERATE,
        fundamental_rating=ConvictionRating.MODERATE,
        narrative_rating=ConvictionRating.MODERATE,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )

    assert conviction.rating == ConvictionRating.MODERATE
    assert conviction.rule_applied == "moderate_variant_with_layer_support"
    assert conviction.weakest_link == "none"


def test_moderate_variant_strong_fundamental_moderate_narrative_is_tradeable():
    regime, candidate, fundamental, narrative = _etn_setup(
        variant_strength=VariantStrength.MODERATE,
        fundamental_rating=ConvictionRating.STRONG,
        narrative_rating=ConvictionRating.MODERATE,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )

    assert conviction.rating == ConvictionRating.MODERATE
    assert conviction.rule_applied == "moderate_variant_with_layer_support"
    assert conviction.weakest_link == "narrative"


def test_moderate_variant_with_weak_layer_still_falls_through_to_weak():
    regime, candidate, fundamental, narrative = _etn_setup(
        variant_strength=VariantStrength.MODERATE,
        fundamental_rating=ConvictionRating.WEAK,
        narrative_rating=ConvictionRating.MODERATE,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )

    assert conviction.rating == ConvictionRating.WEAK
    assert conviction.rule_applied == "insufficient_multi_layer_alignment_weak"
    assert conviction.weakest_link == "fundamental"


def test_weak_variant_with_strong_layers_still_falls_through_to_weak():
    regime, candidate, fundamental, narrative = _etn_setup(
        variant_strength=VariantStrength.WEAK,
        fundamental_rating=ConvictionRating.STRONG,
        narrative_rating=ConvictionRating.STRONG,
    )
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )

    assert conviction.rating == ConvictionRating.WEAK
    assert conviction.rule_applied == "insufficient_multi_layer_alignment_weak"
