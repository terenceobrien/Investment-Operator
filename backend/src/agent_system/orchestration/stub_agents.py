"""
Deterministic stub agents for the v0 execution spine.

These functions intentionally make no network or LLM calls. They produce
valid schema objects for one end-to-end research cycle.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.schemas.common import (
    AnalysisConviction,
    Catalyst,
    CatalystType,
    Conviction,
    ConvictionRating,
    Falsifier,
    FalsifierFrequency,
    FalsifierObservable,
    InefficiencyArchetype,
    NewsEvidence,
    PriceEvidence,
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
from src.agent_system.schemas.narrative import (
    CurrentNarrative,
    InefficiencyThesis,
    NarrativeAge,
    NarrativeAnalysis,
)
from src.agent_system.schemas.regime import (
    EdgeDecayHorizon,
    LayerWeights,
    RegimeDriver,
    RegimeHorizon,
    RegimeLayerScore,
    RegimeLayerStatus,
    RegimeLayers,
    RegimeState,
    ResearchPriority,
)
from src.agent_system.schemas.thematic import (
    Candidate,
    ExclusionRecord,
    InstrumentType,
    ResearchDepth,
    ThematicMap,
    VariantStrength,
)
from src.agent_system.schemas.trade import (
    AlternativeRejected,
    Hedge,
    HedgeType,
    Instrument,
    ProposedSizing,
    ReviewCadence,
    TradeDirection,
    TradeExpression,
    TradeIdea,
    TradeProvenance,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _news(claim: str, title: str, *, supports: bool = True) -> NewsEvidence:
    return NewsEvidence(
        claim=claim,
        supports=supports,
        publisher="Helix Stub Research",
        title=title,
        url="https://example.com/helix-stub",
        published_at=_now(),
    )


def _price(claim: str, ticker: str, metric: str, value: float) -> PriceEvidence:
    return PriceEvidence(
        claim=claim,
        supports=True,
        ticker=ticker,
        metric=metric,
        value=value,
        as_of=_now(),
        timeframe="daily",
    )


def _analysis_conviction(rating: ConvictionRating, ticker: str) -> AnalysisConviction:
    return AnalysisConviction(
        rating=rating,
        justification=(
            f"{ticker} has enough evidence for a {rating.value} stub rating, "
            "with explicit variant evidence and a named uncertainty."
        ),
        primary_uncertainty=(
            "Macro conditions or earnings revisions could move against the "
            "theme before the market reprices the opportunity."
        ),
    )


def make_stub_regime_state() -> RegimeState:
    """Create the macro-regime stub: supply shock with resilient AI earnings."""

    priority_evidence = _news(
        "Grid and power infrastructure demand can extend beyond the semiconductor cycle.",
        "AI data-center power demand pulls forward grid investment",
    )
    priority = ResearchPriority(
        theme="AI power/grid beneficiaries",
        rationale=(
            "Supply-shock inflation and tighter policy make broad beta fragile, "
            "but AI infrastructure demand still supports select grid and power names."
        ),
        edge_hypothesis=(
            "Market attention is concentrated in semiconductors and mega-cap AI, "
            "while the duration and scale of electrical grid and power "
            "infrastructure demand may be underappreciated."
        ),
        sub_questions=[
            "Which names have direct exposure to data-center power equipment demand?",
            "Where is consensus still treating AI grid demand as cyclical rather than structural?",
        ],
        priority_rank=1,
        expected_edge_decay=EdgeDecayHorizon.QUARTERS,
        supporting_evidence=[priority_evidence],
    )

    layers = RegimeLayers(
        monetary=RegimeLayerScore(
            score=3.4,
            inputs={"net_liquidity_z": -0.8},
            signals=["Liquidity tightening"],
            status=RegimeLayerStatus.BEARISH,
            data_quality=0.9,
        ),
        credit=RegimeLayerScore(
            score=4.4,
            inputs={"baa_spread_z": 0.4},
            signals=["Credit is contained but no longer easing"],
            status=RegimeLayerStatus.NEUTRAL,
            data_quality=0.8,
        ),
        volatility=RegimeLayerScore(
            score=4.0,
            inputs={"vix": 22.0},
            signals=["Volatility risk premium elevated"],
            status=RegimeLayerStatus.NEUTRAL,
            data_quality=0.9,
        ),
        breadth=RegimeLayerScore(
            score=3.8,
            inputs={"pct_above_200d": 42.0},
            signals=["Narrow leadership"],
            status=RegimeLayerStatus.BEARISH,
            data_quality=0.85,
        ),
        positioning=RegimeLayerScore(
            score=5.8,
            inputs={"cot_net_large_spec_z": 0.2},
            signals=["AI leadership still supported"],
            status=RegimeLayerStatus.NEUTRAL,
            data_quality=0.75,
        ),
    )
    return RegimeState(
        asof_date="2026-05-19",
        horizon=RegimeHorizon.DEFAULT,
        layers=layers,
        weights=LayerWeights(
            monetary=0.20,
            credit=0.22,
            volatility=0.22,
            breadth=0.20,
            positioning=0.16,
        ),
        composite=43.0,
        layer_agreement=0.72,
        composite_confidence=78.0,
        environment="Late-cycle tightening with narrow AI leadership",
        environment_drivers=["Oil shock", "Fed repricing", "AI earnings resilience"],
        regime_id="supply_shock_inflation",
        regime_label="Supply-shock inflation / late-cycle tightening",
        headline=(
            "Oil-driven inflation pressure is tightening financial conditions "
            "while AI earnings leadership remains intact."
        ),
        summary=(
            "This is a fractured regime: broad beta is less attractive, but "
            "energy, infrastructure, defense, cash, and quality AI-linked "
            "beneficiaries can still work."
        ),
        risk_summary=(
            "The key risk is mistaking narrow leadership for a clean risk-on "
            "environment while rates and liquidity remain restrictive."
        ),
        key_drivers=[
            RegimeDriver(
                name="Oil supply shock",
                status="bearish for broad beta / bullish for energy",
                explanation="Elevated oil keeps inflation risk alive and raises input costs.",
            ),
            RegimeDriver(
                name="AI earnings resilience",
                status="bullish for quality AI infrastructure",
                explanation="Capital spending tied to data-center demand remains durable.",
            ),
        ],
        portfolio_implications=[
            "Favor quality AI infrastructure and short-duration optionality.",
            "Be selective with broad beta and rate-sensitive cyclicals.",
        ],
        best_positioned=["Energy / oil beta", "Quality AI leaders", "Infrastructure / grid"],
        most_vulnerable=["Small caps", "Long-duration bonds", "Unprofitable growth"],
        regime_call_confidence=0.78,
        falsifiers=[
            Falsifier(
                condition="Oil falls below $70 while inflation breakevens compress",
                observable_in=FalsifierObservable.DATA_SERIES,
                check_frequency=FalsifierFrequency.DAILY,
            )
        ],
        research_priorities=[priority],
    )


def _candidate(
    ticker: str,
    name: str,
    rank: int,
    variant_strength: VariantStrength,
    variant_view: str,
    tags: list[str],
) -> Candidate:
    return Candidate(
        ticker=ticker,
        instrument_type=InstrumentType.ETF if ticker in {"SMH", "IFRA", "PAVE"} else InstrumentType.SINGLE_STOCK,
        name=name,
        thematic_fit=(
            f"{ticker} is tied to data-center electrification and grid/power "
            "capacity demand under the AI infrastructure theme."
        ),
        fit_strength=0.86 if ticker == "ETN" else 0.66,
        fit_evidence=[
            _news(
                f"{ticker} has identifiable AI power/grid exposure.",
                f"{ticker} mentioned as AI infrastructure beneficiary",
            )
        ],
        consensus_view="Consensus recognizes AI demand but mostly rewards obvious semiconductor exposure.",
        potential_variant_view=variant_view,
        variant_strength=variant_strength,
        variant_evidence=[
            _news(
                f"{ticker} variant view is underappreciated relative to consensus focus.",
                f"{ticker} grid/power optionality remains debated",
            )
        ],
        catalysts=[
            Catalyst(
                event="Next earnings update on backlog, orders, and AI infrastructure demand",
                catalyst_type=CatalystType.EARNINGS,
                is_ongoing=True,
                asymmetry="Positive order/backlog evidence can force estimate revisions.",
            )
        ],
        priority_rank=rank,
        recommended_research_depth=ResearchDepth.DEEP if ticker == "ETN" else ResearchDepth.STANDARD,
        theme_tags=tags,
    )


def make_stub_thematic_map(regime: RegimeState) -> ThematicMap:
    """Map the regime's first research priority into candidate instruments."""

    priority = regime.research_priorities[0]
    candidates = [
        _candidate(
            "ETN",
            "Eaton",
            1,
            VariantStrength.STRONG,
            (
                "Consensus still treats Eaton as a high-quality industrial, "
                "but AI-driven electrical demand may extend backlog and margins "
                "longer than estimates imply."
            ),
            ["infrastructure", "grid", "quality_ai"],
        ),
        _candidate(
            "NVDA",
            "Nvidia",
            2,
            VariantStrength.WEAK,
            "The AI accelerator thesis is real but widely owned and fully debated.",
            ["quality_ai", "semiconductors", "crowded"],
        ),
        _candidate(
            "SMH",
            "VanEck Semiconductor ETF",
            3,
            VariantStrength.UNCLEAR,
            "",
            ["semiconductors", "quality_ai", "crowded"],
        ),
        _candidate(
            "VST",
            "Vistra",
            4,
            VariantStrength.MODERATE,
            "Power scarcity is relevant, but merchant-power cyclicality makes the edge less clean.",
            ["grid", "power", "cyclical"],
        ),
        _candidate(
            "IFRA",
            "iShares U.S. Infrastructure ETF",
            5,
            VariantStrength.UNCLEAR,
            "",
            ["infrastructure", "grid"],
        ),
        _candidate(
            "PAVE",
            "Global X U.S. Infrastructure Development ETF",
            6,
            VariantStrength.WEAK,
            "Theme fit is broad, but instrument dilution weakens the direct variant view.",
            ["infrastructure", "grid"],
        ),
    ]
    return ThematicMap(
        source_priority=priority,
        candidates=candidates,
        excluded=[
            ExclusionRecord(
                ticker="TSLA",
                reason="Considered but excluded because the AI power/grid thesis is indirect and dominated by unrelated auto and robotaxi narratives.",
            )
        ],
        mapping_logic=(
            "The map favors instruments with direct grid, electrical equipment, "
            "and data-center power exposure, then rejects names where the AI "
            "theme is already obvious or too diluted."
        ),
        universe_considered=42,
    )


