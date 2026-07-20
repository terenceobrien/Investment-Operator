"""Source retrieval adapters for single-name research context packs."""

from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    ResearchSourceProvider,
)
from src.agent_system.research_sources.estimates import YFinanceEstimatesProvider
from src.agent_system.research_sources.finnhub import (
    FinnhubCompanyNewsProvider,
    FinnhubTranscriptProvider,
)
from src.agent_system.research_sources.fmp import FMPTranscriptProvider
from src.agent_system.research_sources.manual_sources import ManualSourceProvider
from src.agent_system.research_sources.newsapi import NewsAPICompanyNewsProvider


__all__ = [
    "ResearchSourceOptions",
    "ResearchSourceProvider",
    "ManualSourceProvider",
    "FMPTranscriptProvider",
    "FinnhubTranscriptProvider",
    "NewsAPICompanyNewsProvider",
    "FinnhubCompanyNewsProvider",
    "YFinanceEstimatesProvider",
]
