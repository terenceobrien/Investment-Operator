"""
Macro agent — translates freeform user input into a structured ResearchPriority.

See agents/macro_agent_contract.md for the behavioral contract (rules MA-1
through MA-11) that this agent must enforce via prompt design and validation.

Implementation arrives in Phase 2.1.2. This module currently contains only
the function signature and exception types so downstream modules (test
harness, UI integration) can import against a stable API.
"""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import Field

from src.agent_system.schemas.common import BaseSchema
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    EdgeDecayHorizon,
    RegimeState,
    ResearchPriority,
)


class MacroAgentValidationError(Exception):
    """
    Raised when the agent fails to produce valid structured output after
    one retry. The caller should surface this to the user as a system error
    rather than substituting a stub priority. Silently producing invalid
    data is explicitly forbidden by contract rule MA-10.
    """


class _MacroDerivedEvidence(BaseSchema):
    """OpenAI-compatible DerivedEvidence subset for macro-agent priorities."""

    source_type: Literal["derived"] = "derived"
    claim: str = Field(min_length=1, max_length=2000)
    supports: bool
    computation: str = Field(min_length=1, max_length=500)
    upstream_claims: list[str] = Field(min_length=1, max_length=20)


class _MacroResearchPriority(BaseSchema):
    """
    OpenAI-compatible subset of ResearchPriority.

    The public ResearchPriority schema supports a discriminated union of all
    evidence types. OpenAI structured output has trouble with the full union,
    so the macro agent emits the supported DerivedEvidence shape directly and
    converts it to the public ResearchPriority schema at the boundary.
    """

    theme: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=2000)
    edge_hypothesis: str = Field(min_length=30, max_length=2000)
    sub_questions: list[str] = Field(default_factory=list, max_length=10)
    priority_rank: int = Field(ge=1, le=5)
    expected_edge_decay: EdgeDecayHorizon
    supporting_evidence: list[_MacroDerivedEvidence] = Field(
        min_length=1,
        max_length=20,
    )

    def to_research_priority(self) -> ResearchPriority:
        return ResearchPriority.model_validate(self.model_dump())


class _MacroAgentResponse(BaseSchema):
    """
    Internal wrapper for OpenAI structured output. The agent returns
    exactly one of priority/clarification populated; the function
    unpacks and returns the populated one.
    """

    priority: Optional[_MacroResearchPriority] = None
    clarification: Optional[ClarificationRequest] = None
    response_kind: Literal["priority", "clarification"]


async def translate_to_priority(
    user_input: str,
    regime_state: RegimeState,
    *,
    enable_clarification: bool = True,
) -> Union[ResearchPriority, ClarificationRequest]:
    """
    Translate freeform user input into a structured research priority.

    See agents/macro_agent_contract.md for the full behavioral contract
    (rules MA-1 through MA-11) that this function enforces via prompt
    design and validation.

    Args:
        user_input: Freeform text from the user. 1-500 chars. Stripped of
            leading/trailing whitespace before being sent to the agent.
        regime_state: Current regime context. Must be a fully-populated
            RegimeState; the agent reads layers, drivers, environment,
            falsifiers, and existing research_priorities.
        enable_clarification: If False, the agent must produce a
            ResearchPriority regardless of input quality (used by the test
            harness in 2.1.4 to compare outputs across runs without
            being interrupted by clarification paths). If True (default),
            vague inputs may return a ClarificationRequest instead.

    Returns:
        ResearchPriority if the input can be narrowed into a sharp priority.
        ClarificationRequest if the input is genuinely ambiguous and
            enable_clarification is True.

    Raises:
        MacroAgentValidationError: If the agent fails to produce valid
            structured output after one retry.
        ValueError: If user_input is empty or > 500 chars (the caller
            should validate before invoking this function).
    """
    # Input validation — keep this defensive even though callers should
    # validate first; surfaces bugs early.
    cleaned_input = user_input.strip() if user_input else ""
    if not cleaned_input:
        raise ValueError("user_input cannot be empty")
    if len(cleaned_input) > 500:
        raise ValueError(
            f"user_input too long: {len(cleaned_input)} chars (max 500)"
        )

    # Build the prompt
    from src.agent_system.agents.macro_agent_prompts import (
        SYSTEM_PROMPT_TEMPLATE,
        render_regime_context,
    )
    from src.agent_system.llm.client import StructuredOutputError, parse_structured
    from src.agent_system.llm.config import MACRO_AGENT_MODEL

    regime_context = render_regime_context(regime_state)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(regime_context=regime_context)

    # The response shape needs to handle the union. OpenAI's structured
    # output doesn't natively handle Union types, so we use a wrapper
    # schema that holds either a priority or a clarification.
    response_schema = _MacroResearchPriority if not enable_clarification else _MacroAgentResponse

    try:
        result = parse_structured(
            system=system_prompt,
            user=cleaned_input,
            model=MACRO_AGENT_MODEL,
            response_schema=response_schema,
            purpose=f"macro agent translate_to_priority: {cleaned_input[:60]}",
            temperature=0.3,
        )
    except StructuredOutputError as e:
        raise MacroAgentValidationError(str(e)) from e

    # If enable_clarification=False, result is already a ResearchPriority
    if not enable_clarification:
        return result.to_research_priority()

    # Otherwise unpack the union wrapper
    if result.priority is not None and result.clarification is not None:
        raise MacroAgentValidationError(
            "Agent returned both priority and clarification — invalid output"
        )
    if result.priority is not None:
        return result.priority.to_research_priority()
    if result.clarification is not None:
        return result.clarification
    raise MacroAgentValidationError(
        "Agent returned neither priority nor clarification — invalid output"
    )
