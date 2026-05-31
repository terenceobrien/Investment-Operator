"""SEC EDGAR retrieval and conservative XBRL/filing-text extraction."""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from datetime import date, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.agent_system.data.cache import cache_get, cache_set
from src.agent_system.data.types import AnnualRevenueRecord, CompanyFacts, FilingExtract

logger = logging.getLogger("agent_system.data.sec")

SEC_USER_AGENT = "AI Financial Operator research@helixintel.io"
_SEC_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_REQUEST_INTERVAL_SECONDS = 0.1
_rate_lock = threading.Lock()
_last_request_at = 0.0

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_FILING_EXTRACTION_VERSION = "v2"

_FLOW_TAGS = {
    "revenue_ttm": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "gross_profit_ttm": ["GrossProfit"],
    "operating_income_ttm": ["OperatingIncomeLoss"],
    "net_income_ttm": ["NetIncomeLoss", "ProfitLoss"],
    "operating_cash_flow_ttm": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex_ttm": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "depreciation_amortization_ttm": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
}
_POINT_IN_TIME_TAGS = {
    "total_assets": ["Assets"],
    "cash_and_equivalents": ["CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "stockholders_equity": ["StockholdersEquity"],
}


def _rate_limited_get(url: str) -> requests.Response:
    global _last_request_at
    with _rate_lock:
        wait = _REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        response = requests.get(url, headers=_SEC_HEADERS, timeout=20)
        _last_request_at = time.monotonic()
    response.raise_for_status()
    return response


def _fetch_json(url: str) -> dict:
    try:
        payload = _rate_limited_get(url).json()
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.warning("SEC JSON fetch failed for %s: %s", url, exc)
        return {}


def ticker_to_cik(ticker: str, *, force_refresh: bool = False) -> str | None:
    """Map a ticker to a zero-padded CIK using SEC's published ticker file."""

    mapping = None if force_refresh else cache_get(
        "sec_ticker_map", "company_tickers", timedelta(days=30)
    )
    if mapping is None:
        mapping = _fetch_json(_TICKER_MAP_URL)
        if mapping:
            cache_set("sec_ticker_map", "company_tickers", mapping)

    lookup = ticker.strip().upper()
    candidates = {lookup, lookup.replace(".", "-")}
    for entry in mapping.values() if isinstance(mapping, dict) else []:
        if str(entry.get("ticker", "")).upper() in candidates:
            try:
                return str(int(entry["cik_str"])).zfill(10)
            except (KeyError, TypeError, ValueError):
                return None
    return None


def fetch_submissions(cik: str, *, force_refresh: bool = False) -> dict:
    """Fetch a company's EDGAR submissions JSON, cached for one day."""

    if not force_refresh:
        cached = cache_get("sec_submissions", cik, timedelta(days=1))
        if cached is not None:
            return cached
    fresh = _fetch_json(_SUBMISSIONS_URL.format(cik=cik))
    if fresh:
        cache_set("sec_submissions", cik, fresh)
    return fresh


def fetch_company_facts(cik: str, *, force_refresh: bool = False) -> dict:
    """Fetch a company's XBRL facts JSON, cached for one day."""

    if not force_refresh:
        cached = cache_get("sec_facts", cik, timedelta(days=1))
        if cached is not None:
            return cached
    fresh = _fetch_json(_FACTS_URL.format(cik=cik))
    if fresh:
        cache_set("sec_facts", cik, fresh)
    return fresh


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _entries_for_tag(raw_facts: dict, tag_candidates: list[str]) -> list[dict]:
    gaap = raw_facts.get("facts", {}).get("us-gaap", {})
    choices: list[tuple[date, int, list[dict]]] = []
    for priority, tag in enumerate(tag_candidates):
        tag_data = gaap.get(tag)
        if not isinstance(tag_data, dict):
            continue
        units = tag_data.get("units", {})
        entries = units.get("USD") if isinstance(units, dict) else None
        if not isinstance(entries, list):
            continue
        valid = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("val"), (int, float))
            and _parse_date(entry.get("end")) is not None
        ]
        if valid:
            latest_end = max(_parse_date(entry["end"]) for entry in valid)
            choices.append((latest_end, -priority, valid))
    if not choices:
        return []
    return max(choices, key=lambda choice: (choice[0], choice[1]))[2]


