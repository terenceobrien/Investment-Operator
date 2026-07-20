"""Common interfaces and helpers for research source providers."""
from __future__ import annotations

from datetime import date, datetime, timezone
import re
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


class ResearchSourceOptions(BaseModel):
    as_of_date: date
    lookback_days: int = 90
    max_documents: int = 10
    max_news_items: int = 10
    max_transcripts: int = 1

    manual_source_paths: list[str] = Field(default_factory=list)
    manual_source_urls: list[str] = Field(default_factory=list)
    transcript_paths: list[str] = Field(default_factory=list)
    earnings_release_paths: list[str] = Field(default_factory=list)
    news_source_paths: list[str] = Field(default_factory=list)


class ResearchSourceProvider(Protocol):
    provider_name: str

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        ...


def make_skipped_source_document(
    *,
    ticker: str,
    source_type: EvidenceSourceType,
    document_purpose: SourceDocumentPurpose,
    source_name: str,
    message: str,
    source_confidence: EvidenceConfidence = EvidenceConfidence.LOW,
    provider_status: str | None = None,
    notes: str | None = None,
) -> SourceDocument:
    clean_message = sanitize_provider_message(message)
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.SKIPPED,
        document_purpose=document_purpose,
        provider_status=provider_status or "skipped",
        ticker=ticker.upper().strip(),
        source_name=source_name,
        retrieved_at=datetime.now(timezone.utc),
        error_message=clean_message,
        notes=notes or clean_message,
        source_confidence=source_confidence,
        metadata={
            "provider": source_name,
            "provider_status": provider_status or "skipped",
        },
    )


def make_not_found_source_document(
    *,
    ticker: str,
    source_type: EvidenceSourceType,
    document_purpose: SourceDocumentPurpose,
    source_name: str,
    message: str,
    source_confidence: EvidenceConfidence = EvidenceConfidence.LOW,
    provider_status: str | None = None,
    notes: str | None = None,
) -> SourceDocument:
    clean_message = sanitize_provider_message(message)
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=document_purpose,
        provider_status=provider_status or "not_found",
        ticker=ticker.upper().strip(),
        source_name=source_name,
        retrieved_at=datetime.now(timezone.utc),
        error_message=clean_message,
        notes=notes or clean_message,
        source_confidence=source_confidence,
        metadata={
            "provider": source_name,
            "provider_status": provider_status or "not_found",
        },
    )


def make_error_source_document(
    *,
    ticker: str,
    source_type: EvidenceSourceType,
    document_purpose: SourceDocumentPurpose,
    source_name: str,
    message: str,
    source_confidence: EvidenceConfidence = EvidenceConfidence.LOW,
    provider_status: str | None = None,
    notes: str | None = None,
) -> SourceDocument:
    clean_message = sanitize_provider_message(message)
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.ERROR,
        document_purpose=document_purpose,
        provider_status=provider_status or "error",
        ticker=ticker.upper().strip(),
        source_name=source_name,
        retrieved_at=datetime.now(timezone.utc),
        error_message=clean_message,
        notes=notes or clean_message,
        source_confidence=source_confidence,
        metadata={
            "provider": source_name,
            "provider_status": provider_status or "error",
        },
    )


def normalize_provider_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return normalize_provider_date(float(text))
    for candidate in (text, text[:10]):
        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
        except ValueError:
            continue
    return None


def safe_get(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return default
    return current


SENSITIVE_QUERY_KEYS = {
    "apikey",
    "api_key",
    "token",
    "access_token",
    "x-api-key",
}


def strip_api_key_from_url(url: str | None) -> str | None:
    """Remove common API-key query parameters from a URL before persistence."""

    if not url:
        return url
    try:
        parsed = urlsplit(url)
    except ValueError:
        return sanitize_provider_message(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def sanitize_provider_message(message: str | None) -> str:
    """Scrub API-key-like tokens from provider error messages."""

    if not message:
        return ""
    text = str(message)
    for key in SENSITIVE_QUERY_KEYS:
        text = re.sub(
            rf"({re.escape(key)}=)[^&\s]+",
            rf"\1***",
            text,
            flags=re.IGNORECASE,
        )
    return text


def truncate_source_text(text: str | None, limit: int = 2500) -> str | None:
    if text is None:
        return None
    clean = str(text).strip()
    if not clean:
        return None
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip()
