"""Transcript retrieval and manual-ingestion scaffolding."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


def load_transcript_from_path(ticker: str, path: str | Path) -> SourceDocument:
    """Load a manually supplied transcript file."""

    clean_ticker = ticker.upper().strip()
    source_path = Path(path)
    try:
        text = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = source_path.read_text(encoding="latin-1")
    return SourceDocument(
        source_type=EvidenceSourceType.TRANSCRIPT,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        ticker=clean_ticker,
        source_name="Manual transcript file",
        title=source_path.name,
        retrieved_at=datetime.now(timezone.utc),
        source_url=str(source_path),
        text=text,
        text_excerpt=text[:2500],
        metadata={"path": str(source_path)},
        source_confidence=EvidenceConfidence.MEDIUM,
    )


def find_latest_transcript(ticker: str) -> SourceDocument:
    """Return a placeholder explaining transcript retrieval limits."""

    return SourceDocument(
        source_type=EvidenceSourceType.TRANSCRIPT,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        ticker=ticker.upper().strip(),
        source_name="Earnings call transcript",
        retrieved_at=datetime.now(timezone.utc),
        error_message=(
            "Earnings call transcripts are not reliably available from SEC; "
            "provide transcript path or configure a third-party transcript provider."
        ),
        source_confidence=EvidenceConfidence.MEDIUM,
    )