def make_stub_fundamental_analysis(candidate: Candidate) -> FundamentalAnalysis:
    """Create a ticker-specific fundamental stub."""

    strong = candidate.ticker == "ETN"
    no_variant = candidate.ticker in {"VST", "PAVE"}
    differ_evidence = [
        _news(
            f"{candidate.ticker} backlog/earnings evidence supports differentiated estimates.",
            f"{candidate.ticker} order backlog points to durable electrification demand",
        )
    ]
    return FundamentalAnalysis(
        ticker=candidate.ticker,
        thesis_statement=(
            f"{candidate.ticker} can compound earnings above consensus as AI "
            "infrastructure demand pulls forward power and grid investment."
        ),
        business_quality=BusinessQuality(
            summary=(
                f"{candidate.name} has meaningful exposure to infrastructure "
                "spending and enough business quality to warrant a structured review."
            ),
            moat_assessment="Scale, installed base, and channel depth support pricing power.",
            cyclicality=Cyclicality.HYBRID,
        ),
        financials=Financials(
            balance_sheet_quality=8.0 if strong else 6.5,
            cash_generation_quality=8.2 if strong else 6.2,
            accounting_red_flags=[],
        ),
        estimates_and_expectations=EstimatesAndExpectations(
            consensus_summary="Consensus expects steady growth but remains cautious on macro-sensitive industrial demand.",
            revision_trend=EstimateRevisionTrend.UPWARD if strong else EstimateRevisionTrend.STABLE,
            where_we_differ=None
            if no_variant
            else (
                "We expect AI electrical infrastructure demand to sustain order growth "
                "and margins longer than consensus models currently imply."
            ),
            differ_magnitude=None if no_variant else DifferMagnitude.SIGNIFICANT,
            differ_evidence=[] if no_variant else differ_evidence,
        ),
        positioning=Positioning(
            institutional_positioning="High-quality buyers are present, but generalists still debate whether the AI grid demand is durable.",
            crowdedness_assessment=Crowdedness.NORMAL if strong else Crowdedness.CROWDED,
        ),
        steelman_bear_case=(
            "The bear case is that AI data-center demand is pulled forward, "
            "industrial demand rolls over as rates stay high, and backlog "
            "normalizes before estimates can move materially higher."
        ),
        bear_case_evidence=[
            _news(
                f"{candidate.ticker} is exposed to cyclical industrial demand.",
                f"{candidate.ticker} macro sensitivity remains a risk",
                supports=True,
            )
        ],
        what_bear_case_misses=(
            "nothing material"
            if candidate.ticker == "PAVE"
            else (
                "The bear case underweights the duration of utility and data-center "
                "capex plans, which are tied to multi-year power constraints rather "
                "than one quarter of industrial activity."
            )
        ),
        conviction=_analysis_conviction(
            ConvictionRating.STRONG if strong else ConvictionRating.MODERATE,
            candidate.ticker,
        ),
    )


