"""Tests for the one-shot priority-generation utility."""
from __future__ import annotations

import asyncio

import pytest
import yaml

from src.agent_system.adapters.regime import _build_seed_research_priorities
from src.agent_system.evals import generate_priorities_from_text as generator
from src.agent_system.schemas.regime import ResearchPriority


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

    with pytest.raises(RuntimeError, match="clarification"):
        asyncio.run(
            generator.convert_text_to_priority(
                "Energy",
                regime_state=object(),
            )
        )
