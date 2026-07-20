from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.agent_system.agents.evidence_extraction_agent import EvidenceExtractionResult
from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    strip_api_key_from_url,
)
from src.agent_system.research_sources.estimates import YFinanceEstimatesProvider
from src.agent_system.research_sources.finnhub import (
    FinnhubCompanyNewsProvider,
    FinnhubTranscriptProvider,
)
from src.agent_system.research_sources.fmp import FMPTranscriptProvider
from src.agent_system.research_sources.manual_sources import ManualSourceProvider
from src.agent_system.research_sources.newsapi import NewsAPICompanyNewsProvider
from src.agent_system.schemas.deep_fundamental import (
    EvidencePolarity,
    EvidenceConfidence,
    EvidenceSourceType,
    SingleNameEvidenceItem,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)
from src.agent_system.services.research_context_builder import (
    build_research_context_pack_async,
    dedupe_and_prioritize_source_documents,
)


def _options(**updates) -> ResearchSourceOptions:
    return ResearchSourceOptions(as_of_date=date(2026, 6, 29), **updates)


def _doc(
    *,
    source_type: EvidenceSourceType,
    purpose: SourceDocumentPurpose,
    source_name: str,
    url: str,
    text: str = "source text",
) -> SourceDocument:
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=purpose,
        ticker="TEST",
        source_name=source_name,
        title=source_name,
        source_date=date(2026, 6, 1),
        retrieved_at=datetime.now(timezone.utc),
        source_url=url,
        text=text,
        text_excerpt=text[:2500],
        metadata={"provider": source_name.split()[0]},
        source_confidence=EvidenceConfidence.HIGH,
    )


def test_strip_api_key_from_url_removes_sensitive_query_params():
    sanitized = strip_api_key_from_url(
        "https://example.test/path?symbol=MU&apikey=secret&token=also-secret"
    )

    assert sanitized == "https://example.test/path?symbol=MU"
    assert "secret" not in sanitized


def test_manual_source_provider_classifies_paths(tmp_path):
    transcript = tmp_path / "latest_transcript.txt"
    transcript.write_text("Operator: welcome to the earnings call.", encoding="utf-8")
    release = tmp_path / "latest_earnings_release.txt"
    release.write_text("Revenue and EPS results.", encoding="utf-8")

    provider = ManualSourceProvider()
    docs = asyncio.run(provider.fetch(
        ticker="MU",
        company_profile=None,
        options=_options(
            transcript_paths=[str(transcript)],
            earnings_release_paths=[str(release)],
            manual_source_paths=[str(tmp_path / "missing.txt")],
        ),
    ))

    assert docs[0].source_type == EvidenceSourceType.TRANSCRIPT
    assert docs[0].document_purpose == SourceDocumentPurpose.TRANSCRIPT
    assert docs[1].document_purpose == SourceDocumentPurpose.EARNINGS_RELEASE
    assert docs[2].retrieval_status == SourceRetrievalStatus.ERROR


