from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Optional
from pydantic import BaseModel, Field, conint


class ThemeScores(BaseModel):
    ai: conint(ge=-2, le=2)
    inflation: conint(ge=-2, le=2)
    liquidity: conint(ge=-2, le=2)
    credit: conint(ge=-2, le=2)
    consumer: conint(ge=-2, le=2)


class ChunkScore(BaseModel):
    tone: conint(ge=-3, le=3)
    uncertainty: conint(ge=0, le=3)
    themes: ThemeScores
    metadata: Optional[Dict] = Field(default_factory=dict)


class BaseScorer(ABC):
    @abstractmethod
    def score(self, text: str) -> ChunkScore:
        """Return a deterministic score for a text chunk."""
        raise NotImplementedError