def _sort_entries(entries: list[dict]) -> list[dict]:
    return sorted(
        entries,
        key=lambda entry: (
            _parse_date(entry.get("end")) or date.min,
            _parse_date(entry.get("filed")) or date.min,
        ),
        reverse=True,
    )


def _quarter_entries(entries: list[dict]) -> list[dict]:
    latest_by_end: dict[date, dict] = {}
    for entry in _sort_entries(entries):
        end = _parse_date(entry.get("end"))
        start = _parse_date(entry.get("start"))
        frame = str(entry.get("frame", ""))
        duration = (end - start).days if end and start else None
        is_quarter = bool(re.search(r"CY\d{4}Q[1-4](?!I)", frame)) or (
            str(entry.get("fp", "")).upper() in {"Q1", "Q2", "Q3", "Q4"}
            and duration is not None
            and duration <= 110
        )
        if is_quarter and end not in latest_by_end:
            latest_by_end[end] = entry
    return _sort_entries(list(latest_by_end.values()))


def _annual_entries(entries: list[dict]) -> list[dict]:
    annual = []
    for entry in entries:
        end = _parse_date(entry.get("end"))
        start = _parse_date(entry.get("start"))
        duration = (end - start).days if end and start else None
        if str(entry.get("fp", "")).upper() == "FY" or (
            duration is not None and duration >= 300
        ):
            annual.append(entry)
    return _sort_entries(annual)


def _duration_days(entry: dict) -> int | None:
    start = _parse_date(entry.get("start"))
    end = _parse_date(entry.get("end"))
    return (end - start).days if start and end else None


def _fiscal_rollforward_ttm(entries: list[dict]) -> float | None:
    """
    Calculate TTM from a fiscal year and comparable interim YTD periods.

    Company-facts commonly reports Q2/Q3 cash flow and revenue as cumulative
    year-to-date values, not discrete quarters. For a newer interim period,
    FY + current YTD - prior-year YTD is the accurate rolling calculation.
    """

    annual = _annual_entries(entries)
    if not annual:
        return None
    latest_annual = annual[0]
    annual_end = _parse_date(latest_annual.get("end"))
    if annual_end is None:
        return None

    interim = [
        entry
        for entry in entries
        if str(entry.get("fp", "")).upper() in {"Q1", "Q2", "Q3"}
        and _parse_date(entry.get("end"))
    ]
    newer_ends = {
        _parse_date(entry["end"])
        for entry in interim
        if _parse_date(entry["end"]) > annual_end
    }
    if not newer_ends:
        return None
    current_end = max(newer_ends)
    current_period_entries = [
        entry for entry in interim if _parse_date(entry["end"]) == current_end
    ]
    current = max(
        current_period_entries,
        key=lambda entry: (
            _duration_days(entry) or 0,
            _parse_date(entry.get("filed")) or date.min,
        ),
    )
    current_fp = str(current.get("fp", "")).upper()
    current_duration = _duration_days(current)
    comparative = [
        entry
        for entry in interim
        if str(entry.get("fp", "")).upper() == current_fp
        and _parse_date(entry["end"]) < current_end
        and (
            current_duration is None
            or _duration_days(entry) is None
            or abs((_duration_days(entry) or 0) - current_duration) <= 15
        )
    ]
    if not comparative:
        return None
    previous = max(
        comparative,
        key=lambda entry: (
            _parse_date(entry.get("end")) or date.min,
            _duration_days(entry) or 0,
        ),
    )
    return float(latest_annual["val"]) + float(current["val"]) - float(previous["val"])


