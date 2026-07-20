"""
Tests for the agent-system OpenAI wrapper.

All OpenAI interactions are mocked; these tests must never make live API calls.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from openai import APIConnectionError
from pydantic import BaseModel, ValidationError

from src.agent_system.llm import client as llm_client
from src.agent_system.llm.client import StructuredOutputError, parse_structured


class DummyResponse(BaseModel):
    value: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as exc_info:
        DummyResponse.model_validate({})
    return exc_info.value


def _parsed_response(value: int = 1):
    parsed = DummyResponse(value=value)
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(parsed=parsed),
            )
        ]
    )


def _mock_client(parse_mock: MagicMock):
    return SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(parse=parse_mock),
            )
        )
    )


def test_parse_structured_returns_parsed_instance_on_success(monkeypatch):
    parse_mock = MagicMock(return_value=_parsed_response(7))
    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", _mock_client(parse_mock))
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", MagicMock())

    result = parse_structured(
        system="system",
        user="user",
        model="test-model",
        response_schema=DummyResponse,
        purpose="test purpose",
    )

    assert result == DummyResponse(value=7)
    parse_mock.assert_called_once()


def test_parse_structured_does_not_retry_validation_error(monkeypatch):
    parse_mock = MagicMock(side_effect=[_validation_error(), _parsed_response(9)])
    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", _mock_client(parse_mock))
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", MagicMock())

    with pytest.raises(StructuredOutputError):
        parse_structured(
            system="system",
            user="user",
            model="test-model",
            response_schema=DummyResponse,
            purpose="test purpose",
            max_retries=1,
        )

    assert parse_mock.call_count == 1


def test_parse_structured_retries_api_connection_error_and_succeeds(monkeypatch):
    request = httpx.Request("POST", "https://api.openai.com/test")
    parse_mock = MagicMock(
        side_effect=[
            APIConnectionError(request=request),
            _parsed_response(9),
        ]
    )
    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", _mock_client(parse_mock))
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", MagicMock())
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)

    result = parse_structured(
        system="system",
        user="user",
        model="test-model",
        response_schema=DummyResponse,
        purpose="test purpose",
    )

    assert result == DummyResponse(value=9)
    assert parse_mock.call_count == 2
    diagnostics = llm_client.get_last_call_diagnostics()
    assert diagnostics["retry_count"] == 1


def test_parse_structured_raises_after_retries_exhausted(monkeypatch):
    parse_mock = MagicMock(side_effect=[_validation_error(), _validation_error()])
    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", _mock_client(parse_mock))
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", MagicMock())

    with pytest.raises(StructuredOutputError):
        parse_structured(
            system="system",
            user="user",
            model="test-model",
            response_schema=DummyResponse,
            purpose="test purpose",
            max_retries=1,
        )


def test_assert_llm_calls_allowed_called_before_client_init(monkeypatch):
    events: list[str] = []

    def fake_guard(_context: str = "") -> None:
        events.append("guard")

    def fake_openai(**_kwargs):
        events.append("client")
        return _mock_client(MagicMock(return_value=_parsed_response(3)))

    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", None)
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", fake_guard)
    monkeypatch.setattr(llm_client, "OpenAI", fake_openai)

    parse_structured(
        system="system",
        user="user",
        model="test-model",
        response_schema=DummyResponse,
        purpose="test purpose",
    )

    assert events[:3] == ["guard", "guard", "client"]


def test_refusal_or_empty_parse_raises_structured_output_error(monkeypatch):
    parse_mock = MagicMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(parsed=None),
                )
            ]
        )
    )
    monkeypatch.setattr(llm_client, "_DEFAULT_CLIENT", _mock_client(parse_mock))
    monkeypatch.setattr(llm_client, "assert_llm_calls_allowed", MagicMock())

    with pytest.raises(StructuredOutputError):
        parse_structured(
            system="system",
            user="user",
            model="test-model",
            response_schema=DummyResponse,
            purpose="test purpose",
        )


def test_parse_structured_handles_temperature_unsupported_error():
    """When the API rejects temperature, the wrapper retries without it
    and records the model so subsequent calls skip the parameter."""
    from openai import BadRequestError

    class TinyResponse(BaseModel):
        text: str

    llm_client._MODELS_WITHOUT_TEMPERATURE_SUPPORT.clear()

    mock_client = MagicMock()
    bad_request = BadRequestError(
        message=(
            "Unsupported value: 'temperature' does not support 0.3 "
            "with this model. Only the default (1) value is supported."
        ),
        response=httpx.Response(
            status_code=400,
            request=httpx.Request("POST", "https://api.openai.com/test"),
        ),
        body=None,
    )

    success_response = MagicMock()
    success_response.choices[0].message.parsed = TinyResponse(text="ok")

    mock_client.beta.chat.completions.parse.side_effect = [
        bad_request,
        success_response,
    ]

    with patch.object(llm_client, "_get_client", return_value=mock_client):
        with patch.object(llm_client, "assert_llm_calls_allowed"):
            result = llm_client.parse_structured(
                system="sys",
                user="usr",
                model="gpt-5.5",
                response_schema=TinyResponse,
                purpose="test",
                temperature=0.3,
            )

    assert result.text == "ok"
    assert "gpt-5.5" in llm_client._MODELS_WITHOUT_TEMPERATURE_SUPPORT

    call_args = mock_client.beta.chat.completions.parse.call_args_list
    assert "temperature" in call_args[0].kwargs
    assert "temperature" not in call_args[1].kwargs
