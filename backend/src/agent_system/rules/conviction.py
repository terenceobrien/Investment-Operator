"""
Deterministic conviction rules for the execution spine.

These rules are intentionally conservative and prompt-free. They convert the
upstream schema outputs into one auditable Conviction object.
"""
from __future__ import annotations

from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.fundamental import FundamentalAnalysis
from src.agent_system.schemas.narrative import NarrativeAge, NarrativeAnalysis
from src.agent_system.schemas.regime import RegimeState
from src.agent_system.schemas.thematic import Candidate, VariantStrength


def _conviction(
    rating: ConvictionRating,
    rule_applied: str,
    weakest_link: str,
    reasoning: str,
) -> Conviction:
    return Conviction(
        rating=rating,
        rule_applied=rule_applied,
        weakest_link=weakest_link,  # type: ignore[arg-type]
        reasoning=reasoning,
    )


def _is_nothing_material(value: str | None) -> bool:
    if value is None:
        return True
    normalized = " ".join(value.lower().strip().replace(".", "").split())
    nothing_phrases = {
        "nothing material",
        "none",
        "no material rebuttal",
        "no material issue",
        "no meaningful rebuttal",
    }
    return normalized in nothing_phrases or normalized.startswith("nothing material")


def _weakest_layer(
    fundamental: FundamentalAnalysis | None,
    narrative: NarrativeAnalysis | None,
) -> str:
    f_rank = fundamental.conviction.rating.rank if fundamental else -1
    n_rank = (
        narrative.conviction.rating.rank
        if _has_narrative_signal(narrative)
        else f_rank
    )
    if f_rank < n_rank:
        return "fundamental"
    if n_rank < f_rank:
        return "narrative"
    return "none"


def _has_narrative_signal(narrative: NarrativeAnalysis | None) -> bool:
    if narrative is None:
        return False
    return getattr(narrative, "coverage_quality", None) != "absent"


