"""
Thin OpenAI wrapper for agent-system LLM calls.

Provides:
- Lazy-initialized module-scoped OpenAI client (separate from the narrative
  pipeline's client so agent-system traffic is operationally distinct)
- Structured output via the beta parse API
- Retry transient transport/rate-limit failures, but not schema errors
- Integration with the existing assert_llm_calls_allowed runtime gate

This is intentionally minimal. Each agent imports `parse_structured` and
passes its system prompt, user message, target model, and target schema.
The wrapper handles retry, validation, and gate integration.
"""
from __future__ import annotations

import logging
import os
import random
import sys
import time
from typing import TypeVar

import httpx
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError
from dotenv import load_dotenv

from src.narrative.runtime_config import assert_llm_calls_allowed

load_dotenv()
logger = logging.getLogger("agent_system.llm")

_DEFAULT_CLIENT: OpenAI | None = None
_MODELS_WITHOUT_TEMPERATURE_SUPPORT: set[str] = set()
_LAST_CALL_DIAGNOSTICS: dict[str, object] = {}

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when structured output cannot be produced after retry."""


def _get_client() -> OpenAI:
    """Lazy-initialize a module-scoped OpenAI client for the agent system."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        assert_llm_calls_allowed("OpenAI client initialization for agent system")
        _DEFAULT_CLIENT = OpenAI(timeout=_openai_timeout_seconds())
    return _DEFAULT_CLIENT


def _openai_timeout_seconds() -> float:
    try:
        return float(os.getenv("OPENAI_TIMEOUT_SECONDS", "180"))
    except ValueError:
        return 180.0


def _openai_max_retries() -> int:
    try:
        return max(0, int(os.getenv("OPENAI_MAX_RETRIES", "3")))
    except ValueError:
        return 3


def get_last_call_diagnostics() -> dict[str, object]:
    """Return diagnostics for the most recent structured-output call."""

    return dict(_LAST_CALL_DIAGNOSTICS)


def _message_diagnostics(messages: list, response_schema: type[BaseModel]) -> dict[str, object]:
    lengths = [
        len(str(message.get("content", "")))
        for message in messages
        if isinstance(message, dict)
    ]
    total_chars = sum(lengths)
    return {
        "message_count": len(messages),
        "prompt_chars": total_chars,
        "prompt_est_tokens": max(1, total_chars // 4),
        "largest_message_chars": max(lengths) if lengths else 0,
        "schema_name": response_schema.__name__,
    }


def _sanitize_error_message(exc: BaseException) -> str:
    text = str(exc)
    for env_name in ("OPENAI_API_KEY", "FMP_API_KEY", "FINNHUB_API_KEY", "NEWS_API_KEY"):
        secret = os.getenv(env_name)
        if secret and len(secret) > 3:
            text = text.replace(secret, "***")
    return text[:500]


def _is_retryable_exception(exc: BaseException) -> bool:
    return isinstance(
        exc,
        (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            httpx.RemoteProtocolError,
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
        ),
    )


def _log_retryable_error(
    *,
    model: str,
    purpose: str,
    attempt: int,
    max_attempts: int,
    exc: BaseException,
) -> None:
    message = (
        f"[OpenAI structured parse retry] model={model} purpose={purpose!r} "
        f"attempt={attempt}/{max_attempts} exception={exc.__class__.__name__}: "
        f"{_sanitize_error_message(exc)}"
    )
    print(message, file=sys.stderr)


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
    timeout_seconds: float | None = None,
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
        max_retries: Deprecated compatibility argument. Validation/schema
            errors are not retried; transient API/network failures use
            OPENAI_MAX_RETRIES.
        timeout_seconds: Optional per-call timeout override. When omitted,
            the agent-system default from OPENAI_TIMEOUT_SECONDS is used.

    Returns:
        Validated instance of response_schema.

    Raises:
        StructuredOutputError: If validation fails or OpenAI returns no parsed output.
    """
    assert_llm_calls_allowed(purpose)
    client = _get_client()
    resolved_timeout_seconds = (
        _openai_timeout_seconds() if timeout_seconds is None else float(timeout_seconds)
    )
    if timeout_seconds is not None:
        client = client.with_options(timeout=resolved_timeout_seconds)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    network_retry_count = 0
    diagnostics = _message_diagnostics(messages, response_schema)
    diagnostics.update(
        {
            "purpose": purpose,
            "model": model,
            "retry_count": 0,
            "last_error": None,
            "timeout_seconds": resolved_timeout_seconds,
        }
    )
    _LAST_CALL_DIAGNOSTICS.clear()
    _LAST_CALL_DIAGNOSTICS.update(diagnostics)
    print(
        "[OpenAI structured parse prompt] "
        f"model={model} purpose={purpose!r} "
        f"messages={diagnostics['message_count']} "
        f"chars={diagnostics['prompt_chars']} "
        f"est_tokens={diagnostics['prompt_est_tokens']} "
        f"largest_message_chars={diagnostics['largest_message_chars']} "
        f"schema={diagnostics['schema_name']} "
        f"timeout_seconds={diagnostics['timeout_seconds']}",
        file=sys.stderr,
    )

    try:
        resp = None
        max_network_attempts = _openai_max_retries() + 1
        timeout_schedule = [
            resolved_timeout_seconds,
            resolved_timeout_seconds * 1.3,
            resolved_timeout_seconds * 1.6,
        ]
        for network_attempt in range(max_network_attempts):
            if network_attempt > 0:
                attempt_timeout_seconds = timeout_schedule[min(network_attempt, 2)]
                client = client.with_options(timeout=attempt_timeout_seconds)
            try:
                resp = _call_openai_parse(
                    client=client,
                    model=model,
                    messages=messages,
                    response_schema=response_schema,
                    temperature=temperature,
                )
                break
            except BadRequestError:
                raise
            except Exception as network_exc:
                if not _is_retryable_exception(network_exc):
                    raise
                network_retry_count += 1
                _LAST_CALL_DIAGNOSTICS.update(
                    {
                        "retry_count": network_retry_count,
                        "last_error": (
                            f"{network_exc.__class__.__name__}: "
                            f"{_sanitize_error_message(network_exc)}"
                        ),
                    }
                )
                if network_attempt >= max_network_attempts - 1:
                    raise
                _log_retryable_error(
                    model=model,
                    purpose=purpose,
                    attempt=network_attempt + 1,
                    max_attempts=max_network_attempts,
                    exc=network_exc,
                )
                sleep_seconds = [2.0, 5.0, 10.0][
                    min(network_attempt, 2)
                ] + random.uniform(0.0, 0.4)
                time.sleep(sleep_seconds)
        if resp is None:
            raise StructuredOutputError(
                f"OpenAI returned no response object for {purpose}."
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
        logger.warning("Validation error for %s: %s", purpose, e)
        raise StructuredOutputError(
            f"Failed to produce valid {response_schema.__name__} for {purpose}. "
            f"Validation/schema errors are not retried. Error: {e}"
        ) from e
