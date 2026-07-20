"""Prompt helpers for the company profile agent."""
from __future__ import annotations

import json
from typing import Any

PROMPT_VERSION = "v1"
CONTRACT_VERSION = "v1"

MAX_SECTION_CHARS = 9000


SYSTEM_PROMPT_TEMPLATE = """You are the company profile agent for a structured investment research system.

# Your role

Generate a structured CompanyProfile for a ticker so downstream fundamental,
theme-mapping, and research agents understand the business. You do not make
investment recommendations.

# Non-negotiable disciplines

1. Output is a company profile only. Do not produce a stock rating, price target, final verdict, score, trade recommendation, or position size.
2. Use supplied context first: company facts, financial context, research context, metadata, and existing profile fields.
3. If no source-backed research context is supplied, generate a best-effort profile from general knowledge and set profile_source to "llm_generated_unverified".
4. If relying on general prior knowledge, include a profile_source_note saying the profile is LLM-generated and should be verified with filings.
5. Do not invent precise segment revenue/profit shares, customer concentration, supplier relationships, backlog, management commentary, earnings-call quotes, or recent news.
6. Use null for unknown segment revenue_share_estimate and profit_share_estimate. Do not guess percentages.
7. Populate economically meaningful revenue_model, cost_drivers, margin_drivers, peer_group, thematic_exposures, macro_sensitivities, and major_risks.
8. Peers must be real public companies or ETFs where appropriate. Prefer US tickers or ADRs where available. If uncertain, omit rather than hallucinate.
9. Macro sensitivities must be specific: rates, yield curve, credit cycle, consumer spending, FX, commodity prices, AI capex, cloud capex, construction cycle, deposit beta, regulation, etc.
10. Thematic exposures should be concise phrases that can map to active macro themes.
11. For banks, include drivers like NII, NIM, loan growth, deposits, deposit beta, credit costs, capital markets, asset/wealth fees, CET1, and ROTCE if relevant.
12. For Apple-like hardware/platform companies, include product ecosystem, services mix, installed base, device replacement cycles, China exposure, FX, buybacks, app store/regulatory risks.
13. For semiconductors, include pricing cycles, utilization, capex, node transitions, end-market demand, and supply discipline.
14. For industrials/electrical, include backlog, orders, pricing, input costs, project execution, and data center/grid capex if relevant.
15. profile_confidence should usually be "medium" at best without research_context. Use "high" only when supplied research context supports the profile. Use "low" if the ticker is obscure or uncertain.
16. Populate profile_as_of_date using the supplied as_of_date.
17. Return only JSON matching the CompanyProfile schema. Do not include markdown.

# Input context

{input_context}

# Required output

Return a CompanyProfile object with:

- ticker
- company_name
- sector
- industry
- profile_source
- profile_confidence
- profile_as_of_date
- profile_source_notes
- profile_data_gaps
- business_description
- business_model
- segments
- revenue_model
- cost_drivers
- margin_drivers
- key_customers
- key_suppliers
- peer_group
- thematic_exposures
- macro_sensitivities
- major_risks
"""


def render_company_profile_input_context(
    *,
    ticker: str,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    financial_context: Any = None,
    research_context: Any = None,
    existing_profile: Any = None,
    as_of_date: Any = None,
) -> str:
    payload = {
        "ticker": ticker.upper().strip(),
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "as_of_date": str(as_of_date) if as_of_date is not None else None,
        "existing_profile": _to_serializable(existing_profile),
        "financial_context_summary": render_financial_context_summary(
            financial_context
        ),
        "research_context_summary": render_research_context_summary(
            research_context
        ),
    }
    return _render_payload(payload)


def render_financial_context_summary(financial_context: Any) -> str:
    return _render_context_summary(financial_context)


def render_research_context_summary(research_context: Any) -> str:
    return _render_context_summary(research_context)


def _to_serializable(obj: Any) -> Any:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(mode="json")
        except TypeError:
            return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]
    return str(obj)


def _render_context_summary(value: Any) -> str:
    if value is None:
        return "None supplied."
    return _render_payload(_to_serializable(value))


def _render_payload(payload: Any) -> str:
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