def _ttm_value(entries: list[dict]) -> float | None:
    rollforward = _fiscal_rollforward_ttm(entries)
    if rollforward is not None:
        return rollforward
    quarters = _quarter_entries(entries)
    if len(quarters) >= 4:
        return float(sum(float(entry["val"]) for entry in quarters[:4]))
    if quarters:
        return float(quarters[0]["val"]) * 4
    annual = _annual_entries(entries)
    return float(annual[0]["val"]) if annual else None


def _latest_value(entries: list[dict]) -> float | None:
    sorted_entries = _sort_entries(entries)
    return float(sorted_entries[0]["val"]) if sorted_entries else None


def _latest_annual_value(entries: list[dict]) -> float | None:
    annual = _annual_entries(entries)
    return float(annual[0]["val"]) if annual else None


def _annual_revenue_history(entries: list[dict]) -> list[AnnualRevenueRecord]:
    latest_by_year_end: dict[date, dict] = {}
    for entry in _sort_entries(_annual_entries(entries)):
        end = _parse_date(entry.get("end"))
        if end is None or end in latest_by_year_end:
            continue
        latest_by_year_end[end] = entry
    records = [
        AnnualRevenueRecord(fiscal_year_end=end, revenue=float(entry["val"]))
        for end, entry in latest_by_year_end.items()
    ]
    return sorted(records, key=lambda record: record.fiscal_year_end, reverse=True)[:4]


def _growth_rate(latest: float | None, previous: float | None) -> float | None:
    if latest is None or previous is None or previous <= 0:
        return None
    return (latest - previous) / previous


