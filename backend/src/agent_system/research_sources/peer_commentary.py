"""Peer commentary retrieval scaffold."""
from __future__ import annotations

from datetime import datetime, timezone

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


def fetch_peer_commentary_sources(
    ticker: str,
    peer_tickers: list[str],
    max_peers: int = 3,
) -> list[SourceDocument]:
    """
    Return v1 peer-commentary coverage placeholders.

    Future versions can retrieve peer earnings releases/transcripts and ask the
    extraction agent for target-ticker readthroughs.
    """

    clean_ticker = ticker.upper().strip()
    peers = [peer.upper().strip() for peer in peer_tickers if peer][:max_peers]
    if not peers:
        return [
            SourceDocument(
                source_type=EvidenceSourceType.PEER_COMMENTARY,
                retrieval_status=SourceRetrievalStatus.SKIPPED,
                document_purpose=SourceDocumentPurpose.PEER_COMMENTARY,
                ticker=clean_ticker,
                source_name="Peer commentary",
                retrieved_at=datetime.now(timezone.utc),
                error_message="Peer commentary skipped; no peer tickers supplied.",
                source_confidence=EvidenceConfidence.LOW,
            )
        ]
    return [
        SourceDocument(
        source_type=EvidenceSourceType.PEER_COMMENTARY,
        retrieval_status=SourceRetrievalStatus.SKIPPED,
        document_purpose=SourceDocumentPurpose.PEER_COMMENTARY,
            ticker=clean_ticker,
            source_name="Peer commentary",
            retrieved_at=datetime.now(timezone.utc),
            error_message=(
                "Automated peer commentary retrieval not implemented in v1. "
                f"Candidate peers for future readthrough: {', '.join(peers)}."
            ),
            metadata={"peer_tickers": peers},
            source_confidence=EvidenceConfidence.LOW,
        )
    ]
