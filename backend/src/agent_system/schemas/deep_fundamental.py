from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class DeepFundamentalInputMode(str, Enum):
    STANDALONE = "standalone"
    ROUTED_CYCLE = "routed_cycle"


class DeepFundamentalVerdict(str, Enum):
    STRONG_ACCEPT = "strong_accept"
    ACCEPT_WITH_CAVEATS = "accept_with_caveats"
    WATCHLIST = "watchlist"
    REJECT = "reject"
    OVERRIDE_SCREEN_REJECT = "override_screen_reject"
    OVERRIDE_SCREEN_ACCEPT_TO_REJECT = "override_screen_accept_to_reject"


class DeepConsensusType(str, Enum):
    NARRATIVE = "narrative"
    ESTIMATE = "estimate"
    POSITIONING = "positioning"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class DeepSynthesisConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VariantViewDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    TWO_SIDED = "two_sided"
    NONE = "none"


class DataConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ThemeFitType(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    PARTIAL = "partial"
    INDIRECT = "indirect"
    NONE = "none"


class MacroImpactDirection(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class EvidenceSourceType(str, Enum):
    EARNINGS_RELEASE = "earnings_release"
    FILING = "filing"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    ESTIMATE = "estimate"
    PEER_COMMENTARY = "peer_commentary"
    INVESTOR_PRESENTATION = "investor_presentation"
    COMPANY_IR = "company_ir"
    SEC_8K_EXHIBIT = "sec_8k_exhibit"
    OTHER = "other"


class EvidencePolarity(str, Enum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class EvidenceConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceRetrievalStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"
    SKIPPED = "skipped"


class SourceDocumentPurpose(str, Enum):
    EARNINGS_RELEASE = "earnings_release"
    QUARTERLY_FILING = "quarterly_filing"
    ANNUAL_FILING = "annual_filing"
    STRATEGIC_TRANSACTION = "strategic_transaction"
    REGULATORY_CAPITAL = "regulatory_capital"
    STRESS_TEST = "stress_test"
    INVESTOR_PRESENTATION = "investor_presentation"
    TRANSCRIPT = "transcript"
    NEWS = "news"
    ESTIMATE = "estimate"
    PEER_COMMENTARY = "peer_commentary"
    OTHER = "other"
    UNKNOWN = "unknown"


class PressureType(str, Enum):
    CYCLICAL = "cyclical"
    STRUCTURAL = "structural"
    COMPANY_SPECIFIC = "company_specific"
    MACRO_DRIVEN = "macro_driven"
    TEMPORARY_COST_PRESSURE = "temporary_cost_pressure"
    DEMAND_TIMING = "demand_timing"
    MARKET_OVERREACTION = "market_overreaction"
    UNKNOWN = "unknown"


class BasicScreenResult(BaseModel):
    """
    Lightweight wrapper around the existing fundamental screen output.

    This lets the deep agent interpret whether the original screen result
    was directionally valid, misleading, too harsh, or too lenient.
    """

    passed: bool
    score: float | None = None

    failed_metrics: list[str] = Field(default_factory=list)
    passed_metrics: list[str] = Field(default_factory=list)

    raw_metrics: dict[str, float | int | str | None] = Field(default_factory=dict)
    threshold_values: dict[str, float | int | str | None] = Field(default_factory=dict)

    screen_summary: str | None = None


class FinancialSnapshot(BaseModel):
    revenue: float | None = None
    revenue_growth_yoy: float | None = None

    gross_margin: float | None = None
    operating_margin: float | None = None
    ebitda_margin: float | None = None
    net_margin: float | None = None

    free_cash_flow: float | None = None
    free_cash_flow_margin: float | None = None

    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    net_debt: float | None = None
    net_debt_to_ebitda: float | None = None

    capex: float | None = None
    capex_as_pct_revenue: float | None = None

    return_on_invested_capital: float | None = None


class FinancialPeriodType(str, Enum):
    QUARTER = "quarter"
    LTM = "ltm"
    FISCAL_YEAR = "fiscal_year"
    TTM = "ttm"


class FinancialPeriodSnapshot(BaseModel):
    period_type: FinancialPeriodType
    fiscal_period: str | None = None
    period_end_date: date | None = None
    filing_date: date | None = None
    source: str | None = None

    revenue: float | None = None
    revenue_growth_yoy: float | None = None
    revenue_growth_qoq: float | None = None

    gross_profit: float | None = None
    gross_margin: float | None = None

    operating_income: float | None = None
    operating_margin: float | None = None

    ebitda: float | None = None
    ebitda_margin: float | None = None

    net_income: float | None = None
    net_margin: float | None = None

    operating_cash_flow: float | None = None
    free_cash_flow: float | None = None
    free_cash_flow_margin: float | None = None

    capex: float | None = None
    capex_as_pct_revenue: float | None = None

    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    net_debt: float | None = None
    net_debt_to_ebitda: float | None = None

    return_on_invested_capital: float | None = None


class QuarterlyFinancialTrendPack(BaseModel):
    latest_quarter: FinancialPeriodSnapshot | None = None
    prior_quarter: FinancialPeriodSnapshot | None = None
    year_ago_quarter: FinancialPeriodSnapshot | None = None

    trailing_four_quarters: FinancialPeriodSnapshot | None = None
    trailing_eight_quarters: list[FinancialPeriodSnapshot] = Field(default_factory=list)

    last_fiscal_year: FinancialPeriodSnapshot | None = None
    prior_fiscal_year: FinancialPeriodSnapshot | None = None

    revenue_trend_8q: str | None = None
    gross_margin_trend_8q: str | None = None
    operating_margin_trend_8q: str | None = None
    fcf_trend_8q: str | None = None
    leverage_trend_8q: str | None = None

    latest_quarter_vs_ltm_notes: list[str] = Field(default_factory=list)
    inflection_flags: list[str] = Field(default_factory=list)
    staleness_warnings: list[str] = Field(default_factory=list)

    latest_period_end_date: date | None = None
    latest_filing_date: date | None = None
    financial_context_stale: bool = False


class FinancialTrendSnapshot(BaseModel):
    latest: FinancialSnapshot | None = None
    prior_year: FinancialSnapshot | None = None

    revenue_growth_direction: Literal[
        "improving", "deteriorating", "stable", "unknown"
    ] = "unknown"
    margin_direction: Literal[
        "improving", "deteriorating", "stable", "unknown"
    ] = "unknown"
    fcf_direction: Literal[
        "improving", "deteriorating", "stable", "unknown"
    ] = "unknown"
    leverage_direction: Literal[
        "improving", "deteriorating", "stable", "unknown"
    ] = "unknown"

    notes: list[str] = Field(default_factory=list)


class PriceSnapshot(BaseModel):
    current_price: float | None = None
    market_cap: float | None = None

    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_1y: float | None = None

    drawdown_from_52w_high: float | None = None
    distance_from_52w_low: float | None = None

    beta: float | None = None


class BenchmarkSelection(BaseModel):
    primary_benchmark: str
    secondary_benchmarks: list[str] = Field(default_factory=list)
    benchmark_reason: str | None = None
    benchmark_source: str = "deterministic_mapping"


class RelativeReturnWindow(BaseModel):
    window: str
    stock_return_pct: float | None = None
    benchmark_return_pct: float | None = None
    excess_return_pct: float | None = None
    relative_ratio_return_pct: float | None = None


class RelativePerformanceMetrics(BaseModel):
    ticker: str
    benchmark: str
    as_of_date: str | None = None
    windows: list[RelativeReturnWindow] = Field(default_factory=list)
    rolling_beta_6m: float | None = None
    beta_adjusted_alpha_6m_pct: float | None = None
    correlation_6m: float | None = None
    upside_capture_6m: float | None = None
    downside_capture_6m: float | None = None
    max_drawdown_stock_6m_pct: float | None = None
    max_drawdown_benchmark_6m_pct: float | None = None
    relative_ratio_above_50dma: bool | None = None
    relative_ratio_above_200dma: bool | None = None
    relative_trend: str | None = None
    relative_performance_label: str | None = None
    interpretation: str | None = None
    data_warnings: list[str] = Field(default_factory=list)


class RelativePerformanceContext(BaseModel):
    benchmark_selection: BenchmarkSelection
    primary_metrics: RelativePerformanceMetrics | None = None
    secondary_metrics: list[RelativePerformanceMetrics] = Field(default_factory=list)
    overall_label: str | None = None
    score_0_to_100: float | None = None
    summary: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ValuationSnapshot(BaseModel):
    trailing_pe: float | None = None
    forward_pe: float | None = None
    ev_to_ebitda: float | None = None
    price_to_sales: float | None = None
    price_to_book: float | None = None

    valuation_notes: list[str] = Field(default_factory=list)


class PeerRelativeSnapshot(BaseModel):
    peer_tickers: list[str] = Field(default_factory=list)

    relative_return_3m: str | None = None
    relative_return_6m: str | None = None
    relative_valuation: str | None = None
    relative_margin_profile: str | None = None
    relative_growth_profile: str | None = None

    notes: list[str] = Field(default_factory=list)


class FundamentalContextPack(BaseModel):
    ticker: str
    as_of_date: date

    financial_trend: FinancialTrendSnapshot | None = None
    quarterly_financial_trend: QuarterlyFinancialTrendPack | None = None
    price_snapshot: PriceSnapshot | None = None
    valuation_snapshot: ValuationSnapshot | None = None
    peer_relative_snapshot: PeerRelativeSnapshot | None = None

    basic_screen_result: BasicScreenResult | None = None

    data_confidence: DataConfidence = DataConfidence.LOW
    missing_fields: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)
    data_freshness_notes: list[str] = Field(default_factory=list)


class MacroScenarioContext(BaseModel):
    scenario_id: str
    label: str | None = None
    probability: float | None = None
    score: float | None = None
    rationale: str | None = None


class MacroSignalContext(BaseModel):
    input_id: str
    label: str | None = None
    category: str | None = None
    signal: str | None = None
    signal_strength: float | None = None
    level_status: str | None = None
    trend_status: str | None = None
    current_value: str | float | int | bool | None = None
    notes: str | None = None
    related_scenario_ids: list[str] = Field(default_factory=list)
    related_theme_ids: list[str] = Field(default_factory=list)


class MacroRankingContext(BaseModel):
    item_id: str
    label: str | None = None
    score: float | None = None
    rationale: str | None = None


class MacroContextPack(BaseModel):
    asof_date: date | None = None
    created_at: datetime | None = None

    regime_id: str | None = None
    regime_label: str | None = None

    top_scenarios: list[MacroScenarioContext] = Field(default_factory=list)
    top_macro_signals: list[MacroSignalContext] = Field(default_factory=list)

    sector_rankings: list[MacroRankingContext] = Field(default_factory=list)
    factor_rankings: list[MacroRankingContext] = Field(default_factory=list)

    summary: str | None = None
    source_path: str | None = None
    source_notes: list[str] = Field(default_factory=list)


class ThemeCatalogItem(BaseModel):
    theme_id: str
    label: str | None = None
    score: float | None = None
    rationale: str | None = None


class ThemeMappingItem(BaseModel):
    theme_id: str
    theme_label: str | None = None
    fit: ThemeFitType
    confidence: float = Field(ge=0, le=1)
    rationale: str


class RejectedThemeMapping(BaseModel):
    theme_id: str
    theme_label: str | None = None
    reason: str


class ThemeMappingResult(BaseModel):
    ticker: str
    mapped_themes: list[ThemeMappingItem] = Field(default_factory=list)
    rejected_themes: list[RejectedThemeMapping] = Field(default_factory=list)

    mapping_summary: str | None = None
    data_confidence: DataConfidence = DataConfidence.MEDIUM
    source: Literal["llm", "deterministic_fallback", "manual", "none"] = "none"


class ThemeScoreContext(BaseModel):
    theme_id: str
    label: str | None = None
    score: float | None = None
    fit: ThemeFitType | None = None
    fit_confidence: float | None = None
    weighted_score: float | None = None
    rationale: str | None = None


class ThemeImpactContext(BaseModel):
    theme_id: str
    theme_label: str | None = None
    direction: MacroImpactDirection = MacroImpactDirection.UNKNOWN
    strength: float | None = None
    rationale: str | None = None
    source_input_id: str | None = None
    source_label: str | None = None
    category: str | None = None


class ThemeContextPack(BaseModel):
    ticker: str

    selected_theme_ids: list[str] = Field(default_factory=list)
    theme_mapping: ThemeMappingResult | None = None

    relevant_theme_scores: list[ThemeScoreContext] = Field(default_factory=list)
    relevant_theme_impacts: list[ThemeImpactContext] = Field(default_factory=list)

    linked_scenarios: list[str] = Field(default_factory=list)
    positive_drivers: list[str] = Field(default_factory=list)
    negative_drivers: list[str] = Field(default_factory=list)
    mixed_drivers: list[str] = Field(default_factory=list)

    aggregate_theme_support_score: float | None = None

    theme_fit_summary: str | None = None
    source_notes: list[str] = Field(default_factory=list)


class DeepFundamentalLLMSynthesis(BaseModel):
    ticker: str

    business_summary: str = Field(min_length=1, max_length=2500)
    business_quality_assessment: str = Field(min_length=1, max_length=2500)

    financial_trend_diagnosis: str = Field(min_length=1, max_length=3000)
    screen_interpretation: str = Field(min_length=1, max_length=2500)
    why_screen_may_be_wrong: str | None = Field(default=None, max_length=2500)

    current_market_narrative: str = Field(min_length=1, max_length=2500)
    consensus_type: DeepConsensusType = DeepConsensusType.UNKNOWN
    consensus_verification_required: list[str] = Field(default_factory=list)

    macro_fit_assessment: str | None = Field(default=None, max_length=2500)
    theme_fit_assessment: str | None = Field(default=None, max_length=2500)

    pressure_inflection_assessment: str = Field(min_length=1, max_length=3000)
    competitive_position_assessment: str = Field(min_length=1, max_length=3000)
    valuation_expectations_assessment: str = Field(min_length=1, max_length=3000)
    benchmark_relative_view: str | None = Field(default=None, max_length=2500)

    variant_view: str = Field(default="", max_length=3000)
    variant_view_direction: VariantViewDirection = VariantViewDirection.NONE
    variant_view_strength: Literal["none", "weak", "medium", "strong"] = "none"
    bull_case_variant_view: str | None = Field(default=None, max_length=2500)
    bear_case_variant_view: str | None = Field(default=None, max_length=2500)
    evidence_supporting_variant_view: list[str] = Field(
        default_factory=list,
        max_length=15,
    )
    evidence_against_variant_view: list[str] = Field(
        default_factory=list,
        max_length=15,
    )

    key_risks: list[str] = Field(default_factory=list, max_length=15)

    fundamental_falsifiers: list[str] = Field(default_factory=list, max_length=15)
    macro_theme_falsifiers: list[str] = Field(default_factory=list, max_length=15)
    valuation_falsifiers: list[str] = Field(default_factory=list, max_length=15)
    timing_falsifiers: list[str] = Field(default_factory=list, max_length=15)

    key_metrics_to_monitor: list[str] = Field(default_factory=list, max_length=20)
    suggested_monitoring_plan: list[str] = Field(default_factory=list, max_length=20)

    underwriting_summary: str = Field(min_length=1, max_length=3000)

    qualitative_conviction: Literal[
        "reject",
        "watchlist",
        "constructive",
        "high_conviction",
    ] = "watchlist"
    suggested_score_adjustment: float = Field(
        default=0.0,
        ge=-10.0,
        le=10.0,
        description=(
            "Suggested adjustment in final underwriting score POINTS on a "
            "0-100 scale. Use +2.0 for a small positive adjustment, +5.0 "
            "for a meaningful positive adjustment, -2.0 for a small negative "
            "adjustment, and -5.0 for a meaningful negative adjustment. Do "
            "not return decimals like 0.25 unless you truly mean one quarter "
            "of one score point."
        ),
    )

    confidence: DeepSynthesisConfidence = DeepSynthesisConfidence.LOW
    data_gaps: list[str] = Field(default_factory=list, max_length=20)


class CompanySegment(BaseModel):
    name: str
    description: str | None = None
    revenue_share_estimate: float | None = Field(
        default=None,
        description="Estimated percentage of total revenue, if known.",
    )
    profit_share_estimate: float | None = Field(
        default=None,
        description="Estimated percentage of total profit/EBIT/EBITDA, if known.",
    )
    key_drivers: list[str] = Field(default_factory=list)


class PeerCompany(BaseModel):
    ticker: str | None = None
    name: str
    relevance: str | None = None


class CompanyProfile(BaseModel):
    ticker: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None

    profile_source: Literal[
        "manual_seed",
        "llm_generated_unverified",
        "llm_generated_research_context",
        "filing_verified",
        "mixed",
    ] = "llm_generated_unverified"
    profile_confidence: DataConfidence = DataConfidence.MEDIUM
    profile_as_of_date: date | None = None
    profile_source_notes: list[str] = Field(default_factory=list)
    profile_data_gaps: list[str] = Field(default_factory=list)

    business_description: str | None = None
    business_model: str | None = None

    segments: list[CompanySegment] = Field(default_factory=list)

    revenue_model: list[str] = Field(default_factory=list)
    cost_drivers: list[str] = Field(default_factory=list)
    margin_drivers: list[str] = Field(default_factory=list)

    key_customers: list[str] = Field(default_factory=list)
    key_suppliers: list[str] = Field(default_factory=list)

    peer_group: list[PeerCompany] = Field(default_factory=list)

    thematic_exposures: list[str] = Field(default_factory=list)
    macro_sensitivities: list[str] = Field(default_factory=list)

    major_risks: list[str] = Field(default_factory=list)


class FinancialTrendAnalysis(BaseModel):
    revenue_growth_trend: str | None = None
    gross_margin_trend: str | None = None
    operating_margin_trend: str | None = None
    ebitda_margin_trend: str | None = None
    fcf_trend: str | None = None
    capex_trend: str | None = None
    leverage_trend: str | None = None
    roic_trend: str | None = None
    working_capital_trend: str | None = None
    estimate_revision_trend: str | None = None

    improving_indicators: list[str] = Field(default_factory=list)
    deteriorating_indicators: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)

    screen_result_context: str | None = Field(
        default=None,
        description="Interpretation of the basic financial screen result.",
    )

    why_screen_may_be_wrong: str | None = Field(
        default=None,
        description="Explains why a threshold-based screen may be too harsh or too lenient.",
    )


class PressureInflectionAnalysis(BaseModel):
    recent_pressure_points: list[str] = Field(default_factory=list)
    recent_strength_points: list[str] = Field(default_factory=list)

    likely_causes: list[str] = Field(default_factory=list)
    pressure_type: PressureType = PressureType.UNKNOWN

    cyclical_vs_structural_assessment: str | None = None

    abatement_evidence: list[str] = Field(
        default_factory=list,
        description="Evidence that current pressure may fade.",
    )

    inflection_catalysts: list[str] = Field(default_factory=list)

    margin_recovery_potential: str | None = None
    demand_recovery_potential: str | None = None
    earnings_inflection_potential: str | None = None

    key_timing_questions: list[str] = Field(default_factory=list)


class CompetitivePositionAnalysis(BaseModel):
    peer_group: list[PeerCompany] = Field(default_factory=list)

    market_share_position: str | None = None
    relative_growth: str | None = None
    relative_margins: str | None = None
    relative_valuation: str | None = None

    moat_sources: list[str] = Field(default_factory=list)
    competitive_advantages: list[str] = Field(default_factory=list)
    competitive_threats: list[str] = Field(default_factory=list)

    pricing_power: str | None = None
    switching_costs: str | None = None
    scale_advantages: str | None = None

    management_quality: str | None = None
    capital_allocation_quality: str | None = None

    competitive_position_summary: str | None = None


class ScenarioImpact(BaseModel):
    scenario_name: str
    impact: Literal["positive", "negative", "mixed", "neutral", "unknown"]
    rationale: str
    sensitivity_level: Literal["low", "medium", "high", "unknown"] = "unknown"


class RegimeSensitivityAnalysis(BaseModel):
    current_regime_fit: str | None = None

    scenario_impacts: list[ScenarioImpact] = Field(default_factory=list)

    oil_sensitivity: str | None = None
    rate_sensitivity: str | None = None
    credit_sensitivity: str | None = None
    dollar_sensitivity: str | None = None
    inflation_sensitivity: str | None = None
    consumer_sensitivity: str | None = None
    ai_capex_sensitivity: str | None = None
    commodity_sensitivity: str | None = None
    policy_sensitivity: str | None = None

    upside_scenario: str | None = None
    downside_scenario: str | None = None
    regime_fit_summary: str | None = None


class MarketExpectationAnalysis(BaseModel):
    recent_price_action: str | None = None
    valuation_vs_history: str | None = None
    valuation_vs_peers: str | None = None
    earnings_revision_context: str | None = None

    narrative_consensus: str | None = None
    implied_expectations: str | None = None

    market_mispricing_hypothesis: str | None = None

    downside_already_priced: bool | None = None
    upside_already_priced: bool | None = None
    crowdedness_risk: str | None = None

    expectation_summary: str | None = None


class VariantView(BaseModel):
    consensus_view: str | None = None
    helix_variant_view: str | None = None
    variant_view_direction: VariantViewDirection = VariantViewDirection.NONE
    bull_case_variant_view: str | None = None
    bear_case_variant_view: str | None = None

    evidence_supporting_variant_view: list[str] = Field(default_factory=list)
    why_market_may_be_wrong: list[str] = Field(default_factory=list)

    required_confirming_evidence: list[str] = Field(default_factory=list)
    risks_to_variant_view: list[str] = Field(default_factory=list)

    variant_view_strength: Literal["none", "weak", "medium", "strong"] = "none"


class FalsificationFramework(BaseModel):
    fundamental_falsifiers: list[str] = Field(default_factory=list)
    macro_falsifiers: list[str] = Field(default_factory=list)
    valuation_falsifiers: list[str] = Field(default_factory=list)
    timing_falsifiers: list[str] = Field(default_factory=list)
    technical_or_price_falsifiers: list[str] = Field(default_factory=list)

    monitoring_triggers: list[str] = Field(default_factory=list)
    key_metrics_to_watch: list[str] = Field(default_factory=list)

    review_dates: list[date] = Field(default_factory=list)

    falsification_summary: str | None = None


class DeepFundamentalScores(BaseModel):
    business_quality: float = Field(ge=0, le=100)
    financial_health: float = Field(ge=0, le=100)
    competitive_position: float = Field(ge=0, le=100)
    earnings_inflection_potential: float = Field(ge=0, le=100)
    regime_fit: float | None = Field(default=None, ge=0, le=100)
    valuation_setup: float = Field(ge=0, le=100)
    relative_strength_benchmark_alpha: float = Field(default=50.0, ge=0, le=100)
    variant_perception_strength: float = Field(ge=0, le=100)
    idiosyncratic_risk: float = Field(
        ge=0,
        le=100,
        description="Higher score means higher idiosyncratic risk.",
    )

    final_underwriting_score: float = Field(ge=0, le=100)


class SourceDocument(BaseModel):
    source_type: EvidenceSourceType
    retrieval_status: SourceRetrievalStatus = SourceRetrievalStatus.FOUND
    document_purpose: SourceDocumentPurpose = SourceDocumentPurpose.UNKNOWN
    classification_confidence: EvidenceConfidence = EvidenceConfidence.MEDIUM
    classification_rationale: str | None = None
    provider_status: str | None = None

    ticker: str
    source_name: str | None = None
    title: str | None = None
    source_date: date | None = None
    retrieved_at: datetime | None = None

    source_url: str | None = None
    accession_number: str | None = None
    cik: str | None = None
    form_type: str | None = None
    exhibit_type: str | None = None

    text: str | None = None
    text_excerpt: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    error_message: str | None = None
    notes: str | None = None
    source_confidence: EvidenceConfidence = EvidenceConfidence.MEDIUM


class SingleNameEvidenceItem(BaseModel):
    source_type: EvidenceSourceType
    ticker: str
    document_purpose: SourceDocumentPurpose | None = None

    source_date: date | None = None
    source_name: str | None = None
    source_url: str | None = None
    accession_number: str | None = None
    form_type: str | None = None
    exhibit_type: str | None = None

    title: str | None = None
    claim: str
    summary: str | None = None
    excerpt: str | None = None

    polarity: EvidencePolarity = EvidencePolarity.NEUTRAL
    confidence: EvidenceConfidence = EvidenceConfidence.MEDIUM
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)

    related_topics: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)

    evidence_tags: list[str] = Field(default_factory=list)
    notes: str | None = None