def _safe_margin(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def parse_company_facts(raw_facts: dict) -> CompanyFacts:
    """Extract standardized metrics from an SEC XBRL company-facts response."""

    flow_entries = {
        key: _entries_for_tag(raw_facts, tags) for key, tags in _FLOW_TAGS.items()
    }
    point_entries = {
        key: _entries_for_tag(raw_facts, tags)
        for key, tags in _POINT_IN_TIME_TAGS.items()
    }
    noncurrent_debt = _latest_value(
        _entries_for_tag(raw_facts, ["LongTermDebtNoncurrent"])
    )
    current_debt = _latest_value(
        _entries_for_tag(raw_facts, ["LongTermDebtCurrent"])
    )
    if noncurrent_debt is not None or current_debt is not None:
        total_debt = (noncurrent_debt or 0.0) + (current_debt or 0.0)
    else:
        total_debt = _latest_value(_entries_for_tag(raw_facts, ["LongTermDebt"]))

    operating_cash_flow = _ttm_value(flow_entries["operating_cash_flow_ttm"])
    capex = _ttm_value(flow_entries["capex_ttm"])
    free_cash_flow = (
        operating_cash_flow - capex
        if operating_cash_flow is not None and capex is not None
        else None
    )
    operating_income_ttm = _ttm_value(flow_entries["operating_income_ttm"])
    depreciation_amortization_ttm = _ttm_value(
        flow_entries["depreciation_amortization_ttm"]
    )
    ebitda_ttm = (
        operating_income_ttm + depreciation_amortization_ttm
        if operating_income_ttm is not None
        and depreciation_amortization_ttm is not None
        else None
    )
    annual_revenue_history = _annual_revenue_history(flow_entries["revenue_ttm"])
    revenue_yoy_growth = (
        _growth_rate(
            annual_revenue_history[0].revenue,
            annual_revenue_history[1].revenue,
        )
        if len(annual_revenue_history) >= 2
        else None
    )
    revenue_3yr_cagr = None
    if len(annual_revenue_history) >= 4 and annual_revenue_history[3].revenue > 0:
        latest = annual_revenue_history[0].revenue
        earliest = annual_revenue_history[3].revenue
        revenue_3yr_cagr = (latest / earliest) ** (1 / 3) - 1

    annual_revenue = annual_revenue_history[0].revenue if annual_revenue_history else None
    annual_gross_profit = _latest_annual_value(flow_entries["gross_profit_ttm"])
    annual_operating_income = _latest_annual_value(flow_entries["operating_income_ttm"])
    annual_net_income = _latest_annual_value(flow_entries["net_income_ttm"])

    all_selected_entries = [
        entry
        for entries in [*flow_entries.values(), *point_entries.values()]
        for entry in entries
    ]
    annual_dates = [
        _parse_date(entry.get("end"))
        for entry in _annual_entries(all_selected_entries)
        if _parse_date(entry.get("end"))
    ]
    quarter_dates = [
        _parse_date(entry.get("end"))
        for entry in _quarter_entries(all_selected_entries)
        if _parse_date(entry.get("end"))
    ]

    return CompanyFacts(
        revenue_ttm=_ttm_value(flow_entries["revenue_ttm"]),
        gross_profit_ttm=_ttm_value(flow_entries["gross_profit_ttm"]),
        operating_income_ttm=operating_income_ttm,
        net_income_ttm=_ttm_value(flow_entries["net_income_ttm"]),
        total_assets=_latest_value(point_entries["total_assets"]),
        total_debt=total_debt,
        cash_and_equivalents=_latest_value(point_entries["cash_and_equivalents"]),
        stockholders_equity=_latest_value(point_entries["stockholders_equity"]),
        operating_cash_flow_ttm=operating_cash_flow,
        free_cash_flow_ttm=free_cash_flow,
        capex_ttm=capex,
        depreciation_amortization_ttm=depreciation_amortization_ttm,
        ebitda_ttm=ebitda_ttm,
        most_recent_fiscal_year_end=max(annual_dates) if annual_dates else None,
        most_recent_quarter_end=max(quarter_dates) if quarter_dates else None,
        annual_revenue_history=annual_revenue_history,
        revenue_yoy_growth=revenue_yoy_growth,
        revenue_3yr_cagr=revenue_3yr_cagr,
        gross_margin=_safe_margin(annual_gross_profit, annual_revenue),
        operating_margin=_safe_margin(annual_operating_income, annual_revenue),
        net_margin=_safe_margin(annual_net_income, annual_revenue),
    )


def _extract_relevant_sections(text: str) -> tuple[str, str]:
    heading_patterns = [
        r"\bitem\s+1a[.\s:-]+risk\s+factors\b",
        r"\bitem\s+7[.\s:-]+management[^\n]{0,80}discussion\b",
        r"\bitem\s+2[.\s:-]+management[^\n]{0,80}discussion\b",
        r"\bmanagement[^\n]{0,80}discussion\s+and\s+analysis\b",
    ]
    starts = []
    for pattern in heading_patterns:
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if matches:
            # Filings commonly repeat headings in a table of contents before
            # the actual section body. The final match is the usable section.
            starts.append(matches[-1].start())
    if not starts:
        return text, "fallback"

    excerpts = []
    for start in sorted(set(starts)):
        following = re.search(r"\bitem\s+\d+[a-z]?[.\s:-]+", text[start + 20 :], re.IGNORECASE)
        end = start + 20 + following.start() if following else len(text)
        excerpts.append(text[start:end])
    return "\n\n".join(excerpts), "primary_doc_sections"


def _fetch_filing_text_with_metadata(
    filing_url: str,
    max_chars: int = 50000,
    *,
    force_refresh: bool = False,
) -> tuple[str | None, bool, str]:
    key = (
        f"{_FILING_EXTRACTION_VERSION}_"
        f"{hashlib.sha256(filing_url.encode('utf-8')).hexdigest()}_{max_chars}"
    )
    if not force_refresh:
        cached = cache_get("sec_filing_text", key, timedelta(days=30))
        if cached is not None:
            return (
                cached.get("text"),
                bool(cached.get("text_was_truncated", False)),
                str(cached.get("extraction_method", "unknown")),
            )
    try:
        response = _rate_limited_get(filing_url)
        content_type = response.headers.get("Content-Type", "").lower()
        if "html" in content_type or "<html" in response.text[:1000].lower():
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            text = soup.get_text("\n", strip=True)
        else:
            text = response.text
        text = re.sub(r"[ \t]+", " ", text)
        selected, method = _extract_relevant_sections(text)
        truncated = len(selected) > max_chars
        result = selected[:max_chars]
        cache_set(
            "sec_filing_text",
            key,
            {
                "text": result,
                "text_was_truncated": truncated,
                "extraction_method": method,
            },
        )
        return result, truncated, method
    except Exception as exc:
        logger.warning("SEC filing fetch failed for %s: %s", filing_url, exc)
        return None, False, "fetch_failed"


def extract_filing_text(filing_url: str, max_chars: int = 50000) -> str | None:
    """Download a filing primary document and extract MD&A/risk-factor text."""

    text, _, _ = _fetch_filing_text_with_metadata(filing_url, max_chars)
    return text


def _recent_rows(submissions: dict) -> list[dict]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", []) if isinstance(recent, dict) else []
    rows = []
    for index, form in enumerate(forms):
        try:
            report_dates = recent.get("reportDate", [])
            rows.append(
                {
                    "form": form,
                    "filing_date": recent["filingDate"][index],
                    "report_date": (
                        report_dates[index] if index < len(report_dates) else None
                    ),
                    "accession": recent["accessionNumber"][index],
                    "primary_document": recent["primaryDocument"][index],
                }
            )
        except (IndexError, KeyError, TypeError):
            continue
    return rows


def _filing_url(cik: str, row: dict) -> str:
    accession = str(row["accession"]).replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
        f"{accession}/{row['primary_document']}"
    )


