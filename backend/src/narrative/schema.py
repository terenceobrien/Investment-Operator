from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field

Stance = Literal["risk_on", "risk_off", "mixed", "unclear"]
RiskAppetite = Literal["high", "medium", "low", "unclear"]
Fragility = Literal["stable", "fragile", "very_fragile", "unclear"]
Positioning = Literal["clean", "crowded", "unclear"]


class EvidenceItem(BaseModel):
    channel: str
    source: str
    title: str
    url: Optional[str] = None


class DominantNarrative(BaseModel):
    # Keep structure open: title/stance/confidence + big freeform fields
    title: str
    stance: Stance = "unclear"
    confidence: int = Field(default=50, ge=0, le=100)

    why_now: str = Field(default="")
    # Freeform bullets encourage expressive synthesis without rambling
    takeaways: List[str] = Field(default_factory=list, max_length=12)
    key_catalysts: List[str] = Field(default_factory=list, max_length=12)

    tickers: List[str] = Field(default_factory=list, max_length=40)
    evidence: List[EvidenceItem] = Field(default_factory=list, max_length=12)

    what_would_change: List[str] = Field(default_factory=list, max_length=8)
    risks_to_watch: List[str] = Field(default_factory=list, max_length=8)


class MarketTone(BaseModel):
    # Not forcing a single answer
    risk_appetite: RiskAppetite = "unclear"
    fragility: Fragility = "unclear"
    positioning_guess: Positioning = "unclear"
    tone_notes: str = Field(default="")  # freeform


class Signals(BaseModel):
    # Intensity sliders remain useful for scoring
    headline_intensity: int = Field(default=50, ge=0, le=100)
    earnings_intensity: int = Field(default=50, ge=0, le=100)
    macro_intensity: int = Field(default=50, ge=0, le=100)
    social_intensity: int = Field(default=30, ge=0, le=100)


class ExecutiveBullets(BaseModel):
    """Three concise bullets the answer-first UI renders verbatim."""
    reality: str = Field(default="")
    story: str = Field(default="")
    price: str = Field(default="")


class ExecutiveSnapshot(BaseModel):
    """
    Top-level answer for the page. The LLM fills these directly so the
    frontend never has to parse them out of long text.

    Conservative defaults are returned when the LLM cannot determine a field
    with confidence (e.g. "Not specified", "Mixed/unclear") rather than
    fabricating.
    """
    regime_tone: str = Field(default="Not specified")
    primary_gap: str = Field(default="Not specified")
    primary_archetype: str = Field(default="Not specified")
    price_confirmation: str = Field(default="Mixed")
    confidence: Optional[float] = None
    executive_bullets: ExecutiveBullets = Field(default_factory=ExecutiveBullets)


class InefficiencyMapItem(BaseModel):
    """One concrete dislocation between reality, story, and price."""
    subject: str
    gap: str
    archetype: str
    archetype_id: Optional[str] = None
    confidence: Optional[float] = None
    evidence: Optional[str] = None
    falsifier: Optional[str] = None
    taxonomy_basis: Optional[str] = None
    underlying_gap_type: Optional[str] = None


class PriceSummary(BaseModel):
    """LLM-provided one-line reads of price behavior in context."""
    cross_asset: str = Field(default="")
    sector: str = Field(default="")
    timeframe: str = Field(default="")
    relationship: str = Field(default="")


class NarrativeStateV1(BaseModel):
    asof_utc: str

    # Allow 0–6 narratives; some days are “no dominant story”
    dominant_narratives: List[DominantNarrative] = Field(default_factory=list, max_length=6)

    # Add explicitly open-ended sections
    one_paragraph_summary: str = Field(default="")
    raw_takeaways: List[str] = Field(default_factory=list, max_length=15)
    counter_narratives: List[str] = Field(default_factory=list, max_length=8)
    unknowns: List[str] = Field(default_factory=list, max_length=10)

    market_tone: MarketTone = Field(default_factory=MarketTone)
    signals: Signals = Field(default_factory=Signals)

    # ── Explicit answer-first fields (added in prompt v3) ──
    # Replaces frontend heuristics. Older snapshots without these fields
    # remain valid because every nested field has a default.
    executive_snapshot: ExecutiveSnapshot = Field(default_factory=ExecutiveSnapshot)
    inefficiency_map: List[InefficiencyMapItem] = Field(default_factory=list, max_length=6)
    price_summary: PriceSummary = Field(default_factory=PriceSummary)
