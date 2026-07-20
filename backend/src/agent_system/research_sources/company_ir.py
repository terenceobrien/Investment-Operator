"""Company investor-relations retrieval placeholder."""
from __future__ import annotations

from datetime import datetime, timezone

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


def find_company_ir_source(ticker: str) -> SourceDocument:
    """Return a v1 placeholder until IR crawling/configured URLs exist."""

    return SourceDocument(
        source_type=EvidenceSourceType.COMPANY_IR,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=SourceDocumentPurpose.OTHER,
        ticker=ticker.upper().strip(),
        source_name="Company investor relations",
        retrieved_at=datetime.now(timezone.utc),
        error_message="Automated company IR retrieval not implemented in v1.",
        source_confidence=EvidenceConfidence.MEDIUM,
    )