def make_stub_narrative_analysis(candidate: Candidate) -> NarrativeAnalysis:
    """Create a ticker-specific narrative stub."""

    mature = candidate.ticker in {"NVDA", "SMH"}
    return NarrativeAnalysis(
        ticker=candidate.ticker,
        current_narrative=CurrentNarrative(
            summary=(
                f"{candidate.ticker} is viewed through the AI infrastructure lens, "
                "but the market differs on whether the edge is still early or already crowded."
            ),
            dominant_archetype=InefficiencyArchetype("narrative_fundamental_divergence"),
            narrative_strength=9.0 if mature else 6.8,
            narrative_age=NarrativeAge.MATURE if mature else NarrativeAge.ESTABLISHED,
        ),
        inefficiency_thesis=InefficiencyThesis(
            archetype=InefficiencyArchetype("narrative_fundamental_divergence"),
            description=(
                f"The market narrative around {candidate.ticker} may be too "
                "focused on near-term cyclicality rather than the multi-year "
                "power infrastructure requirement behind AI demand."
            ),
            evidence=[
                _price(
                    f"{candidate.ticker} price action is consistent with selective infrastructure leadership.",
                    candidate.ticker,
                    "relative_strength_3m",
                    7.5,
                )
            ],
            why_it_persists=(
                "The theme cuts across industrials, utilities, and technology, "
                "so benchmarked investors are slow to size it outside obvious AI names."
            ),
            expected_resolution_path=(
                "Backlog, orders, and margin guidance should reveal whether "
                "demand is structural enough to force estimate revisions."
            ),
            resolution_horizon=EdgeDecayHorizon.QUARTERS,
        ),
        narrative_could_be_wrong_if=[
            "AI infrastructure orders prove to be pulled-forward rather than structural.",
            "Management commentary shows backlog conversion slowing faster than expected.",
        ],
        contradicting_signals=[],
        conviction=_analysis_conviction(
            ConvictionRating.STRONG if candidate.ticker == "ETN" else ConvictionRating.MODERATE,
            candidate.ticker,
        ),
        source_narrative_state_asof="2026-05-19",
    )


