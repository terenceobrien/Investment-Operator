from __future__ import annotations

import asyncio
from datetime import date

from src.agent_system.agents.deep_fundamental_agent_prompts import (
    render_basic_screen_result,
    render_company_profile,
    render_deep_fundamental_context,
)
from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    DataConfidence,
    DeepConsensusType,
    DeepFundamentalInputMode,
    DeepFundamentalLLMSynthesis,
    DeepFundamentalScores,
    DeepFundamentalVerdict,
    DeepSynthesisConfidence,
    EvidencePolarity,
    EvidenceSourceType,
    FinancialTrendAnalysis,
    FinancialTrendSnapshot,
    FundamentalContextPack,
    PressureInflectionAnalysis,
    SingleNameEvidenceItem,
    SingleNameResearchContextPack,
    SourceDocumentPurpose,
    VariantView,
    VariantViewDirection,
)
from src.agent_system.services import deep_fundamental_agent
from src.agent_system.services.deep_fundamental_verdict import (
    classify_llm_risk_items,
    determine_deep_fundamental_verdict,
)


def _synthesis() -> DeepFundamentalLLMSynthesis:
    return DeepFundamentalLLMSynthesis(
        ticker="TEST",
        business_summary="TestCo sells mission-critical components.",
        business_quality_assessment="Business quality is reasonable but still requires source validation.",
        financial_trend_diagnosis="Revenue and margins are improving in the supplied context.",
        screen_interpretation="No basic screen result was supplied.",
        why_screen_may_be_wrong="No screen exists; trend direction matters more than a static pass/fail.",
        current_market_narrative="Our prior is that consensus appears focused on cyclical recovery.",
        consensus_type=DeepConsensusType.NARRATIVE,
        macro_fit_assessment="Macro fit is neutral without a macro context.",
        theme_fit_assessment="Theme fit is not available without mapped themes.",
        pressure_inflection_assessment="Pressure looks cyclical rather than structural in the supplied context.",
        competitive_position_assessment="Competitive position remains underdeveloped without peer evidence.",
        valuation_expectations_assessment="Valuation cannot be judged without a valuation snapshot.",
        variant_view="Variant view: margins can recover faster than the market prior assumes.",
        variant_view_direction=VariantViewDirection.BULLISH,
        variant_view_strength="medium",
        bull_case_variant_view="Bull case: margin recovery is underappreciated.",
        evidence_supporting_variant_view=["Supplied financial trend direction is improving."],
        evidence_against_variant_view=["Company profile is sparse."],
        key_risks=["Sparse profile data."],
        fundamental_falsifiers=["Revenue growth rolls over."],
        macro_theme_falsifiers=["Macro support turns negative."],
        valuation_falsifiers=["Multiple expands without estimate support."],
        timing_falsifiers=["No confirmation within the stated horizon."],
        key_metrics_to_monitor=["revenue growth", "operating margin"],
        suggested_monitoring_plan=["Rerun after next financial update."],
        underwriting_summary="Constructive but not high conviction due to sparse profile data.",
        qualitative_conviction="watchlist",
        suggested_score_adjustment=2.0,
        confidence=DeepSynthesisConfidence.MEDIUM,
        data_gaps=["Need direct consensus and positioning data."],
    )


def test_deep_fundamental_llm_synthesis_schema_validates():
    synthesis = _synthesis()

    assert synthesis.ticker == "TEST"
    assert synthesis.consensus_type == DeepConsensusType.NARRATIVE
    assert synthesis.confidence == DeepSynthesisConfidence.MEDIUM


def test_deep_fundamental_prompt_renderers_are_defensive():
    assert render_company_profile(None) == "None supplied."
    assert "ticker" in render_company_profile({"ticker": "TEST"})
    assert render_basic_screen_result(None) == "None supplied."

    prompt = render_deep_fundamental_context(
        ticker="TEST",
        horizon="6m",
        user_supplied_thesis=None,
        company_profile=CompanyProfile(ticker="TEST"),
        fundamental_context=None,
        macro_context=None,
        theme_context=None,
        basic_screen_result=None,
    )

    assert "# Ticker and horizon" in prompt
    assert "TEST" in prompt


