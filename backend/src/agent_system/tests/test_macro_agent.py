"""
Tests for the macro agent implementation.

The LLM wrapper is mocked throughout; no live API calls are made.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from src.agent_system.agents import macro_agent
from src.agent_system.agents.macro_agent import (
    MacroAgentValidationError,
    _MacroAgentResponse,
    _MacroResearchPriority,
    translate_to_priority,
)
from src.agent_system.agents.macro_agent_prompts import render_regime_context
from src.agent_system.llm.client import StructuredOutputError
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.forward import (
    FedPathReading,
    ForwardContext,
    InflationExpectations,
    MarketEvent,
)
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    EdgeDecayHorizon,
    ResearchPriority,
)


def _priority() -> ResearchPriority:
    return ResearchPriority(
        theme="Energy producer durability vs. consensus mean reversion",
        rationale=(
            "Oil supply shock is a named regime driver and breadth is bearish, "
            "so the priority should focus on durable energy exposure rather "
            "than broad beta."
        ),
        edge_hypothesis=(
            "Consensus is pricing oil tightness as transient while producer "
            "capex discipline implies supply response may lag for quarters."
        ),
        sub_questions=[
            "Which producers have the lowest break-even costs?",
            "Where are analyst models assuming the fastest oil mean reversion?",
        ],
        priority_rank=2,
        expected_edge_decay=EdgeDecayHorizon.QUARTERS,
        supporting_evidence=[
            DerivedEvidence(
                claim="Oil supply shock is a named regime driver",
                supports=True,
                computation="test fixture derived from regime context",
                upstream_claims=["regime state: key_drivers include Oil supply shock"],
            )
        ],
    )


def _macro_priority() -> _MacroResearchPriority:
    priority = _priority()
    return _MacroResearchPriority.model_validate(
        {
            "theme": priority.theme,
            "rationale": priority.rationale,
            "edge_hypothesis": priority.edge_hypothesis,
            "sub_questions": priority.sub_questions,
            "priority_rank": priority.priority_rank,
            "expected_edge_decay": priority.expected_edge_decay,
            "supporting_evidence": [
                {
                    "source_type": "derived",
                    "claim": "Oil supply shock is a named regime driver",
                    "supports": True,
                    "computation": "test fixture derived from regime context",
                    "upstream_claims": [
                        "regime state: key_drivers include Oil supply shock"
                    ],
                }
            ],
        }
    )


def _clarification() -> ClarificationRequest:
    return ClarificationRequest(
        question="Which AI infrastructure mispricing should the agent investigate?",
        suggested_options=[
            "Grid equipment backlog underappreciation",
            "Power generation scarcity premium",
        ],
        reasoning=(
            "The input is ambiguous between several distinct AI infrastructure "
            "mispricing theses and needs a narrower framing."
        ),
        original_input="AI infrastructure",
    )


def test_empty_user_input_raises_value_error():
    with pytest.raises(ValueError):
        asyncio.run(translate_to_priority("   ", make_stub_regime_state()))


def test_too_long_user_input_raises_value_error():
    with pytest.raises(ValueError):
        asyncio.run(translate_to_priority("x" * 501, make_stub_regime_state()))


def test_successful_call_returns_research_priority(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _MacroAgentResponse(
            response_kind="priority",
            priority=_macro_priority(),
            clarification=None,
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(translate_to_priority("energy", make_stub_regime_state()))

    assert isinstance(result, ResearchPriority)
    assert result.theme.startswith("Energy producer")
    assert result.supporting_evidence


def test_successful_call_returns_clarification_request(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _MacroAgentResponse(
            response_kind="clarification",
            priority=None,
            clarification=_clarification(),
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(
        translate_to_priority("AI infrastructure", make_stub_regime_state())
    )

    assert isinstance(result, ClarificationRequest)
    assert result.suggested_options


def test_structured_output_error_becomes_macro_agent_validation_error(monkeypatch):
    def fake_parse_structured(**_kwargs):
        raise StructuredOutputError("bad structured output")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(MacroAgentValidationError):
        asyncio.run(translate_to_priority("energy", make_stub_regime_state()))


def test_both_priority_and_clarification_populated_raises(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _MacroAgentResponse(
            response_kind="priority",
            priority=_macro_priority(),
            clarification=_clarification(),
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(MacroAgentValidationError):
        asyncio.run(translate_to_priority("energy", make_stub_regime_state()))


def test_neither_priority_nor_clarification_populated_raises(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _MacroAgentResponse(
            response_kind="priority",
            priority=None,
            clarification=None,
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(MacroAgentValidationError):
        asyncio.run(translate_to_priority("energy", make_stub_regime_state()))


def test_enable_clarification_false_forces_research_priority_schema(monkeypatch):
    captured = {}

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _macro_priority()

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(
        translate_to_priority(
            "energy",
            make_stub_regime_state(),
            enable_clarification=False,
        )
    )

    assert isinstance(result, ResearchPriority)
    assert captured["response_schema"] is _MacroResearchPriority


def test_render_regime_context_with_forward_context_is_specific():
    regime = make_stub_regime_state().model_copy_validate(
        {
            "forward_context": ForwardContext(
                fed_path=[
                    FedPathReading(
                        meeting_date="2026-06-17",
                        prob_cut_50=0.02,
                        prob_cut_25=0.18,
                        prob_hold=0.70,
                        prob_hike_25=0.09,
                        prob_hike_50=0.01,
                        source="CME FedWatch as of 2026-05-19",
                    )
                ],
                inflation_expectations=InflationExpectations(
                    breakeven_5y=2.45,
                    as_of=datetime.now(timezone.utc),
                    notes="5y breakeven up 30bps in 30 days",
                ),
                upcoming_catalysts=[
                    MarketEvent(
                        name="FOMC June Meeting",
                        date="2026-06-17",
                        category="fed",
                        significance="high",
                    )
                ],
                as_of=datetime.now(timezone.utc),
            )
        }
    )

    rendered = render_regime_context(regime)

    assert rendered
    assert "Supply-shock inflation / late-cycle tightening" in rendered
    assert "monetary: 3.4" in rendered
    assert "Fed path:" in rendered
    assert "2026-06-17" in rendered


def test_render_regime_context_handles_none_forward_context():
    rendered = render_regime_context(make_stub_regime_state())

    assert rendered
    assert "Forward context:" not in rendered


def test_render_regime_context_handles_empty_research_priorities():
    regime = make_stub_regime_state().model_copy_validate(
        {"research_priorities": []}
    )

    rendered = render_regime_context(regime)

    assert "Existing research priorities: none." in rendered
