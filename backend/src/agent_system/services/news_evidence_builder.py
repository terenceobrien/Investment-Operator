"""Deterministic fallback evidence builder for headline/snippet news sources."""
from __future__ import annotations

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidencePolarity,
    EvidenceSourceType,
    SingleNameEvidenceItem,
    SourceDocument,
    SourceDocumentPurpose,
)


POSITIVE_WORDS = {
    "beats",
    "beat",
    "raises",
    "raised",
    "upgrade",
    "upgraded",
    "growth",
    "record",
    "strong",
    "surges",
    "wins",
}

NEGATIVE_WORDS = {
    "misses",
    "miss",
    "cuts",
    "cut",
    "downgrade",
    "downgraded",
    "lawsuit",
    "probe",
    "weak",
    "falls",
    "slumps",
}


def build_news_evidence_from_source_documents(
    ticker: str,
    news_documents: list[SourceDocument],
    max_items: int = 10,
) -> list[SingleNameEvidenceItem]:
    """Create conservative evidence items from news snippets when LLM extraction is empty."""

    clean_ticker = ticker.upper().strip()
    items: list[SingleNameEvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    for document in news_documents:
        if document.source_type != EvidenceSourceType.NEWS:
            continue
        title = (document.title or "").strip()
        summary = _summary_text(document)
        if not title and not summary:
            continue
        key = (_normalize(document.source_url), _normalize(title or summary))
        if key in seen:
            continue
        seen.add(key)
        text = " ".join(part for part in (title, summary) if part)
        confidence = (
            EvidenceConfidence.MEDIUM
            if summary and summary != title
            else EvidenceConfidence.LOW
        )
        items.append(
            SingleNameEvidenceItem(
                source_type=EvidenceSourceType.NEWS,
                document_purpose=SourceDocumentPurpose.NEWS,
                ticker=clean_ticker,
                source_date=document.source_date,
                source_name=document.source_name,
                source_url=document.source_url,
                title=title or None,
                claim=title or summary,
                summary=summary or title,
                excerpt=document.text_excerpt,
                polarity=_infer_polarity(text),
                confidence=confidence,
                relevance_score=_relevance_score(clean_ticker, text, confidence),
                related_topics=["news"],
                evidence_tags=[
                    "news",
                    "headline_snippet_only",
                    "deterministic_fallback",
                ],
                notes=(
                    "Generated from headline/snippet-only news source; full "
                    "article body unavailable."
                ),
            )
        )
        if len(items) >= max_items:
            break
    return items


def _summary_text(document: SourceDocument) -> str:
    text = document.text or document.text_excerpt or ""
    title = document.title or ""
    if title and text.startswith(title):
        text = text[len(title):].strip()
    return text.strip() or title.strip()


def _infer_polarity(text: str) -> EvidencePolarity:
    clean = text.lower()
    positive = sum(1 for word in POSITIVE_WORDS if word in clean)
    negative = sum(1 for word in NEGATIVE_WORDS if word in clean)
    if positive > negative and positive >= 2:
        return EvidencePolarity.SUPPORTS
    if negative > positive and negative >= 1:
        return EvidencePolarity.CHALLENGES
    return EvidencePolarity.NEUTRAL


def _relevance_score(
    ticker: str,
    text: str,
    confidence: EvidenceConfidence,
) -> float:
    score = 0.55 if confidence == EvidenceConfidence.MEDIUM else 0.4
    if ticker.lower() in text.lower():
        score += 0.15
    return min(1.0, score)


def _normalize(value: str | None) -> str:
    return " ".join((value or "").lower().strip().rstrip("/").split())