def test_fmp_transcript_provider_missing_key(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    docs = asyncio.run(FMPTranscriptProvider().fetch(
        ticker="MU",
        company_profile=None,
        options=_options(),
    ))

    assert docs[0].retrieval_status == SourceRetrievalStatus.SKIPPED


def test_fmp_transcript_provider_success_and_empty(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")
    called_endpoints: list[str] = []

    def fake_get_json(endpoint, params):
        called_endpoints.append(endpoint)
        if endpoint == "/stable/earning-call-transcript-dates":
            return [{"symbol": "MU", "quarter": 3, "year": 2026, "date": "2026-06-25"}]
        return [{"content": "Management discussed HBM demand and gross margin."}]

    from src.agent_system.research_sources import fmp

    monkeypatch.setattr(fmp, "_fmp_get_json", fake_get_json)
    docs = asyncio.run(FMPTranscriptProvider().fetch(
        ticker="MU",
        company_profile=None,
        options=_options(),
    ))

    assert docs[0].retrieval_status == SourceRetrievalStatus.FOUND
    assert docs[0].document_purpose == SourceDocumentPurpose.TRANSCRIPT
    assert "HBM demand" in (docs[0].text or "")
    assert "test-key" not in (docs[0].source_url or "")
    assert docs[0].metadata["provider"] == "FMP"
    assert docs[0].metadata["ticker"] == "MU"
    assert docs[0].provider_status == "found"
    assert all("/api/v" not in endpoint for endpoint in called_endpoints)

    monkeypatch.setattr(fmp, "_fmp_get_json", lambda endpoint, params: [])
    empty = asyncio.run(FMPTranscriptProvider().fetch(
        ticker="MU",
        company_profile=None,
        options=_options(),
    ))
    assert empty[0].retrieval_status == SourceRetrievalStatus.NOT_FOUND
    assert "test-key" not in (empty[0].error_message or "")


def test_fmp_transcript_provider_status_mapping(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "test-key")

    from src.agent_system.research_sources import fmp

    monkeypatch.setattr(
        fmp,
        "_fmp_get_json",
        lambda endpoint, params: (_ for _ in ()).throw(
            fmp.FMPHTTPError(402, "Restricted Endpoint")
        ),
    )
    restricted = asyncio.run(FMPTranscriptProvider().fetch(
        ticker="MU",
        company_profile=None,
        options=_options(),
    ))
    assert restricted[0].retrieval_status == SourceRetrievalStatus.SKIPPED
    assert restricted[0].provider_status == "plan_restricted"

    monkeypatch.setattr(
        fmp,
        "_fmp_get_json",
        lambda endpoint, params: (_ for _ in ()).throw(
            fmp.FMPHTTPError(401, "Invalid API KEY")
        ),
    )
    invalid = asyncio.run(FMPTranscriptProvider().fetch(
        ticker="MU",
        company_profile=None,
        options=_options(),
    ))
    assert invalid[0].retrieval_status == SourceRetrievalStatus.ERROR
    assert invalid[0].provider_status == "invalid_key"


def test_finnhub_transcript_and_news_providers(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    def fake_get_json(endpoint, params):
        if endpoint == "/stock/transcripts/list":
            return {"transcripts": [{"id": "abc", "date": "2026-06-25", "quarter": 3, "year": 2026}]}
        if endpoint == "/stock/transcripts":
            return {"transcript": "CEO: demand is improving."}
        return [
            {
                "headline": "Company announces concrete event",
                "summary": "The company announced a concrete event.",
                "url": "https://news.test/item",
                "datetime": 1782604800,
                "source": "Reuters",
            },
            {
                "headline": "Company announces concrete event",
                "summary": "Duplicate",
                "url": "https://news.test/item",
                "datetime": 1782604800,
                "source": "Reuters",
            },
        ]

    from src.agent_system.research_sources import finnhub

    monkeypatch.setattr(finnhub, "_finnhub_get_json", fake_get_json)
    transcript = asyncio.run(FinnhubTranscriptProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))
    news = asyncio.run(FinnhubCompanyNewsProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))

    assert transcript[0].retrieval_status == SourceRetrievalStatus.FOUND
    assert transcript[0].document_purpose == SourceDocumentPurpose.TRANSCRIPT
    assert transcript[0].provider_status == "found"
    assert "test-key" not in (transcript[0].source_url or "")
    assert len(news) == 1
    assert news[0].source_type == EvidenceSourceType.NEWS
    assert news[0].metadata["snippet_only"] is True
    assert news[0].metadata["provider"] == "Finnhub"
    assert news[0].provider_status == "found"
    assert news[0].text
    assert news[0].source_confidence == EvidenceConfidence.MEDIUM


def test_finnhub_transcript_empty_result(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    from src.agent_system.research_sources import finnhub

    monkeypatch.setattr(finnhub, "_finnhub_get_json", lambda endpoint, params: [])
    transcript = asyncio.run(FinnhubTranscriptProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))

    assert transcript[0].retrieval_status == SourceRetrievalStatus.NOT_FOUND
    assert "test-key" not in (transcript[0].error_message or "")


def test_finnhub_transcript_plan_restricted(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "test-key")

    from src.agent_system.research_sources import finnhub

    monkeypatch.setattr(
        finnhub,
        "_finnhub_get_json",
        lambda endpoint, params: (_ for _ in ()).throw(
            finnhub.FinnhubHTTPError(403, "You don't have access to this resource.")
        ),
    )
    transcript = asyncio.run(FinnhubTranscriptProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))

    assert transcript[0].retrieval_status == SourceRetrievalStatus.SKIPPED
    assert transcript[0].provider_status == "plan_restricted"