class SourceCoverageItem(BaseModel):
    source_type: EvidenceSourceType
    document_purpose: SourceDocumentPurpose = SourceDocumentPurpose.UNKNOWN
    status: SourceRetrievalStatus
    provider_status: str | None = None
    provider: str | None = None
    source_name: str | None = None
    source_date: date | None = None
    source_url: str | None = None
    accession_number: str | None = None
    notes: str | None = None


class SingleNameResearchContextPack(BaseModel):
    ticker: str
    as_of_date: date
    created_at: datetime = Field(default_factory=datetime.utcnow)

    source_coverage: list[SourceCoverageItem] = Field(default_factory=list)
    source_coverage_summary: str | None = None
    extraction_source_summary: list[dict[str, Any]] = Field(default_factory=list)

    earnings_release_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    filing_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    transcript_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    news_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    estimate_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    peer_commentary_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    strategic_transaction_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    regulatory_capital_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    stress_test_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    investor_presentation_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    other_sec_8k_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)

    management_guidance: list[SingleNameEvidenceItem] = Field(default_factory=list)
    segment_kpis: list[SingleNameEvidenceItem] = Field(default_factory=list)
    consensus_narrative: list[SingleNameEvidenceItem] = Field(default_factory=list)

    bullish_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    bearish_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)
    mixed_evidence: list[SingleNameEvidenceItem] = Field(default_factory=list)

    unresolved_questions: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    raw_source_count: int = 0
    evidence_item_count: int = 0