def _to_filing_extract(
    cik: str,
    row: dict,
    *,
    force_refresh: bool = False,
) -> FilingExtract | None:
    filing_date = _parse_date(row.get("filing_date"))
    if filing_date is None:
        return None
    url = _filing_url(cik, row)
    text, truncated, method = _fetch_filing_text_with_metadata(
        url, force_refresh=force_refresh
    )
    return FilingExtract(
        filing_type=str(row["form"]),
        filing_date=filing_date,
        period_of_report=_parse_date(row.get("report_date")),
        accession_number=str(row["accession"]),
        primary_document_url=url,
        extracted_text=text,
        text_was_truncated=truncated,
        extraction_method=method,
    )


def fetch_most_recent_filing(
    submissions: dict,
    filing_types: list[str],
    *,
    force_refresh: bool = False,
) -> FilingExtract | None:
    """Return the newest requested filing, using 20-F as a 10-K fallback."""

    cik = str(submissions.get("cik", "")).zfill(10)
    if not cik.strip("0"):
        return None
    rows = _recent_rows(submissions)
    wanted = set(filing_types)
    matching = [row for row in rows if row["form"] in wanted]
    if not matching and "10-K" in wanted:
        matching = [row for row in rows if row["form"] == "20-F"]
    if not matching:
        return None
    matching.sort(key=lambda row: str(row.get("filing_date", "")), reverse=True)
    return _to_filing_extract(cik, matching[0], force_refresh=force_refresh)


def fetch_recent_8ks(
    submissions: dict,
    max_count: int = 4,
    *,
    force_refresh: bool = False,
) -> list[FilingExtract]:
    """Return recent 8-K filings, falling back to 6-K for foreign issuers."""

    cik = str(submissions.get("cik", "")).zfill(10)
    if not cik.strip("0"):
        return []
    rows = _recent_rows(submissions)
    matching = [row for row in rows if str(row["form"]).startswith("8-K")]
    if not matching:
        matching = [row for row in rows if str(row["form"]).startswith("6-K")]
    matching.sort(key=lambda row: str(row.get("filing_date", "")), reverse=True)
    extracts = [
        _to_filing_extract(cik, row, force_refresh=force_refresh)
        for row in matching[:max_count]
    ]
    return [extract for extract in extracts if extract is not None]
