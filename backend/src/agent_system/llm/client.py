"""
Thin OpenAI wrapper for agent-system LLM calls.

Provides:
- Lazy-initialized module-scoped OpenAI client (separate from the narrative
  pipeline's client so agent-system traffic is operationally distinct)
- Structured output via the beta parse API
- Retry on ValidationError with the error fed back as feedback
- Integration with the existing assert_llm_calls_allowed runtime gate

This is intentionally minimal. Each agent imports `parse_structured` and
passes its system prompt, user message, target model, and target schema.
The wrapper handles retry, validation, and gate integration.
"""
from __future__ import annotations

import logging
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

from src.narrative.runtime_config import assert_llm_calls_allowed

load_dotenv()
logger = logging.getLogger("agent_system.llm")

_DEFAULT_CLIENT: OpenAI | None = None
_MODELS_WITHOUT_TEMPERATURE_SUPPORT: set[str] = set()

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when structured output cannot be produced after retry."""


def _get_client() -> OpenAI:
    """Lazy-initialize a module-scoped OpenAI client for the agent system."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        assert_llm_calls_allowed("OpenAI client initialization for agent system")
        _DEFAULT_CLIENT = OpenAI()
    return _DEFAULT_CLIENT


def _call_openai_parse(
    *,
    client,
    model: str,
    messages: list,
    response_schema,
    temperature: float,
):
    """
    Make the actual API call, omitting temperature for models that don't
    support customization. Handles the "temperature does not support"
    error by recording the model and retrying without the parameter.
    """
    from openai import BadRequestError

    if model in _MODELS_WITHOUT_TEMPERATURE_SUPPORT:
        # Known not to support; omit temperature entirely.
        return client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_schema,
        )

    try:
        return client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_schema,
            temperature=temperature,
        )
    except BadRequestError as e:
        # Specifically detect the "temperature does not support" error.
        # If we see it, remember this model and retry without temperature.
        error_str = str(e).lower()
        if "temperature" in error_str and "does not support" in error_str:
            logger.info(
                "Model %s does not support custom temperature; retrying "
                "without parameter and recording for subsequent calls.",
                model,
            )
            _MODELS_WITHOUT_TEMPERATURE_SUPPORT.add(model)
            return client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_schema,
            )
        # Any other BadRequestError is a real error — re-raise.
        raise


def parse_structured(
    *,
    system: str,
    user: str,
    model: str,
    response_schema: type[T],
    purpose: str,
    temperature: float = 0.3,
    max_retries: int = 1,
) -> T:
    """
    Make a structured-output OpenAI call returning a validated Pydantic instance.

    Note on temperature: some newer OpenAI models (gpt-5 family) don't
    support custom temperature values. The wrapper detects this on first
    call and automatically omits the parameter for subsequent calls to
    the same model. The temperature argument is treated as a hint when
    supported, and silently ignored when not.

    Args:
        system: The system prompt (agent role, rules, few-shot examples).
        user: The user message (the actual input the agent is responding to).
        model: Model name (from src/agent_system/llm/config.py constants).
        response_schema: Pydantic model class for the response shape.
        purpose: Short description for the assert_llm_calls_allowed gate
            and for logging (e.g. "macro agent translate_to_priority").
        temperature: Lower is more consistent. 0.3 default for reasoning
            tasks; raise for creative tasks. Ignored for models that
            don't support custom temperature.
        max_retries: Number of retries on ValidationError. Default 1.

    Returns:
        Validated instance of response_schema.

    Raises:
        StructuredOutputError: If validation fails after max_retries.
    """
    assert_llm_calls_allowed(purpose)
    client = _get_client()

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_error: ValidationError | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = _call_openai_parse(
                client=client,
                model=model,
                messages=messages,
                response_schema=response_schema,
                temperature=temperature,
            )
            parsed = resp.choices[0].message.parsed
            if parsed is None:
                # OpenAI returned a refusal or empty parse — treat as error
                raise StructuredOutputError(
                    f"OpenAI returned no parsed content for {purpose}; "
                    f"refusal or empty response."
                )
            return parsed

        except ValidationError as e:
            last_error = e
            logger.warning(
                "Validation error on attempt %d for %s: %s",
                attempt + 1,
                purpose,
                e,
            )
            if attempt < max_retries:
                # Append the validation error to the user message and retry
                feedback = (
                    f"\n\n[Your previous response failed validation with these "
                    f"errors:\n{e}\nPlease produce a response that satisfies "
                    f"the schema. Pay attention to required fields, minimum "
                    f"lengths, and field types.]"
                )
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user + feedback},
                ]

    raise StructuredOutputError(
        f"Failed to produce valid {response_schema.__name__} for {purpose} "
        f"after {max_retries + 1} attempts. Last error: {last_error}"
    )
