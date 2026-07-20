"""Estimate-context retrieval using lightweight yfinance fields when present."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.agent_system.research_sources.base import ResearchSourceOptions
from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


class YFinanceEstimatesProvider:
    provider_name = "yfinance"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        return _fetch_yfinance_estimates(ticker)


def fetch_estimate_context(ticker: str) -> list[SourceDocument]:
    """Fetch low/medium-confidence estimate context from yfinance if available."""

    return _fetch_yfinance_estimates(ticker)


def _fetch_yfinance_estimates(ticker: str) -> list[SourceDocument]:
    clean_ticker = ticker.upper().strip()
    try:
        import yfinance as yf

        yf_ticker = yf.Ticker(clean_ticker)
        payload: dict[str, Any] = {}
        for attribute in (
            "recommendations_summary",
            "upgrades_downgrades",
            "earnings_estimate",
            "revenue_estimate",
            "eps_trend",
            "eps_revisions",
        ):
            try:
                value = getattr(yf_ticker, attribute)
                if value is not None and hasattr(value, "empty") and not value.empty:
                    payload[attribute] = value.tail(20).to_dict()
                elif value is not None and not hasattr(value, "empty"):
                    payload[attribute] = value
            except Exception:
                continue
        if not payload:
            return [_not_found_doc(clean_ticker, "No usable yfinance estimate fields returned.")]
        serializable_payload = _to_serializable(payload)
        text = "\n".join(
            [
                "yfinance analyst estimate context is available.",
                "Treat this as a low/medium-confidence vendor-derived summary, not full institutional revision history.",
                json.dumps(serializable_payload, indent=2, sort_keys=True, default=str)[:6000],
            ]
        )
        return [
            SourceDocument(
                source_type=EvidenceSourceType.ESTIMATE,
                retrieval_status=SourceRetrievalStatus.FOUND,
                document_purpose=SourceDocumentPurpose.ESTIMATE,
                provider_status="found",
                ticker=clean_ticker,
                source_name="yfinance analyst estimates",
                title="Analyst estimate summary",
                retrieved_at=datetime.now(timezone.utc),
                text=text,
                text_excerpt=text,
                metadata={
                    "provider": "yfinance",
                    "provider_status": "found",
                    **serializable_payload,
                },
                source_confidence=EvidenceConfidence.MEDIUM,
            )
        ]
    except Exception as exc:
        return [_error_doc(clean_ticker, str(exc))]


def _to_serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_serializable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_serializable(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _not_found_doc(ticker: str, message: str) -> SourceDocument:
    return SourceDocument(
        source_type=EvidenceSourceType.ESTIMATE,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=SourceDocumentPurpose.ESTIMATE,
        provider_status="not_found",
        ticker=ticker,
        source_name="yfinance analyst estimates",
        retrieved_at=datetime.now(timezone.utc),
        error_message=message,
        source_confidence=EvidenceConfidence.LOW,
        notes=message,
        metadata={"provider": "yfinance", "provider_status": "not_found"},
    )


def _error_doc(ticker: str, message: str) -> SourceDocument:
    return SourceDocument(
        source_type=EvidenceSourceType.ESTIMATE,
        retrieval_status=SourceRetrievalStatus.ERROR,
        document_purpose=SourceDocumentPurpose.ESTIMATE,
        provider_status="error",
        ticker=ticker,
        source_name="yfinance analyst estimates",
        retrieved_at=datetime.now(timezone.utc),
        error_message=message,
        source_confidence=EvidenceConfidence.LOW,
        notes=message,
        metadata={"provider": "yfinance", "provider_status": "error"},
    )