def _accepted_expression(candidate: Candidate) -> TradeExpression:
    instrument = Instrument(
        ticker=candidate.ticker,
        instrument_type=candidate.instrument_type,
        direction=TradeDirection.LONG,
        description=f"Long {candidate.ticker} common equity",
    )
    return TradeExpression(
        primary_instrument=instrument,
        rationale_for_instrument=(
            "Direct equity exposure captures the company-specific estimate "
            "revision and narrative repricing path better than a broad ETF."
        ),
        alternatives_considered=[
            AlternativeRejected(
                instrument=Instrument(
                    ticker="IFRA",
                    instrument_type=InstrumentType.ETF,
                    direction=TradeDirection.LONG,
                ),
                why_rejected="ETF exposure is too diluted for the variant view.",
            )
        ],
        entry_logic="Open a starter position post-close and add only if backlog commentary remains supportive.",
        exit_target="Exit when consensus estimate revisions catch up or valuation discounts the grid demand path.",
        exit_stop="Reduce if price breaks below the 200-day trend with negative order commentary.",
        exit_time_stop="Review after two earnings cycles if no estimate revision occurs.",
        hedges=[
            Hedge(
                hedge_type=HedgeType.INDEX_SHORT,
                instrument=Instrument(
                    ticker="SPY",
                    instrument_type=InstrumentType.ETF,
                    direction=TradeDirection.SHORT,
                ),
                hedge_ratio=0.25,
                rationale="Small index hedge dampens broad late-cycle beta risk.",
            )
        ],
    )


