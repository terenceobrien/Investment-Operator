"""
Fundamental schemas — the single-name research agent's output for fundamentals
and positioning.

This is the heaviest schema in the system. The design enforces several
anti-confirmation disciplines structurally:

- `steelman_bear_case` and `bear_case_evidence` are mandatory non-empty fields.
  An analysis without a steelmanned bear case isn't research — it's a pitch.
- `what_bear_case_misses` defaults to the explicit string "nothing material",
  which downstream conviction rules treat as a cap on rating. Forcing the
  agent to affirmatively claim it has a counter prevents quiet skipping.
- `where_we_differ` is Optional[str] with None permitted. None means "we
  agree with consensus" — which downstream rules treat as a hard pass.
- `accounting_red_flags` is a list with no minimum length, but the agent has
  to emit the list at all. An empty list is itself a claim (no red flags
  found) that becomes auditable evidence.

The schema does NOT enforce specific financial metrics. Different industries
need different metrics (banks: NIM and CET1; software: NRR and Rule of 40;
energy: F&D costs and netbacks). The `key_metrics` list is open-ended; the
single-name agent is responsible for picking the right ones for the business.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import Field

from agent_system.schemas.common import (
    AnalysisConviction,
    BaseSchema,
    Evidence,
    Score0to10,
    UnitInterval,
)


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class Cyclicality(str, Enum):
    """High-level cyclicality of the business."""

    SECULAR = "secular"          # demand mostly independent of macro cycle
    CYCLICAL = "cyclical"        # demand swings with macro cycle
    HYBRID = "hybrid"            # mix of secular and cyclical drivers


class EstimateRevisionTrend(str, Enum):
    """Direction of consensus estimate revisions."""

    UPWARD = "upward"
    DOWNWARD = "downward"
    STABLE = "stable"
    DISPERSED = "dispersed"      # analysts disagree — no clear direction


class DifferMagnitude(str, Enum):
    """How far the agent's view differs from consensus."""

    IN_LINE = "in_line"
    MODEST = "modest"
    SIGNIFICANT = "significant"


class Crowdedness(str, Enum):
    """How crowded the position is among institutional holders."""

    UNCROWDED = "uncrowded"
    NORMAL = "normal"
    CROWDED = "crowded"
    EXTREME = "extreme"


# ─────────────────────────────────────────────────────────────────────────────
# Building blocks
# ─────────────────────────────────────────────────────────────────────────────


class BusinessQuality(BaseSchema):
    """
    Qualitative assessment of the business itself.

    `moat_evidence` must back up the moat_assessment claim. An agent that
    asserts a moat without evidence will fail validation if the evidence
    list is empty — but the schema allows empty here because some
    businesses genuinely have no moat ("commodity producer with no
    differentiation" is a legitimate moat_assessment).
    """

    summary: str = Field(min_length=20, max_length=2000)
    moat_assessment: str = Field(min_length=10, max_length=1000)
    moat_evidence: List[Evidence] = Field(default_factory=list, max_length=15)
    cyclicality: Cyclicality


class KeyMetric(BaseSchema):
    """
    A single quantitative metric describing the business.

    `vs_history` and `vs_peers` are required prose comparisons. A bare number
    isn't analysis — the relative position is. Both fields use plain English
    rather than structured percentile data because the comparison set is
    different per industry and the agent should articulate it.
    """

    metric: str = Field(min_length=1, max_length=100)
    value: float
    unit: str = Field(
        default="",
        max_length=50,
        description="e.g. '%', 'x', '$M', 'bps'. Optional — some metrics are dimensionless.",
    )
    vs_history: str = Field(min_length=5, max_length=500)
    vs_peers: str = Field(min_length=5, max_length=500)
    source: Evidence


class Financials(BaseSchema):
    """
    Quantitative profile of the business.

    `key_metrics` is open-ended (no required metrics) because the right
    metrics depend on the industry. `accounting_red_flags` is a list with
    no minimum — empty means "agent looked and found none," not "agent
    forgot to check." This is enforced by making the field non-defaultable
    in the agent prompt, not by the schema.
    """

    key_metrics: List[KeyMetric] = Field(default_factory=list, max_length=20)
    balance_sheet_quality: Score0to10
    cash_generation_quality: Score0to10
    accounting_red_flags: List[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Specific concerns found, empty list if none. The empty list is "
            "itself a claim that the agent looked and found nothing."
        ),
    )


