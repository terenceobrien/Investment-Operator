from __future__ import annotations

import asyncio
from datetime import date

from src.agent_system.agents.evidence_extraction_agent import EvidenceExtractionResult
from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidencePolarity,
    EvidenceSourceType,
    SingleNameEvidenceItem,
    SingleNameResearchContextPack,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)
from src.agent_system.services.research_context_builder import (
    _apply_source_document_purpose,
    bucket_evidence_items,
    build_research_context_pack_async,
    dedupe_evidence_items,
    dedupe_and_prioritize_source_documents,
    find_source_for_evidence_item,
)
from src.agent_system.research_sources.sec_filings import (
    classify_8k_exhibit_document,
)
from src.agent_system.storage import repository


def _item(
    claim: str,
    source_type: EvidenceSourceType = EvidenceSourceType.OTHER,
    document_purpose: SourceDocumentPurpose | None = None,
):
    return SingleNameEvidenceItem(
        source_type=source_type,
        document_purpose=document_purpose,
        ticker="TEST",
        claim=claim,
        summary="Evidence summary.",
        polarity=EvidencePolarity.SUPPORTS,
        relevance_score=0.8,
        related_topics=["guidance", "segment"],
        related_metrics=["orders"],
        evidence_tags=["management guidance", "segment KPI"],
    )


def _source(
    *,
    accession_number: str = "0000000000-26-000001",
    source_url: str = "https://sec.test/ex991.htm",
    title: str = "8-K exhibit: ex991.htm",
    source_type: EvidenceSourceType = EvidenceSourceType.SEC_8K_EXHIBIT,
    document_purpose: SourceDocumentPurpose = SourceDocumentPurpose.OTHER,
    source_name: str = "Source",
    metadata: dict | None = None,
) -> SourceDocument:
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=document_purpose,
        provider_status="found",
        ticker="TEST",
        source_name=source_name,
        title=title,
        source_date=date(2026, 6, 24),
        source_url=source_url,
        accession_number=accession_number,
        form_type="8-K" if source_type == EvidenceSourceType.SEC_8K_EXHIBIT else None,
        exhibit_type="99.1" if "99" in title or "99" in source_url else None,
        text="Source text.",
        text_excerpt="Source text.",
        metadata=metadata or {},
    )


def test_research_context_pack_schema_validates():
    pack = SingleNameResearchContextPack(
        ticker="TEST",
        as_of_date=date(2026, 6, 28),
        bullish_evidence=[_item("Orders improved.")],
        evidence_item_count=1,
    )

    assert pack.ticker == "TEST"
    assert pack.bullish_evidence[0].claim == "Orders improved."


def test_dedupe_and_bucket_evidence_items():
    items = [
        _item(
            "Orders improved.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.EARNINGS_RELEASE,
        ),
        _item(
            "Orders improved.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.EARNINGS_RELEASE,
        ),
        _item(
            "Credit costs worsened.",
            EvidenceSourceType.FILING,
            SourceDocumentPurpose.QUARTERLY_FILING,
        ).model_copy(
            update={
                "polarity": EvidencePolarity.CHALLENGES,
                "related_topics": ["credit"],
                "related_metrics": ["credit costs"],
                "evidence_tags": ["risk commentary"],
            }
        ),
    ]

    deduped = dedupe_evidence_items(items)
    buckets = bucket_evidence_items(deduped)

    assert len(deduped) == 2
    assert len(buckets["earnings_release_evidence"]) == 1
    assert len(buckets["filing_evidence"]) == 1
    assert len(buckets["management_guidance"]) == 1
    assert len(buckets["segment_kpis"]) == 1
    assert len(buckets["bullish_evidence"]) == 1
    assert len(buckets["bearish_evidence"]) == 1


def test_bucket_evidence_routes_sec_8k_by_document_purpose():
    items = [
        _item(
            "Transaction should create synergies.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.STRATEGIC_TRANSACTION,
        ),
        _item(
            "Stress capital buffer changed.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.STRESS_TEST,
        ),
        _item(
            "Capital ratios remain above requirements.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.REGULATORY_CAPITAL,
        ),
        _item(
            "Debt offering completed.",
            EvidenceSourceType.SEC_8K_EXHIBIT,
            SourceDocumentPurpose.OTHER,
        ),
    ]

    buckets = bucket_evidence_items(items)

    assert len(buckets["earnings_release_evidence"]) == 0
    assert len(buckets["strategic_transaction_evidence"]) == 1
    assert len(buckets["stress_test_evidence"]) == 1
    assert len(buckets["regulatory_capital_evidence"]) == 1
    assert len(buckets["other_sec_8k_evidence"]) == 1


