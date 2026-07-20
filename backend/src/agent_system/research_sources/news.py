"""News source scaffolding for research context packs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


def fetch_recent_news(
    ticker: str,
    company_name: str | None,
    days: int = 30,
) -> list[SourceDocument]:
    """Fetch recent headlines/snippets when a news API key is configured."""

    clean_ticker = ticker.upper().strip()
    news_api_key = os.getenv("NEWS_API_KEY")
    newsdata_key = os.getenv("NEWSDATA_API_KEY")
    if news_api_key:
        return _fetch_newsapi(clean_ticker, company_name, days, news_api_key)
    if newsdata_key:
        return _fetch_newsdata(clean_ticker, company_name, days, newsdata_key)
    return [
        SourceDocument(
            source_type=EvidenceSourceType.NEWS,
            retrieval_status=SourceRetrievalStatus.SKIPPED,
            document_purpose=SourceDocumentPurpose.NEWS,
            ticker=clean_ticker,
            source_name="News",
            retrieved_at=datetime.now(timezone.utc),
            error_message=(
                "News retrieval skipped; NEWS_API_KEY or NEWSDATA_API_KEY is "
                "not configured."
            ),
            source_confidence=EvidenceConfidence.LOW,
        )
    ]


def _fetch_newsapi(
    ticker: str,
    company_name: str | None,
    days: int,
    api_key: str,
) -> list[SourceDocument]:
    query = quote_plus(f"{ticker} OR \"{company_name}\"" if company_name else ticker)
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    url = (
        "https://newsapi.org/v2/everything?"
        f"q={query}&from={from_date}&language=en&sortBy=publishedAt&pageSize=8"
    )
    try:
        payload = _fetch_json(url, {"X-Api-Key": api_key})
        docs = [
            _news_doc_from_article(ticker, "NewsAPI", article)
            for article in payload.get("articles", [])
        ]
        return docs or [_not_found_doc(ticker, "NewsAPI")]
    except Exception as exc:
        return [_error_doc(ticker, "NewsAPI", str(exc))]


def _fetch_newsdata(
    ticker: str,
    company_name: str | None,
    days: int,
    api_key: str,
) -> list[SourceDocument]:
    query = quote_plus(f"{ticker} {company_name or ''}".strip())
    url = f"https://newsdata.io/api/1/news?apikey={api_key}&q={query}&language=en"
    try:
        payload = _fetch_json(url, {})
        docs = [
            _newsdata_doc_from_article(ticker, article)
            for article in payload.get("results", [])[:8]
        ]
        return docs or [_not_found_doc(ticker, "NewsData")]
    except Exception as exc:
        return [_error_doc(ticker, "NewsData", str(exc))]


def _fetch_json(url: str, headers: dict[str, str]) -> dict:
    req = Request(url, headers=headers)
    with urlopen(req, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def _news_doc_from_article(
    ticker: str,
    source_name: str,
    article: dict,
) -> SourceDocument:
    text = " ".join(
        str(part)
        for part in [
            article.get("title"),
            article.get("description"),
            article.get("content"),
        ]
        if part
    )
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.NEWS,
        ticker=ticker,
        source_name=(article.get("source") or {}).get("name") or source_name,
        title=article.get("title"),
        source_date=_parse_date(article.get("publishedAt")),
        retrieved_at=datetime.now(timezone.utc),
        source_url=article.get("url"),
        text=text or None,
        text_excerpt=(text or "")[:1500] or None,
        metadata={"provider": source_name},
        source_confidence=EvidenceConfidence.LOW,
    )


def _newsdata_doc_from_article(ticker: str, article: dict) -> SourceDocument:
    text = " ".join(
        str(part)
        for part in [article.get("title"), article.get("description")]
        if part
    )
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=SourceDocumentPurpose.NEWS,
        ticker=ticker,
        source_name=article.get("source_id") or "NewsData",
        title=article.get("title"),
        source_date=_parse_date(article.get("pubDate")),
        retrieved_at=datetime.now(timezone.utc),
        source_url=article.get("link"),
        text=text or None,
        text_excerpt=(text or "")[:1500] or None,
        metadata={"provider": "NewsData"},
        source_confidence=EvidenceConfidence.LOW,
    )


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _not_found_doc(ticker: str, source_name: str) -> SourceDocument:
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=SourceDocumentPurpose.NEWS,
        ticker=ticker,
        source_name=source_name,
        retrieved_at=datetime.now(timezone.utc),
        error_message="No recent news items were returned.",
        source_confidence=EvidenceConfidence.LOW,
    )


def _error_doc(ticker: str, source_name: str, message: str) -> SourceDocument:
    return SourceDocument(
        source_type=EvidenceSourceType.NEWS,
        retrieval_status=SourceRetrievalStatus.ERROR,
        document_purpose=SourceDocumentPurpose.NEWS,
        ticker=ticker,
        source_name=source_name,
        retrieved_at=datetime.now(timezone.utc),
        error_message=message,
        source_confidence=EvidenceConfidence.LOW,
    )
