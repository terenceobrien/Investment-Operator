"""LLM-backed company profile generation agent."""
from __future__ import annotations

from datetime import date
from typing import Any

from src.agent_system.schemas.deep_fundamental import (
    CompanyProfile,
    DataConfidence,
    FundamentalContextPack,
)


class CompanyProfileAgentValidationError(Exception):
    """
    Raised when the company profile agent fails to produce a valid
    CompanyProfile. Callers should surface this instead of substituting
    hallucinated profile data.
    """


async def generate_company_profile(
    *,
    ticker: str,
    company_name: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    financial_context: FundamentalContextPack | dict[str, Any] | None = None,
    research_context: Any | None = None,
    existing_profile: CompanyProfile | dict[str, Any] | None = None,
    as_of_date: date | None = None,
) -> CompanyProfile:
    """Generate a structured CompanyProfile using the standard LLM client."""

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")

    from src.agent_system.agents.company_profile_agent_prompts import (
        SYSTEM_PROMPT_TEMPLATE,
        render_company_profile_input_context,
    )
    from src.agent_system.llm.client import StructuredOutputError, parse_structured
    from src.agent_system.llm.config import COMPANY_PROFILE_AGENT_MODEL

    profile_date = as_of_date or date.today()
    input_context = render_company_profile_input_context(
        ticker=clean_ticker,
        company_name=company_name,
        sector=sector,
        industry=industry,
        financial_context=financial_context,
        research_context=research_context,
        existing_profile=existing_profile,
        as_of_date=profile_date,
    )
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(input_context=input_context)
    user_message = (
        f"Generate a structured CompanyProfile for {clean_ticker}. "
        "Return only the JSON object. Do not include an investment rating, "
        "stock recommendation, price target, score, or position sizing."
    )

    try:
        profile = parse_structured(
            system=system_prompt,
            user=user_message,
            model=COMPANY_PROFILE_AGENT_MODEL,
            response_schema=CompanyProfile,
            purpose=f"company profile generation: {clean_ticker}",
            temperature=0.2,
            max_retries=1,
        )
    except StructuredOutputError as exc:
        raise CompanyProfileAgentValidationError(str(exc)) from exc

    updates: dict[str, Any] = {
        "ticker": clean_ticker,
        "profile_as_of_date": profile.profile_as_of_date or profile_date,
    }

    notes = list(profile.profile_source_notes)
    if research_context is None:
        if profile.profile_source in {
            "filing_verified",
            "llm_generated_research_context",
        }:
            updates["profile_source"] = "llm_generated_unverified"
            notes.append(
                "No research_context was supplied; filing-verified or "
                "research-context source label was downgraded."
            )
        elif profile.profile_source == "mixed":
            notes.append(
                "Profile may include general LLM prior knowledge; no "
                "research_context was supplied."
            )
        else:
            updates["profile_source"] = "llm_generated_unverified"
        notes.append(
            "Company profile is LLM-generated from supplied metadata and "
            "general prior knowledge; verify with filings before relying on "
            "precise business details."
        )
        if profile.profile_confidence == DataConfidence.HIGH:
            updates["profile_confidence"] = DataConfidence.MEDIUM
    else:
        notes.append("research_context was supplied to the profile agent.")

    updates["profile_source_notes"] = _dedupe_preserve_order(notes)
    return profile.model_copy(update=updates)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip() if isinstance(value, str) else str(value).strip()
        if not clean:
            continue
        key = clean.lower().rstrip(".!?:;").strip()
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result