def test_bucket_estimate_with_null_document_purpose():
    buckets = bucket_evidence_items([
        _item("Analyst estimates were revised higher.", EvidenceSourceType.ESTIMATE)
    ])

    assert len(buckets["estimate_evidence"]) == 1


def test_document_purpose_propagates_to_evidence_items():
    source = _source(document_purpose=SourceDocumentPurpose.STRATEGIC_TRANSACTION)
    item = _item(
        "RMT transaction should reshape the portfolio.",
        EvidenceSourceType.SEC_8K_EXHIBIT,
    ).model_copy(
        update={
            "source_url": source.source_url,
            "accession_number": source.accession_number,
            "document_purpose": None,
        }
    )

    matched = find_source_for_evidence_item(item, [source])
    repaired = _apply_source_document_purpose([item], [source])[0]

    assert matched == source
    assert repaired.document_purpose == SourceDocumentPurpose.STRATEGIC_TRANSACTION
    assert "document_purpose:strategic_transaction" in repaired.evidence_tags


def test_dedupe_prefers_classified_exhibit_over_txt():
    accession = "0000000000-26-000002"
    txt = _source(
        accession_number=accession,
        source_url="https://sec.test/full-submission.txt",
        title="8-K exhibit: full-submission.txt",
        document_purpose=SourceDocumentPurpose.OTHER,
    )
    index = _source(
        accession_number=accession,
        source_url="https://sec.test/index.html",
        title="8-K exhibit: index.html",
        document_purpose=SourceDocumentPurpose.OTHER,
    )
    exhibit = _source(
        accession_number=accession,
        source_url="https://sec.test/ex991.htm",
        title="8-K exhibit: ex991.htm",
        document_purpose=SourceDocumentPurpose.STRATEGIC_TRANSACTION,
    )

    selected = dedupe_and_prioritize_source_documents([txt, index, exhibit])

    assert selected == [exhibit]


def test_builder_with_manual_source_and_fake_extraction(monkeypatch, tmp_path):
    source_path = tmp_path / "manual.txt"
    source_path.write_text("Management said orders improved.", encoding="utf-8")

    async def fake_extract_evidence_from_sources(**kwargs):
        return EvidenceExtractionResult(
            ticker=kwargs["ticker"],
            source_count=len(kwargs["source_documents"]),
            evidence_items=[_item("Orders improved.", EvidenceSourceType.OTHER)],
        )

    from src.agent_system.agents import evidence_extraction_agent

    monkeypatch.setattr(
        evidence_extraction_agent,
        "extract_evidence_from_sources",
        fake_extract_evidence_from_sources,
    )

    pack = asyncio.run(
        build_research_context_pack_async(
            ticker="TEST",
            include_earnings_release=False,
            include_filing=False,
            include_transcript=False,
            include_news=False,
            include_estimates=False,
            include_peer_commentary=False,
            manual_source_paths=[source_path],
            save=False,
        )
    )

    assert pack.raw_source_count == 1
    assert pack.evidence_item_count == 1
    assert pack.bullish_evidence[0].claim == "Orders improved."


