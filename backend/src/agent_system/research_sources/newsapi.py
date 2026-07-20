"""NewsAPI source provider for company news snippets."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.agent_system.research_sources.config import NEWS_API_KEY_ENV
from src.agent_system.research_sources.base import (
    ResearchSourceOptions,
    make_error_source_document,
    make_skipped_source_document,
    normalize_provider_date,
    sanitize_provider_message,
    truncate_source_text,
)
from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


NEWSAPI_URL = "https://newsapi.org/v2/everything"
NEWSAPI_TIMEOUT_SECONDS = 15


class NewsAPICompanyNewsProvider:
    provider_name = "NewsAPI"

    async def fetch(
        self,
        *,
        ticker: str,
        company_profile: Any | None,
        options: ResearchSourceOptions,
    ) -> list[SourceDocument]:
        clean_ticker = ticker.upper().strip()
        api_key = os.getenv(NEWS_API_KEY_ENV)
        if not api_key:
            return [
                make_skipped_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.NEWS,
                    document_purpose=SourceDocumentPurpose.NEWS,
                    source_name="NewsAPI company news",
                    message=f"{NEWS_API_KEY_ENV} not configured.",
                    provider_status="skipped_no_key",
                )
            ]
        try:
            from_date = options.as_of_date - timedelta(days=options.lookback_days)
            query = _build_query(clean_ticker, company_profile)
            payload = _newsapi_get_json(
                {
                    "q": query,
                    "from": from_date.isoformat(),
                    "to": options.as_of_date.isoformat(),
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": options.max_news_items,
                },
                api_key=api_key,
            )
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            docs = [
                _doc_from_article(
                    clean_ticker,
                    article,
                    total_results=payload.get("totalResults")
                    if isinstance(payload, dict)
                    else None,
                )
                for article in articles
                if isinstance(article, dict)
            ]
            docs = _dedupe_docs(docs)
            if docs:
                return docs[:options.max_news_items]
            return [
                SourceDocument(
                    source_type=EvidenceSourceType.NEWS,
                    retrieval_status=SourceRetrievalStatus.NOT_FOUND,
                    document_purpose=SourceDocumentPurpose.NEWS,
                    ticker=clean_ticker,
                    source_name="NewsAPI company news",
                    retrieved_at=datetime.now(timezone.utc),
                    error_message="No NewsAPI company-news articles returned.",
                    source_confidence=EvidenceConfidence.LOW,
                    metadata={"provider": "NewsAPI", "query": query},
                    provider_status="not_found",
                )
            ]
        except Exception as exc:
            return [
                make_error_source_document(
                    ticker=clean_ticker,
                    source_type=EvidenceSourceType.NEWS,
                    document_purpose=SourceDocumentPurpose.NEWS,
                    source_name="NewsAPI company news",
                    message=(
                        "NewsAPI retrieval failed: "
                        f"{sanitize_provider_message(str(exc))}"
                    ),
                    provider_status="error",
                )
            ]


def _newsapi_get_json(params: dict[str, Any], *, api_key: str) -> dict[str, Any]:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    req = Request(
        f"{NEWSAPI_URL}?{query}",
        headers={
            "User-Agent": "HelixResearchContext/0.1",
            "X-Api-Key": api_key,
        },
    )
    with urlopen(req, timeout=NEWSAPI_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _build_query(ticker: str, company_profile: Any | None) -> str:
    company_name = getattr(company_profile, "company_name", None) if company_profile else None
    aliases = getattr(company_profile, "aliases", None) if company_profile else None
    terms: list[str] = []
    if company_name:
        terms.append(f'"{company_name}"')
        short_name = str(company_name).replace(" Inc.", "").replace(" Corporation", "").replace(" Corp.", "")
        if short_name and short_name != company_name:
            terms.append(short_name)
    if aliases:
        terms.extend(str(alias) for alias in aliases[:3] if alias)
    if not terms:
        terms.append(ticker)
    elif ticker not in {"A", "AA", "C", "F", "T"}:
        terms.append(ticker)
    return " OR ".join(terms)


def _doc_from_article(
    ticker: str,
    article: dict[str, Any],
    *,
    total_results: int | None = None,
) -> SourceDocument:
    title = article.get("title")
    description = article.get("description")
    content = article.get("content")
    text_parts = [part for part in (title, description, content) if part]
    text = "\n".join(str(part) for part in text_parts)
    snippet_only_note = "Headline/snippet-only news evidence; full article body may be unavailable."
    source = article.get("source") or {}
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.NEWS,
        provider_status="found",
        ticker=ticker,
        source_name=source.get("name") or "NewsAPI company news",
        title=title,
        source_date=normalize_provider_date(article.get("publishedAt")),
        retrieved_at=datetime.now(timezone.utc),
        source_url=article.get("url"),
        text=text or None,
        text_excerpt=truncate_source_text(text, 1500),
        metadata={
            "provider": "NewsAPI",
            "author": article.get("author"),
            "source": source,
            "source_id": source.get("id"),
            "source_name": source.get("name"),
            "publishedAt": article.get("publishedAt"),
            "total_results": total_results,
            "sort": "publishedAt",
            "urlToImage": article.get("urlToImage"),
            "snippet_only": True,
            "body_availability": snippet_only_note,
            "notes": snippet_only_note,
        },
        source_confidence=(
            EvidenceConfidence.MEDIUM
            if description or content
            else EvidenceConfidence.LOW
        ),
    )


def _dedupe_docs(docs: list[SourceDocument]) -> list[SourceDocument]:
    seen: set[tuple[str, str]] = set()
    result: list[SourceDocument] = []
    for doc in docs:
        key = (
            (doc.source_url or "").strip().lower().rstrip("/"),
            " ".join((doc.title or "").lower().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result