def _accepted_falsifiers(candidate: Candidate) -> list[Falsifier]:
    return [
        Falsifier(
            condition=f"{candidate.ticker} reports backlog contraction while management cuts full-year demand commentary.",
            observable_in=FalsifierObservable.EARNINGS,
            check_frequency=FalsifierFrequency.EVENT_DRIVEN,
        ),
        Falsifier(
            condition="AI data-center capex guidance from hyperscalers weakens for two consecutive earnings cycles.",
            observable_in=FalsifierObservable.EARNINGS,
            check_frequency=FalsifierFrequency.EVENT_DRIVEN,
        ),
        Falsifier(
            condition=f"{candidate.ticker} underperforms XLI by more than 12% over 30 trading days without a market-wide drawdown.",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        ),
    ]


def construct_trade_idea(
    *,
    candidate: Candidate,
    fundamental: FundamentalAnalysis | None,
    narrative: NarrativeAnalysis | None,
    regime: RegimeState,
    conviction: Conviction,
) -> TradeIdea:
    """Construct either an accepted TradeIdea or a first-class rejection."""

    if conviction.rating in (ConvictionRating.PASS, ConvictionRating.WEAK):
        stage = {
            "thematic": "thematic",
            "fundamental": "single_name",
            "narrative": "narrative",
        }.get(conviction.weakest_link, "construction")
        return TradeIdea(
            underlying=candidate.ticker,
            fundamental=fundamental,
            narrative=narrative,
            research_priority=regime.research_priorities[0],
            regime=regime,
            combined_conviction=conviction,
            rejection_reason=conviction.reasoning,
            rejection_stage=stage,  # type: ignore[arg-type]
            rejection_rule_fired=conviction.rule_applied,
        )

    return TradeIdea(
        underlying=candidate.ticker,
        fundamental=fundamental,
        narrative=narrative,
        research_priority=regime.research_priorities[0],
        regime=regime,
        combined_conviction=conviction,
        expression=_accepted_expression(candidate),
        proposed_sizing=ProposedSizing(
            base_size_pct=0.04,
            sizing_logic=(
                "4% NAV is large enough to matter for a strong thesis but "
                "small enough to respect late-cycle macro uncertainty."
            ),
            kelly_implied=0.07,
            max_loss_estimate_pct=0.018,
        ),
        expected_holding_period="6 to 12 months",
        thesis_review_cadence=ReviewCadence.WEEKLY,
        next_review_trigger="Next earnings report, material backlog update, or 30-day relative drawdown.",
        trade_falsifiers=_accepted_falsifiers(candidate),
        invalidation_price=None,
        invalidation_thesis=(
            "The thesis is invalidated if AI infrastructure demand stops "
            "translating into orders/backlog or if the market fully prices the "
            "multi-year grid demand path before estimates revise."
        ),
        provenance=TradeProvenance(),
    )


def build_stub_trade_for_candidate(
    candidate: Candidate,
    regime: RegimeState,
) -> TradeIdea:
    """Convenience helper used by fixture generation and tests."""

    fundamental = make_stub_fundamental_analysis(candidate)
    narrative = make_stub_narrative_analysis(candidate)
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )
    return construct_trade_idea(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
        conviction=conviction,
    )