def test_finnhub_missing_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    transcript = asyncio.run(FinnhubTranscriptProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))
    news = asyncio.run(FinnhubCompanyNewsProvider().fetch(
        ticker="JPM",
        company_profile=None,
        options=_options(),
    ))

    assert transcript[0].retrieval_status == SourceRetrievalStatus.SKIPPED
    assert news[0].retrieval_status == SourceRetrievalStatus.SKIPPED


def test_newsapi_provider(monkeypatch):
    monkeypatch.setenv("NEWS_API_KEY", "test-key")

    def fake_get_json(params, *, api_key):
        return {
            "articles": [
                {
                    "title": "Headline only",
                    "url": "https://news.test/headline",
                    "publishedAt": "2026-06-28T12:00:00Z",
                    "source": {"name": "Wire"},
                },
                {
                    "title": "Article with snippet",
                    "description": "Concrete company event.",
                    "content": "Snippet only.",
                    "url": "https://news.test/snippet",
                    "publishedAt": "2026-06-28T13:00:00Z",
                    "source": {"name": "Wire"},
                },
            ]
        }

    from src.agent_system.research_sources import newsapi

    monkeypatch.setattr(newsapi, "_newsapi_get_json", fake_get_json)
    docs = asyncio.run(NewsAPICompanyNewsProvider().fetch(
        ticker="AAPL",
        company_profile=SimpleNamespace(company_name="Apple Inc."),
        options=_options(max_news_items=5),
    ))

    assert len(docs) == 2
    assert docs[0].source_confidence == EvidenceConfidence.LOW
    assert docs[1].source_confidence == EvidenceConfidence.MEDIUM
    assert docs[0].metadata["snippet_only"] is True
    assert docs[1].metadata["snippet_only"] is True
    assert docs[0].metadata["provider"] == "NewsAPI"
    assert docs[0].provider_status == "found"
    assert docs[0].text
    assert "test-key" not in (docs[0].source_url or "")

    monkeypatch.delenv("NEWS_API_KEY", raising=False)
    skipped = asyncio.run(NewsAPICompanyNewsProvider().fetch(
        ticker="AAPL",
        company_profile=None,
        options=_options(),
    ))
    assert skipped[0].retrieval_status == SourceRetrievalStatus.SKIPPED


def test_yfinance_estimates_provider(monkeypatch):
    class FakeFrame:
        empty = False

        def tail(self, _count):
            return self

        def to_dict(self):
            return {"row": {"eps": 1.23}}

    class FakeTicker:
        recommendations_summary = FakeFrame()
        earnings_estimate = FakeFrame()
        revenue_estimate = None
        eps_trend = None
        eps_revisions = None
        upgrades_downgrades = None

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda ticker: FakeTicker()))
    docs = asyncio.run(YFinanceEstimatesProvider().fetch(
        ticker="AAPL",
        company_profile=None,
        options=_options(),
    ))

    assert docs[0].retrieval_status == SourceRetrievalStatus.FOUND
    assert docs[0].document_purpose == SourceDocumentPurpose.ESTIMATE
    assert docs[0].source_confidence == EvidenceConfidence.MEDIUM


