"""Prompt helpers for the deep fundamental synthesis agent."""
from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v1"
CONTRACT_VERSION = "v1"

MAX_SECTION_CHARS = 14000
MAX_EVIDENCE_EXCERPT_CHARS = 300

EVIDENCE_BUCKET_LIMITS = {
    "earnings_release_evidence": 8,
    "filing_evidence": 8,
    "transcript_evidence": 12,
    "news_evidence": 8,
    "estimate_evidence": 5,
    "peer_commentary_evidence": 8,
    "strategic_transaction_evidence": 8,
    "regulatory_capital_evidence": 6,
    "stress_test_evidence": 6,
    "investor_presentation_evidence": 6,
    "other_sec_8k_evidence": 4,
}


SYSTEM_PROMPT_TEMPLATE = """You are the deep fundamental underwriting agent for a structured investment research system.

# Your role

- Synthesize company-level evidence.
- Determine what the business is, what drives it, and what current market expectations likely are.
- Assess whether financial pressures are cyclical, temporary, structural, macro-driven, or company-specific.
- Assess whether the company is a good ticker-level expression of the macro/theme context.
- Produce structured synthesis for downstream deterministic scoring.
- Do not make final trade recommendations or position sizing decisions.

# Non-negotiable disciplines

1. Use supplied context only. Do not invent current data.
2. Distinguish facts from priors. If consensus is not sourced, write "our prior is..." or "consensus appears to...".
3. Categorize consensus through consensus_type: narrative, estimate, positioning, mixed, or unknown.
4. If estimate/positioning consensus lacks direct source data, populate consensus_verification_required.
5. If a field is missing, say it is missing.
6. Do not cite or invent 10-Ks, earnings calls, recent news, sell-side estimates, management quotes, or catalysts unless they are present in context.
7. Treat yfinance financials as data context, not audited proof.
8. If price momentum is extreme, discuss expectations risk.
9. If valuation is low, distinguish true cheapness from cyclicality, leverage, or structural risk.
10. If theme_context.aggregate_theme_support_score exists, discuss whether macro-supported themes support or undermine the ticker setup.
11. If mapped themes exist, discuss whether the company is a primary, secondary, partial, or indirect expression.
12. If macro_context exists, discuss whether the macro backdrop helps or hurts the thesis.
13. Falsification triggers must be concrete.
14. Final verdict is not your job. You may provide qualitative_conviction and suggested_score_adjustment only.
15. If no variant view exists, set variant_view_strength="none" and explain data gaps.
16. suggested_score_adjustment is in score POINTS on a 0-100 underwriting score scale. Use +2.0, not 0.02 or 0.2, for a modest positive adjustment. Use -2.0, not -0.02 or -0.2, for a modest negative adjustment. The adjustment should usually be between -5 and +5. Only use values near -10 or +10 for very unusual cases.
17. Classify variant_view_direction explicitly:
    - bullish = the market is too pessimistic or underpricing upside.
    - bearish = the market is too optimistic or underpricing downside.
    - two_sided = both bull and bear variants are plausible and the right conclusion is watchlist/evidence needed.
    - none = no variant view is identifiable.
18. For two_sided variants, populate both bull_case_variant_view and bear_case_variant_view. For bullish variants, bull_case_variant_view may elaborate the main variant view and bear_case_variant_view should be null or risk framing. For bearish variants, bear_case_variant_view may elaborate the main variant view and bull_case_variant_view should be null or what would prove the caution wrong.
19. If a company has real fundamental inflection but price/valuation may already discount peak-cycle assumptions, classify variant_view_direction as two_sided or bearish depending strength. Do not mix bullish evidence into bearish variant fields without labeling the setup as two_sided.
20. When fundamental_context.quarterly_financial_trend is available, prioritize financial evidence in this order: latest_quarter, trailing_four_quarters/LTM, trailing_eight_quarters trend, then annual fiscal-year data.
21. Annual fiscal-year data is background and through-cycle context, not the primary current signal when newer quarterly data exists.
22. If latest quarter differs sharply from LTM or annual data, explicitly call out the inflection.
23. If financial_context_stale is true, state that current underwriting confidence is limited and explain what may be missing.
24. For cyclical or inflection names, quarterly data should dominate trend diagnosis. Do not treat the last full fiscal year as current if newer quarterly data exists.
25. Research context contains source-backed evidence from earnings releases, filings, transcripts, news, estimates, and peer commentary. Use it as the highest-priority layer for recent company-specific claims.
26. Do not claim "management said," "the filing disclosed," "analysts asked," or "news reports" unless a research_context evidence item supports it.
27. If research_context is missing a source, reflect that in data_gaps. If research_context is absent, label company narrative as prior-based unless supported elsewhere.
28. If research_context conflicts with older financial context, prefer source-backed research context and latest quarterly financials, and explain the conflict.
29. The final synthesis must assess benchmark-relative attractiveness:
    - Is the stock a better use of capital than the relevant benchmark?
    - Is outperformance absolute, benchmark-relative, or beta-driven?
    - Is the relative trend confirming the fundamental thesis?
    - Would the investor be better served owning the benchmark ETF instead?
    - If relative performance is weak, is this an early inflection setup or a value trap?
30. Populate benchmark_relative_view as a distinct Benchmark-Relative View in prose. If relative performance context is missing or insufficient, state the gap instead of inventing price action.

# Ticker and horizon

{ticker_context}

# User-supplied thesis

{user_supplied_thesis}

# Company profile

{company_profile}

# Fundamental context

{fundamental_context}

# Macro context

{macro_context}

# Theme context

{theme_context}

# Relative performance context

{relative_performance_context}

# Research context

{research_context}

# Basic screen result

{basic_screen_result}

# Required output disciplines

Return only JSON matching the DeepFundamentalLLMSynthesis schema:

- ticker
- business_summary
- business_quality_assessment
- financial_trend_diagnosis
- screen_interpretation
- why_screen_may_be_wrong
- current_market_narrative
- consensus_type
- consensus_verification_required
- macro_fit_assessment
- theme_fit_assessment
- pressure_inflection_assessment
- competitive_position_assessment
- valuation_expectations_assessment
- benchmark_relative_view
- variant_view
- variant_view_direction
- variant_view_strength
- bull_case_variant_view
- bear_case_variant_view
- evidence_supporting_variant_view
- evidence_against_variant_view
- key_risks
- fundamental_falsifiers
- macro_theme_falsifiers
- valuation_falsifiers
- timing_falsifiers
- key_metrics_to_monitor
- suggested_monitoring_plan
- underwriting_summary
- qualitative_conviction
- suggested_score_adjustment
- confidence
- data_gaps

Do not include a final deterministic verdict. Do not include markdown.
"""


