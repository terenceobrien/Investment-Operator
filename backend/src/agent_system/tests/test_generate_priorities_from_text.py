"""Tests for the one-shot priority-generation utility."""
from __future__ import annotations

import asyncio

import pytest
import yaml

from src.agent_system.agents.macro_agent import MacroAgentValidationError
from src.agent_system.adapters.regime import _build_seed_research_priorities
from src.agent_system.evals import generate_priorities_from_text as generator
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.regime import EdgeDecayHorizon, ResearchPriority


def _priority(theme: str = "Manual breadth rotation") -> ResearchPriority:
    return ResearchPriority(
        theme=theme,
        rationale="Breadth deterioration is visible beneath headline index resilience.",
        edge_hypothesis=(
            "The market is underpricing the persistence of dispersion after "
            "breadth breaks down under narrow mega-cap leadership."
        ),
        sub_questions=[
            "Which defensives are seeing improving revisions?",
            "Which crowded leaders are losing breadth support?",
        ],
        priority_rank=1,
        expected_edge_decay=EdgeDecayHorizon.MONTHS,
        supporting_evidence=[
            DerivedEvidence(
                claim="Breadth deterioration supports this manual priority.",
                supports=True,
                computation="test fixture",
                upstream_claims=["test"],
            )
        ],
    )


def test_load_input_lines_ignores_blanks_and_comments(tmp_path):
    path = tmp_path / "inputs.txt"
    path.write_text(
        "\n"
        "# comment\n"
        "Hormuz closure risk\n"
        "   \n"
        "Quantum computing winners\n",
        encoding="utf-8",
    )

    assert generator.load_input_lines(path) == [
        "Hormuz closure risk",
        "Quantum computing winners",
    ]


def test_known_input_produces_valid_research_priority(monkeypatch, research_priority):
    async def fake_translate_to_priority(**kwargs):
        assert kwargs["user_input"] == "Hormuz closure risk"
        return research_priority

    monkeypatch.setattr(generator, "translate_to_priority", fake_translate_to_priority)

    result = asyncio.run(
        generator.convert_text_to_priority(
            "Hormuz closure risk",
            regime_state=object(),
        )
    )

    assert isinstance(result, ResearchPriority)
    assert result.theme == research_priority.theme


def test_yaml_output_round_trips_through_seed_priority_loader(research_priority):
    rendered = generator.render_priorities([research_priority], output_format="yaml")
    payload = yaml.safe_load(rendered)

    priorities = _build_seed_research_priorities(payload)

    assert len(priorities) == 1
    assert priorities[0].theme == research_priority.theme
    assert priorities[0].rationale == research_priority.rationale
    assert priorities[0].edge_hypothesis == research_priority.edge_hypothesis
    assert priorities[0].expected_edge_decay == research_priority.expected_edge_decay
    assert priorities[0].supporting_evidence


def test_clarification_response_is_not_serialized(monkeypatch):
    from src.agent_system.schemas.regime import ClarificationRequest

    async def fake_translate_to_priority(**_kwargs):
        return ClarificationRequest(
            question="Which specific mispricing should be converted?",
            suggested_options=[
                "Energy logistics beneficiaries",
                "Oil beta downside hedges",
            ],
            reasoning=(
                "The input spans multiple distinct research priorities and "
                "needs a narrower thesis before serialization."
            ),
            original_input="Energy",
        )

    monkeypatch.setattr(generator, "translate_to_priority", fake_translate_to_priority)

    with pytest.raises(generator.PriorityGenerationError, match="clarification"):
        asyncio.run(
            generator.convert_text_to_priority(
                "Energy",
                regime_state=object(),
            )
        )


