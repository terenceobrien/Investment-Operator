"""Finnhub source providers for transcripts and company news."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.agent_system.research_sources.config import FINNHUB_API_KEY_ENV
from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    make_error_source_document,
    make_not_found_source_document,
    make_skipped_source_document,
    normalize_provider_date,
    sanitize_provider_message,
    strip_api_key_from_url,
    truncate_source_text,
)
from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
FINNHUB_TIMEOUT_SECONDS = 15


class FinnhubHTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = sanitize_provider_message(body)
        super().__init__(f"HTTP {status_code}: {self.body}")


class FinnhubTranscriptProvider:
    provider_name = "Finnhub"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        clean_ticker = ticker.upper().strip()
        api_key = os.getenv(FINNHUB_API_KEY_ENV)
        if not api_key:
            return [_skipped(
                clean_ticker,
                EvidenceSourceType.TRANSCRIPT,
                SourceDocumentPurpose.TRANSCRIPT,
                f"{FINNHUB_API_KEY_ENV} not configured.",
                provider_status="skipped_no_key",
            )]
        try:
            metadata = _find_latest_transcript(clean_ticker, api_key=api_key, as_of_date=options.as_of_date)
            if metadata is None:
                return [_not_found_transcript(clean_ticker, "No Finnhub earnings transcript found.")]
            text = _fetch_transcript_text(metadata, api_key=api_key)
            if not text:
                return [_not_found_transcript(clean_ticker, "Finnhub transcript metadata found but full transcript text was unavailable.")]
            source_date = normalize_provider_date(
                metadata.get("date")
                or metadata.get("time")
                or metadata.get("year")
            )
            return [
                SourceDocument(
                    source_type=EvidenceSourceType.TRANSCRIPT,
                    retrieval_status=SourceRetrievalStatus.FOUND,
                    document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                    provider_status="found",
                    ticker=clean_ticker,
                    source_name="Finnhub earnings transcript",
                    title=metadata.get("title") or _transcript_title(clean_ticker, metadata),
                    source_date=source_date,
                    retrieved_at=datetime.now(timezone.utc),
                    source_url=strip_api_key_from_url(
                        "https://finnhub.io/api/v1/stock/transcripts"
                    ),
                    text=text,
                    text_excerpt=truncate_source_text(text, 2500),
                    metadata={
                        "provider": "Finnhub",
                        "ticker": clean_ticker,
                        "id": metadata.get("id"),
                        "quarter": metadata.get("quarter"),
                        "year": metadata.get("year"),
                        "date": metadata.get("date") or metadata.get("time"),
                        "symbol": metadata.get("symbol") or clean_ticker,
                        "provider_status": "found",
                    },
                    source_confidence=EvidenceConfidence.HIGH,
                )
            ]
        except FinnhubHTTPError as exc:
            return [_transcript_http_status_doc(clean_ticker, exc)]
        except Exception as exc:
            return [
                make_error_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.TRANSCRIPT,
                    document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                    source_name="Finnhub earnings transcript",
                    message=(
                        "Finnhub transcript retrieval failed: "
                        f"{sanitize_provider_message(str(exc))}"
                    ),
                    provider_status="error",
                )
            ]


class FinnhubCompanyNewsProvider:
    provider_name = "Finnhub"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        clean_ticker = ticker.upper().strip()
        api_key = os.getenv(FINNHUB_API_KEY_ENV)
        if not api_key:
            return [_skipped(
                clean_ticker,
                EvidenceSourceType.NEWS,
                SourceDocumentPurpose.NEWS,
                f"{FINNHUB_API_KEY_ENV} not configured.",
                provider_status="skipped_no_key",
            )]
        try:
            start = options.as_of_date - timedelta(days=options.lookback_days)
            payload = _finnhub_get_json(
                "/company-news",
                {
                    "symbol": clean_ticker,
                    "from": start.isoformat(),
                    "to": options.as_of_date.isoformat(),
                    "token": api_key,
                },
            )
            articles = payload if isinstance(payload, list) else []
            docs = [
                _news_doc(clean_ticker, item)
                for item in articles[:options.max_news_items]
                if isinstance(item, dict)
            ]
            docs = _dedupe_news_docs(docs)
            if docs:
                return docs[:options.max_news_items]
            return [
                SourceDocument(
                    source_type=EvidenceSourceType.NEWS,
                    retrieval_status=SourceRetrievalStatus.NOT_FOUND,
                    document_purpose=SourceDocumentPurpose.NEWS,
                    ticker=clean_ticker,
                    source_name="Finnhub company news",
                    retrieved_at=datetime.now(timezone.utc),
                    error_message="No Finnhub company news returned.",
                    source_confidence=EvidenceConfidence.LOW,
                    metadata={"provider": "Finnhub"},
                )
            ]
        except Exception as exc:
            return [
                make_error_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.NEWS,
                    document_purpose=SourceDocumentPurpose.NEWS,
                    source_name="Finnhub company news",
                    message=(
                        "Finnhub company news retrieval failed: "
                        f"{sanitize_provider_message(str(exc))}"
                    ),
                )
            ]


def _finnhub_get_json(endpoint: str, params: dict[str, Any]) -> Any:
    clean_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    query = urlencode({key: value for key, value in params.items() if value is not None})
    req = Request(
        f"{FINNHUB_BASE_URL}{clean_endpoint}?{query}",
        headers={"User-Agent": "HelixResearchContext/0.1"},
    )
    try:
        with urlopen(req, timeout=FINNHUB_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        raise FinnhubHTTPError(exc.code, body) from exc


def _find_latest_transcript(
    ticker: str,
    *,
    api_key: str,
    as_of_date,
) -> dict[str, Any] | None:
    payload = _finnhub_get_json(
        "/stock/transcripts/list",
        {"symbol": ticker, "token": api_key},
    )
    items = payload.get("transcripts", payload) if isinstance(payload, dict) else payload
    candidates = items if isinstance(items, list) else []
    dated = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        item_date = normalize_provider_date(item.get("date") or item.get("time"))
        if item_date is not None and item_date > as_of_date:
            continue
        dated.append((item_date or as_of_date, item))
    if not dated:
        return None
    return sorted(dated, key=lambda pair: pair[0], reverse=True)[0][1]


def _fetch_transcript_text(metadata: dict[str, Any], *, api_key: str) -> str | None:
    for key in ("transcript", "content", "text"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    transcript_id = metadata.get("id")
    if not transcript_id:
        return None
    payload = _finnhub_get_json(
        "/stock/transcripts",
        {"id": transcript_id, "token": api_key},
    )
    if isinstance(payload, dict):
        metadata.update(payload)
        for key in ("transcript", "content", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        transcript = payload.get("transcript")
        if isinstance(transcript, list):
            lines = []
            for row in transcript:
                if isinstance(row, dict):
                    speaker = row.get("speaker") or row.get("name")
                    speech = row.get("speech") or row.get("text")
                    if speech:
                        lines.append(f"{speaker}: {speech}" if speaker else str(speech))
            if lines:
                return "\n".join(lines)
    return None


def _news_doc(ticker: str, item: dict[str, Any]) -> SourceDocument:
    headline = str(item.get("headline") or item.get("title") or "").strip()
    summary = str(item.get("summary") or "").strip()
    text = summary or headline
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.NEWS,
        provider_status="found",
        ticker=ticker,
        source_name=item.get("source") or "Finnhub company news",
        title=headline or None,
        source_date=normalize_provider_date(item.get("datetime")),
        retrieved_at=datetime.now(timezone.utc),
        source_url=item.get("url"),
        text="\n".join(part for part in (headline, summary) if part) or None,
        text_excerpt=truncate_source_text(text, 1500),
        metadata={
            "provider": "Finnhub",
            "provider_status": "found",
            "category": item.get("category"),
            "related": item.get("related"),
            "id": item.get("id"),
            "image": item.get("image"),
            "snippet_only": True,
            "notes": "Headline/snippet-only news evidence; full article body may be unavailable.",
        },
        source_confidence=EvidenceConfidence.MEDIUM if summary else EvidenceConfidence.LOW,
    )


def _dedupe_news_docs(docs: list[SourceDocument]) -> list[SourceDocument]:
    seen: set[tuple[str, str]] = set()
    result: list[SourceDocument] = []
    for doc in docs:
        key = (_normalize_url(doc.source_url), _normalize_title(doc.title))
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result


def _normalize_url(value: str | None) -> str:
    return (value or "").strip().lower().rstrip("/")


def _normalize_title(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _skipped(
    ticker: str,
    source_type: EvidenceSourceType,
    purpose: SourceDocumentPurpose,
    message: str,
    provider_status: str = "skipped",
) -> SourceDocument:
    source_name = (
        "Finnhub earnings transcript"
        if source_type == EvidenceSourceType.TRANSCRIPT
        else "Finnhub company news"
    )
    return make_skipped_source_document(
        ticker=ticker,
        source_type=source_type,
        document_purpose=purpose,
        source_name=source_name,
        message=message,
        provider_status=provider_status,
    )


def _not_found_transcript(ticker: str, message: str) -> SourceDocument:
    return make_not_found_source_document(
        ticker=ticker,
        source_type=EvidenceSourceType.TRANSCRIPT,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="Finnhub earnings transcript",
        message=message,
        source_confidence=EvidenceConfidence.MEDIUM,
        provider_status="not_found",
    )


def _transcript_http_status_doc(ticker: str, exc: FinnhubHTTPError) -> SourceDocument:
    if exc.status_code == 403:
        return make_skipped_source_document(
            ticker=ticker,
            source_type=EvidenceSourceType.TRANSCRIPT,
            document_purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="Finnhub earnings transcript",
            message="Finnhub transcript endpoint is not available under current entitlement.",
            source_confidence=EvidenceConfidence.LOW,
            provider_status="plan_restricted",
            notes="Finnhub transcript endpoint is not available under current entitlement.",
        ).model_copy(
            update={
                "metadata": {
                    "provider": "Finnhub",
                    "provider_status": "plan_restricted",
                    "http_status": exc.status_code,
                    "response_preview": truncate_source_text(exc.body, 500),
                }
            }
        )
    if exc.status_code == 401:
        return make_error_source_document(
            ticker=ticker,
            source_type=EvidenceSourceType.TRANSCRIPT,
            document_purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="Finnhub earnings transcript",
            message="FINNHUB_API_KEY appears invalid.",
            source_confidence=EvidenceConfidence.LOW,
            provider_status="invalid_key",
            notes="FINNHUB_API_KEY appears invalid.",
        ).model_copy(
            update={
                "metadata": {
                    "provider": "Finnhub",
                    "provider_status": "invalid_key",
                    "http_status": exc.status_code,
                    "response_preview": truncate_source_text(exc.body, 500),
                }
            }
        )
    return make_error_source_document(
        ticker=ticker,
        source_type=EvidenceSourceType.TRANSCRIPT,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="Finnhub earnings transcript",
        message=f"Finnhub transcript endpoint returned HTTP {exc.status_code}.",
        source_confidence=EvidenceConfidence.LOW,
        provider_status="error",
    ).model_copy(
        update={
            "metadata": {
                "provider": "Finnhub",
                "provider_status": "error",
                "http_status": exc.status_code,
                "response_preview": truncate_source_text(exc.body, 500),
            }
        }
    )


def _transcript_title(ticker: str, metadata: dict[str, Any]) -> str:
    quarter = metadata.get("quarter")
    year = metadata.get("year")
    date_value = metadata.get("date") or metadata.get("time")
    if quarter and year:
        return f"Finnhub earnings transcript: {ticker} Q{quarter} {year}"
    if date_value:
        return f"Finnhub earnings transcript: {ticker} {date_value}"
    return f"Finnhub earnings transcript: {ticker}"