class EstimatesAndExpectations(BaseSchema):
    """
    Where consensus is and where the agent differs.

    `where_we_differ` is Optional[str]. None is a meaningful value — it
    means "we agree with consensus." Downstream conviction rules treat
    None as a hard pass: if you can't articulate a variant view, you have
    no edge.

    `differ_magnitude` must be None when `where_we_differ` is None.
    `differ_evidence` must be non-empty if `where_we_differ` is not None.
    Both are enforced by the model validator below.
    """

    consensus_summary: str = Field(min_length=10, max_length=2000)
    revision_trend: EstimateRevisionTrend
    where_we_differ: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Variant view, or None if agreeing with consensus.",
    )
    differ_magnitude: Optional[DifferMagnitude] = None
    differ_evidence: List[Evidence] = Field(default_factory=list, max_length=15)

    def model_post_init(self, __context) -> None:
        # Cross-field validation: differ_magnitude and differ_evidence must
        # be consistent with where_we_differ. Run after individual field
        # validation so we have access to all fields.
        if self.where_we_differ is None:
            if self.differ_magnitude is not None:
                raise ValueError(
                    "differ_magnitude must be None when where_we_differ is None"
                )
            if self.differ_evidence:
                raise ValueError(
                    "differ_evidence must be empty when where_we_differ is None"
                )
        else:
            if self.differ_magnitude is None:
                raise ValueError(
                    "differ_magnitude is required when where_we_differ is set"
                )
            if not self.differ_evidence:
                raise ValueError(
                    "differ_evidence must be non-empty when where_we_differ is set"
                )


class ShortInterestSnapshot(BaseSchema):
    """Short interest with percentile vs history for context."""

    value_pct_float: UnitInterval = Field(
        description="Short interest as fraction of float, 0.0–1.0."
    )
    percentile_vs_history: UnitInterval = Field(
        description="Where current short interest sits in its historical distribution, 0.0–1.0."
    )
    source: Evidence


class Positioning(BaseSchema):
    """
    Institutional positioning and crowdedness signals.

    `options_skew_signal` is Optional because not all names have meaningful
    options markets. None means "not analyzed" or "no clear signal,"
    distinct from a present-but-neutral read.
    """

    institutional_positioning: str = Field(min_length=10, max_length=2000)
    short_interest: Optional[ShortInterestSnapshot] = None
    options_skew_signal: Optional[str] = Field(default=None, max_length=1000)
    crowdedness_assessment: Crowdedness


# ─────────────────────────────────────────────────────────────────────────────
# FundamentalAnalysis — top-level per-name output
# ─────────────────────────────────────────────────────────────────────────────


class FundamentalAnalysis(BaseSchema):
    """
    Single-name fundamental + positioning analysis.

    The thesis_statement should be falsifiable in one sentence. "CVX is a
    good company" is not falsifiable; "CVX will grow free cash flow per
    share by 15%+ over the next 12 months driven by Permian unit cost
    improvements" is.

    The anti-confirmation block (steelman_bear_case, bear_case_evidence,
    what_bear_case_misses) is the most important part of this schema. The
    schema cannot force an agent to do this well, but it can force the
    agent to *do it at all*, which is most of the battle.
    """

    ticker: str = Field(min_length=1, max_length=20)
    thesis_statement: str = Field(
        min_length=30,
        max_length=1000,
        description=(
            "One-sentence falsifiable thesis. Minimum 30 chars to prevent "
            "non-thesis placeholders like 'long CVX' or 'overweight'."
        ),
    )

    business_quality: BusinessQuality
    financials: Financials
    estimates_and_expectations: EstimatesAndExpectations
    positioning: Positioning

    # Anti-confirmation block — mandatory
    steelman_bear_case: str = Field(
        min_length=50,
        max_length=3000,
        description=(
            "The strongest argument AGAINST the thesis, stated in the bear's "
            "own terms. Minimum 50 chars enforced — short bear cases are "
            "evidence of insufficient engagement with the counter-argument."
        ),
    )
    bear_case_evidence: List[Evidence] = Field(
        min_length=1,
        max_length=15,
        description=(
            "Evidence supporting the bear case. Minimum 1 — at least one "
            "piece of cited evidence must support the steelman, or the "
            "steelman isn't real."
        ),
    )
    what_bear_case_misses: str = Field(
        default="nothing material",
        min_length=15,
        max_length=2000,
        description=(
            "What the agent thinks the bear case misses. The default value "
            "'nothing material' is intentional — it caps conviction at "
            "MODERATE in the rules engine. Forces the agent to affirmatively "
            "claim a counter rather than quietly skipping the field."
        ),
    )

    # Self-rated conviction
    conviction: AnalysisConviction