def evaluate_conviction(
    *,
    candidate: Candidate,
    fundamental: FundamentalAnalysis | None,
    narrative: NarrativeAnalysis | None,
    regime: RegimeState | None = None,
) -> Conviction:
    """
    Evaluate the combined conviction for a candidate and its analyses.

    The first decisive rule wins. Hard-pass rules fire before constructive
    ratings so weak inputs cannot be rescued by narrative polish.
    """

    if candidate.variant_strength == VariantStrength.UNCLEAR:
        return _conviction(
            ConvictionRating.PASS,
            "no_variant_view_pass",
            "thematic",
            (
                "Candidate has thematic fit but no clear variant view. A theme "
                "without an articulated edge is not enough to build a trade."
            ),
        )

    if fundamental is None:
        return _conviction(
            ConvictionRating.PASS,
            "missing_fundamental_analysis_pass",
            "fundamental",
            "No FundamentalAnalysis was provided, so the idea cannot clear construction.",
        )

    if narrative is None:
        return _conviction(
            ConvictionRating.PASS,
            "missing_narrative_analysis_pass",
            "narrative",
            "No NarrativeAnalysis was provided, so the setup lacks story/price validation.",
        )

    if fundamental.estimates_and_expectations.where_we_differ is None:
        return _conviction(
            ConvictionRating.PASS,
            "no_fundamental_variant_view_pass",
            "fundamental",
            "Fundamental view agrees with consensus; without a differentiated estimate or expectation edge, there is no tradeable advantage.",
        )

    if _is_nothing_material(fundamental.what_bear_case_misses):
        if (
            fundamental.conviction.rating.at_least(ConvictionRating.MODERATE)
            and (
                not _has_narrative_signal(narrative)
                or narrative.conviction.rating.at_least(ConvictionRating.MODERATE)
            )
        ):
            return _conviction(
                ConvictionRating.MODERATE,
                "bear_case_not_rebutted_cap_moderate",
                "fundamental",
                "The setup has some support, but the bear case was not materially rebutted, capping conviction at MODERATE.",
            )
        return _conviction(
            ConvictionRating.PASS,
            "bear_case_not_rebutted_pass",
            "fundamental",
            "The bear case was not materially rebutted and the supporting evidence is not strong enough to justify continued construction.",
        )

    if (
        _has_narrative_signal(narrative)
        and narrative.current_narrative.narrative_age == NarrativeAge.MATURE
        and narrative.current_narrative.narrative_strength >= 8
        and candidate.variant_strength != VariantStrength.STRONG
    ):
        return _conviction(
            ConvictionRating.WEAK,
            "crowded_mature_narrative_weak",
            "narrative",
            "The narrative is mature and strong, while the candidate's variant view is not strong enough to overcome crowding risk.",
        )

    if not _has_narrative_signal(narrative):
        # Absent broad-snapshot coverage is neutral, not bearish. The gate
        # combines thematic variant strength with fundamentals, but caps at
        # MODERATE because there is no active narrative support.
        if (
            candidate.variant_strength == VariantStrength.STRONG
            and fundamental.conviction.rating.at_least(ConvictionRating.MODERATE)
        ):
            return _conviction(
                ConvictionRating.MODERATE,
                "moderate_fundamental_variant_no_narrative_signal",
                _weakest_layer(fundamental, narrative),
                "The setup has a strong variant view and sufficient fundamentals, but no current narrative snapshot coverage, so conviction is capped at MODERATE.",
            )
        if (
            candidate.variant_strength == VariantStrength.MODERATE
            and fundamental.conviction.rating.at_least(ConvictionRating.MODERATE)
        ):
            return _conviction(
                ConvictionRating.MODERATE,
                "moderate_variant_fundamental_no_narrative_signal",
                _weakest_layer(fundamental, narrative),
                "The setup has a moderate variant view and sufficient fundamentals, while absent narrative coverage is treated as neutral rather than negative.",
            )

        return _conviction(
            ConvictionRating.WEAK,
            "insufficient_fundamental_variant_no_narrative_signal_weak",
            _weakest_layer(fundamental, narrative),
            "Absent narrative coverage is neutral, but the remaining thematic and fundamental evidence is not strong enough for construction.",
        )

    if (
        candidate.variant_strength == VariantStrength.STRONG
        and fundamental.conviction.rating == ConvictionRating.EXCEPTIONAL
        and narrative.conviction.rating == ConvictionRating.EXCEPTIONAL
        and not narrative.contradicting_signals
    ):
        return _conviction(
            ConvictionRating.EXCEPTIONAL,
            "exceptional_all_layers_clear",
            "none",
            "Candidate, fundamentals, and narrative are all exceptional with a clear variant view and no contradicting narrative signals.",
        )

    if (
        candidate.variant_strength == VariantStrength.STRONG
        and fundamental.conviction.rating.at_least(ConvictionRating.STRONG)
        and narrative.conviction.rating.at_least(ConvictionRating.STRONG)
    ):
        return _conviction(
            ConvictionRating.STRONG,
            "strong_multi_layer_alignment",
            "none",
            "Strong thematic, fundamental, and narrative alignment with a differentiated expectations view.",
        )

    if (
        candidate.variant_strength == VariantStrength.STRONG
        and fundamental.conviction.rating.at_least(ConvictionRating.MODERATE)
        and narrative.conviction.rating.at_least(ConvictionRating.MODERATE)
    ):
        return _conviction(
            ConvictionRating.MODERATE,
            "moderate_multi_layer_alignment",
            _weakest_layer(fundamental, narrative),
            "The setup has multi-layer support, but one analytical layer is only moderate, so construction should stay modest.",
        )

    if (
        candidate.variant_strength == VariantStrength.MODERATE
        and fundamental.conviction.rating.at_least(ConvictionRating.MODERATE)
        and narrative.conviction.rating.at_least(ConvictionRating.MODERATE)
    ):
        return _conviction(
            ConvictionRating.MODERATE,
            "moderate_variant_with_layer_support",
            _weakest_layer(fundamental, narrative),
            "The variant view is moderate but both analytical layers provide "
            "moderate support; the setup is tradeable at modest size.",
        )

    return _conviction(
        ConvictionRating.WEAK,
        "insufficient_multi_layer_alignment_weak",
        _weakest_layer(fundamental, narrative),
        "The idea survived hard-pass checks but lacks enough multi-layer confirmation for an accepted trade.",
    )
