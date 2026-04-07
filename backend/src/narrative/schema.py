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
