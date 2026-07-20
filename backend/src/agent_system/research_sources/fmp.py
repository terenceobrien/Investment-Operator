"""Financial Modeling Prep source providers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.agent_system.research_sources.config import FMP_API_KEY_ENV
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


FMP_BASE_URL = "https://financialmodelingprep.com"
FMP_TIMEOUT_SECONDS = 15


class FMPHTTPError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = sanitize_provider_message(body)
        super().__init__(f"HTTP {status_code}: {self.body}")


class FMPTranscriptProvider:
    provider_name = "FMP"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        clean_ticker = ticker.upper().strip()
        api_key = os.getenv(FMP_API_KEY_ENV)
        if not api_key:
            return [
                make_skipped_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.TRANSCRIPT,
                    document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                    source_name="FMP earnings transcript",
                    message=f"{FMP_API_KEY_ENV} not configured.",
                    provider_status="skipped_no_key",
                )
            ]

        try:
            metadata = _find_latest_transcript_metadata(
                clean_ticker,
                api_key=api_key,
                as_of_date=options.as_of_date,
            )
            if metadata is None:
                return [_not_found(clean_ticker, "No FMP earnings transcript metadata found.")]

            text = _fetch_transcript_text(clean_ticker, metadata, api_key=api_key)
            if not text:
                return [_not_found(clean_ticker, "FMP transcript metadata found but full transcript text was unavailable.")]

            source_date = (
                normalize_provider_date(metadata.get("date"))
                or normalize_provider_date(metadata.get("call_date"))
                or normalize_provider_date(metadata.get("fillingDate"))
            )
            return [
                SourceDocument(
                    source_type=EvidenceSourceType.TRANSCRIPT,
                    retrieval_status=SourceRetrievalStatus.FOUND,
                    document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                    provider_status="found",
                    ticker=clean_ticker,
                    source_name="FMP earnings transcript",
                    title=_transcript_title(clean_ticker, metadata),
                    source_date=source_date,
                    retrieved_at=datetime.now(timezone.utc),
                    source_url=strip_api_key_from_url(
                        "https://financialmodelingprep.com/stable/earning-call-transcript"
                    ),
                    text=text,
                    text_excerpt=truncate_source_text(text, 2500),
                    metadata={
                        "provider": "FMP",
                        "ticker": clean_ticker,
                        "fiscal_year": metadata.get("year") or metadata.get("fiscalYear"),
                        "quarter": metadata.get("quarter"),
                        "symbol": metadata.get("symbol") or clean_ticker,
                        "call_date": metadata.get("call_date") or metadata.get("date"),
                        "transcript_date": metadata.get("date"),
                        "provider_status": "found",
                    },
                    source_confidence=EvidenceConfidence.HIGH,
                )
            ]
        except FMPHTTPError as exc:
            return [_http_status_doc(clean_ticker, exc)]
        except Exception as exc:
            return [
                make_error_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.TRANSCRIPT,
                    document_purpose=SourceDocumentPurpose.TRANSCRIPT,
                    source_name="FMP earnings transcript",
                    message=(
                        "FMP transcript retrieval failed: "
                        f"{sanitize_provider_message(str(exc))}"
                    ),
                    provider_status="error",
                )
            ]


def _fmp_get_json(endpoint: str, params: dict[str, Any]) -> Any:
    clean_endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    clean_params = {key: value for key, value in params.items() if value is not None}
    query = urlencode(clean_params)
    url = f"{FMP_BASE_URL}{clean_endpoint}"
    if query:
        url = f"{url}?{query}"
    req = Request(url, headers={"User-Agent": "HelixResearchContext/0.1"})
    try:
        with urlopen(req, timeout=FMP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = str(exc)
        raise FMPHTTPError(exc.code, body) from exc


def _find_latest_transcript_metadata(
    ticker: str,
    *,
    api_key: str,
    as_of_date,
) -> dict[str, Any] | None:
    payload = _fmp_get_json(
        "/stable/earning-call-transcript-dates",
        {"symbol": ticker, "apikey": api_key},
    )
    candidates = _as_items(payload)
    dated = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        item_date = normalize_provider_date(
            item.get("date") or item.get("call_date") or item.get("fillingDate")
        )
        if item_date is not None and item_date > as_of_date:
            continue
        dated.append((item_date or as_of_date, item))
    if dated:
        return sorted(dated, key=lambda pair: pair[0], reverse=True)[0][1]
    return None


def _fetch_transcript_text(
    ticker: str,
    metadata: dict[str, Any],
    *,
    api_key: str,
) -> str | None:
    for key in ("content", "transcript", "text"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    quarter = metadata.get("quarter")
    year = metadata.get("year") or metadata.get("fiscalYear")
    if quarter is None or year is None:
        return None
    payload = _fmp_get_json(
        "/stable/earning-call-transcript",
        {
            "symbol": ticker,
            "quarter": quarter,
            "year": year,
            "apikey": api_key,
        },
    )
    items = _as_items(payload)
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("content", "transcript", "text"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                metadata.update(item)
                return value.strip()
    return None


def _as_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "transcripts", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    return []


def _transcript_title(ticker: str, metadata: dict[str, Any]) -> str:
    quarter = metadata.get("quarter")
    year = metadata.get("year") or metadata.get("fiscalYear")
    date_value = metadata.get("call_date") or metadata.get("date")
    if quarter and year:
        return f"FMP earnings transcript: {ticker} Q{quarter} {year}"
    if date_value:
        return f"FMP earnings transcript: {ticker} {date_value}"
    return f"FMP earnings transcript: {ticker}"


def _not_found(ticker: str, message: str) -> SourceDocument:
    return make_not_found_source_document(
        ticker=ticker,
        source_type=EvidenceSourceType.TRANSCRIPT,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="FMP earnings transcript",
        message=message,
        source_confidence=EvidenceConfidence.MEDIUM,
        provider_status="not_found",
    )


def _http_status_doc(ticker: str, exc: FMPHTTPError) -> SourceDocument:
    if exc.status_code == 402:
        return make_skipped_source_document(
            ticker=ticker,
            source_type=EvidenceSourceType.TRANSCRIPT,
            document_purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="FMP earnings transcript",
            message="FMP transcript endpoint is plan-restricted for current subscription.",
            source_confidence=EvidenceConfidence.LOW,
            provider_status="plan_restricted",
            notes="FMP transcript endpoint is plan-restricted for current subscription.",
        ).model_copy(
            update={
                "metadata": {
                    "provider": "FMP",
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
            source_name="FMP earnings transcript",
            message="FMP_API_KEY appears invalid.",
            source_confidence=EvidenceConfidence.LOW,
            provider_status="invalid_key",
            notes="FMP_API_KEY appears invalid.",
        ).model_copy(
            update={
                "metadata": {
                    "provider": "FMP",
                    "provider_status": "invalid_key",
                    "http_status": exc.status_code,
                    "response_preview": truncate_source_text(exc.body, 500),
                }
            }
        )
    if exc.status_code == 403:
        return make_skipped_source_document(
            ticker=ticker,
            source_type=EvidenceSourceType.TRANSCRIPT,
            document_purpose=SourceDocumentPurpose.TRANSCRIPT,
            source_name="FMP earnings transcript",
            message="FMP transcript endpoint is not available under current entitlement.",
            source_confidence=EvidenceConfidence.LOW,
            provider_status="plan_restricted",
            notes="FMP transcript endpoint is not available under current entitlement.",
        ).model_copy(
            update={
                "metadata": {
                    "provider": "FMP",
                    "provider_status": "plan_restricted",
                    "http_status": exc.status_code,
                    "response_preview": truncate_source_text(exc.body, 500),
                }
            }
        )
    return make_error_source_document(
        ticker=ticker,
        source_type=EvidenceSourceType.TRANSCRIPT,
        document_purpose=SourceDocumentPurpose.TRANSCRIPT,
        source_name="FMP earnings transcript",
        message=f"FMP transcript endpoint returned HTTP {exc.status_code}.",
        source_confidence=EvidenceConfidence.LOW,
        provider_status="error",
    ).model_copy(
        update={
            "metadata": {
                "provider": "FMP",
                "provider_status": "error",
                "http_status": exc.status_code,
                "response_preview": truncate_source_text(exc.body, 500),
            }
        }
    )