def test_deep_fundamental_prompt_compacts_research_context():
    research_context = SingleNameResearchContextPack(
        ticker="TEST",
        as_of_date=date(2026, 7, 1),
        transcript_evidence=[
            SingleNameEvidenceItem(
                source_type=EvidenceSourceType.TRANSCRIPT,
                document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                ticker="TEST",
                claim=f"transcript claim {index}",
                summary="summary",
                excerpt="x" * 1000,
                polarity=EvidencePolarity.NEUTRAL,
                relevance_score=0.8,
            )
            for index in range(20)
        ],
        news_evidence=[
            SingleNameEvidenceItem(
                source_type=EvidenceSourceType.NEWS,
                document_purpose=SourceDocumentPurpose.NEWS,
                ticker="TEST",
                claim=f"news claim {index}",
                summary="summary",
                excerpt="y" * 1000,
                polarity=EvidencePolarity.NEUTRAL,
                relevance_score=0.5,
            )
            for index in range(20)
        ],
    )

    prompt = render_deep_fundamental_context(
        ticker="TEST",
        horizon="6m",
        user_supplied_thesis=None,
        company_profile=CompanyProfile(ticker="TEST"),
        fundamental_context=None,
        macro_context=None,
        theme_context=None,
        research_context=research_context,
        basic_screen_result=None,
    )

    assert prompt.count("transcript claim") == 12
    assert prompt.count("news claim") == 8
    assert "x" * 700 not in prompt


def test_deterministic_report_accepts_injected_llm_synthesis(monkeypatch):
    context = FundamentalContextPack(
        ticker="TEST",
        as_of_date=date(2026, 6, 26),
        financial_trend=FinancialTrendSnapshot(),
        data_confidence=DataConfidence.LOW,
        source_notes=["test context"],
    )
    monkeypatch.setattr(
        deep_fundamental_agent,
        "build_fundamental_context_pack",
        lambda **_kwargs: context,
    )

    synthesis = _synthesis()
    report = deep_fundamental_agent.build_deep_fundamental_report(
        ticker="TEST",
        input_mode=DeepFundamentalInputMode.STANDALONE,
        horizon="6m",
        llm_synthesis=synthesis,
        use_llm_synthesis=False,
        use_llm_profile=False,
        use_research_context=False,
        skip_relative_performance=True,
    )

    assert report.llm_synthesis == synthesis
    assert report.run_configuration is not None
    assert report.run_configuration.llm_synthesis_used is True
    assert report.run_configuration.research_context_used is False
    assert synthesis.variant_view in (report.variant_view.helix_variant_view or "")
    assert report.variant_view.variant_view_direction == VariantViewDirection.BULLISH
    assert "LLM synthesis summary" in report.final_rationale
    assert "revenue growth" in report.falsification_framework.key_metrics_to_watch


def test_final_llm_failure_produces_partial_report(monkeypatch):
    context = FundamentalContextPack(
        ticker="TEST",
        as_of_date=date(2026, 7, 1),
        financial_trend=FinancialTrendSnapshot(),
        data_confidence=DataConfidence.LOW,
        source_notes=["test context"],
    )
    monkeypatch.setattr(
        deep_fundamental_agent,
        "build_fundamental_context_pack",
        lambda **_kwargs: context,
    )

    async def fail_synthesis(**_kwargs):
        raise RuntimeError("connection dropped")

    import src.agent_system.agents.deep_fundamental_agent as llm_agent

    monkeypatch.setattr(
        llm_agent,
        "synthesize_deep_fundamental_view",
        fail_synthesis,
    )

    report = asyncio.run(
        deep_fundamental_agent.build_deep_fundamental_report_async(
            ticker="TEST",
            input_mode=DeepFundamentalInputMode.STANDALONE,
            horizon="6m",
            use_llm_synthesis=True,
            use_llm_profile=False,
            use_research_context=False,
            skip_relative_performance=True,
        )
    )

    assert report.llm_synthesis is None
    assert report.run_configuration is not None
    assert report.run_configuration.llm_synthesis_status == "failed"
    assert report.run_configuration.llm_last_error is not None
    assert any("Final LLM synthesis failed" in warning for warning in report.warnings)


