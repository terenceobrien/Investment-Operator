"""Deterministic fallback evidence builder for yfinance estimate context."""
from __future__ import annotations

import json
from typing import Any

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidencePolarity,
    EvidenceSourceType,
    SingleNameEvidenceItem,
    SourceDocument,
    SourceDocumentPurpose,
)


def build_estimate_evidence_from_source_document(
    ticker: str,
    estimate_document: SourceDocument,
) -> list[SingleNameEvidenceItem]:
    """Create conservative evidence items from a yfinance estimate SourceDocument."""

    clean_ticker = ticker.upper().strip()
    metadata = estimate_document.metadata or {}
    items: list[SingleNameEvidenceItem] = []

    revision_text = _compact_field(metadata.get("eps_revisions"))
    if revision_text:
        items.append(
            _item(
                ticker=clean_ticker,
                document=estimate_document,
                claim="yfinance EPS revision context is available.",
                summary=revision_text,
                polarity=_revision_polarity(revision_text),
                confidence=EvidenceConfidence.MEDIUM,
                tags=["estimate", "yfinance", "eps_revisions", "deterministic_fallback"],
            )
        )

    eps_trend = _compact_field(metadata.get("eps_trend"))
    if eps_trend:
        items.append(
            _item(
                ticker=clean_ticker,
                document=estimate_document,
                claim="yfinance EPS trend context is available.",
                summary=eps_trend,
                polarity=EvidencePolarity.NEUTRAL,
                confidence=EvidenceConfidence.MEDIUM,
                tags=["estimate", "yfinance", "eps_trend", "deterministic_fallback"],
            )
        )

    revenue_estimate = _compact_field(metadata.get("revenue_estimate"))
    if revenue_estimate:
        items.append(
            _item(
                ticker=clean_ticker,
                document=estimate_document,
                claim="yfinance revenue estimate context is available.",
                summary=revenue_estimate,
                polarity=EvidencePolarity.NEUTRAL,
                confidence=EvidenceConfidence.MEDIUM,
                tags=[
                    "estimate",
                    "yfinance",
                    "revenue_estimate",
                    "deterministic_fallback",
                ],
            )
        )

    recommendations = _compact_field(metadata.get("recommendations_summary"))
    if recommendations:
        items.append(
            _item(
                ticker=clean_ticker,
                document=estimate_document,
                claim="yfinance recommendation summary context is available.",
                summary=recommendations,
                polarity=EvidencePolarity.NEUTRAL,
                confidence=EvidenceConfidence.LOW,
                tags=[
                    "estimate",
                    "yfinance",
                    "recommendations",
                    "deterministic_fallback",
                ],
            )
        )

    if not items and (estimate_document.text or estimate_document.text_excerpt):
        items.append(
            _item(
                ticker=clean_ticker,
                document=estimate_document,
                claim="yfinance analyst estimate context is available.",
                summary=estimate_document.text_excerpt or estimate_document.text,
                polarity=EvidencePolarity.NEUTRAL,
                confidence=EvidenceConfidence.LOW,
                tags=["estimate", "yfinance", "deterministic_fallback"],
            )
        )
    return items


def _item(
    *,
    ticker: str,
    document: SourceDocument,
    claim: str,
    summary: str | None,
    polarity: EvidencePolarity,
    confidence: EvidenceConfidence,
    tags: list[str],
) -> SingleNameEvidenceItem:
    return SingleNameEvidenceItem(
        source_type=EvidenceSourceType.ESTIMATE,
        document_purpose=SourceDocumentPurpose.ESTIMATE,
        ticker=ticker,
        source_date=document.source_date,
        source_name=document.source_name,
        source_url=document.source_url,
        title=document.title,
        claim=claim,
        summary=summary,
        excerpt=document.text_excerpt,
        polarity=polarity,
        confidence=confidence,
        relevance_score=0.65 if confidence == EvidenceConfidence.MEDIUM else 0.45,
        related_topics=["estimates"],
        related_metrics=["eps", "revenue", "revisions"],
        evidence_tags=tags,
        notes=(
            "Generated from yfinance estimate summary; not a complete "
            "institutional estimate-history feed."
        ),
    )


def _compact_field(value: Any) -> str | None:
    if value in (None, {}, [], ""):
        return None
    try:
        rendered = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        rendered = str(value)
    rendered = rendered.strip()
    if not rendered:
        return None
    return rendered[:1500]


def _revision_polarity(text: str) -> EvidencePolarity:
    clean = text.lower()
    positive_terms = ("up", "upward", "positive", "raise", "raised", "higher")
    negative_terms = ("down", "downward", "negative", "cut", "lower", "reduced")
    positive = sum(term in clean for term in positive_terms)
    negative = sum(term in clean for term in negative_terms)
    if positive > negative:
        return EvidencePolarity.SUPPORTS
    if negative > positive:
        return EvidencePolarity.CHALLENGES
    return EvidencePolarity.NEUTRAL
