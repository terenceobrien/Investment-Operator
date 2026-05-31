"""
Pydantic schemas for the agent system.

All schemas are frozen (immutable). Mutation attempts raise ValidationError.
Use `.model_copy(update={...})` to create modified versions.

Import everything from `common` here for convenience:
    from src.agent_system.schemas import Evidence, Falsifier, ConvictionRating
"""
from src.agent_system.schemas.common import (
    # Enums
    ConvictionRating,
    EvidenceSourceType,
    FalsifierObservable,
    FalsifierFrequency,
    FalsifierStatus,
    CatalystType,
    InefficiencyArchetype,
    # Base
    BaseSchema,
    # Evidence union and members
    Evidence,
    FREDEvidence,
    NewsEvidence,
    FilingEvidence,
    PriceEvidence,
    PositioningEvidence,
    DerivedEvidence,
    # Other domain types
    Falsifier,
    Catalyst,
    Conviction,
    AnalysisConviction,
    # Constrained number types
    UnitInterval,
    Score0to10,
    Score0to100,
    # Helpers
    archetype_from_taxonomy_id,
)
from src.agent_system.schemas.forward import (
    FedPathReading,
    ForwardContext,
    InflationExpectations,
    MarketEvent,
    PredictionMarketReading,
)
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    EdgeDecayHorizon,
    LayerWeights,
    RegimeDriver,
    RegimeHorizon,
    RegimeLayers,
    RegimeLayerScore,
    RegimeLayerStatus,
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
from src.agent_system.schemas.fundamental import (
    BusinessQuality,
    Crowdedness,
    Cyclicality,
    DifferMagnitude,
    EstimateRevisionTrend,
    EstimatesAndExpectations,
    Financials,
    FundamentalAnalysis,
    KeyMetric,
    Positioning,
    ShortInterestSnapshot,
)
from src.agent_system.schemas.fundamental_screen import (
    Archetype,
    FundamentalScreen,
    ScreenVerdict,
)
from src.agent_system.schemas.narrative import (
    CurrentNarrative,
    InefficiencyThesis,
    NarrativeAge,
    NarrativeAnalysis,
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
from src.agent_system.schemas.portfolio import (
    ActiveThesis,
    AlignmentSummary,
    AlternativePath,
    ConstraintResponse,
    ExposureBucket,
    FalsifierCheckResult,
    PortfolioDecision,
    PortfolioDecisionType,
    PortfolioState,
    Position,
    ThesisPerformance,
    ThesisStatus,
)
from src.agent_system.schemas.portfolio_plan import (
    PortfolioPlan,
    PortfolioTradeDecision,
    SizingAdjustment,
)

__all__ = [
    # common
    "ConvictionRating",
    "EvidenceSourceType",
    "FalsifierObservable",
    "FalsifierFrequency",
    "FalsifierStatus",
    "CatalystType",
    "InefficiencyArchetype",
    "BaseSchema",
    "Evidence",
    "FREDEvidence",
    "NewsEvidence",
    "FilingEvidence",
    "PriceEvidence",
    "PositioningEvidence",
    "DerivedEvidence",
    "Falsifier",
    "Catalyst",
    "Conviction",
    "AnalysisConviction",
    "UnitInterval",
    "Score0to10",
    "Score0to100",
    "archetype_from_taxonomy_id",
    # forward
    "FedPathReading",
    "ForwardContext",
    "InflationExpectations",
    "MarketEvent",
    "PredictionMarketReading",
    # regime
    "EdgeDecayHorizon",
    "LayerWeights",
    "RegimeDriver",
    "RegimeHorizon",
    "RegimeLayers",
    "RegimeLayerScore",
    "RegimeLayerStatus",
    "RegimeState",
    "ResearchPriority",
    "ClarificationRequest",
    # thematic
    "Candidate",
    "ExclusionRecord",
    "InstrumentType",
    "ResearchDepth",
    "ThematicMap",
    "VariantStrength",
    # fundamental
    "BusinessQuality",
    "Crowdedness",
    "Cyclicality",
    "DifferMagnitude",
    "EstimateRevisionTrend",
    "EstimatesAndExpectations",
    "Financials",
    "FundamentalAnalysis",
    "KeyMetric",
    "Positioning",
    "ShortInterestSnapshot",
    # fundamental screen
    "Archetype",
    "FundamentalScreen",
    "ScreenVerdict",
    # narrative
    "CurrentNarrative",
    "InefficiencyThesis",
    "NarrativeAge",
    "NarrativeAnalysis",
    # trade
    "AlternativeRejected",
    "Hedge",
    "HedgeType",
    "Instrument",
    "ProposedSizing",
    "ReviewCadence",
    "TradeDirection",
    "TradeExpression",
    "TradeIdea",
    "TradeProvenance",
    # portfolio
    "ActiveThesis",
    "AlignmentSummary",
    "AlternativePath",
    "ConstraintResponse",
    "ExposureBucket",
    "FalsifierCheckResult",
    "PortfolioDecision",
    "PortfolioDecisionType",
    "PortfolioState",
    "Position",
    "ThesisPerformance",
    "ThesisStatus",
    # portfolio plan
    "PortfolioPlan",
    "PortfolioTradeDecision",
    "SizingAdjustment",
]
