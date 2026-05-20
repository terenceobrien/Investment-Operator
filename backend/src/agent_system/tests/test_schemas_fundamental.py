"""
Tests for agent_system.schemas.fundamental.

Focuses on the anti-confirmation disciplines:
- steelman_bear_case minimum length (50 chars)
- bear_case_evidence minimum length (1 item)
- what_bear_case_misses default value and minimum length
- where_we_differ None/non-None consistency with differ_magnitude and evidence
- thesis_statement minimum length (30 chars)
- Cross-field validation in EstimatesAndExpectations

Shared fixtures (fundamental_analysis, news_evidence, strong_analysis_conviction)
come from conftest.py.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent_system.schemas.common import (
    AnalysisConviction,
    ConvictionRating,
)
from src.agent_system.schemas.fundamental import (
    BusinessQuality,
    Crowdedness,
    Cyclicality,
    DifferMagnitude,
    EstimateRevisionTrend,
    EstimatesAndExpectations,
    Financials,
    FundamentalAnalysis,
    Positioning,
)


# ─────────────────────────────────────────────────────────────────────────────
# BusinessQuality
# ─────────────────────────────────────────────────────────────────────────────


class TestBusinessQuality:
    def test_well_formed(self):
        bq = BusinessQuality(
            summary="Integrated major with Permian leverage and refining optionality.",
            moat_assessment="Scale + tier-1 acreage + integrated downstream.",
            cyclicality=Cyclicality.CYCLICAL,
        )
        assert bq.cyclicality == Cyclicality.CYCLICAL

    def test_summary_minimum_length(self):
        with pytest.raises(ValidationError):
            BusinessQuality(
                summary="short",  # < 20 chars
                moat_assessment="something at least 10 chars",
                cyclicality=Cyclicality.SECULAR,
            )

    def test_moat_can_be_no_moat(self):
        # "Commodity producer with no differentiation" is a legitimate
        # moat_assessment — the field requires SOMETHING be said, not that
        # the answer must claim a moat exists.
        bq = BusinessQuality(
            summary="A commodity producer with no meaningful differentiation from peers.",
            moat_assessment="No meaningful moat — pure commodity exposure.",
            cyclicality=Cyclicality.CYCLICAL,
        )
        assert "no meaningful moat" in bq.moat_assessment.lower()


# ─────────────────────────────────────────────────────────────────────────────
# EstimatesAndExpectations — cross-field validation
# ─────────────────────────────────────────────────────────────────────────────


class TestEstimatesAndExpectations:
    def test_agreeing_with_consensus_valid(self):
        # When where_we_differ is None, differ_magnitude must be None and
        # differ_evidence must be empty. This is the "we have no edge" case.
        ee = EstimatesAndExpectations(
            consensus_summary="Consensus expects 8% growth.",
            revision_trend=EstimateRevisionTrend.STABLE,
            where_we_differ=None,
            differ_magnitude=None,
            differ_evidence=[],
        )
        assert ee.where_we_differ is None

    def test_differing_requires_magnitude(self, news_evidence):
        # If you have a variant view, you must say how much you differ
        # and provide evidence.
        with pytest.raises(ValidationError):
            EstimatesAndExpectations(
                consensus_summary="Consensus expects 8% growth.",
                revision_trend=EstimateRevisionTrend.STABLE,
                where_we_differ="We see 15%+ growth instead.",
                differ_magnitude=None,  # invalid — must be set
                differ_evidence=[news_evidence],
            )

    def test_differing_requires_evidence(self):
        # Variant view without evidence is just an opinion.
        with pytest.raises(ValidationError):
            EstimatesAndExpectations(
                consensus_summary="Consensus expects 8% growth.",
                revision_trend=EstimateRevisionTrend.STABLE,
                where_we_differ="We see 15%+ growth instead.",
                differ_magnitude=DifferMagnitude.SIGNIFICANT,
                differ_evidence=[],  # invalid — must be non-empty
            )

    def test_agreeing_rejects_magnitude(self):
        # If you're not differing, you can't have a magnitude.
        with pytest.raises(ValidationError):
            EstimatesAndExpectations(
                consensus_summary="Consensus expects 8% growth.",
                revision_trend=EstimateRevisionTrend.STABLE,
                where_we_differ=None,
                differ_magnitude=DifferMagnitude.MODEST,  # invalid
                differ_evidence=[],
            )

    def test_agreeing_rejects_evidence(self, news_evidence):
        # Same — agreeing with consensus can't come with "differ evidence."
        with pytest.raises(ValidationError):
            EstimatesAndExpectations(
                consensus_summary="Consensus expects 8% growth.",
                revision_trend=EstimateRevisionTrend.STABLE,
                where_we_differ=None,
                differ_magnitude=None,
                differ_evidence=[news_evidence],  # invalid
            )

    def test_well_formed_variant_view(self, news_evidence):
        ee = EstimatesAndExpectations(
            consensus_summary="Consensus expects 8% growth on $75 WTI.",
            revision_trend=EstimateRevisionTrend.UPWARD,
            where_we_differ="We see 15%+ on Permian unit cost improvement.",
            differ_magnitude=DifferMagnitude.SIGNIFICANT,
            differ_evidence=[news_evidence],
        )
        assert ee.differ_magnitude == DifferMagnitude.SIGNIFICANT


# ─────────────────────────────────────────────────────────────────────────────
# Financials
# ─────────────────────────────────────────────────────────────────────────────


class TestFinancials:
    def test_empty_red_flags_allowed(self):
        # Empty list = agent looked and found no red flags. That's a claim.
        f = Financials(
            balance_sheet_quality=8.0,
            cash_generation_quality=7.5,
            accounting_red_flags=[],
        )
        assert f.accounting_red_flags == []

    def test_with_red_flags(self):
        f = Financials(
            balance_sheet_quality=4.0,
            cash_generation_quality=3.0,
            accounting_red_flags=[
                "Aggressive revenue recognition on multi-year contracts",
                "Days sales outstanding has grown faster than revenue for 4 quarters",
            ],
        )
        assert len(f.accounting_red_flags) == 2

    def test_quality_scores_bounded(self):
        with pytest.raises(ValidationError):
            Financials(
                balance_sheet_quality=11.0,  # > 10
                cash_generation_quality=5.0,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Positioning
# ─────────────────────────────────────────────────────────────────────────────


class TestPositioning:
    def test_minimal_positioning(self):
        p = Positioning(
            institutional_positioning="Long-only sector funds modestly overweight.",
            crowdedness_assessment=Crowdedness.NORMAL,
        )
        assert p.short_interest is None
        assert p.options_skew_signal is None

    def test_options_skew_optional(self):
        # None is different from blank — None means "didn't analyze",
        # which is distinct from a present-but-neutral signal.
        p = Positioning(
            institutional_positioning="Generalists underweight.",
            crowdedness_assessment=Crowdedness.UNCROWDED,
            options_skew_signal=None,
        )
        assert p.options_skew_signal is None


# ─────────────────────────────────────────────────────────────────────────────
# FundamentalAnalysis — the main anti-confirmation disciplines
# ─────────────────────────────────────────────────────────────────────────────


class TestFundamentalAnalysis:
    def test_well_formed_via_fixture(self, fundamental_analysis):
        # The fixture itself proves a well-formed analysis constructs cleanly.
        assert fundamental_analysis.ticker == "CVX"
        assert len(fundamental_analysis.bear_case_evidence) == 1
        assert fundamental_analysis.what_bear_case_misses != "nothing material"

    def test_thesis_statement_minimum_length(self, fundamental_analysis):
        # Replace just the thesis_statement with something too short.
        # Uses model_copy_validate so the new value is actually validated —
        # plain model_copy(update=...) skips field validators in Pydantic v2.
        with pytest.raises(ValidationError):
            fundamental_analysis.model_copy_validate({"thesis_statement": "long CVX"})

    def test_steelman_minimum_length(
        self,
        news_evidence,
        strong_analysis_conviction,
    ):
        # 50-char minimum on steelman_bear_case.
        with pytest.raises(ValidationError):
            FundamentalAnalysis(
                ticker="CVX",
                thesis_statement=(
                    "CVX will compound FCF/share at 15%+ on Permian unit cost "
                    "improvements."
                ),
                business_quality=BusinessQuality(
                    summary="Integrated major with Permian leverage and refining.",
                    moat_assessment="Scale + tier-1 acreage.",
                    cyclicality=Cyclicality.CYCLICAL,
                ),
                financials=Financials(
                    balance_sheet_quality=8.0,
                    cash_generation_quality=8.0,
                ),
                estimates_and_expectations=EstimatesAndExpectations(
                    consensus_summary="Consensus 8% growth.",
                    revision_trend=EstimateRevisionTrend.STABLE,
                ),
                positioning=Positioning(
                    institutional_positioning="Sector funds overweight.",
                    crowdedness_assessment=Crowdedness.NORMAL,
                ),
                steelman_bear_case="Oil goes down.",  # < 50 chars
                bear_case_evidence=[news_evidence],
                what_bear_case_misses="The bear case understates capex discipline materially.",
                conviction=strong_analysis_conviction,
            )

    def test_bear_case_evidence_required(
        self,
        strong_analysis_conviction,
    ):
        # bear_case_evidence with min_length=1 — empty list is invalid.
        with pytest.raises(ValidationError):
            FundamentalAnalysis(
                ticker="CVX",
                thesis_statement=(
                    "CVX will compound FCF/share at 15%+ on Permian unit cost "
                    "improvements."
                ),
                business_quality=BusinessQuality(
                    summary="Integrated major with Permian leverage and refining.",
                    moat_assessment="Scale + tier-1 acreage.",
                    cyclicality=Cyclicality.CYCLICAL,
                ),
                financials=Financials(
                    balance_sheet_quality=8.0,
                    cash_generation_quality=8.0,
                ),
                estimates_and_expectations=EstimatesAndExpectations(
                    consensus_summary="Consensus 8% growth.",
                    revision_trend=EstimateRevisionTrend.STABLE,
                ),
                positioning=Positioning(
                    institutional_positioning="Sector funds overweight.",
                    crowdedness_assessment=Crowdedness.NORMAL,
                ),
                steelman_bear_case=(
                    "Oil reverts to $65 on Hormuz de-escalation and Permian decline "
                    "rates accelerate. Capex discipline collapses by 2027."
                ),
                bear_case_evidence=[],  # empty — invalid
                what_bear_case_misses="Capex discipline is real and visible.",
                conviction=strong_analysis_conviction,
            )

    def test_default_what_bear_case_misses_allowed(
        self,
        fundamental_analysis,
        news_evidence,
        strong_analysis_conviction,
    ):
        # The default value "nothing material" is allowed by the schema —
        # downstream conviction rules treat it as a cap, not the schema.
        # We test this by explicitly setting it via model_copy_validate.
        capped = fundamental_analysis.model_copy_validate(
            {"what_bear_case_misses": "nothing material"}
        )
        assert capped.what_bear_case_misses == "nothing material"

    def test_what_bear_case_misses_minimum_length(self, fundamental_analysis):
        # Short non-default value should fail the min_length check.
        # Uses model_copy_validate so field validators actually run.
        with pytest.raises(ValidationError):
            fundamental_analysis.model_copy_validate(
                {"what_bear_case_misses": "no"}
            )

    def test_analysis_is_frozen(self, fundamental_analysis):
        with pytest.raises(ValidationError):
            fundamental_analysis.thesis_statement = "different thesis"