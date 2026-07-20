"""LLM-backed extraction of source-backed single-name evidence."""
from __future__ import annotations

from pydantic import BaseModel, Field

from src.agent_system.schemas.deep_fundamental import (
    SingleNameEvidenceItem,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


class EvidenceExtractionAgentValidationError(Exception):
    """Raised when evidence extraction cannot produce valid structured output."""


class EvidenceExtractionResult(BaseModel):
    ticker: str
    source_count: int
    evidence_items: list[SingleNameEvidenceItem] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def extract_evidence_from_sources(
    *,
    ticker: str,
    source_documents: list[SourceDocument],
    max_items_per_source: int = 12,
) -> EvidenceExtractionResult:
    """Extract structured evidence items from source documents."""

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")

    usable_sources = [
        source for source in source_documents
        if source.retrieval_status == SourceRetrievalStatus.FOUND
        and (source.text or source.text_excerpt or source.metadata)
    ]
    if not usable_sources:
        return EvidenceExtractionResult(
            ticker=clean_ticker,
            source_count=0,
            data_gaps=["No found source documents with usable text or metadata."],
        )

    from src.agent_system.agents.evidence_extraction_agent_prompts import (
        render_evidence_extraction_context,
    )
    from src.agent_system.llm.client import StructuredOutputError, parse_structured
    from src.agent_system.llm.config import EVIDENCE_EXTRACTION_AGENT_MODEL

    system_prompt = render_evidence_extraction_context(
        ticker=clean_ticker,
        source_documents=usable_sources,
        max_items_per_source=max_items_per_source,
    )
    user_message = (
        f"Extract source-backed single-name evidence for {clean_ticker}. "
        "Return only the EvidenceExtractionResult JSON object."
    )

    try:
        result = parse_structured(
            system=system_prompt,
            user=user_message,
            model=EVIDENCE_EXTRACTION_AGENT_MODEL,
            response_schema=EvidenceExtractionResult,
            purpose=f"single-name evidence extraction: {clean_ticker}",
            temperature=0.2,
            max_retries=1,
        )
    except StructuredOutputError as exc:
        raise EvidenceExtractionAgentValidationError(str(exc)) from exc

    if result.ticker != clean_ticker:
        result = result.model_copy(update={"ticker": clean_ticker})
    return _preserve_source_metadata(result, usable_sources)


def _preserve_source_metadata(
    result: EvidenceExtractionResult,
    source_documents: list[SourceDocument],
) -> EvidenceExtractionResult:
    enriched = []
    for item in result.evidence_items:
        source = _find_source_for_item(item, source_documents)
        if source is None:
            enriched.append(item)
            continue
        updates = {}
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
        enriched.append(item.model_copy(update=updates) if updates else item)
    return result.model_copy(update={"evidence_items": enriched})


def _find_source_for_item(
    item: SingleNameEvidenceItem,
    source_documents: list[SourceDocument],
) -> SourceDocument | None:
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
    if len(source_documents) == 1:
        return source_documents[0]
    return None
