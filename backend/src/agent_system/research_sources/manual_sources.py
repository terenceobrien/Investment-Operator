"""Manual/local source ingestion for research context packs."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    make_error_source_document,
)
from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".html", ".htm"}


class ManualSourceProvider:
    provider_name = "Manual"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        clean_ticker = ticker.upper().strip()
        docs: list[SourceDocument] = []

        for path in options.transcript_paths:
            docs.append(_load_path(
                clean_ticker,
                path,
                source_type=EvidenceSourceType.TRANSCRIPT,
                purpose=SourceDocumentPurpose.TRANSCRIPT,
                source_name="Manual transcript",
                confidence=EvidenceConfidence.HIGH,
            ))
        for path in options.earnings_release_paths:
            docs.append(_load_path(
                clean_ticker,
                path,
                source_type=EvidenceSourceType.COMPANY_IR,
                purpose=SourceDocumentPurpose.EARNINGS_RELEASE,
                source_name="Manual earnings release",
                confidence=EvidenceConfidence.HIGH,
            ))
        for path in options.news_source_paths:
            docs.append(_load_path(
                clean_ticker,
                path,
                source_type=EvidenceSourceType.NEWS,
                purpose=SourceDocumentPurpose.NEWS,
                source_name="Manual news source",
                confidence=EvidenceConfidence.MEDIUM,
            ))
        for path in options.manual_source_paths:
            docs.append(_load_path(
                clean_ticker,
                path,
                source_type=None,
                purpose=None,
                source_name="Manual source",
                confidence=EvidenceConfidence.MEDIUM,
            ))
        for url in options.manual_source_urls:
            docs.append(_load_url(clean_ticker, url))

        return docs


def _load_path(
    ticker: str,
    path: str | Path,
    *,
    source_type: EvidenceSourceType | None,
    purpose: SourceDocumentPurpose | None,
    source_name: str,
    confidence: EvidenceConfidence,
) -> SourceDocument:
    source_path = Path(path)
    if not source_path.exists():
        return make_error_source_document(
            ticker=ticker,
            source_type=source_type or EvidenceSourceType.OTHER,
            document_purpose=purpose or SourceDocumentPurpose.UNKNOWN,
            source_name=source_name,
            message=f"Manual source path does not exist: {source_path}",
        )

    if source_path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
        return make_error_source_document(
            ticker=ticker,
            source_type=source_type or EvidenceSourceType.OTHER,
            document_purpose=purpose or SourceDocumentPurpose.UNKNOWN,
            source_name=source_name,
            message=(
                f"Unsupported manual source extension {source_path.suffix!r}; "
                "v1 supports txt, md, html, and htm."
            ),
        )

    try:
        raw = source_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = source_path.read_text(encoding="latin-1")
    except Exception as exc:
        return make_error_source_document(
            ticker=ticker,
            source_type=source_type or EvidenceSourceType.OTHER,
            document_purpose=purpose or SourceDocumentPurpose.UNKNOWN,
            source_name=source_name,
            message=f"Manual source read failed: {exc}",
        )

    text = _html_to_text(raw) if source_path.suffix.lower() in {".html", ".htm"} else raw
    inferred_purpose = purpose or _infer_purpose(source_path.name, text[:2500])
    inferred_source_type = source_type or _source_type_for_purpose(inferred_purpose)
    return SourceDocument(
        source_type=inferred_source_type,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=inferred_purpose,
        ticker=ticker,
        source_name=source_name,
        title=source_path.name,
        retrieved_at=datetime.now(timezone.utc),
        source_url=str(source_path),
        text=text,
        text_excerpt=text[:2500],
        metadata={"provider": "Manual", "path": str(source_path)},
        source_confidence=confidence,
    )


def _load_url(ticker: str, url: str) -> SourceDocument:
    try:
        req = Request(url, headers={"User-Agent": "HelixResearchContext/0.1"})
        with urlopen(req, timeout=12) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        return make_error_source_document(
            ticker=ticker,
            source_type=EvidenceSourceType.OTHER,
            document_purpose=SourceDocumentPurpose.UNKNOWN,
            source_name="Manual URL source",
            message=f"Manual URL fetch failed: {exc}",
        )

    text = _html_to_text(raw)
    purpose = _infer_purpose(url, text[:2500])
    return SourceDocument(
        source_type=_source_type_for_purpose(purpose),
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=purpose,
        ticker=ticker,
        source_name="Manual URL source",
        title=url.rsplit("/", 1)[-1] or url,
        retrieved_at=datetime.now(timezone.utc),
        source_url=url,
        text=text,
        text_excerpt=text[:2500],
        metadata={"provider": "Manual", "url": url},
        source_confidence=EvidenceConfidence.MEDIUM,
    )


def _infer_purpose(name: str, text_excerpt: str) -> SourceDocumentPurpose:
    haystack = f"{name} {text_excerpt}".lower()
    if "transcript" in haystack or "earnings call" in haystack:
        return SourceDocumentPurpose.TRANSCRIPT
    if any(term in haystack for term in ("earnings", "release", "results", "quarterly results")):
        return SourceDocumentPurpose.EARNINGS_RELEASE
    if "presentation" in haystack or "investor day" in haystack:
        return SourceDocumentPurpose.INVESTOR_PRESENTATION
    if "news" in haystack or "press" in haystack or "headline" in haystack:
        return SourceDocumentPurpose.NEWS
    return SourceDocumentPurpose.OTHER


def _source_type_for_purpose(purpose: SourceDocumentPurpose) -> EvidenceSourceType:
    if purpose == SourceDocumentPurpose.TRANSCRIPT:
        return EvidenceSourceType.TRANSCRIPT
    if purpose == SourceDocumentPurpose.NEWS:
        return EvidenceSourceType.NEWS
    if purpose == SourceDocumentPurpose.INVESTOR_PRESENTATION:
        return EvidenceSourceType.INVESTOR_PRESENTATION
    if purpose == SourceDocumentPurpose.EARNINGS_RELEASE:
        return EvidenceSourceType.COMPANY_IR
    return EvidenceSourceType.OTHER


def _html_to_text(value: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()