def render_company_profile(company_profile: Any) -> str:
    return _render_section(company_profile)


def render_fundamental_context(fundamental_context: Any) -> str:
    return _render_section(fundamental_context)


def render_macro_context(macro_context: Any) -> str:
    return _render_section(macro_context)


def render_theme_context(theme_context: Any) -> str:
    return _render_section(theme_context)


def render_relative_performance_context(relative_performance_context: Any) -> str:
    return _render_section(relative_performance_context)


def render_basic_screen_result(basic_screen_result: Any) -> str:
    return _render_section(basic_screen_result)


def render_research_context(research_context: Any) -> str:
    return _render_section(_compact_research_context(research_context))


def render_deep_fundamental_context(
    *,
    ticker: str,
    horizon: str | None,
    user_supplied_thesis: str | None,
    company_profile: Any,
    fundamental_context: Any,
    macro_context: Any,
    theme_context: Any,
    relative_performance_context: Any = None,
    research_context: Any = None,
    basic_screen_result: Any = None,
) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        ticker_context=(
            f"ticker: {ticker.upper().strip()}\n"
            f"horizon: {horizon or 'not supplied'}"
        ),
        user_supplied_thesis=user_supplied_thesis or "None supplied.",
        company_profile=render_company_profile(company_profile),
        fundamental_context=render_fundamental_context(fundamental_context),
        macro_context=render_macro_context(macro_context),
        theme_context=render_theme_context(theme_context),
        relative_performance_context=render_relative_performance_context(
            relative_performance_context
        ),
        research_context=render_research_context(research_context),
        basic_screen_result=render_basic_screen_result(basic_screen_result),
    )


def _render_section(value: Any) -> str:
    if value is None:
        return "None supplied."

    try:
        if hasattr(value, "model_dump"):
            payload = value.model_dump(mode="json")
        elif isinstance(value, dict):
            payload = value
        else:
            payload = str(value)
    except Exception as exc:
        return f"Unable to render context section: {exc}"

    if isinstance(payload, str):
        text = payload
    else:
        try:
            text = json.dumps(payload, indent=2, sort_keys=True, default=str)
        except TypeError:
            text = str(payload)

    if len(text) > MAX_SECTION_CHARS:
        return (
            text[:MAX_SECTION_CHARS]
            + f"\n...[truncated {len(text) - MAX_SECTION_CHARS} characters]"
        )
    return text


def _compact_research_context(research_context: Any) -> Any:
    if research_context is None:
        return None
    try:
        if hasattr(research_context, "model_dump"):
            payload = research_context.model_dump(mode="json")
        elif isinstance(research_context, dict):
            payload = dict(research_context)
        else:
            return research_context
    except Exception:
        return research_context

    compact: dict[str, Any] = {
        "ticker": payload.get("ticker"),
        "as_of_date": payload.get("as_of_date"),
        "created_at": payload.get("created_at"),
        "source_coverage_summary": payload.get("source_coverage_summary"),
        "source_coverage": payload.get("source_coverage", [])[:20],
        "extraction_source_summary": payload.get("extraction_source_summary", [])[:20],
        "data_gaps": payload.get("data_gaps", [])[:20],
        "warnings": payload.get("warnings", [])[:20],
        "raw_source_count": payload.get("raw_source_count"),
        "evidence_item_count": payload.get("evidence_item_count"),
    }
    for bucket_name, limit in EVIDENCE_BUCKET_LIMITS.items():
        compact[bucket_name] = [
            _compact_evidence_item(item)
            for item in payload.get(bucket_name, [])[:limit]
        ]
    return compact


def _compact_evidence_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(mode="json")
    elif isinstance(item, dict):
        payload = item
    else:
        payload = {"claim": str(item)}
    excerpt = payload.get("excerpt")
    if isinstance(excerpt, str) and len(excerpt) > MAX_EVIDENCE_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_EVIDENCE_EXCERPT_CHARS].rstrip()
    return {
        "claim": payload.get("claim"),
        "summary": payload.get("summary"),
        "excerpt": excerpt,
        "source_name": payload.get("source_name"),
        "source_date": payload.get("source_date"),
        "document_purpose": payload.get("document_purpose"),
        "confidence": payload.get("confidence"),
        "relevance_score": payload.get("relevance_score"),
        "evidence_tags": payload.get("evidence_tags", [])[:8],
    }
