"""
Regime schemas — the macro agent's structured output.

These schemas wrap the existing regime_layers.py and regime_overlay.py output
in frozen Pydantic models, then add the new ResearchPriority type that is the
bridge from "what the world looks like" to "what to investigate."

Boundary contracts:
- RegimeLayerScore mirrors regime_layers.LayerScore field-for-field. A small
  adapter in this module (RegimeLayerScore.from_layer_score) converts at the
  boundary. The new schema is stricter (frozen, validated bounds) — call sites
  that mutate LayerScore objects need to refactor before adopting these.
- RegimeState wraps both the algorithmic layer output AND the curated overlay
  data (CURRENT_REGIME in regime_overlay.py). The two have different update
  cadences: layers refresh daily at close, the overlay is manually curated.
- ResearchPriority is new. Macro agents emit a list of these as the "research
  agenda" — themes worth investigating given the current regime, with edge
  hypotheses about why mispricing might exist.
"""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator, model_validator

from agent_system.schemas.common import (
    BaseSchema,
    Conviction,
    Evidence,
    Falsifier,
    Score0to10,
    Score0to100,
    UnitInterval,
)


# ─────────────────────────────────────────────────────────────────────────────
# Enums — closed vocabularies tied to existing Helix code
# ─────────────────────────────────────────────────────────────────────────────


class RegimeLayerStatus(str, Enum):
    """
    Plain-english direction for a single regime layer.

    Matches the string values emitted by regime_layers._status():
    score >= 6.5 -> "bullish", score <= 3.5 -> "bearish", else "neutral".
    """

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


class RegimeHorizon(str, Enum):
    """
    Horizon-specific weighting for the composite score.

    Matches the keys of regime_layers.WEIGHTS. Different horizons weight the
    five layers differently — a swing trader cares more about volatility and
    positioning; a long-horizon investor cares more about monetary and credit.
    """

    SWING = "swing"
    INVESTOR = "investor"
    DEFAULT = "default"


class EdgeDecayHorizon(str, Enum):
    """
    Expected time over which a research priority's edge would decay if real.

    Used by the construction agent to size ideas appropriately and by the
    scheduler to prioritize re-evaluation cadence.
    """

    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    QUARTERS = "quarters"


# ─────────────────────────────────────────────────────────────────────────────
# Per-layer score — mirror of regime_layers.LayerScore
# ─────────────────────────────────────────────────────────────────────────────


class RegimeLayerScore(BaseSchema):
    """
    Score and metadata for a single regime layer.

    Field names match regime_layers.LayerScore exactly so adaptation at the
    boundary is mechanical. `inputs` is the raw input dict (FRED values etc.);
    `signals` is the plain-english list of signals fired during scoring.

    Unlike the existing dataclass, this is frozen and bounds-checked.
    """

    score: Score0to10
    inputs: Dict[str, Optional[float]] = Field(default_factory=dict)
    signals: List[str] = Field(default_factory=list, max_length=20)
    status: RegimeLayerStatus
    data_quality: UnitInterval = Field(
        description="0–1, fraction of input slots that had data."
    )

    @classmethod
    def from_layer_score(cls, ls: Any) -> "RegimeLayerScore":
        """
        Adapter: convert a regime_layers.LayerScore dataclass to this schema.

        Tolerant of status values outside the enum (defaults to NEUTRAL) so
        legacy data doesn't break on ingest. Log a warning at the call site
        if you want to know when this happens.
        """
        try:
            status = RegimeLayerStatus(ls.status)
        except (ValueError, AttributeError):
            status = RegimeLayerStatus.NEUTRAL
        return cls(
            score=float(ls.score),
            inputs=dict(ls.inputs) if ls.inputs else {},
            signals=list(ls.signals) if ls.signals else [],
            status=status,
            data_quality=float(ls.data_quality),
        )


class RegimeLayers(BaseSchema):
    """
    The five-layer regime breakdown. Mirror of regime_layers.LayerScores.

    Field names match exactly: monetary, credit, volatility, breadth,
    positioning. The composite and derived fields live on RegimeState instead
    of being mixed in here, which keeps this object focused on the per-layer
    inputs and lets the top-level state own the synthesis.
    """

    monetary: RegimeLayerScore
    credit: RegimeLayerScore
    volatility: RegimeLayerScore
    breadth: RegimeLayerScore
    positioning: RegimeLayerScore


# ─────────────────────────────────────────────────────────────────────────────
# Layer weights and composite
# ─────────────────────────────────────────────────────────────────────────────


class LayerWeights(BaseSchema):
    """
    Per-layer weights for composite computation.

    Mirror of an entry in regime_layers.WEIGHTS. Sum should be ~1.0; validator
    enforces this with a small tolerance to allow for floating point.
    """

    monetary: UnitInterval
    credit: UnitInterval
    volatility: UnitInterval
    breadth: UnitInterval
    positioning: UnitInterval

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "LayerWeights":
        total = (
            self.monetary
            + self.credit
            + self.volatility
            + self.breadth
            + self.positioning
        )
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Layer weights must sum to ~1.0 (got {total:.4f})"
            )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Drivers and key narrative
# ─────────────────────────────────────────────────────────────────────────────