def test_source_dedupe_priorities():
    manual = _doc(
        source_type=EvidenceSourceType.TRANSCRIPT,
        purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="Manual transcript",
        url="manual-transcript",
    )
    fmp = _doc(
        source_type=EvidenceSourceType.TRANSCRIPT,
        purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="FMP earnings transcript",
        url="fmp-transcript",
    )
    finnhub = _doc(
        source_type=EvidenceSourceType.TRANSCRIPT,
        purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="Finnhub earnings transcript",
        url="finnhub-transcript",
    )
    newsapi = _doc(
        source_type=EvidenceSourceType.NEWS,
        purpose=SourceDocumentPurpose.NEWS,
        source_name="NewsAPI",
        url="https://news.test/same",
    )
    finnhub_news = _doc(
        source_type=EvidenceSourceType.NEWS,
        purpose=SourceDocumentPurpose.NEWS,
        source_name="Finnhub company news",
        url="https://news.test/same",
    )

    selected = dedupe_and_prioritize_source_documents(
        [finnhub, fmp, manual, finnhub_news, newsapi],
        max_news_items=10,
    )

    assert manual in selected
    assert fmp not in selected
    assert finnhub not in selected
    assert newsapi in selected
    assert finnhub_news not in selected


def test_research_context_builder_runs_automatic_providers(monkeypatch):
    async def fake_fmp_fetch(self, **kwargs):
        return [_doc(
            source_type=EvidenceSourceType.TRANSCRIPT,
            purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="FMP earnings transcript",
            url="fmp-transcript",
        )]

    async def fake_finnhub_transcript_fetch(self, **kwargs):
        return [_doc(
            source_type=EvidenceSourceType.TRANSCRIPT,
            purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="Finnhub earnings transcript",
            url="finnhub-transcript",
        )]

    async def fake_newsapi_fetch(self, **kwargs):
        return [_doc(
            source_type=EvidenceSourceType.NEWS,
            purpose=SourceDocumentPurpose.NEWS,
            source_name="NewsAPI",
            url="https://news.test/same",
        )]

    async def fake_finnhub_news_fetch(self, **kwargs):
        return [_doc(
            source_type=EvidenceSourceType.NEWS,
            purpose=SourceDocumentPurpose.NEWS,
            source_name="Finnhub company news",
            url="https://news.test/same",
        )]

    async def fake_estimates_fetch(self, **kwargs):
        return [_doc(
            source_type=EvidenceSourceType.ESTIMATE,
            purpose=SourceDocumentPurpose.ESTIMATE,
            source_name="yfinance analyst estimates",
            url="yfinance-estimates",
        )]

    async def fake_extract_evidence_from_sources(**kwargs):
        items = [
            SingleNameEvidenceItem(
                source_type=doc.source_type,
                document_purpose=doc.document_purpose,
                ticker=kwargs["ticker"],
                source_url=doc.source_url,
                source_date=doc.source_date,
                title=doc.title,
                claim=f"{doc.source_name} evidence",
                polarity=EvidencePolarity.NEUTRAL,
            )
            for doc in kwargs["source_documents"]
        ]
        return EvidenceExtractionResult(
            ticker=kwargs["ticker"],
            source_count=len(kwargs["source_documents"]),
            evidence_items=items,
        )

    from src.agent_system.agents import evidence_extraction_agent
    from src.agent_system.research_sources import estimates, finnhub, fmp, newsapi

    monkeypatch.setattr(fmp.FMPTranscriptProvider, "fetch", fake_fmp_fetch)
    monkeypatch.setattr(finnhub.FinnhubTranscriptProvider, "fetch", fake_finnhub_transcript_fetch)
    monkeypatch.setattr(newsapi.NewsAPICompanyNewsProvider, "fetch", fake_newsapi_fetch)
    monkeypatch.setattr(finnhub.FinnhubCompanyNewsProvider, "fetch", fake_finnhub_news_fetch)
    monkeypatch.setattr(estimates.YFinanceEstimatesProvider, "fetch", fake_estimates_fetch)
    monkeypatch.setattr(evidence_extraction_agent, "extract_evidence_from_sources", fake_extract_evidence_from_sources)

    pack = asyncio.run(build_research_context_pack_async(
        ticker="TEST",
        include_earnings_release=False,
        include_other_8k=False,
        include_filing=False,
        include_peer_commentary=False,
        save=False,
    ))

    assert len(pack.transcript_evidence) == 1
    assert "FMP" in pack.transcript_evidence[0].claim
    assert len(pack.news_evidence) == 1
    assert "NewsAPI" in pack.news_evidence[0].claim
    assert len(pack.estimate_evidence) == 1
