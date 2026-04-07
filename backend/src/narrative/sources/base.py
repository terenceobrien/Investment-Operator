from __future__ import annotations
from typing import List, Optional, Dict
from abc import ABC, abstractmethod
from datetime import datetime
from pydantic import BaseModel, Field

class RawTextItem(BaseModel):
    id: str
    source: str
    published_at: datetime
    title: Optional[str] = None
    body: str
    url: Optional[str] = None
    tickers: Optional[List[str]] = None
    metadata: Dict = Field(default_factory=dict)

class BaseSource(ABC):
    @abstractmethod
    def fetch(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[RawTextItem]:
        """Fetch RawTextItem objects between optional start (inclusive) and end (exclusive)."""
        raise NotImplementedError