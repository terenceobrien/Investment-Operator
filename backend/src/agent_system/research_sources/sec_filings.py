"""SEC EDGAR retrieval scaffolding for single-name research context."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from html import unescape
from typing import Any
from urllib.request import Request, urlopen

from src.agent_system.schemas.deep_fundamental import (
    EvidenceConfidence,
    EvidenceSourceType,
    SourceDocument,
    SourceDocumentPurpose,
    SourceRetrievalStatus,
)


SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT",
    "HelixResearchContext/0.1 contact@example.com",
)
SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"
REQUEST_TIMEOUT_SECONDS = 12

_TICKER_CIK_CACHE: dict[str, str] | None = None


def get_cik_for_ticker(ticker: str) -> str | None:
    """Return a zero-padded 10-digit CIK for ticker, if found."""

    global _TICKER_CIK_CACHE
    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        return None

    if _TICKER_CIK_CACHE is None:
        try:
            data = _fetch_json(SEC_COMPANY_TICKERS_URL)
            _TICKER_CIK_CACHE = {
                str(item.get("ticker", "")).upper(): str(item.get("cik_str", "")).zfill(10)
                for item in data.values()
                if item.get("ticker") and item.get("cik_str")
            }
        except Exception:
            _TICKER_CIK_CACHE = {}
    return _TICKER_CIK_CACHE.get(clean_ticker)


def fetch_company_submissions(cik: str) -> dict[str, Any] | None:
    """Fetch SEC submissions JSON for a zero-padded CIK."""

    clean_cik = str(cik).strip().zfill(10)
    try:
        return _fetch_json(SEC_SUBMISSIONS_URL.format(cik=clean_cik))
    except Exception:
        return None


def find_latest_filing(cik: str, form_types: list[str]) -> SourceDocument | None:
    """Find the latest SEC filing for a CIK and form set."""

    clean_cik = str(cik).strip().zfill(10)
    submissions = fetch_company_submissions(clean_cik)
    if submissions is None:
        return _error_document(
            ticker="",
            cik=clean_cik,
            source_type=EvidenceSourceType.FILING,
            message="SEC submissions JSON could not be retrieved.",
        )

    ticker = _submission_ticker(submissions)
    filing = _latest_recent_filing(submissions, form_types)
    if filing is None:
        return _not_found_document(
            ticker=ticker,
            cik=clean_cik,
            source_type=EvidenceSourceType.FILING,
            message=f"No recent SEC filing found for forms: {', '.join(form_types)}.",
        )
    return _document_from_filing(
        ticker=ticker,
        cik=clean_cik,
        filing=filing,
        source_type=EvidenceSourceType.FILING,
        source_name="SEC EDGAR",
    )


def find_latest_10q_or_10k(ticker: str) -> SourceDocument | None:
    """Find the latest 10-Q or 10-K filing through SEC submissions."""

    clean_ticker = ticker.upper().strip()
    cik = get_cik_for_ticker(clean_ticker)
    if cik is None:
        return _not_found_document(
            ticker=clean_ticker,
            cik=None,
            source_type=EvidenceSourceType.FILING,
            message="CIK could not be resolved from SEC ticker mapping.",
        )
    return find_latest_filing(cik, ["10-Q", "10-K"])


def find_latest_8k_earnings_release(ticker: str) -> SourceDocument | None:
    """Return the newest 8-K exhibit confidently classified as earnings release."""

    docs = find_recent_8k_exhibits(ticker, max_filings=20, max_documents=40)
    for doc in docs:
        if (
            doc.retrieval_status == SourceRetrievalStatus.FOUND
            and doc.document_purpose == SourceDocumentPurpose.EARNINGS_RELEASE
            and doc.classification_confidence
            in {EvidenceConfidence.MEDIUM, EvidenceConfidence.HIGH}
        ):
            return doc

    clean_ticker = ticker.upper().strip()
    cik = get_cik_for_ticker(clean_ticker)
    return _not_found_document(
        ticker=clean_ticker,
        cik=cik,
        source_type=EvidenceSourceType.SEC_8K_EXHIBIT,
        message="No recent SEC 8-K exhibit confidently classified as earnings release.",
        document_purpose=SourceDocumentPurpose.EARNINGS_RELEASE,
    )


def find_recent_8k_exhibits(
    ticker: str,
    max_filings: int = 10,
    max_documents: int = 20,
) -> list[SourceDocument]:
    """Return classified recent 8-K exhibit documents across purposes."""

    clean_ticker = ticker.upper().strip()
    cik = get_cik_for_ticker(clean_ticker)
    if cik is None:
        return [
            _not_found_document(
                ticker=clean_ticker,
                cik=None,
                source_type=EvidenceSourceType.SEC_8K_EXHIBIT,
                message="CIK could not be resolved from SEC ticker mapping.",
            )
        ]

    submissions = fetch_company_submissions(cik)
    if submissions is None:
        return [
            _error_document(
                ticker=clean_ticker,
                cik=cik,
                source_type=EvidenceSourceType.SEC_8K_EXHIBIT,
                message="SEC submissions JSON could not be retrieved.",
            )
        ]

    docs: list[SourceDocument] = []
    filings_seen = 0
    for filing in _recent_filings(submissions):
        if filing.get("form") != "8-K":
            continue
        filings_seen += 1
        docs.extend(_classified_8k_exhibits(clean_ticker, cik, filing))
        if filings_seen >= max_filings or len(docs) >= max_documents:
            break

    found_docs = [
        doc for doc in docs
        if doc.retrieval_status == SourceRetrievalStatus.FOUND
    ]
    if found_docs:
        return found_docs[:max_documents]
    return [
        _not_found_document(
            ticker=clean_ticker,
            cik=cik,
            source_type=EvidenceSourceType.SEC_8K_EXHIBIT,
            message="No recent SEC 8-K exhibits could be retrieved.",
        )
    ]


def classify_8k_exhibit_document(
    *,
    title: str | None,
    source_url: str | None,
    text_excerpt: str | None,
    form_items: list[str] | None = None,
    exhibit_type: str | None = None,
) -> tuple[SourceDocumentPurpose, EvidenceConfidence, str]:
    """Classify a retrieved 8-K exhibit by document purpose."""

    title_text = (title or "").lower()
    url_text = (source_url or "").lower()
    excerpt_text = (text_excerpt or "").lower()
    combined = " ".join([title_text, url_text, excerpt_text])
    form_items = form_items or []

    stress_terms = [
        "dfast",
        "stress test",
        "stress capital buffer",
        " scb",
        "cet1",
        "ccar",
        "severely adverse scenario",
        "projected minimum capital",
        "basel iii",
        "risk-weighted assets",
        " rwa",
        "capital ratios",
        "federal reserve stress",
    ]
    regulatory_terms = [
        "regulatory capital",
        "capital plan",
        "capital requirements",
        "capital distribution",
        "common equity tier",
    ]
    transaction_terms = [
        "transaction",
        "merger",
        "acquisition",
        "divestiture",
        "spin-off",
        "spinoff",
        "split-off",
        "splitoff",
        "reverse morris trust",
        " rmt",
        "definitive agreement",
        "combine with",
        "shareholder approval",
        "regulatory clearances",
        "closing conditions",
        "purchase price",
        "enterprise value",
        "synergies",
    ]
    presentation_terms = [
        "investor presentation",
        "investor day",
        "slide deck",
        "conference presentation",
    ]
    earnings_title_terms = [
        "earnings",
        "quarterly results",
        "financial results",
        "fiscal q",
        "quarter ended",
        "reports first quarter",
        "reports second quarter",
        "reports third quarter",
        "reports fourth quarter",
        "business outlook",
    ]
    earnings_markers = [
        "revenue",
        "gross margin",
        "operating income",
        "net income",
        "diluted earnings per share",
        "diluted eps",
        " eps",
        "cash flow",
        "guidance",
        "business outlook",
    ]

    stress_score = _term_count(combined, stress_terms)
    if stress_score:
        return (
            SourceDocumentPurpose.STRESS_TEST,
            EvidenceConfidence.HIGH if stress_score >= 2 else EvidenceConfidence.MEDIUM,
            "Classified as stress-test/regulatory capital disclosure due to DFAST, SCB, CET1, CCAR, or Federal Reserve stress-test language.",
        )

    regulatory_score = _term_count(combined, regulatory_terms)
    if regulatory_score >= 2:
        return (
            SourceDocumentPurpose.REGULATORY_CAPITAL,
            EvidenceConfidence.MEDIUM,
            "Classified as regulatory-capital disclosure due to repeated capital-plan or capital-requirement language.",
        )

    transaction_score = _term_count(combined, transaction_terms)
    if transaction_score >= 2:
        return (
            SourceDocumentPurpose.STRATEGIC_TRANSACTION,
            EvidenceConfidence.HIGH if transaction_score >= 4 else EvidenceConfidence.MEDIUM,
            "Classified as strategic transaction because merger/acquisition/divestiture/RMT/deal terms dominate the document.",
        )

    presentation_score = _term_count(combined, presentation_terms)
    if presentation_score:
        return (
            SourceDocumentPurpose.INVESTOR_PRESENTATION,
            EvidenceConfidence.MEDIUM,
            "Classified as investor presentation based on title or exhibit language.",
        )

    item_202 = any(item.strip() == "2.02" for item in form_items)
    title_score = _term_count(title_text, earnings_title_terms)
    marker_score = _term_count(excerpt_text, earnings_markers)
    earnings_score = (2 if item_202 else 0) + title_score + min(marker_score, 5)
    negative_score = transaction_score + stress_score + regulatory_score
    if earnings_score >= 4 and earnings_score > negative_score + 1:
        return (
            SourceDocumentPurpose.EARNINGS_RELEASE,
            EvidenceConfidence.HIGH if item_202 and marker_score >= 3 else EvidenceConfidence.MEDIUM,
            "Classified as earnings release because Item 2.02 and/or multiple financial-results markers dominate the exhibit.",
        )

    debt_terms = [
        "notes offering",
        "senior notes",
        "debt securities",
        "indenture",
        "credit agreement",
        "term loan",
        "revolving credit facility",
    ]
    if _term_count(combined, debt_terms):
        return (
            SourceDocumentPurpose.OTHER,
            EvidenceConfidence.MEDIUM,
            "Classified as other 8-K exhibit; debt or capital-markets document is not an earnings release.",
        )

    return (
        SourceDocumentPurpose.OTHER,
        EvidenceConfidence.LOW,
        "Could not classify exhibit as earnings release, strategic transaction, stress test, regulatory capital, or presentation.",
    )


def _classified_8k_exhibits(
    ticker: str,
    cik: str,
    filing: dict[str, Any],
) -> list[SourceDocument]:
    accession = str(filing.get("accessionNumber") or "")
    accession_no_dashes = accession.replace("-", "")
    cik_no_pad = str(int(cik))
    index_url = (
        f"{SEC_ARCHIVES_BASE}/{cik_no_pad}/{accession_no_dashes}/index.json"
    )
    try:
        index = _fetch_json(index_url)
    except Exception:
        return []

    docs: list[SourceDocument] = []
    items = ((index.get("directory") or {}).get("item") or [])
    form_items = _form_items(filing)
    for item in items:
        name = str(item.get("name") or "")
        lower = name.lower()
        if not name or not lower.endswith((".htm", ".html", ".txt")):
            continue
        if lower.endswith((".xml", ".xsd")) or lower.startswith("r"):
            continue
        url = f"{SEC_ARCHIVES_BASE}/{cik_no_pad}/{accession_no_dashes}/{name}"
        text = _fetch_url_text(url)
        excerpt = _excerpt(text)
        exhibit_type = "99.1" if "99" in lower else None
        purpose, confidence, rationale = classify_8k_exhibit_document(
            title=name,
            source_url=url,
            text_excerpt=excerpt,
            form_items=form_items,
            exhibit_type=exhibit_type,
        )
        docs.append(SourceDocument(
            source_type=EvidenceSourceType.SEC_8K_EXHIBIT,
            retrieval_status=SourceRetrievalStatus.FOUND,
            document_purpose=purpose,
            classification_confidence=confidence,
            classification_rationale=rationale,
            ticker=ticker,
            source_name="SEC EDGAR",
            title=f"8-K exhibit: {name}",
            source_date=_parse_date(filing.get("filingDate")),
            retrieved_at=datetime.now(timezone.utc),
            source_url=url,
            accession_number=accession,
            cik=cik,
            form_type="8-K",
            exhibit_type=exhibit_type,
            text=text,
            text_excerpt=excerpt,
            metadata={
                "primary_document": filing.get("primaryDocument"),
                "items": filing.get("items"),
                "document_purpose": purpose.value,
            },
            source_confidence=confidence,
        ))
    return docs


def _document_from_filing(
    *,
    ticker: str,
    cik: str,
    filing: dict[str, Any],
    source_type: EvidenceSourceType,
    source_name: str,
) -> SourceDocument:
    accession = str(filing.get("accessionNumber") or "")
    accession_no_dashes = accession.replace("-", "")
    primary_doc = str(filing.get("primaryDocument") or "")
    cik_no_pad = str(int(cik))
    url = (
        f"{SEC_ARCHIVES_BASE}/{cik_no_pad}/{accession_no_dashes}/{primary_doc}"
        if primary_doc
        else None
    )
    form_type = str(filing.get("form") or "")
    text = _fetch_url_text(url, form_type=form_type) if url else None
    purpose = (
        SourceDocumentPurpose.QUARTERLY_FILING
        if form_type == "10-Q"
        else SourceDocumentPurpose.ANNUAL_FILING
        if form_type == "10-K"
        else SourceDocumentPurpose.OTHER
    )
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.FOUND,
        document_purpose=purpose,
        classification_confidence=EvidenceConfidence.HIGH,
        classification_rationale=f"SEC filing form type is {form_type}.",
        ticker=ticker,
        source_name=source_name,
        title=str(filing.get("primaryDocDescription") or filing.get("form") or ""),
        source_date=_parse_date(filing.get("filingDate")),
        retrieved_at=datetime.now(timezone.utc),
        source_url=url,
        accession_number=accession,
        cik=cik,
        form_type=form_type,
        text=text,
        text_excerpt=_excerpt(text),
        metadata={
            "report_date": filing.get("reportDate"),
            "items": filing.get("items"),
            "primary_document": primary_doc,
            "document_purpose": purpose.value,
            "cleaning_notes": (
                "Filing text cleaned to reduce XBRL/taxonomy noise and prefer "
                "readable MD&A, risk, liquidity, and segment sections."
            ),
        },
        source_confidence=EvidenceConfidence.HIGH,
    )


def _fetch_json(url: str) -> dict[str, Any]:
    raw = _fetch_bytes(url)
    return json.loads(raw.decode("utf-8"))


def _fetch_url_text(url: str | None, form_type: str | None = None) -> str | None:
    if not url:
        return None
    try:
        raw = _fetch_bytes(url)
        text = raw.decode("utf-8", errors="replace")
        if form_type in {"10-Q", "10-K"}:
            return clean_sec_filing_text(text, form_type)
        return _clean_sec_text(text)
    except Exception:
        return None


def _fetch_bytes(url: str) -> bytes:
    time.sleep(0.12)
    req = Request(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept-Encoding": "identity",
        },
    )
    with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return response.read()


def _clean_sec_text(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def clean_sec_filing_text(raw_html_or_text: str, form_type: str) -> str:
    """Clean SEC 10-Q/K text, suppressing inline-XBRL/taxonomy noise."""

    text = re.sub(r"<script.*?</script>", " ", raw_html_or_text, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<ix:[^>]+>.*?</ix:[^>]+>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in text.splitlines()
    ]
    noise_markers = (
        "us-gaap:",
        "dei:",
        "iso4217:",
        "xbrli:",
        "contextref",
        "decimals=",
        "unitref",
        "segmentmember",
        "axis",
        " member",
        "schemaref",
        "linkbase",
        "ix:",
    )
    readable_lines: list[str] = []
    for line in lines:
        if len(line) < 20:
            continue
        lower = line.lower()
        if any(marker in lower for marker in noise_markers):
            continue
        alpha_count = sum(char.isalpha() for char in line)
        if alpha_count / max(len(line), 1) < 0.45:
            continue
        readable_lines.append(line)

    clean_text = "\n".join(readable_lines)
    sections = extract_filing_sections(clean_text, form_type)
    if sections:
        ordered = [
            f"{name}\n{text}"
            for name, text in sections.items()
            if text.strip()
        ]
        return "\n\n".join(ordered)[:120_000]
    return re.sub(r"\n{3,}", "\n\n", clean_text).strip()[:120_000]


def extract_filing_sections(clean_text: str, form_type: str) -> dict[str, str]:
    """Extract high-signal readable filing sections when headings are present."""

    if not clean_text:
        return {}
    wanted = (
        [
            "item 1. business",
            "item 1a. risk factors",
            "item 7. management",
            "liquidity and capital resources",
            "results of operations",
            "segment",
        ]
        if form_type == "10-K"
        else [
            "item 2. management",
            "item 3. quantitative",
            "item 1. financial statements",
            "liquidity and capital resources",
            "results of operations",
            "segment",
            "risk factors",
        ]
    )
    lower = clean_text.lower()
    starts: list[tuple[int, str]] = []
    for heading in wanted:
        index = lower.find(heading)
        if index >= 0:
            starts.append((index, heading.title()))
    starts = sorted(starts)
    sections: dict[str, str] = {}
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else start + 30_000
        section = clean_text[start:end].strip()
        if len(section) >= 200:
            sections[name] = section[:30_000]
    return sections


def _recent_filings(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    filings: list[dict[str, Any]] = []
    for index, form in enumerate(forms):
        filing: dict[str, Any] = {}
        for key, values in recent.items():
            if isinstance(values, list) and index < len(values):
                filing[key] = values[index]
        filing["form"] = form
        filings.append(filing)
    return filings


def _form_items(filing: dict[str, Any]) -> list[str]:
    raw_items = str(filing.get("items") or "")
    return [
        item.strip()
        for item in re.split(r"[,;\s]+", raw_items)
        if item.strip()
    ]


def _term_count(text: str, terms: list[str]) -> int:
    count = 0
    for term in terms:
        clean = term.lower().strip()
        if clean and clean in text:
            count += 1
    return count


def _latest_recent_filing(
    submissions: dict[str, Any],
    form_types: list[str],
) -> dict[str, Any] | None:
    wanted = {form.upper() for form in form_types}
    for filing in _recent_filings(submissions):
        if str(filing.get("form", "")).upper() in wanted:
            return filing
    return None


def _submission_ticker(submissions: dict[str, Any]) -> str:
    tickers = submissions.get("tickers") or []
    if tickers:
        return str(tickers[0]).upper()
    return str(submissions.get("ticker") or "").upper()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _excerpt(text: str | None, limit: int = 2500) -> str | None:
    if not text:
        return None
    return text[:limit]


def _not_found_document(
    *,
    ticker: str,
    cik: str | None,
    source_type: EvidenceSourceType,
    message: str,
    document_purpose: SourceDocumentPurpose = SourceDocumentPurpose.UNKNOWN,
) -> SourceDocument:
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.NOT_FOUND,
        document_purpose=document_purpose,
        ticker=ticker.upper().strip(),
        source_name="SEC EDGAR",
        retrieved_at=datetime.now(timezone.utc),
        cik=cik,
        error_message=message,
        source_confidence=EvidenceConfidence.HIGH,
    )


def _error_document(
    *,
    ticker: str,
    cik: str | None,
    source_type: EvidenceSourceType,
    message: str,
) -> SourceDocument:
    return SourceDocument(
        source_type=source_type,
        retrieval_status=SourceRetrievalStatus.ERROR,
        ticker=ticker.upper().strip(),
        source_name="SEC EDGAR",
        retrieved_at=datetime.now(timezone.utc),
        cik=cik,
        error_message=message,
        source_confidence=EvidenceConfidence.MEDIUM,
    )
