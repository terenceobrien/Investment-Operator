from __future__ import annotations

from agent_system.orchestration.stub_agents import (
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from agent_system.rules.conviction import evaluate_conviction
from agent_system.schemas.common import ConvictionRating


def _candidate(ticker: str):
    regime = make_stub_regime_state()
    thematic_map = make_stub_thematic_map(regime)
    return regime, next(c for c in thematic_map.candidates if c.ticker == ticker)


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
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.WEAK
    assert conviction.rule_applied == "crowded_mature_narrative_weak"


def test_strong_multi_layer_alignment_accepts_etn():
    regime, candidate = _candidate("ETN")
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=make_stub_fundamental_analysis(candidate),
        narrative=make_stub_narrative_analysis(candidate),
        regime=regime,
    )
    assert conviction.rating == ConvictionRating.STRONG
    assert conviction.rule_applied == "strong_multi_layer_alignment"