class RegimeDriver(BaseSchema):
    """
    A named driver of the current regime.

    Structured version of the items in regime_overlay.CURRENT_REGIME["key_drivers"].
    Each driver has a name, a directional status (free-text — these are
    sometimes phrased as "bearish for X / bullish for Y"), and an explanation.
    """

    name: str = Field(min_length=1, max_length=200)
    status: str = Field(
        min_length=1,
        max_length=300,
        description="Directional read, e.g. 'bearish for broad beta / bullish for energy'.",
    )
    explanation: str = Field(min_length=1, max_length=1000)


# ─────────────────────────────────────────────────────────────────────────────
# Research priority — the bridge from regime to investigation
# ─────────────────────────────────────────────────────────────────────────────


class ResearchPriority(BaseSchema):
    """
    A theme worth investigating, given the current regime.

    This is the macro agent's "research agenda" output — the link between
    "what the world looks like" and "what to investigate." The thematic agent
    consumes these and produces ranked candidate instruments.

    The `edge_hypothesis` field is the anti-helpfulness lever at this layer.
    A priority without an articulated edge hypothesis is rejected. The
    distinction matters: "energy is interesting because oil is high" is not
    an edge hypothesis — the market already sees oil. "Energy is interesting
    because the market is pricing the Hormuz risk premium as transient, but
    the structural supply response requires 18+ months of capex" is an edge
    hypothesis.
    """

    theme: str = Field(min_length=1, max_length=300)
    rationale: str = Field(
        min_length=1,
        max_length=2000,
        description="How this theme ties to current regime layers and drivers.",
    )
    edge_hypothesis: str = Field(
        min_length=30,
        max_length=2000,
        description=(
            "Why mispricing might exist here. Must articulate where the market "
            "is wrong, not just that the theme is relevant. Minimum 30 chars "
            "enforced to prevent agents emitting one-line placeholders."
        ),
    )
    sub_questions: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Specific questions for the thematic/single-name agents.",
    )
    priority_rank: int = Field(ge=1, le=5)
    expected_edge_decay: EdgeDecayHorizon
    supporting_evidence: List[Evidence] = Field(default_factory=list, max_length=20)


# ─────────────────────────────────────────────────────────────────────────────
# Regime state — top-level output of the macro agent
# ─────────────────────────────────────────────────────────────────────────────


class RegimeState(BaseSchema):
    """
    Top-level macro agent output for a given asof_date and horizon.

    Combines:
    - Algorithmic layer scores (from regime_layers.score_all_layers)
    - Horizon-weighted composite
    - Curated qualitative read (regime_id, label, drivers — from
      regime_overlay.CURRENT_REGIME when applicable)
    - Confidence and falsification logic
    - The new research_priorities list

    Two confidence fields:
    - `composite_confidence` mirrors regime_layers._composite_confidence
      output (0-100, based on layer agreement + data quality).
    - `regime_call_confidence` is the macro agent's overall confidence in
      the regime label (0-1). These are not the same number: high layer
      confidence with a contested narrative read still means the call is
      uncertain.
    """

    asof_date: str = Field(
        description="ISO date string for the regime snapshot (e.g. '2026-05-19')."
    )
    horizon: RegimeHorizon

    # Algorithmic side
    layers: RegimeLayers
    weights: LayerWeights
    composite: Score0to100
    layer_agreement: UnitInterval
    composite_confidence: Score0to100
    environment: str = Field(
        min_length=1,
        max_length=200,
        description="Algorithmic classification, e.g. 'Risk-On — Liquidity Driven'.",
    )
    environment_drivers: List[str] = Field(default_factory=list, max_length=10)

    # Curated qualitative side
    regime_id: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "Snake-case regime id, e.g. 'supply_shock_inflation'. Stable identifier "
            "across snapshots; the label and headline may evolve with the data."
        ),
    )
    regime_label: str = Field(
        min_length=1,
        max_length=300,
        description="Human-readable label, e.g. 'Supply-shock inflation / late-cycle tightening'.",
    )
    headline: str = Field(default="", max_length=1000)
    summary: str = Field(default="", max_length=3000)
    risk_summary: str = Field(default="", max_length=3000)

    key_drivers: List[RegimeDriver] = Field(default_factory=list, max_length=10)
    portfolio_implications: List[str] = Field(default_factory=list, max_length=10)
    best_positioned: List[str] = Field(default_factory=list, max_length=15)
    most_vulnerable: List[str] = Field(default_factory=list, max_length=15)

    # Confidence and falsification
    regime_call_confidence: UnitInterval = Field(
        description="Overall confidence in the regime label, 0–1."
    )
    falsifiers: List[Falsifier] = Field(default_factory=list, max_length=20)

    # The new piece — research agenda
    research_priorities: List[ResearchPriority] = Field(
        default_factory=list, max_length=10
    )

    @field_validator("asof_date")
    @classmethod
    def _validate_asof_date(cls, v: str) -> str:
        # Cheap format check; full datetime parsing happens at consumer side.
        if not (len(v) == 10 and v[4] == "-" and v[7] == "-"):
            raise ValueError(
                f"asof_date must be 'YYYY-MM-DD' format (got {v!r})"
            )
        return v