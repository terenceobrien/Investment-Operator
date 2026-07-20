"""Build source-backed research context packs for single-name underwriting."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    sanitize_provider_message,
)
from src.agent_system.research_sources.config import (
    DEFAULT_MAX_TRANSCRIPTS,
    DEFAULT_MAX_NEWS_ITEMS,
    DEFAULT_NEWS_LOOKBACK_DAYS,
)
from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    EvidencePolarity,
    EvidenceSourceType,
    SingleNameEvidenceItem,
    SingleNameResearchContextPack,
    SourceCoverageItem,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


async def build_research_context_pack_async(
    *,
    ticker: str,
    as_of_date: date | None = None,
    company_profile: CompanyProfile | None = None,
    include_earnings_release: bool = True,
    include_filing: bool = True,
    include_transcript: bool = True,
    include_news: bool = True,
    include_estimates: bool = True,
    include_peer_commentary: bool = True,
    include_other_8k: bool = True,
    transcript_path: str | Path | None = None,
    transcript_paths: list[str | Path] | None = None,
    manual_source_paths: list[str | Path] | None = None,
    manual_source_urls: list[str] | None = None,
    earnings_release_paths: list[str | Path] | None = None,
    news_source_paths: list[str | Path] | None = None,
    news_days: int | None = DEFAULT_NEWS_LOOKBACK_DAYS,
    news_lookback_days: int | None = None,
    max_news_items: int = DEFAULT_MAX_NEWS_ITEMS,
    max_peer_tickers: int = 3,
    max_8k_filings: int = 10,
    save: bool = True,
) -> SingleNameResearchContextPack:
    """Build and optionally persist a SingleNameResearchContextPack."""

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")
    pack_date = as_of_date or date.today()
    source_documents: list[SourceDocument] = []
    data_gaps: list[str] = []
    warnings: list[str] = []

    if include_earnings_release:
        from src.agent_system.research_sources.sec_filings import (
            find_latest_8k_earnings_release,
        )
        from src.agent_system.research_sources.company_ir import (
            find_company_ir_source,
        )

        earnings_doc = _safe_source(find_latest_8k_earnings_release, clean_ticker)
        source_documents.append(earnings_doc)
        if (
            earnings_doc.retrieval_status != SourceRetrievalStatus.FOUND
            or earnings_doc.document_purpose != SourceDocumentPurpose.EARNINGS_RELEASE
        ):
            data_gaps.append("Earnings release not confidently retrieved via SEC 8-K exhibit.")
            source_documents.append(find_company_ir_source(clean_ticker))

    if include_other_8k:
        from src.agent_system.research_sources.sec_filings import (
            find_recent_8k_exhibits,
        )

        existing_keys = {_source_key(doc) for doc in source_documents}
        docs = find_recent_8k_exhibits(
            clean_ticker,
            max_filings=max_8k_filings,
            max_documents=30,
        )
        other_docs = [
            doc for doc in docs
            if _source_key(doc) not in existing_keys
            and (
                doc.document_purpose
                in {
                    SourceDocumentPurpose.STRATEGIC_TRANSACTION,
                    SourceDocumentPurpose.STRESS_TEST,
                    SourceDocumentPurpose.REGULATORY_CAPITAL,
                    SourceDocumentPurpose.INVESTOR_PRESENTATION,
                    SourceDocumentPurpose.OTHER,
                }
            )
        ]
        source_documents.extend(other_docs)

    if include_filing:
        from src.agent_system.research_sources.sec_filings import find_latest_10q_or_10k

        source_documents.append(_safe_source(find_latest_10q_or_10k, clean_ticker))
        if source_documents[-1].retrieval_status != SourceRetrievalStatus.FOUND:
            data_gaps.append("Latest 10-Q/10-K filing could not be retrieved from SEC.")

    provider_docs = await _fetch_provider_documents(
        ticker=clean_ticker,
        company_profile=company_profile,
        as_of_date=pack_date,
        include_transcript=include_transcript,
        include_news=include_news,
        include_estimates=include_estimates,
        transcript_path=transcript_path,
        transcript_paths=transcript_paths,
        manual_source_paths=manual_source_paths,
        manual_source_urls=manual_source_urls,
        earnings_release_paths=earnings_release_paths,
        news_source_paths=news_source_paths,
        news_days=news_days,
        news_lookback_days=news_lookback_days,
        max_news_items=max_news_items,
    )
    source_documents.extend(provider_docs)

    if include_peer_commentary:
        from src.agent_system.research_sources.peer_commentary import (
            fetch_peer_commentary_sources,
        )

        peer_tickers = [
            peer.ticker
            for peer in (company_profile.peer_group if company_profile else [])
            if peer.ticker
        ]
        docs = fetch_peer_commentary_sources(
            clean_ticker,
            peer_tickers,
            max_peers=max_peer_tickers,
        )
        source_documents.extend(docs)
        if not any(doc.retrieval_status == SourceRetrievalStatus.FOUND for doc in docs):
            data_gaps.append("Peer commentary retrieval skipped or unavailable in v1.")

    found_sources = [
        doc for doc in source_documents
        if doc.retrieval_status == SourceRetrievalStatus.FOUND
    ]
    extraction_sources = dedupe_and_prioritize_source_documents(
        found_sources,
        max_news_items=max_news_items,
    )
    found_news_sources = [
        source for source in found_sources
        if source.source_type == EvidenceSourceType.NEWS
    ]
    selected_news_sources = [
        source for source in extraction_sources
        if source.source_type == EvidenceSourceType.NEWS
    ]
    found_estimate_sources = [
        source for source in found_sources
        if source.source_type == EvidenceSourceType.ESTIMATE
    ]
    selected_estimate_sources = [
        source for source in extraction_sources
        if source.source_type == EvidenceSourceType.ESTIMATE
    ]
    if found_news_sources and not selected_news_sources:
        warnings.append("News documents found but none selected for extraction.")
    if found_estimate_sources and not selected_estimate_sources:
        warnings.append("Estimate document found but not selected for extraction.")
    dropped_source_count = len(found_sources) - len(extraction_sources)
    if dropped_source_count > 0:
        warnings.append(
            f"Dropped {dropped_source_count} duplicate or lower-quality source "
            "documents before evidence extraction."
        )
    evidence_items: list[SingleNameEvidenceItem] = []
    extraction_gaps: list[str] = []
    extraction_warnings: list[str] = []
    if extraction_sources:
        try:
            from src.agent_system.agents.evidence_extraction_agent import (
                extract_evidence_from_sources,
            )

            result = await extract_evidence_from_sources(
                ticker=clean_ticker,
                source_documents=extraction_sources,
            )
            evidence_items = _apply_source_document_purpose(
                result.evidence_items,
                extraction_sources,
            )
            extraction_gaps = result.data_gaps
            extraction_warnings = result.warnings
        except Exception as exc:
            warnings.append(f"Evidence extraction failed: {exc}")

    evidence_items = dedupe_evidence_items(evidence_items)
    buckets = bucket_evidence_items(evidence_items)
    if selected_news_sources and not buckets["news_evidence"]:
        from src.agent_system.services.news_evidence_builder import (
            build_news_evidence_from_source_documents,
        )

        fallback_news = build_news_evidence_from_source_documents(
            clean_ticker,
            selected_news_sources,
            max_items=max_news_items,
        )
        if fallback_news:
            warnings.append(
                "Evidence extractor returned no news evidence; used deterministic "
                "headline/snippet fallback."
            )
            evidence_items.extend(fallback_news)
    if selected_estimate_sources and not buckets["estimate_evidence"]:
        from src.agent_system.services.estimate_evidence_builder import (
            build_estimate_evidence_from_source_document,
        )

        fallback_estimates = build_estimate_evidence_from_source_document(
            clean_ticker,
            selected_estimate_sources[0],
        )
        if fallback_estimates:
            warnings.append(
                "Evidence extractor returned no estimate evidence; used deterministic "
                "estimate fallback."
            )
            evidence_items.extend(fallback_estimates)
    evidence_items = dedupe_evidence_items(evidence_items)
    buckets = bucket_evidence_items(evidence_items)
    source_coverage = [_coverage_from_source(doc) for doc in source_documents]
    pack = SingleNameResearchContextPack(
        ticker=clean_ticker,
        as_of_date=pack_date,
        source_coverage=source_coverage,
        source_coverage_summary=_coverage_summary(
            source_coverage,
            selected_sources=extraction_sources,
            extraction_selected_count=len(extraction_sources),
            duplicate_dropped_count=dropped_source_count,
        ),
        extraction_source_summary=_extraction_source_summary(extraction_sources),
        earnings_release_evidence=buckets["earnings_release_evidence"],
        filing_evidence=buckets["filing_evidence"],
        transcript_evidence=buckets["transcript_evidence"],
        news_evidence=buckets["news_evidence"],
        estimate_evidence=buckets["estimate_evidence"],
        peer_commentary_evidence=buckets["peer_commentary_evidence"],
        strategic_transaction_evidence=buckets["strategic_transaction_evidence"],
        regulatory_capital_evidence=buckets["regulatory_capital_evidence"],
        stress_test_evidence=buckets["stress_test_evidence"],
        investor_presentation_evidence=buckets["investor_presentation_evidence"],
        other_sec_8k_evidence=buckets["other_sec_8k_evidence"],
        management_guidance=buckets["management_guidance"],
        segment_kpis=buckets["segment_kpis"],
        consensus_narrative=buckets["consensus_narrative"],
        bullish_evidence=buckets["bullish_evidence"],
        bearish_evidence=buckets["bearish_evidence"],
        mixed_evidence=buckets["mixed_evidence"],
        unresolved_questions=_dedupe_strings(extraction_gaps),
        data_gaps=_dedupe_strings(data_gaps + extraction_gaps),
        warnings=_dedupe_strings(warnings + extraction_warnings),
        raw_source_count=len(source_documents),
        evidence_item_count=len(evidence_items),
    )

    if save:
        from src.agent_system.storage.repository import save_research_context_pack

        save_research_context_pack(pack)
    return pack


async def _fetch_provider_documents(
    *,
    ticker: str,
    company_profile: CompanyProfile | None,
    as_of_date: date,
    include_transcript: bool,
    include_news: bool,
    include_estimates: bool,
    transcript_path: str | Path | None,
    transcript_paths: list[str | Path] | None,
    manual_source_paths: list[str | Path] | None,
    manual_source_urls: list[str] | None,
    earnings_release_paths: list[str | Path] | None,
    news_source_paths: list[str | Path] | None,
    news_days: int | None,
    news_lookback_days: int | None,
    max_news_items: int,
) -> list[SourceDocument]:
    lookback_days = _coerce_int(
        news_lookback_days
        or os.getenv("RESEARCH_CONTEXT_NEWS_LOOKBACK_DAYS", "")
        or news_days,
        DEFAULT_NEWS_LOOKBACK_DAYS,
    )
    max_news = _coerce_int(
        os.getenv("RESEARCH_CONTEXT_MAX_NEWS_ITEMS", "")
        or max_news_items,
        DEFAULT_MAX_NEWS_ITEMS,
    )
    max_transcripts = _coerce_int(
        os.getenv("RESEARCH_CONTEXT_MAX_TRANSCRIPTS", ""),
        DEFAULT_MAX_TRANSCRIPTS,
    )
    all_transcript_paths = [str(path) for path in (transcript_paths or [])]
    if transcript_path:
        all_transcript_paths.insert(0, str(transcript_path))

    options = ResearchSourceOptions(
        as_of_date=as_of_date,
        lookback_days=lookback_days,
        max_documents=10,
        max_news_items=max_news,
        max_transcripts=max_transcripts,
        manual_source_paths=[str(path) for path in (manual_source_paths or [])],
        manual_source_urls=list(manual_source_urls or []),
        transcript_paths=all_transcript_paths,
        earnings_release_paths=[str(path) for path in (earnings_release_paths or [])],
        news_source_paths=[str(path) for path in (news_source_paths or [])],
    )

    providers = []
    if (
        options.manual_source_paths
        or options.manual_source_urls
        or options.transcript_paths
        or options.earnings_release_paths
        or options.news_source_paths
    ):
        from src.agent_system.research_sources.manual_sources import ManualSourceProvider

        providers.append(ManualSourceProvider())
    if include_transcript:
        from src.agent_system.research_sources.finnhub import FinnhubTranscriptProvider
        from src.agent_system.research_sources.fmp import FMPTranscriptProvider

        providers.extend([FMPTranscriptProvider(), FinnhubTranscriptProvider()])
    if include_news:
        from src.agent_system.research_sources.finnhub import FinnhubCompanyNewsProvider
        from src.agent_system.research_sources.newsapi import NewsAPICompanyNewsProvider

        providers.extend([NewsAPICompanyNewsProvider(), FinnhubCompanyNewsProvider()])
    if include_estimates:
        from src.agent_system.research_sources.estimates import YFinanceEstimatesProvider

        providers.append(YFinanceEstimatesProvider())

    docs: list[SourceDocument] = []
    for provider in providers:
        try:
            docs.extend(
                await provider.fetch(
                    ticker=ticker,
                    company_profile=company_profile,
                    options=options,
                )
            )
        except Exception as exc:
            docs.append(_error_source(
                ticker,
                EvidenceSourceType.OTHER,
                (
                    f"{getattr(provider, 'provider_name', provider.__class__.__name__)} "
                    f"provider failed: {sanitize_provider_message(str(exc))}"
                ),
            ))
    return docs


def dedupe_evidence_items(
    items: list[SingleNameEvidenceItem],
) -> list[SingleNameEvidenceItem]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SingleNameEvidenceItem] = []
    for item in items:
        key = (
            item.source_type.value,
            str(item.source_date or ""),
            item.claim.lower().strip().rstrip(".!?:;"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


PURPOSE_PRIORITY = {
    SourceDocumentPurpose.EARNINGS_RELEASE: 1,
    SourceDocumentPurpose.STRATEGIC_TRANSACTION: 2,
    SourceDocumentPurpose.STRESS_TEST: 3,
    SourceDocumentPurpose.REGULATORY_CAPITAL: 4,
    SourceDocumentPurpose.INVESTOR_PRESENTATION: 5,
    SourceDocumentPurpose.QUARTERLY_FILING: 6,
    SourceDocumentPurpose.ANNUAL_FILING: 7,
    SourceDocumentPurpose.TRANSCRIPT: 8,
    SourceDocumentPurpose.NEWS: 9,
    SourceDocumentPurpose.ESTIMATE: 10,
    SourceDocumentPurpose.PEER_COMMENTARY: 11,
    SourceDocumentPurpose.OTHER: 12,
    SourceDocumentPurpose.UNKNOWN: 13,
}


def dedupe_and_prioritize_source_documents(
    source_documents: list[SourceDocument],
    *,
    max_news_items: int | None = None,
) -> list[SourceDocument]:
    """Select extraction sources, preferring classified exhibits over filing noise."""

    selected: list[SourceDocument] = []
    sec_8k_by_accession: dict[str, list[SourceDocument]] = {}
    transcripts: list[SourceDocument] = []
    news_docs: list[SourceDocument] = []
    estimates: list[SourceDocument] = []
    non_8k: dict[tuple[str, str, str], SourceDocument] = {}

    for source in source_documents:
        if source.retrieval_status != SourceRetrievalStatus.FOUND:
            continue
        if source.source_type == EvidenceSourceType.TRANSCRIPT:
            transcripts.append(source)
            continue
        if source.source_type == EvidenceSourceType.NEWS:
            news_docs.append(source)
            continue
        if source.source_type == EvidenceSourceType.ESTIMATE:
            estimates.append(source)
            continue
        if (
            source.source_type == EvidenceSourceType.SEC_8K_EXHIBIT
            and source.accession_number
        ):
            sec_8k_by_accession.setdefault(source.accession_number, []).append(source)
            continue
        key = _source_key(source)
        existing = non_8k.get(key)
        if existing is None or _source_rank(source) < _source_rank(existing):
            non_8k[key] = source

    if transcripts:
        selected.append(min(transcripts, key=_transcript_rank))
    if estimates:
        selected.append(min(estimates, key=_provider_rank))
    selected.extend(_dedupe_news_sources(news_docs, max_items=max_news_items))

    for group in sec_8k_by_accession.values():
        specific = [
            source for source in group
            if source.document_purpose
            not in {SourceDocumentPurpose.OTHER, SourceDocumentPurpose.UNKNOWN}
        ]
        if specific:
            by_purpose: dict[SourceDocumentPurpose, SourceDocument] = {}
            for source in specific:
                existing = by_purpose.get(source.document_purpose)
                if existing is None or _source_rank(source) < _source_rank(existing):
                    by_purpose[source.document_purpose] = source
            selected.extend(
                by_purpose[purpose]
                for purpose in sorted(by_purpose, key=lambda p: PURPOSE_PRIORITY[p])
            )
            continue
        selected.append(min(group, key=_source_rank))

    selected.extend(non_8k.values())
    return sorted(selected, key=_source_rank)


def bucket_evidence_items(
    items: list[SingleNameEvidenceItem],
) -> dict[str, list[SingleNameEvidenceItem]]:
    buckets = {
        "earnings_release_evidence": [],
        "filing_evidence": [],
        "transcript_evidence": [],
        "news_evidence": [],
        "estimate_evidence": [],
        "peer_commentary_evidence": [],
        "strategic_transaction_evidence": [],
        "regulatory_capital_evidence": [],
        "stress_test_evidence": [],
        "investor_presentation_evidence": [],
        "other_sec_8k_evidence": [],
        "management_guidance": [],
        "segment_kpis": [],
        "consensus_narrative": [],
        "bullish_evidence": [],
        "bearish_evidence": [],
        "mixed_evidence": [],
    }
    for item in items:
        purpose = item.document_purpose
        if purpose == SourceDocumentPurpose.EARNINGS_RELEASE:
            buckets["earnings_release_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.STRATEGIC_TRANSACTION:
            buckets["strategic_transaction_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.REGULATORY_CAPITAL:
            buckets["regulatory_capital_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.STRESS_TEST:
            buckets["stress_test_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.INVESTOR_PRESENTATION:
            buckets["investor_presentation_evidence"].append(item)
        elif purpose in {
            SourceDocumentPurpose.QUARTERLY_FILING,
            SourceDocumentPurpose.ANNUAL_FILING,
        }:
            buckets["filing_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.NEWS:
            buckets["news_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.ESTIMATE:
            buckets["estimate_evidence"].append(item)
        elif purpose == SourceDocumentPurpose.TRANSCRIPT:
            buckets["transcript_evidence"].append(item)
        elif item.source_type == EvidenceSourceType.TRANSCRIPT:
            buckets["transcript_evidence"].append(item)
        elif item.source_type == EvidenceSourceType.NEWS:
            buckets["news_evidence"].append(item)
        elif item.source_type == EvidenceSourceType.ESTIMATE:
            buckets["estimate_evidence"].append(item)
        elif item.source_type == EvidenceSourceType.PEER_COMMENTARY:
            buckets["peer_commentary_evidence"].append(item)
        elif (
            item.source_type == EvidenceSourceType.SEC_8K_EXHIBIT
            and purpose in {SourceDocumentPurpose.OTHER, SourceDocumentPurpose.UNKNOWN, None}
        ):
            buckets["other_sec_8k_evidence"].append(item)
        elif item.source_type == EvidenceSourceType.FILING:
            buckets["filing_evidence"].append(item)

        search_text = " ".join(
            [
                item.claim,
                item.summary or "",
                " ".join(item.related_topics),
                " ".join(item.related_metrics),
                " ".join(item.evidence_tags),
            ]
        ).lower()
        if any(word in search_text for word in ("guidance", "outlook", "forecast")):
            buckets["management_guidance"].append(item)
        if any(word in search_text for word in ("segment", "kpi", "unit", "orders", "backlog")):
            buckets["segment_kpis"].append(item)
        if any(word in search_text for word in ("consensus", "analyst", "estimate", "revision")):
            buckets["consensus_narrative"].append(item)

        if item.polarity == EvidencePolarity.SUPPORTS:
            buckets["bullish_evidence"].append(item)
        elif item.polarity == EvidencePolarity.CHALLENGES:
            buckets["bearish_evidence"].append(item)
        elif item.polarity == EvidencePolarity.MIXED:
            buckets["mixed_evidence"].append(item)
    return buckets


def _safe_source(func, ticker: str) -> SourceDocument:
    try:
        doc = func(ticker)
        if doc is None:
            return _error_source(ticker, EvidenceSourceType.OTHER, "Source function returned None.")
        return doc
    except Exception as exc:
        return _error_source(ticker, EvidenceSourceType.OTHER, str(exc))


def _coerce_int(value: Any, default: int) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _apply_source_document_purpose(
    items: list[SingleNameEvidenceItem],
    source_documents: list[SourceDocument],
) -> list[SingleNameEvidenceItem]:
    enriched: list[SingleNameEvidenceItem] = []
    for item in items:
        source = find_source_for_evidence_item(item, source_documents)
        if source is None:
            enriched.append(item)
            continue
        updates: dict[str, Any] = {}
        if (
            item.document_purpose in {None, SourceDocumentPurpose.UNKNOWN}
            and source.document_purpose != SourceDocumentPurpose.UNKNOWN
        ):
            updates["document_purpose"] = source.document_purpose
        if item.source_name is None:
            updates["source_name"] = source.source_name
        if item.source_date is None:
            updates["source_date"] = source.source_date
        if item.title is None:
            updates["title"] = source.title
        tags = list(item.evidence_tags)
        purpose_tag = f"document_purpose:{source.document_purpose.value}"
        confidence_tag = f"classification_confidence:{source.classification_confidence.value}"
        if source.document_purpose != SourceDocumentPurpose.UNKNOWN and purpose_tag not in tags:
            tags.append(purpose_tag)
        if confidence_tag not in tags:
            tags.append(confidence_tag)
        if tags != item.evidence_tags:
            updates["evidence_tags"] = tags
        if (
            not item.notes
            and source.classification_rationale
            and len(source.classification_rationale) <= 240
        ):
            updates["notes"] = source.classification_rationale
        enriched.append(item.model_copy(update=updates) if updates else item)
    return enriched


def find_source_for_evidence_item(
    item: SingleNameEvidenceItem,
    source_documents: list[SourceDocument],
) -> SourceDocument | None:
    """Find the SourceDocument that produced an evidence item."""

    if item.source_url:
        for source in source_documents:
            if source.source_url == item.source_url:
                return source

    if item.accession_number and item.title:
        for source in source_documents:
            if (
                source.accession_number == item.accession_number
                and source.title == item.title
            ):
                return source

    if item.accession_number and item.source_date:
        for source in source_documents:
            if (
                source.accession_number == item.accession_number
                and source.source_type == item.source_type
                and source.source_date == item.source_date
            ):
                return source

    if item.accession_number:
        matches = [
            source for source in source_documents
            if source.accession_number == item.accession_number
        ]
        if len(matches) == 1:
            return matches[0]

    return None


def _source_key(source: SourceDocument) -> tuple[str, str, str]:
    return (
        source.accession_number or "",
        source.source_url or "",
        source.source_type.value,
    )


def _source_rank(source: SourceDocument) -> tuple[int, int, int, str]:
    return (
        PURPOSE_PRIORITY.get(source.document_purpose, 99),
        _provider_rank(source),
        _source_quality_rank(source),
        source.source_url or source.title or "",
    )


def _provider_rank(source: SourceDocument) -> int:
    provider = _provider_name(source)
    if source.source_type == EvidenceSourceType.TRANSCRIPT:
        return {
            "manual": 1,
            "fmp": 2,
            "finnhub": 3,
        }.get(provider, 9)
    if source.source_type == EvidenceSourceType.NEWS:
        return {
            "manual": 1,
            "newsapi": 2,
            "finnhub": 3,
        }.get(provider, 9)
    if source.source_type == EvidenceSourceType.ESTIMATE:
        return {"yfinance": 1}.get(provider, 9)
    return 5


def _transcript_rank(source: SourceDocument) -> tuple[int, str, str]:
    quarter = str(source.metadata.get("quarter") or "")
    year = str(source.metadata.get("year") or source.metadata.get("fiscal_year") or "")
    date_key = source.source_date.isoformat() if source.source_date else ""
    return (_provider_rank(source), f"{year}Q{quarter}", date_key)


def _dedupe_news_sources(
    docs: list[SourceDocument],
    *,
    max_items: int | None,
) -> list[SourceDocument]:
    by_key: dict[tuple[str, str], SourceDocument] = {}
    manual_docs: list[SourceDocument] = []
    for doc in docs:
        key = _news_key(doc)
        if _provider_name(doc) == "manual":
            manual_docs.append(doc)
            continue
        existing = by_key.get(key)
        if existing is None or _news_rank(doc) < _news_rank(existing):
            by_key[key] = doc
    selected = manual_docs + sorted(by_key.values(), key=_news_rank)
    if max_items is None:
        return selected
    return selected[:max_items]


def _news_rank(source: SourceDocument) -> tuple[int, int, str]:
    has_text = 0 if source.text or source.text_excerpt else 1
    date_key = source.source_date.isoformat() if source.source_date else ""
    return (_provider_rank(source), has_text, date_key)


def _news_key(source: SourceDocument) -> tuple[str, str]:
    url = (source.source_url or "").strip().lower().rstrip("/")
    title = " ".join((source.title or "").lower().split())
    if url:
        return (url, "")
    return ("", title)


def _provider_name(source: SourceDocument) -> str:
    provider = source.metadata.get("provider") if isinstance(source.metadata, dict) else None
    if provider:
        provider_text = str(provider).lower()
        if "manual" in provider_text:
            return "manual"
        if "fmp" in provider_text:
            return "fmp"
        if "finnhub" in provider_text:
            return "finnhub"
        if "newsapi" in provider_text:
            return "newsapi"
        if "yfinance" in provider_text:
            return "yfinance"
        if "sec" in provider_text:
            return "sec"
        return provider_text
    source_name = (source.source_name or "").lower()
    if "manual" in source_name:
        return "manual"
    if "fmp" in source_name:
        return "fmp"
    if "finnhub" in source_name:
        return "finnhub"
    if "newsapi" in source_name:
        return "newsapi"
    if "yfinance" in source_name:
        return "yfinance"
    if "sec" in source_name:
        return "sec"
    return source_name or "unknown"


def _source_quality_rank(source: SourceDocument) -> int:
    text = f"{source.title or ''} {source.source_url or ''}".lower()
    if (
        source.source_type == EvidenceSourceType.SEC_8K_EXHIBIT
        and source.exhibit_type
        and text.endswith((".htm", ".html"))
    ):
        return 1
    if (
        source.source_type == EvidenceSourceType.SEC_8K_EXHIBIT
        and ("ex-99" in text or "ex99" in text or "99.1" in text)
        and text.endswith((".htm", ".html"))
    ):
        return 1
    if "index-headers" in text or "index.html" in text or "index.htm" in text:
        return 5
    if text.endswith(".txt"):
        return 4
    if source.form_type in {"8-K", "10-Q", "10-K"} and text.endswith((".htm", ".html")):
        return 2
    return 3


def _load_manual_source(ticker: str, path: str | Path) -> SourceDocument:
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source_path.read_text(encoding="latin-1")
    return SourceDocument(
        source_type=EvidenceSourceType.OTHER,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.OTHER,
        ticker=ticker,
        source_name="Manual source file",
        title=source_path.name,
        retrieved_at=datetime.now(timezone.utc),
        source_url=str(source_path),
        text=text,
        text_excerpt=text[:2500],
        metadata={"path": str(source_path)},
    )


def _error_source(
    ticker: str,
    source_type: EvidenceSourceType,
    message: str,
) -> SourceDocument:
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.ERROR,
        ticker=ticker,
        retrieved_at=datetime.now(timezone.utc),
        error_message=message,
    )


def _coverage_from_source(source: SourceDocument) -> SourceCoverageItem:
    return SourceCoverageItem(
        source_type=source.source_type,
        document_purpose=source.document_purpose,
        status=source.retrieval_status,
        provider_status=source.provider_status or source.metadata.get("provider_status"),
        provider=_provider_name(source),
        source_name=source.source_name,
        source_date=source.source_date,
        source_url=source.source_url,
        accession_number=source.accession_number,
        notes=source.notes or source.error_message or source.classification_rationale,
    )


def _coverage_summary(
    items: list[SourceCoverageItem],
    *,
    selected_sources: list[SourceDocument] | None = None,
    extraction_selected_count: int | None = None,
    duplicate_dropped_count: int | None = None,
) -> str:
    if not items:
        return "No source retrieval attempted."
    counts: dict[str, int] = {}
    for item in items:
        key = _coverage_key(item)
        counts[key] = counts.get(key, 0) + 1
    parts = [f"{key}={value}" for key, value in sorted(counts.items())]
    if selected_sources:
        selected_counts: dict[str, int] = {}
        for source in selected_sources:
            key = _selected_coverage_key(source)
            selected_counts[key] = selected_counts.get(key, 0) + 1
        parts.extend(
            f"{key}={value}" for key, value in sorted(selected_counts.items())
        )
    if extraction_selected_count is not None:
        parts.append(f"extraction_selected={extraction_selected_count}")
    if duplicate_dropped_count:
        parts.append(f"duplicate_dropped={duplicate_dropped_count}")
    return "; ".join(parts)


def _coverage_key(item: SourceCoverageItem) -> str:
    provider = _coverage_provider(item)
    status = _coverage_status_label(item)
    if item.source_type == EvidenceSourceType.TRANSCRIPT:
        return f"transcript:{provider}_{status}"
    if item.source_type == EvidenceSourceType.NEWS:
        return f"news:{provider}_{status}"
    if item.source_type == EvidenceSourceType.ESTIMATE:
        return f"estimates:{provider}_{status}"
    if item.source_type == EvidenceSourceType.SEC_8K_EXHIBIT:
        if item.document_purpose == SourceDocumentPurpose.OTHER:
            return f"other_8k:sec_{status}"
        if item.document_purpose != SourceDocumentPurpose.UNKNOWN:
            return f"{item.document_purpose.value}:sec_{status}"
        return f"sec_8k_exhibit:sec_{status}"
    if item.source_type == EvidenceSourceType.FILING and item.document_purpose in {
        SourceDocumentPurpose.QUARTERLY_FILING,
        SourceDocumentPurpose.ANNUAL_FILING,
    }:
        return f"filing:sec_{status}"
    return f"{item.source_type.value}:{provider}_{status}"


def _coverage_status_label(item: SourceCoverageItem) -> str:
    if item.provider_status:
        return item.provider_status
    if item.status == SourceRetrievalStatus.SKIPPED and "not configured" in (item.notes or "").lower():
        return "skipped_no_key"
    return item.status.value


def _coverage_provider(item: SourceCoverageItem) -> str:
    if item.provider:
        return item.provider
    source_name = (item.source_name or "").lower()
    if "manual" in source_name:
        return "manual"
    if "fmp" in source_name:
        return "fmp"
    if "finnhub" in source_name:
        return "finnhub"
    if "newsapi" in source_name:
        return "newsapi"
    if "yfinance" in source_name:
        return "yfinance"
    if "sec" in source_name:
        return "sec"
    if "company ir" in source_name:
        return "company_ir"
    return item.source_type.value


def _selected_coverage_key(source: SourceDocument) -> str:
    provider = _provider_name(source)
    if source.source_type == EvidenceSourceType.NEWS:
        return f"news:{provider}_selected"
    if source.source_type == EvidenceSourceType.ESTIMATE:
        return f"estimates:{provider}_selected"
    if source.source_type == EvidenceSourceType.TRANSCRIPT:
        return f"transcript:{provider}_selected"
    if source.source_type == EvidenceSourceType.SEC_8K_EXHIBIT:
        if source.document_purpose == SourceDocumentPurpose.OTHER:
            return "other_8k:sec_selected"
        if source.document_purpose != SourceDocumentPurpose.UNKNOWN:
            return f"{source.document_purpose.value}:sec_selected"
        return "sec_8k_exhibit:sec_selected"
    if source.source_type == EvidenceSourceType.FILING:
        return "filing:sec_selected"
    return f"{source.source_type.value}:{provider}_selected"


def _extraction_source_summary(
    sources: list[SourceDocument],
) -> list[dict[str, Any]]:
    summary: list[dict[str, Any]] = []
    for source in sources:
        summary.append(
            {
                "source_type": source.source_type.value,
                "document_purpose": source.document_purpose.value,
                "source_name": source.source_name,
                "title": source.title,
                "source_date": source.source_date.isoformat()
                if source.source_date
                else None,
                "source_url": source.source_url,
                "text_len": len(source.text or ""),
                "text_excerpt_len": len(source.text_excerpt or ""),
                "provider": _provider_name(source),
                "provider_status": source.provider_status
                or source.metadata.get("provider_status"),
                "selected_reason": _selected_reason(source),
            }
        )
    return summary


def _selected_reason(source: SourceDocument) -> str:
    if source.source_type == EvidenceSourceType.NEWS:
        return "news_selected_for_snippet_extraction"
    if source.source_type == EvidenceSourceType.ESTIMATE:
        return "estimate_selected_for_extraction"
    if source.source_type == EvidenceSourceType.TRANSCRIPT:
        return "highest_priority_transcript_provider"
    if source.source_type == EvidenceSourceType.SEC_8K_EXHIBIT:
        return "classified_sec_8k_document"
    if source.source_type == EvidenceSourceType.FILING:
        return "latest_sec_filing"
    return "selected_for_extraction"


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if not clean:
            continue
        key = clean.lower().rstrip(".!?:;").strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result
