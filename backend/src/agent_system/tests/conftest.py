"""
Shared pytest fixtures for the agent_system test suite.

Pytest auto-discovers fixtures in conftest.py files. Anything defined here
is available to every test file in this directory (and subdirectories)
without needing imports.

Naming convention: fixtures that build a minimal valid instance of a schema
are named `<lowercase_schema_name>` (e.g. `research_priority`). Fixtures that
build helper utilities or factories are named with a `make_` prefix (e.g.
`make_priority` returns a callable that produces a new priority each call).

When to add a fixture here:
- The helper is used in more than one test file
- The helper builds a minimal valid instance that other tests can compose with
- The helper is stable enough that downstream tests can rely on its shape

When to keep a helper local to one test file:
- It's only used in one test file
- It exercises a specific edge case (then it belongs in the test, not as a fixture)
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[3]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.agent_system.schemas.common import (
    AnalysisConviction,
    ConvictionRating,
    DerivedEvidence,
    FREDEvidence,
    InefficiencyArchetype,
    NewsEvidence,
)
from src.agent_system.schemas.fundamental import (
    BusinessQuality,
    Crowdedness,
    Cyclicality,
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
    RegimeLayers,
    RegimeLayerScore,
    RegimeLayerStatus,
    ResearchPriority,
)


# ─────────────────────────────────────────────────────────────────────────────
# Mock dataclasses — for testing boundary adapters without importing the
# actual regime_layers module (keeps tests self-contained)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class MockLayerScore:
    """Mimics regime_layers.LayerScore shape for adapter testing."""

    score: float
    inputs: Dict[str, Optional[float]]
    signals: List[str]
    status: str
    data_quality: float


@pytest.fixture
def mock_layer_score_cls():
    """Returns the MockLayerScore class so tests can construct instances."""
    return MockLayerScore


# ─────────────────────────────────────────────────────────────────────────────
# Regime fixtures — minimal valid instances for composition
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def neutral_layer_score() -> RegimeLayerScore:
    """A minimal valid RegimeLayerScore with neutral status."""
    return RegimeLayerScore(
        score=5.0,
        inputs={},
        signals=[],
        status=RegimeLayerStatus.NEUTRAL,
        data_quality=1.0,
    )


@pytest.fixture
def regime_layers(neutral_layer_score: RegimeLayerScore) -> RegimeLayers:
    """A minimal valid RegimeLayers with all five layers neutral."""
    return RegimeLayers(
        monetary=neutral_layer_score,
        credit=neutral_layer_score,
        volatility=neutral_layer_score,
        breadth=neutral_layer_score,
        positioning=neutral_layer_score,
    )


@pytest.fixture
def default_weights() -> LayerWeights:
    """Mirrors regime_layers.WEIGHTS['default']."""
    return LayerWeights(
        monetary=0.20,
        credit=0.22,
        volatility=0.22,
        breadth=0.20,
        positioning=0.16,
    )


@pytest.fixture
def research_priority() -> ResearchPriority:
    """A minimal valid ResearchPriority that passes all field validators."""
    return ResearchPriority(
        theme="energy supply shock beneficiaries",
        rationale="Hormuz disruption + tight policy keeps oil bid",
        edge_hypothesis=(
            "Market is pricing the Hormuz risk premium as transient, but the "
            "structural supply response requires 18+ months of capex."
        ),
        priority_rank=1,
        expected_edge_decay=EdgeDecayHorizon.QUARTERS,
        supporting_evidence=[
            DerivedEvidence(
                claim="Hormuz disruption and tight policy support the priority",
                supports=True,
                computation="test fixture derived from regime narrative",
                upstream_claims=["test fixture: energy supply shock beneficiaries"],
            )
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Evidence fixtures — minimal valid instances
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fred_evidence() -> FREDEvidence:
    """A minimal FREDEvidence example."""
    return FREDEvidence(
        claim="10y yields broke above 4.5%",
        supports=True,
        series_id="DGS10",
        observation_date=datetime.now(timezone.utc),
        observation_value=4.55,
    )


@pytest.fixture
def news_evidence() -> NewsEvidence:
    """A minimal NewsEvidence example."""
    return NewsEvidence(
        claim="CVX guided to lower capex despite higher oil",
        supports=True,
        publisher="Reuters",
        title="Chevron trims 2026 capex guidance on cost discipline",
        url="https://reuters.com/example",
        published_at=datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Analysis conviction fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def strong_analysis_conviction() -> AnalysisConviction:
    """A STRONG self-rated conviction with all required fields."""
    return AnalysisConviction(
        rating=ConvictionRating.STRONG,
        justification=(
            "The variant view is well-supported by forward-curve data and "
            "the structural capex backdrop. Bear case is real but limited."
        ),
        primary_uncertainty=(
            "Hormuz could de-escalate faster than the supply response, "
            "compressing the window."
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Fundamental fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def fundamental_analysis(
    news_evidence: NewsEvidence,
    strong_analysis_conviction: AnalysisConviction,
) -> FundamentalAnalysis:
    """
    A minimal valid FundamentalAnalysis for CVX, with all required disciplines
    in place: thesis_statement, steelman bear case, bear case evidence,
    differing-from-consensus variant view.
    """
    return FundamentalAnalysis(
        ticker="CVX",
        thesis_statement=(
            "CVX will grow free cash flow per share by 15%+ over the next 12 "
            "months driven by Permian unit cost improvements and disciplined buybacks."
        ),
        business_quality=BusinessQuality(
            summary=(
                "Integrated major with a tier-1 Permian footprint, strong refining "
                "complex, and one of the best balance sheets in the sector."
            ),
            moat_assessment="Scale + low-cost Permian acreage + integrated downstream optionality.",
            cyclicality=Cyclicality.CYCLICAL,
        ),
        financials=Financials(
            balance_sheet_quality=8.5,
            cash_generation_quality=8.0,
            accounting_red_flags=[],  # empty = checked and found none
        ),
        estimates_and_expectations=EstimatesAndExpectations(
            consensus_summary="Consensus FCF/share growth ~8% on $75 WTI assumption.",
            revision_trend=EstimateRevisionTrend.STABLE,
            where_we_differ=(
                "We see 15%+ FCF/share growth driven by Permian unit cost "
                "improvements that consensus has not yet baked in."
            ),
            differ_magnitude="significant",  # type: ignore[arg-type]
            differ_evidence=[news_evidence],
        ),
        positioning=Positioning(
            institutional_positioning="Long-only sector funds modestly overweight; generalist funds underweight.",
            crowdedness_assessment=Crowdedness.NORMAL,
        ),
        steelman_bear_case=(
            "Oil mean-reverts to $65 on Hormuz de-escalation and Saudi/UAE adding "
            "capacity. Permian decline rates accelerate faster than capex discipline "
            "can offset, compressing FCF in 2027."
        ),
        bear_case_evidence=[news_evidence],
        what_bear_case_misses=(
            "The capex discipline is real and visible in Q3 guidance — bear case "
            "assumes a return to growth-mode spending that current management has "
            "explicitly rejected."
        ),
        conviction=strong_analysis_conviction,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Narrative fixture
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def narrative_analysis(
    strong_analysis_conviction: AnalysisConviction,
) -> NarrativeAnalysis:
    """A minimal valid NarrativeAnalysis for CVX."""
    return NarrativeAnalysis(
        ticker="CVX",
        current_narrative=CurrentNarrative(
            summary=(
                "Market sees CVX as a defensive energy play but is mispricing the "
                "duration of the Permian unit-cost advantage."
            ),
            dominant_archetype=InefficiencyArchetype(
                "narrative_fundamental_divergence"
            ),
            narrative_strength=6.5,
            narrative_age=NarrativeAge.ESTABLISHED,
        ),
        inefficiency_thesis=InefficiencyThesis(
            archetype=InefficiencyArchetype("narrative_fundamental_divergence"),
            description=(
                "The market views CVX as a generic E&P proxy, but its Permian "
                "cost structure and refining optionality create earnings durability "
                "that is not reflected in the multiple."
            ),
            why_it_persists=(
                "Generalist allocators avoid energy entirely; sector specialists "
                "are mandate-constrained from sizing up beyond benchmark weight."
            ),
            expected_resolution_path=(
                "Q4 results showing sustained unit cost improvement force "
                "estimate revisions upward."
            ),
            resolution_horizon=EdgeDecayHorizon.MONTHS,
        ),
        narrative_could_be_wrong_if=[
            "Consensus actually does reflect the Permian advantage and we're double-counting.",
            "Refining margins collapse, removing the integrated optionality narrative.",
        ],
        conviction=strong_analysis_conviction,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Trade fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def strong_combined_conviction() -> "Conviction":
    """A STRONG conviction from the rules engine — for accepted-trade tests."""
    from src.agent_system.schemas.common import Conviction

    return Conviction(
        rating=ConvictionRating.STRONG,
        rule_applied="rule_exceptional_requires_all_strong",
        weakest_link="none",
        reasoning=(
            "Fundamental, narrative, and regime alignment all rated STRONG. "
            "Promoted from all-strong combination."
        ),
    )


@pytest.fixture
def pass_combined_conviction() -> "Conviction":
    """A PASS conviction — for rejection tests."""
    from src.agent_system.schemas.common import Conviction

    return Conviction(
        rating=ConvictionRating.PASS,
        rule_applied="rule_missing_variant_view",
        weakest_link="fundamental",
        reasoning=(
            "FundamentalAnalysis.estimates_and_expectations.where_we_differ is "
            "None — agreeing with consensus is not a thesis."
        ),
    )


@pytest.fixture
def long_cvx_expression() -> "TradeExpression":
    """A minimal valid TradeExpression for long CVX."""
    from src.agent_system.schemas.trade import (
        Instrument,
        TradeDirection,
        TradeExpression,
    )
    from src.agent_system.schemas.thematic import InstrumentType

    return TradeExpression(
        primary_instrument=Instrument(
            ticker="CVX",
            instrument_type=InstrumentType.SINGLE_STOCK,
            direction=TradeDirection.LONG,
        ),
        rationale_for_instrument=(
            "Direct exposure to the Permian unit-cost thesis; cleaner expression "
            "than XLE (avoids smaller-cap noise) and cheaper than calls (long horizon)."
        ),
        entry_logic="Scale in over 3 sessions if price holds above the 50-DMA.",
        exit_target="20% gain or estimate revisions catch up to our view.",
        exit_stop="10% loss from average entry or thesis violation.",
    )


@pytest.fixture
def proposed_sizing_4pct() -> "ProposedSizing":
    """A minimal valid ProposedSizing at 4% NAV."""
    from src.agent_system.schemas.trade import ProposedSizing

    return ProposedSizing(
        base_size_pct=0.04,
        sizing_logic=(
            "4% reflects strong-conviction sizing without crowding out other "
            "energy exposure. Kelly-implied is higher but capped for diversification."
        ),
        kelly_implied=0.08,
        max_loss_estimate_pct=0.02,
    )


@pytest.fixture
def three_trade_falsifiers() -> List["Falsifier"]:
    """Three trade falsifiers — minimum required for an accepted trade."""
    from src.agent_system.schemas.common import (
        Falsifier,
        FalsifierFrequency,
        FalsifierObservable,
    )

    return [
        Falsifier(
            condition="WTI falls below $65 and stays for 10 sessions",
            observable_in=FalsifierObservable.PRICE_ACTION,
            check_frequency=FalsifierFrequency.DAILY,
        ),
        Falsifier(
            condition="CVX Q4 capex guide raised by >15% vs Q3",
            observable_in=FalsifierObservable.EARNINGS,
            check_frequency=FalsifierFrequency.EVENT_DRIVEN,
        ),
        Falsifier(
            condition="Refining crack spreads break below 5-year low",
            observable_in=FalsifierObservable.DATA_SERIES,
            check_frequency=FalsifierFrequency.DAILY,
        ),
    ]
