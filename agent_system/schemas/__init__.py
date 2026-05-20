"""
Pydantic schemas for the agent system.

All schemas are frozen (immutable). Mutation attempts raise ValidationError.
Use `.model_copy(update={...})` to create modified versions.

Import everything from `common` here for convenience:
    from agent_system.schemas import Evidence, Falsifier, ConvictionRating
"""
from agent_system.schemas.common import (
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
from agent_system.schemas.regime import (
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
from agent_system.schemas.thematic import (
    Candidate,
    ExclusionRecord,
    InstrumentType,
    ResearchDepth,
    ThematicMap,
    VariantStrength,
)
from agent_system.schemas.fundamental import (
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
from agent_system.schemas.narrative import (
    CurrentNarrative,
    InefficiencyThesis,
    NarrativeAge,
    NarrativeAnalysis,
)
from agent_system.schemas.trade import (
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
from agent_system.schemas.portfolio import (
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
]