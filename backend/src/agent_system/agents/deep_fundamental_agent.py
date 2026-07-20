"""LLM-backed deep fundamental synthesis agent."""
from __future__ import annotations

from typing import Any

from src.agent_system.schemas.common import BaseSchema
from src.agent_system.schemas.deep_fundamental import (
    BasicScreenResult,
    CompanyProfile,
    DeepFundamentalLLMSynthesis,
    FundamentalContextPack,
    MacroContextPack,
    RelativePerformanceContext,
    SingleNameResearchContextPack,
    ThemeContextPack,
)


class DeepFundamentalAgentValidationError(Exception):
    """
    Raised when the deep fundamental agent fails to produce valid structured
    synthesis after retry. Callers should surface this instead of substituting
    fake synthesis.
    """


class _DeepFundamentalAgentResponse(BaseSchema):
    """Internal wrapper reserved for future multi-response variants."""

    synthesis: DeepFundamentalLLMSynthesis


async def synthesize_deep_fundamental_view(
    *,
    ticker: str,
    horizon: str | None,
    company_profile: CompanyProfile,
    fundamental_context: FundamentalContextPack | None = None,
    macro_context: MacroContextPack | dict[str, Any] | None = None,
    theme_context: ThemeContextPack | dict[str, Any] | None = None,
    relative_performance_context: RelativePerformanceContext | None = None,
    research_context: SingleNameResearchContextPack | None = None,
    basic_screen_result: BasicScreenResult | None = None,
    user_supplied_thesis: str | None = None,
) -> DeepFundamentalLLMSynthesis:
    """Produce structured single-name underwriting synthesis via LLM."""

    clean_ticker = ticker.upper().strip()
    if not clean_ticker:
        raise ValueError("ticker cannot be empty")
    if company_profile is None:
        raise ValueError("company_profile cannot be None")

    from src.agent_system.agents.deep_fundamental_agent_prompts import (
        render_deep_fundamental_context,
    )
    from src.agent_system.llm.client import StructuredOutputError, parse_structured
    from src.agent_system.llm.config import DEEP_FUNDAMENTAL_AGENT_MODEL

    system_prompt = render_deep_fundamental_context(
        ticker=clean_ticker,
        horizon=horizon,
        user_supplied_thesis=user_supplied_thesis,
        company_profile=company_profile,
        fundamental_context=fundamental_context,
        macro_context=macro_context,
        theme_context=theme_context,
        relative_performance_context=relative_performance_context,
        research_context=research_context,
        basic_screen_result=basic_screen_result,
    )
    user_message = (
        f"Produce deep fundamental synthesis for {clean_ticker}. "
        "Return only the structured JSON object. Do not choose final verdict "
        "or position size."
    )

    try:
        synthesis = parse_structured(
            system=system_prompt,
            user=user_message,
            model=DEEP_FUNDAMENTAL_AGENT_MODEL,
            response_schema=DeepFundamentalLLMSynthesis,
            purpose=f"deep fundamental synthesis: {clean_ticker}",
            temperature=0.2,
            max_retries=1,
        )
    except StructuredOutputError as exc:
        raise DeepFundamentalAgentValidationError(str(exc)) from exc

    if synthesis.ticker != clean_ticker:
        synthesis = synthesis.model_copy(update={"ticker": clean_ticker})
    return synthesis
