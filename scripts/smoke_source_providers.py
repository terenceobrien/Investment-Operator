#!/usr/bin/env python3
"""Smoke-test external research source APIs for Helix ResearchContextPack.

This script checks API key loading and endpoint responses for:

* FMP transcripts
* Finnhub transcripts
* NewsAPI company news
* Finnhub company news

It redacts API keys and does not run the full deep fundamental pipeline.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"

API_KEY_ENV_NAMES = ("FMP_API_KEY", "FINNHUB_API_KEY", "NEWS_API_KEY")
SENSITIVE_QUERY_KEYS = {"apikey", "apiKey", "token", "access_key"}
USER_AGENT = "HelixResearchContextSmoke/0.1"


def _load_env_files() -> None:
    for path in (REPO_ROOT / ".env", REPO_ROOT / ".env.local", BACKEND_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#") or "=" not in clean:
                continue
            key, value = clean.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and (path == BACKEND_ROOT / ".env" or key not in os.environ):
                os.environ[key] = value


def mask_key(value: str | None) -> str:
    if not value:
        return "present=no"
    return f"present=yes prefix={value[:4]}... length={len(value)}"


def sanitize_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return sanitize_text(url)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in SENSITIVE_QUERY_KEYS or key.lower() in {
            item.lower() for item in SENSITIVE_QUERY_KEYS
        }:
            query.append((key, "REDACTED"))
        else:
            query.append((key, value))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query),
            parsed.fragment,
        )
    )


def sanitize_text(value: Any) -> str:
    text = str(value)
    for env_name in API_KEY_ENV_NAMES:
        secret = os.getenv(env_name)
        if secret and len(secret) > 3:
            text = text.replace(secret, "REDACTED")
    for key in SENSITIVE_QUERY_KEYS:
        text = _replace_query_secret(text, key)
    return text


def _replace_query_secret(text: str, key: str) -> str:
    return re.sub(
        rf"([?&]{re.escape(key)}=)[^&\s]+",
        rf"\1REDACTED",
        text,
        flags=re.IGNORECASE,
    )


def safe_json_preview(obj: Any, max_chars: int = 1000) -> str:
    try:
        rendered = json.dumps(obj, indent=2, sort_keys=True, default=str)
    except TypeError:
        rendered = str(obj)
    rendered = sanitize_text(rendered)
    if len(rendered) <= max_chars:
        return rendered
    return rendered[:max_chars].rstrip() + "..."


def request_json(url: str, timeout: int) -> tuple[int | None, Any | None, str | None]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = getattr(response, "status", None) or response.getcode()
            try:
                return status, json.loads(body), None
            except json.JSONDecodeError:
                return status, None, f"Non-JSON response: {sanitize_text(body[:1000])}"
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        preview = sanitize_text(body[:1000]) if body else str(exc)
        return exc.code, None, f"HTTP Error {exc.code}: {preview}"
    except URLError as exc:
        return None, None, f"URL Error: {sanitize_text(exc.reason)}"
    except Exception as exc:
        return None, None, f"Error: {sanitize_text(exc)}"


def parse_date(value: str | None) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def top_level_shape(payload: Any) -> str:
    if isinstance(payload, dict):
        return f"dict keys={list(payload.keys())[:20]}"
    if isinstance(payload, list):
        return f"list length={len(payload)}"
    if payload is None:
        return "none"
    return type(payload).__name__


def _find_transcript_candidates(payload: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def visit(value: Any, depth: int = 0) -> None:
        if depth > 3:
            return
        if isinstance(value, dict):
            if _looks_like_transcript_candidate(value):
                candidates.append(value)
            for child_key in ("transcripts", "data", "results", "items"):
                child = value.get(child_key)
                if child is not None:
                    visit(child, depth + 1)
        elif isinstance(value, list):
            for item in value[:50]:
                visit(item, depth + 1)

    visit(payload)
    return candidates


def _looks_like_transcript_candidate(value: dict[str, Any]) -> bool:
    keys = {str(key).lower() for key in value}
    transcript_keys = {
        "content",
        "transcript",
        "text",
        "date",
        "quarter",
        "year",
        "symbol",
        "participant",
        "presentation",
        "qa",
    }
    return bool(keys & transcript_keys)


def _transcript_text_length(candidate: dict[str, Any]) -> int:
    for key in ("content", "transcript", "text"):
        value = candidate.get(key)
        if isinstance(value, str):
            return len(value)
        if isinstance(value, list):
            return len(json.dumps(value, default=str))
    for key in ("presentation", "qa", "data"):
        value = candidate.get(key)
        if value:
            return len(json.dumps(value, default=str))
    return 0


def _selected_transcript_summary(candidate: dict[str, Any] | None) -> str:
    if not candidate:
        return "n/a"
    return (
        f"date={candidate.get('date') or candidate.get('time') or 'n/a'} "
        f"quarter={candidate.get('quarter') or 'n/a'} "
        f"year={candidate.get('year') or candidate.get('fiscalYear') or 'n/a'}"
    )


def _print_http_guidance(provider: str, status: int | None) -> None:
    if status == 401:
        if provider == "FMP":
            print(
                "Note: 401 Unauthorized: likely missing/invalid FMP_API_KEY, "
                "wrong endpoint family for this key, or plan does not include this endpoint."
            )
        else:
            print("Note: 401 Unauthorized: key missing/invalid or token not being sent correctly.")
    elif status == 403:
        if provider == "Finnhub":
            print(
                "Note: 403 Forbidden: FINNHUB_API_KEY may be valid, but this endpoint "
                "may require a paid plan or different entitlement."
            )
        else:
            print("Note: 403 Forbidden: key recognized but plan/endpoint permission may be blocked.")
    elif status == 404:
        print("Note: 404 Not Found: endpoint path may be wrong for this API generation.")
    elif status == 426:
        print(
            "Note: 426 Upgrade Required: NewsAPI key/plan likely does not allow this "
            "request from the current environment, or endpoint requires upgraded plan. "
            "Verify plan restrictions, HTTPS URL, and whether server-side requests are allowed."
        )


def test_fmp_transcripts(
    ticker: str,
    api_key: str | None,
    timeout: int,
    verbose: bool,
) -> str:
    print("\n=== FMP Transcript Smoke ===")
    if not api_key:
        print("Result: skipped")
        print("Reason: FMP_API_KEY not configured.")
        return "skipped"

    encoded_ticker = ticker.upper()
    endpoints = [
        (
            "provider_configured_endpoint",
            "https://financialmodelingprep.com/api/v4/earning_call_transcript?"
            + urlencode({"symbol": encoded_ticker, "apikey": api_key}),
        ),
        (
            "stable_earning_call_transcript",
            "https://financialmodelingprep.com/stable/earning-call-transcript?"
            + urlencode({"symbol": encoded_ticker, "apikey": api_key}),
        ),
        (
            "v3_symbol_transcript",
            f"https://financialmodelingprep.com/api/v3/earning_call_transcript/{encoded_ticker}?"
            + urlencode({"apikey": api_key}),
        ),
        (
            "v4_batch_transcript",
            f"https://financialmodelingprep.com/api/v4/batch_earning_call_transcript/{encoded_ticker}?"
            + urlencode({"apikey": api_key}),
        ),
    ]
    final_result = "not_found"
    for label, url in endpoints:
        print(f"\nAttempt: {label}")
        print(f"Endpoint attempted: {sanitize_url(url)}")
        status, payload, error = request_json(url, timeout)
        print(f"HTTP status: {status if status is not None else 'n/a'}")
        print(f"Response shape: {top_level_shape(payload)}")
        candidates = _find_transcript_candidates(payload)
        selected = candidates[0] if candidates else None
        text_length = _transcript_text_length(selected) if selected else 0
        result = "success" if candidates else "not_found"
        if error:
            result = "error"
            print(f"Error: {sanitize_text(error)}")
        print(f"Result: {result}")
        print(f"Transcript candidates found: {len(candidates)}")
        print(f"Selected transcript date/quarter/year: {_selected_transcript_summary(selected)}")
        print(f"Transcript text length: {text_length}")
        _print_http_guidance("FMP", status)
        if verbose and payload is not None:
            print(f"Short response preview: {safe_json_preview(payload)}")
        if result == "success":
            return "success"
        if final_result != "error" and result == "error":
            final_result = "error"
    return final_result


def test_finnhub_transcripts(
    ticker: str,
    api_key: str | None,
    timeout: int,
    verbose: bool,
) -> str:
    print("\n=== Finnhub Transcript Smoke ===")
    if not api_key:
        print("Result: skipped")
        print("Reason: FINNHUB_API_KEY not configured.")
        return "skipped"

    profile_url = "https://finnhub.io/api/v1/stock/profile2?" + urlencode(
        {"symbol": ticker.upper(), "token": api_key}
    )
    print("\nSanity check: stock/profile2")
    print(f"Endpoint attempted: {sanitize_url(profile_url)}")
    status, payload, error = request_json(profile_url, timeout)
    print(f"HTTP status: {status if status is not None else 'n/a'}")
    print(f"Response shape: {top_level_shape(payload)}")
    if error:
        print(f"Error: {sanitize_text(error)}")
    elif isinstance(payload, dict):
        print(f"Company/profile name: {payload.get('name') or payload.get('ticker') or 'n/a'}")
    _print_http_guidance("Finnhub", status)

    list_url = "https://finnhub.io/api/v1/stock/transcripts/list?" + urlencode(
        {"symbol": ticker.upper(), "token": api_key}
    )
    print("\nAttempt: provider_configured_transcripts_list")
    print(f"Endpoint attempted: {sanitize_url(list_url)}")
    status, payload, error = request_json(list_url, timeout)
    print(f"HTTP status: {status if status is not None else 'n/a'}")
    print(f"Response shape: {top_level_shape(payload)}")
    if error:
        print(f"Result: error")
        print(f"Error: {sanitize_text(error)}")
        _print_http_guidance("Finnhub", status)
        return "error"
    if verbose and payload is not None:
        print(f"Short response preview: {safe_json_preview(payload)}")

    transcripts = []
    if isinstance(payload, dict):
        value = payload.get("transcripts", payload.get("data", []))
        transcripts = value if isinstance(value, list) else []
    elif isinstance(payload, list):
        transcripts = payload

    print(f"Transcript candidates found: {len(transcripts)}")
    if not transcripts:
        print("Result: not_found")
        return "not_found"

    selected = next((item for item in transcripts if isinstance(item, dict)), None)
    transcript_id = selected.get("id") if selected else None
    print(f"Selected transcript date/quarter/year: {_selected_transcript_summary(selected)}")
    if not transcript_id:
        text_length = _transcript_text_length(selected) if selected else 0
        print(f"Transcript text length: {text_length}")
        print(f"Result: {'success' if text_length else 'not_found'}")
        return "success" if text_length else "not_found"

    detail_url = "https://finnhub.io/api/v1/stock/transcripts?" + urlencode(
        {"id": transcript_id, "token": api_key}
    )
    print("\nAttempt: provider_configured_transcript_detail")
    print(f"Endpoint attempted: {sanitize_url(detail_url)}")
    status, detail_payload, error = request_json(detail_url, timeout)
    print(f"HTTP status: {status if status is not None else 'n/a'}")
    print(f"Response shape: {top_level_shape(detail_payload)}")
    if error:
        print("Result: error")
        print(f"Error: {sanitize_text(error)}")
        _print_http_guidance("Finnhub", status)
        return "error"
    candidates = _find_transcript_candidates(detail_payload)
    selected_detail = candidates[0] if candidates else (
        detail_payload if isinstance(detail_payload, dict) else None
    )
    text_length = _transcript_text_length(selected_detail) if selected_detail else 0
    print(f"Transcript text length: {text_length}")
    if verbose and detail_payload is not None:
        print(f"Short response preview: {safe_json_preview(detail_payload)}")
    result = "success" if text_length else "not_found"
    print(f"Result: {result}")
    return result


def test_newsapi(
    company_name: str | None,
    ticker: str,
    api_key: str | None,
    as_of_date: date,
    lookback_days: int,
    timeout: int,
    verbose: bool,
) -> str:
    print("\n=== NewsAPI Smoke ===")
    if not api_key:
        print("Result: skipped")
        print("Reason: NEWS_API_KEY not configured.")
        return "skipped"

    query = _news_query(company_name, ticker)
    start = as_of_date - timedelta(days=lookback_days)
    url = "https://newsapi.org/v2/everything?" + urlencode(
        {
            "q": query,
            "from": start.isoformat(),
            "to": as_of_date.isoformat(),
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 5,
            "apiKey": api_key,
        }
    )
    print(f"Endpoint attempted: {sanitize_url(url)}")
    status, payload, error = request_json(url, timeout)
    print(f"HTTP status: {status if status is not None else 'n/a'}")
    if isinstance(payload, dict):
        print(f"Response status field: {payload.get('status') or 'n/a'}")
        print(f"totalResults: {payload.get('totalResults', 'n/a')}")
    if error:
        print("Result: error")
        print(f"Error: {sanitize_text(error)}")
        _print_http_guidance("NewsAPI", status)
        return "error"
    articles = payload.get("articles", []) if isinstance(payload, dict) else []
    print(f"Article count: {len(articles)}")
    if articles:
        first = articles[0]
        source = first.get("source") if isinstance(first, dict) else {}
        print(
            "First article source/title/date/url: "
            f"{(source or {}).get('name') or 'n/a'} | "
            f"{first.get('title') or 'n/a'} | "
            f"{first.get('publishedAt') or 'n/a'} | "
            f"{sanitize_text(first.get('url') or 'n/a')}"
        )
    if verbose and payload is not None:
        print(f"Short response preview: {safe_json_preview(payload)}")
    result = "success" if articles else "not_found"
    print(f"Result: {result}")
    return result


def test_finnhub_company_news(
    ticker: str,
    api_key: str | None,
    as_of_date: date,
    lookback_days: int,
    timeout: int,
    verbose: bool,
) -> str:
    print("\n=== Finnhub Company News Smoke ===")
    if not api_key:
        print("Result: skipped")
        print("Reason: FINNHUB_API_KEY not configured.")
        return "skipped"

    start = as_of_date - timedelta(days=lookback_days)
    url = "https://finnhub.io/api/v1/company-news?" + urlencode(
        {
            "symbol": ticker.upper(),
            "from": start.isoformat(),
            "to": as_of_date.isoformat(),
            "token": api_key,
        }
    )
    print(f"Endpoint attempted: {sanitize_url(url)}")
    status, payload, error = request_json(url, timeout)
    print(f"HTTP status: {status if status is not None else 'n/a'}")
    if error:
        print("Result: error")
        print(f"Error: {sanitize_text(error)}")
        _print_http_guidance("Finnhub", status)
        return "error"
    articles = payload if isinstance(payload, list) else []
    print(f"Article count: {len(articles)}")
    for index, article in enumerate(articles[:3], start=1):
        if not isinstance(article, dict):
            continue
        published = article.get("datetime")
        published_text = _datetime_from_epoch(published) if published else "n/a"
        print(
            f"Article {index}: "
            f"{article.get('source') or 'n/a'} | "
            f"{article.get('headline') or 'n/a'} | "
            f"{published_text} | "
            f"{sanitize_text(article.get('url') or 'n/a')}"
        )
    if verbose and payload is not None:
        print(f"Short response preview: {safe_json_preview(payload)}")
    result = "success" if articles else "not_found"
    print(f"Result: {result}")
    return result


def _datetime_from_epoch(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(value)


def _news_query(company_name: str | None, ticker: str) -> str:
    if not company_name:
        return ticker.upper()
    short_name = (
        company_name.replace(" Inc.", "")
        .replace(" Corporation", "")
        .replace(" Corp.", "")
        .replace(", Inc.", "")
        .strip()
    )
    if short_name and short_name != company_name:
        return f'"{company_name}" OR {short_name}'
    return f'"{company_name}" OR {ticker.upper()}'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test external ResearchContextPack source providers."
    )
    parser.add_argument("--ticker", default="MU")
    parser.add_argument("--company-name", default=None)
    parser.add_argument("--as-of-date", type=parse_date, default=None)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--timeout", type=int, default=20)
    return parser.parse_args()


def print_environment() -> None:
    print("=== Environment ===")
    for env_name in API_KEY_ENV_NAMES:
        print(f"{env_name}: {mask_key(os.getenv(env_name))}")


def print_summary(results: dict[str, str]) -> None:
    print("\n=== Summary ===")
    print(f"FMP transcripts: {results['fmp_transcripts']}")
    print(f"Finnhub transcripts: {results['finnhub_transcripts']}")
    print(f"NewsAPI news: {results['newsapi_news']}")
    print(f"Finnhub company news: {results['finnhub_news']}")
    print("\nSuggested next action:")
    if results["fmp_transcripts"] == "error":
        print("- If FMP returned 401, check FMP_API_KEY loading, endpoint version, and plan entitlement.")
    if results["finnhub_transcripts"] == "error" and results["finnhub_news"] == "success":
        print("- Finnhub key works for company news; transcript endpoint is likely plan/entitlement restricted.")
    elif results["finnhub_transcripts"] == "error":
        print("- If Finnhub returned 401/403, check token validity and transcript endpoint entitlement.")
    if results["newsapi_news"] == "error":
        print("- If NewsAPI returned 426, check plan restrictions, endpoint access, and server-side request rules.")
    if results["finnhub_news"] == "success":
        print("- Finnhub company news is usable while primary NewsAPI access is fixed.")
    if all(value in {"success", "skipped"} for value in results.values()):
        print("- No provider errors detected by this smoke test.")


def main() -> int:
    _load_env_files()
    args = parse_args()
    as_of_date = args.as_of_date or date.today()
    ticker = args.ticker.upper().strip()

    print_environment()
    results = {
        "fmp_transcripts": test_fmp_transcripts(
            ticker=ticker,
            api_key=os.getenv("FMP_API_KEY"),
            timeout=args.timeout,
            verbose=args.verbose,
        ),
        "finnhub_transcripts": test_finnhub_transcripts(
            ticker=ticker,
            api_key=os.getenv("FINNHUB_API_KEY"),
            timeout=args.timeout,
            verbose=args.verbose,
        ),
        "newsapi_news": test_newsapi(
            company_name=args.company_name,
            ticker=ticker,
            api_key=os.getenv("NEWS_API_KEY"),
            as_of_date=as_of_date,
            lookback_days=args.lookback_days,
            timeout=args.timeout,
            verbose=args.verbose,
        ),
        "finnhub_news": test_finnhub_company_news(
            ticker=ticker,
            api_key=os.getenv("FINNHUB_API_KEY"),
            as_of_date=as_of_date,
            lookback_days=args.lookback_days,
            timeout=args.timeout,
            verbose=args.verbose,
        ),
    }
    print_summary(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
