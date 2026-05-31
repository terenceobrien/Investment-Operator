"""
Tests for the thematic agent implementation.

The LLM wrapper is mocked throughout; no live API calls are made.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from src.agent_system.agents.thematic_agent import (
    ThematicAgentValidationError,
    _ThematicAgentResponse,
    _ThematicCandidate,
    _ThematicDerivedEvidence,
    _ThematicMapOutput,
    translate_priority_to_candidates,
)
from src.agent_system.agents.thematic_agent_prompts import render_priority_context
from src.agent_system.llm.client import StructuredOutputError
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.regime import ClarificationRequest, ResearchPriority
from src.agent_system.schemas.thematic import (
    ExclusionRecord,
    InstrumentType,
    ResearchDepth,
    ThematicMap,
    VariantStrength,
)


def _priority() -> ResearchPriority:
    return make_stub_regime_state().research_priorities[0]


def _thematic_output() -> _ThematicMapOutput:
    return _ThematicMapOutput(
        candidates=[
            _ThematicCandidate(
                ticker="ETN",
                instrument_type=InstrumentType.SINGLE_STOCK,
                name="Eaton",
                thematic_fit=(
                    "Electrical equipment exposure directly captures the "
                    "AI power and grid-capacity thesis."
                ),
                fit_strength=0.86,
                fit_evidence=[
                    _ThematicDerivedEvidence(
                        claim="Grid-capacity beneficiaries fit the priority.",
                        supports=True,
                        computation="Derived from source priority theme.",
                        upstream_claims=["ResearchPriority.theme"],
                    )
                ],
                consensus_view=(
                    "Our prior is that consensus recognizes data-center demand "
                    "but underweights grid-upgrade duration."
                ),
                potential_variant_view=(
                    "Backlog persistence may support earnings durability beyond "
                    "the semiconductor-led AI capital-spending cycle."
                ),
                variant_strength=VariantStrength.STRONG,
                priority_rank=1,
                recommended_research_depth=ResearchDepth.DEEP,
                theme_tags=["ai_power", "infrastructure"],
            )
        ],
        excluded=[
            ExclusionRecord(
                ticker="SMH",
                reason=(
                    "Semiconductor exposure reflects first-order AI leadership "
                    "rather than the grid-capacity bottleneck thesis."
                ),
            )
        ],
        mapping_logic=(
            "Mapped the grid-beneficiary priority into electrical equipment "
            "exposure while excluding adjacent first-order AI beneficiaries."
        ),
        universe_considered=8,
    )


def _clarification() -> ClarificationRequest:
    return ClarificationRequest(
        question="Which concrete thematic segment should candidates represent?",
        suggested_options=[
            "Grid equipment beneficiaries",
            "Power-generation capacity scarcity",
        ],
        reasoning=(
            "The priority does not distinguish between multiple instrument "
            "segments with materially different candidate sets."
        ),
        original_input="AI infrastructure opportunity",
    )


def test_none_priority_raises_value_error():
    with pytest.raises(ValueError):
        asyncio.run(translate_priority_to_candidates(None, make_stub_regime_state()))


def test_none_regime_state_raises_value_error():
    with pytest.raises(ValueError):
        asyncio.run(translate_priority_to_candidates(_priority(), None))


def test_successful_call_returns_thematic_map(monkeypatch):
    priority = _priority()

    def fake_parse_structured(**_kwargs):
        return _ThematicAgentResponse(
            response_kind="thematic_map",
            thematic_map=_thematic_output(),
            clarification=None,
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(
        translate_priority_to_candidates(priority, make_stub_regime_state())
    )

    assert isinstance(result, ThematicMap)
    assert result.candidates[0].ticker == "ETN"
    assert result.source_priority is priority
    assert result.candidates[0].fit_evidence


def test_successful_call_returns_clarification_request(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _ThematicAgentResponse(
            response_kind="clarification",
            thematic_map=None,
            clarification=_clarification(),
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(
        translate_priority_to_candidates(_priority(), make_stub_regime_state())
    )

    assert isinstance(result, ClarificationRequest)
    assert result.suggested_options


def test_structured_output_error_becomes_thematic_agent_validation_error(monkeypatch):
    def fake_parse_structured(**_kwargs):
        raise StructuredOutputError("bad structured output")

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(ThematicAgentValidationError):
        asyncio.run(
            translate_priority_to_candidates(_priority(), make_stub_regime_state())
        )


def test_both_thematic_map_and_clarification_populated_raises(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _ThematicAgentResponse(
            response_kind="thematic_map",
            thematic_map=_thematic_output(),
            clarification=_clarification(),
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(ThematicAgentValidationError):
        asyncio.run(
            translate_priority_to_candidates(_priority(), make_stub_regime_state())
        )


def test_neither_thematic_map_nor_clarification_populated_raises(monkeypatch):
    def fake_parse_structured(**_kwargs):
        return _ThematicAgentResponse(
            response_kind="thematic_map",
            thematic_map=None,
            clarification=None,
        )

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(ThematicAgentValidationError):
        asyncio.run(
            translate_priority_to_candidates(_priority(), make_stub_regime_state())
        )


def test_enable_clarification_false_forces_thematic_map_schema(monkeypatch):
    captured = {}
    priority = _priority()

    def fake_parse_structured(**kwargs):
        captured.update(kwargs)
        return _thematic_output()

    monkeypatch.setattr(
        "src.agent_system.llm.client.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(
        translate_priority_to_candidates(
            priority,
            make_stub_regime_state(),
            enable_clarification=False,
        )
    )

    assert isinstance(result, ThematicMap)
    assert result.source_priority is priority
    assert captured["response_schema"] is _ThematicMapOutput


@pytest.mark.parametrize("response_schema", [_ThematicMapOutput, _ThematicAgentResponse])
def test_llm_facing_thematic_schemas_contain_no_one_of(response_schema):
    schema_json = json.dumps(to_strict_json_schema(response_schema))

    assert '"oneOf"' not in schema_json


def test_llm_facing_candidate_matches_rank_and_ticker_constraints():
    candidate_data = _thematic_output().candidates[0].model_dump()
    candidate_data["priority_rank"] = 12
    assert _ThematicCandidate.model_validate(candidate_data).priority_rank == 12

    candidate_data["ticker"] = "RSP/SPY"
    with pytest.raises(ValidationError, match="ticker must be a single symbol"):
        _ThematicCandidate.model_validate(candidate_data)


def test_render_priority_context_is_specific():
    priority = _priority()
    rendered = render_priority_context(priority)

    assert rendered
    assert priority.theme in rendered
    assert priority.rationale in rendered
    assert priority.sub_questions[0] in rendered
    assert "Key supporting evidence:" in rendered


def test_render_priority_context_handles_empty_supporting_evidence():
    priority = _priority().model_copy(update={"supporting_evidence": []})
    rendered = render_priority_context(priority)

    assert "No supporting evidence supplied" in rendered
    assert priority.theme in rendered