class DeepFundamentalRunConfiguration(BaseModel):
    llm_synthesis_used: bool = True
    llm_synthesis_status: str | None = None
    llm_synthesis_prompt_chars: int | None = None
    llm_synthesis_prompt_est_tokens: int | None = None
    llm_retry_count: int | None = None
    llm_last_error: str | None = None
    llm_profile_used: bool = True
    research_context_used: bool = True

    company_profile_source: str | None = None
    research_context_created_at: datetime | None = None
    research_context_refreshed: bool = False
    research_context_cache_used: bool = False
    manual_transcript_path_used: str | None = None
    manual_transcript_source: str | None = None
    transcript_mapping_warning: str | None = None

    source_providers_attempted: list[str] = Field(default_factory=list)
    source_providers_found: list[str] = Field(default_factory=list)
    source_providers_skipped: list[str] = Field(default_factory=list)
    source_providers_error: list[str] = Field(default_factory=list)

    source_coverage_summary: str | None = None
    data_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DeepFundamentalReport(BaseModel):
    """
    Primary output object for the deeper fundamental agent.

    This should be usable both:
    1. Standalone, when a user provides tickers manually.
    2. Inside a full Helix research cycle, after candidate generation and basic screening.
    """

    ticker: str
    as_of_date: date
    created_at: datetime = Field(default_factory=datetime.utcnow)

    input_mode: DeepFundamentalInputMode
    horizon: str | None = None

    cycle_id: str | None = None
    candidate_id: str | None = None
    trade_id: str | None = None

    macro_context: MacroContextPack | dict[str, Any] | None = None
    theme_context: ThemeContextPack | dict[str, Any] | None = None
    research_context: SingleNameResearchContextPack | None = None
    user_supplied_thesis: str | None = None

    basic_screen_result: BasicScreenResult | None = None
    fundamental_context: FundamentalContextPack | None = None
    relative_performance_context: RelativePerformanceContext | None = None
    llm_synthesis: DeepFundamentalLLMSynthesis | None = None
    run_configuration: DeepFundamentalRunConfiguration | None = None

    company_profile: CompanyProfile
    financial_trend_analysis: FinancialTrendAnalysis
    pressure_inflection_analysis: PressureInflectionAnalysis
    competitive_position_analysis: CompetitivePositionAnalysis
    regime_sensitivity_analysis: RegimeSensitivityAnalysis | None = None
    market_expectation_analysis: MarketExpectationAnalysis
    variant_view: VariantView
    falsification_framework: FalsificationFramework

    scores: DeepFundamentalScores

    verdict: DeepFundamentalVerdict
    screen_override: bool = False
    screen_override_rationale: str | None = None

    final_rationale: str
    key_monitoring_items: list[str] = Field(default_factory=list)
    recommended_next_action: str | None = None

    data_confidence: DataConfidence = DataConfidence.MEDIUM

    source_notes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