def test_malformed_llm_output_error_exposes_raw_output(monkeypatch):
    class RawOutputError(Exception):
        raw_output = '{"priority": {"theme": ""}}'

    async def fake_translate_to_priority(**_kwargs):
        raise MacroAgentValidationError("bad structured output") from RawOutputError("raw")

    monkeypatch.setattr(generator, "translate_to_priority", fake_translate_to_priority)

    with pytest.raises(generator.PriorityGenerationError) as excinfo:
        asyncio.run(
            generator.convert_text_to_priority(
                "rotation breadth thesis",
                regime_state=object(),
            )
        )

    assert excinfo.value.raw_output == '{"priority": {"theme": ""}}'
    assert "bad structured output" in excinfo.value.validation_error


def test_append_manual_priority_preserves_existing_entries_and_assigns_next_rank(tmp_path):
    path = tmp_path / "manual_research_priorities.yaml"
    original = """
priorities:
  - theme: Existing one
    rationale: Existing rationale one.
    edge_hypothesis: This existing edge hypothesis is long enough for schema validation.
    sub_questions:
      - First existing question?
    priority_rank: 1
    expected_edge_decay: weeks
  - theme: Existing two
    rationale: Existing rationale two.
    edge_hypothesis: This second existing edge hypothesis is also valid for tests.
    sub_questions:
      - Second existing question?
    priority_rank: 2
    expected_edge_decay: months
""".lstrip()
    path.write_text(original, encoding="utf-8")

    loaded = generator.append_manual_priority(
        _priority("Approved rotation thesis"),
        "The original operator thesis text.",
        approved_by="tester",
        path=path,
    )

    rendered = path.read_text(encoding="utf-8")
    assert rendered.startswith(original)
    assert len(loaded) == 3
    approved = loaded[-1]
    assert approved.theme == "Approved rotation thesis"
    assert approved.priority_rank == 3
    assert approved.source == "operator_manual"
    assert approved.source_macro_forecast_id is None
    assert approved.source_thesis_text == "The original operator thesis text."
    assert approved.approved_by == "tester"


def test_replace_manual_priority_discards_existing_entries_and_resets_rank(tmp_path):
    path = tmp_path / "manual_research_priorities.yaml"
    original = """
priorities:
  - theme: Existing one
    rationale: Existing rationale one.
    edge_hypothesis: This existing edge hypothesis is long enough for schema validation.
    sub_questions:
      - First existing question?
    priority_rank: 1
    expected_edge_decay: weeks
  - theme: Existing two
    rationale: Existing rationale two.
    edge_hypothesis: This second existing edge hypothesis is also valid for tests.
    sub_questions:
      - Second existing question?
    priority_rank: 2
    expected_edge_decay: months
""".lstrip()
    path.write_text(original, encoding="utf-8")
    candidate = _priority("Replacement rotation thesis").model_copy_validate(
        update={"priority_rank": 5}
    )

    loaded = generator.replace_manual_priority(
        candidate,
        "The replacement operator thesis text.",
        approved_by="tester",
        path=path,
    )

    rendered = path.read_text(encoding="utf-8")
    assert "Existing one" not in rendered
    assert "Existing two" not in rendered
    assert len(loaded) == 1
    approved = loaded[0]
    assert approved.theme == "Replacement rotation thesis"
    assert approved.priority_rank == 1
    assert approved.source == "operator_manual"
    assert approved.source_macro_forecast_id is None
    assert approved.source_thesis_text == "The replacement operator thesis text."
    assert approved.approved_by == "tester"


def test_append_manual_priority_round_trip_failure_leaves_original_untouched(tmp_path, monkeypatch):
    path = tmp_path / "manual_research_priorities.yaml"
    original = "priorities: []\n"
    path.write_text(original, encoding="utf-8")

    def fail_round_trip(_path):
        raise RuntimeError("synthetic validation failure")

    monkeypatch.setattr(generator, "load_manual_research_priorities", fail_round_trip)

    with pytest.raises(generator.ManualPriorityAppendError, match="Round-trip validation failed"):
        generator.append_manual_priority(
            _priority(),
            "A thesis that should not corrupt the file.",
            path=path,
        )

    assert path.read_text(encoding="utf-8") == original