def test_builder_falls_back_to_news_and_estimate_evidence(monkeypatch):
    async def fake_newsapi_fetch(self, **kwargs):
        return [
            SourceDocument(
                source_type=EvidenceSourceType.NEWS,
                retrieval_status=SourceRetrievalStatus.FOUND,
                document_purpose=SourceDocumentPurpose.NEWS,
                provider_status="found",
                ticker="TEST",
                source_name="NewsAPI",
                title="Test company announces concrete event",
                source_date=date(2026, 6, 28),
                source_url="https://news.test/test-company-event",
                text="Test company announces concrete event.\nSnippet details.",
                text_excerpt="Snippet details.",
                source_confidence=EvidenceConfidence.MEDIUM,
                metadata={"provider": "NewsAPI", "provider_status": "found"},
            )
        ]

    async def fake_estimates_fetch(self, **kwargs):
        return [
            SourceDocument(
                source_type=EvidenceSourceType.ESTIMATE,
                retrieval_status=SourceRetrievalStatus.FOUND,
                document_purpose=SourceDocumentPurpose.ESTIMATE,
                provider_status="found",
                ticker="TEST",
                source_name="yfinance analyst estimates",
                title="Analyst estimate summary",
                text="yfinance analyst estimate context is available.",
                text_excerpt="yfinance analyst estimate context is available.",
                source_confidence=EvidenceConfidence.MEDIUM,
                metadata={
                    "provider": "yfinance",
                    "provider_status": "found",
                    "eps_revisions": {"upLast30days": 3, "downLast30days": 1},
                    "recommendations_summary": {"buy": 10, "hold": 4},
                },
            )
        ]

    async def fake_empty_extract(**kwargs):
        return EvidenceExtractionResult(
            ticker=kwargs["ticker"],
            source_count=len(kwargs["source_documents"]),
            evidence_items=[],
        )

    from src.agent_system.agents import evidence_extraction_agent
    from src.agent_system.research_sources import estimates, newsapi

    monkeypatch.setattr(newsapi.NewsAPICompanyNewsProvider, "fetch", fake_newsapi_fetch)
    monkeypatch.setattr(estimates.YFinanceEstimatesProvider, "fetch", fake_estimates_fetch)
    monkeypatch.setattr(
        evidence_extraction_agent,
        "extract_evidence_from_sources",
        fake_empty_extract,
    )

    pack = asyncio.run(
        build_research_context_pack_async(
            ticker="TEST",
            include_earnings_release=False,
            include_other_8k=False,
            include_filing=False,
            include_transcript=False,
            include_news=True,
            include_estimates=True,
            include_peer_commentary=False,
            max_news_items=10,
            save=False,
        )
    )

    assert len(pack.news_evidence) == 1
    assert len(pack.estimate_evidence) >= 1
    assert "deterministic_fallback" in pack.news_evidence[0].evidence_tags
    assert "deterministic_fallback" in pack.estimate_evidence[0].evidence_tags
    assert "news:newsapi_found=1" in (pack.source_coverage_summary or "")
    assert "news:newsapi_selected=1" in (pack.source_coverage_summary or "")
    assert "estimates:yfinance_found=1" in (pack.source_coverage_summary or "")
    assert "estimates:yfinance_selected=1" in (pack.source_coverage_summary or "")
    assert pack.extraction_source_summary


def test_classify_8k_exhibit_distinguishes_purposes():
    earnings = classify_8k_exhibit_document(
        title="exhibit 99.1 fiscal Q3 financial results",
        source_url="https://sec.test/ex991.htm",
        text_excerpt=(
            "Revenue increased, gross margin expanded, operating income rose, "
            "net income improved, diluted earnings per share increased, cash "
            "flow was strong, and guidance includes business outlook."
        ),
        form_items=["2.02", "9.01"],
        exhibit_type="99.1",
    )
    transaction = classify_8k_exhibit_document(
        title="press release reverse morris trust transaction",
        source_url="https://sec.test/ex991.htm",
        text_excerpt=(
            "The company entered a definitive agreement for a Reverse Morris "
            "Trust transaction with closing conditions, regulatory clearances, "
            "enterprise value, purchase price, and expected synergies."
        ),
        form_items=["9.01"],
        exhibit_type="99.1",
    )
    stress = classify_8k_exhibit_document(
        title="DFAST stress test results",
        source_url="https://sec.test/ex991.htm",
        text_excerpt=(
            "The Federal Reserve stress test includes DFAST, stress capital "
            "buffer, CET1, CCAR, severely adverse scenario, projected minimum "
            "capital ratios, and risk-weighted assets."
        ),
        form_items=["7.01", "9.01"],
        exhibit_type="99.1",
    )

    assert earnings[0] == SourceDocumentPurpose.EARNINGS_RELEASE
    assert transaction[0] == SourceDocumentPurpose.STRATEGIC_TRANSACTION
    assert stress[0] == SourceDocumentPurpose.STRESS_TEST


def test_repository_save_and_load_research_context(monkeypatch, tmp_path):
    monkeypatch.setattr(repository, "RESEARCH_CONTEXT_DIR", tmp_path)
    pack = SingleNameResearchContextPack(
        ticker="TEST",
        as_of_date=date(2026, 6, 28),
    )

    path = repository.save_research_context_pack(pack)
    loaded = repository.load_research_context_pack("TEST", "2026-06-28")
    latest = repository.load_latest_research_context_pack("TEST")

    assert path.exists()
    assert loaded is not None
    assert latest is not None
    assert loaded.ticker == "TEST"