def test_strict_llm_preserves_final_synthesis_failure(monkeypatch):
    context = FundamentalContextPack(
        ticker="TEST",
        as_of_date=date(2026, 7, 1),
        financial_trend=FinancialTrendSnapshot(),
        data_confidence=DataConfidence.LOW,
        source_notes=["test context"],
    )
    monkeypatch.setattr(
        deep_fundamental_agent,
        "build_fundamental_context_pack",
        lambda **_kwargs: context,
    )

    async def fail_synthesis(**_kwargs):
        raise RuntimeError("connection dropped")

    import src.agent_system.agents.deep_fundamental_agent as llm_agent

    monkeypatch.setattr(
        llm_agent,
        "synthesize_deep_fundamental_view",
        fail_synthesis,
    )

    try:
        asyncio.run(
            deep_fundamental_agent.build_deep_fundamental_report_async(
                ticker="TEST",
                input_mode=DeepFundamentalInputMode.STANDALONE,
                horizon="6m",
                use_llm_synthesis=True,
                strict_llm=True,
                use_llm_profile=False,
                use_research_context=False,
                skip_relative_performance=True,
            )
        )
    except RuntimeError as exc:
        assert "connection dropped" in str(exc)
    else:
        raise AssertionError("strict_llm should preserve synthesis failure")


def test_two_sided_variant_evidence_is_labeled_without_bull_bear_blur(monkeypatch):
    context = FundamentalContextPack(
        ticker="TEST",
        as_of_date=date(2026, 6, 26),
        financial_trend=FinancialTrendSnapshot(),
        data_confidence=DataConfidence.LOW,
        source_notes=["test context"],
    )
    monkeypatch.setattr(
        deep_fundamental_agent,
        "build_fundamental_context_pack",
        lambda **_kwargs: context,
    )
    synthesis = _synthesis().model_copy(
        update={
            "variant_view_direction": VariantViewDirection.TWO_SIDED,
            "bull_case_variant_view": "Bull case: margins keep improving.",
            "bear_case_variant_view": "Bear case: valuation already discounts it.",
            "evidence_supporting_variant_view": [
                "Valuation already discounts the cycle."
            ],
            "evidence_against_variant_view": ["Margins are improving."],
        }
    )

    report = deep_fundamental_agent.build_deep_fundamental_report(
        ticker="TEST",
        input_mode=DeepFundamentalInputMode.STANDALONE,
        horizon="6m",
        llm_synthesis=synthesis,
        use_llm_synthesis=False,
        use_llm_profile=False,
        use_research_context=False,
        skip_relative_performance=True,
    )

    assert report.variant_view.variant_view_direction == VariantViewDirection.TWO_SIDED
    assert any(
        item.startswith("Two-sided evidence: Valuation")
        for item in report.variant_view.evidence_supporting_variant_view
    )
    assert not any(
        item.startswith("Bull evidence: Valuation")
        for item in report.variant_view.evidence_supporting_variant_view
    )


def test_constructive_llm_floor_upgrades_near_threshold_reject_to_watchlist():
    synthesis = _synthesis().model_copy(
        update={
            "qualitative_conviction": "constructive",
            "confidence": DeepSynthesisConfidence.MEDIUM,
        }
    )
    verdict, screen_override, rationale = determine_deep_fundamental_verdict(
        scores=DeepFundamentalScores(
            business_quality=70,
            financial_health=54,
            competitive_position=60,
            earnings_inflection_potential=65,
            regime_fit=45,
            valuation_setup=50,
            variant_perception_strength=55,
            idiosyncratic_risk=70,
            final_underwriting_score=57,
        ),
        basic_screen_result=None,
        financial_trend_analysis=FinancialTrendAnalysis(),
        pressure_inflection_analysis=PressureInflectionAnalysis(),
        variant_view=VariantView(variant_view_strength="weak"),
        llm_synthesis=synthesis,
    )

    assert verdict == DeepFundamentalVerdict.WATCHLIST
    assert screen_override is False
    assert rationale is not None


def test_risk_classifier_separates_generic_risks_from_business_specific_risk():
    classified = classify_llm_risk_items(
        [
            "Valuation compression from elevated multiples.",
            "Memory pricing downturn.",
            "Backlog conversion execution risk.",
            "Refinancing risk if liquidity tightens.",
            "Crowded positioning reversal.",
        ]
    )

    assert classified["valuation_expectations"]
    assert classified["cycle"]
    assert classified["business_idiosyncratic"]
    assert classified["balance_sheet"]
    assert classified["technical_positioning"]
