"""Tests for the macro priority propose/promote workflow."""
from __future__ import annotations

import asyncio
from argparse import Namespace

import pytest
import yaml

from src.agent_system.agents.macro_agent import MacroAgentValidationError
from src.agent_system.macro import __main__ as macro_cli
from src.agent_system.macro import loader
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.common import DerivedEvidence
from src.agent_system.schemas.regime import (
    ClarificationRequest,
    EdgeDecayHorizon,
    ResearchPriority,
)


def _priority(theme: str = "AI grid bottleneck mispricing", rank: int = 1) -> ResearchPriority:
    return ResearchPriority(
        theme=theme,
        rationale=(
            "The current regime supports a focused research priority because "
            "broad beta is fragile while this theme has specific forward catalysts."
        ),
        edge_hypothesis=(
            "Consensus is treating this as a generic macro exposure, while the "
            "actual edge may sit in a narrower group whose earnings revisions "
            "lag the regime shift."
        ),
        sub_questions=[
            "Which names have the cleanest exposure?",
            "Where is consensus still stale?",
        ],
        priority_rank=rank,
        expected_edge_decay=EdgeDecayHorizon.QUARTERS,
        supporting_evidence=[
            DerivedEvidence(
                claim=f"{theme} is supported by the regime context",
                supports=True,
                computation="test fixture derived from current regime context",
                upstream_claims=["test current regime"],
            )
        ],
    )


def _clarification(original_input: str = "Software") -> ClarificationRequest:
    return ClarificationRequest(
        question="Which software mispricing should be narrowed into a priority?",
        suggested_options=[
            "Profitable AI monetizers",
            "Seat-based SaaS compression shorts",
        ],
        reasoning=(
            "The input is broad enough to contain several distinct variants, "
            "so the user should pick the intended mispricing first."
        ),
        original_input=original_input,
    )


def _write_current_regime(path, priorities: list[ResearchPriority]) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "regime_id": "test_regime",
                "regime_label": "Test regime",
                "headline": "Keep this field untouched",
                "seed_research_priorities": [
                    loader.priority_to_yaml_dict(priority)
                    for priority in priorities
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_propose_all_clear_writes_priorities(monkeypatch, tmp_path, capsys):
    inputs_file = tmp_path / "inputs.txt"
    inputs_file.write_text("AI power\nQuantum picks\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        macro_cli,
        "_select_regime_state",
        lambda: (make_stub_regime_state(), "stub", None),
    )

    priorities = [_priority("AI power grid beneficiaries", 1), _priority("Quantum suppliers", 2)]

    async def fake_translate_to_priority(**kwargs):
        assert kwargs["enable_clarification"] is True
        return priorities.pop(0)

    monkeypatch.setattr(macro_cli, "translate_to_priority", fake_translate_to_priority)

    result = asyncio.run(
        macro_cli._cmd_propose(
            Namespace(inputs_file=inputs_file, no_clarification=False)
        )
    )

    assert result == 0
    staged, clarifications = loader.load_proposed_priorities()
    assert [p.theme for p in staged] == [
        "AI power grid beneficiaries",
        "Quantum suppliers",
    ]
    assert clarifications == []
    assert "Estimated LLM cost: $0.60-$1.00" in capsys.readouterr().out


def test_propose_mixed_priorities_and_clarifications(monkeypatch, tmp_path, capsys):
    inputs_file = tmp_path / "inputs.txt"
    inputs_file.write_text("AI power\nSoftware\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        macro_cli,
        "_select_regime_state",
        lambda: (make_stub_regime_state(), "stub", None),
    )

    responses = [_priority("AI power grid beneficiaries", 1), _clarification("Software")]

    async def fake_translate_to_priority(**_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(macro_cli, "translate_to_priority", fake_translate_to_priority)

    result = asyncio.run(
        macro_cli._cmd_propose(
            Namespace(inputs_file=inputs_file, no_clarification=False)
        )
    )

    assert result == 0
    staged, clarifications = loader.load_proposed_priorities()
    assert len(staged) == 1
    assert len(clarifications) == 1
    assert clarifications[0]["original_user_input"] == "Software"
    assert "1 input(s) need clarification" in capsys.readouterr().out


def test_propose_validation_error_does_not_write_partial(monkeypatch, tmp_path, capsys):
    inputs_file = tmp_path / "inputs.txt"
    inputs_file.write_text("AI power\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(
        macro_cli,
        "_select_regime_state",
        lambda: (make_stub_regime_state(), "stub", None),
    )

    async def fake_translate_to_priority(**_kwargs):
        raise MacroAgentValidationError("bad macro output")

    monkeypatch.setattr(macro_cli, "translate_to_priority", fake_translate_to_priority)

    result = asyncio.run(
        macro_cli._cmd_propose(
            Namespace(inputs_file=inputs_file, no_clarification=False)
        )
    )

    assert result == 1
    assert not loader.proposed_priorities_path().exists()
    assert "no proposed_priorities.yaml was written" in capsys.readouterr().err


def test_promote_replace_mode_replaces_seed_priorities_and_preserves_other_fields(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    current_path = tmp_path / "current_regime.yaml"
    _write_current_regime(current_path, [_priority("Old priority", 1)])
    proposed = _priority("New priority", 2)
    loader.write_proposed_priorities([proposed], [])

    count, archive_path, _comments_preserved = loader.promote_priorities(
        append=False,
        current_regime_path=current_path,
    )

    raw = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    assert count == 1
    assert archive_path.exists()
    assert raw["headline"] == "Keep this field untouched"
    assert [item["theme"] for item in raw["seed_research_priorities"]] == ["New priority"]


def test_promote_append_mode_extends_seed_priorities(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    current_path = tmp_path / "current_regime.yaml"
    _write_current_regime(current_path, [_priority("Old priority", 1)])
    loader.write_proposed_priorities([_priority("New priority", 2)], [])

    loader.promote_priorities(append=True, current_regime_path=current_path)

    raw = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    assert [item["theme"] for item in raw["seed_research_priorities"]] == [
        "Old priority",
        "New priority",
    ]


def test_promote_ignores_clarifications(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    current_path = tmp_path / "current_regime.yaml"
    _write_current_regime(current_path, [_priority("Old priority", 1)])
    monkeypatch.setattr(loader, "DEFAULT_CURRENT_REGIME_PATH", current_path)
    loader.write_proposed_priorities(
        [_priority("New priority", 2)],
        [loader.clarification_to_yaml_dict("Software", _clarification("Software"))],
    )

    result = macro_cli._cmd_promote(Namespace(append=False))

    raw = yaml.safe_load(current_path.read_text(encoding="utf-8"))
    assert result == 0
    assert [item["theme"] for item in raw["seed_research_priorities"]] == ["New priority"]
    assert "Ignored 1 clarification" in capsys.readouterr().out


def test_promote_missing_staging_file_is_clear(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))

    result = macro_cli._cmd_promote(Namespace(append=False))

    assert result == 1
    assert "proposed priorities file not found" in capsys.readouterr().err


def test_show_proposed_and_current(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    current_path = tmp_path / "current_regime.yaml"
    _write_current_regime(current_path, [_priority("Current priority", 1)])
    monkeypatch.setattr(loader, "DEFAULT_CURRENT_REGIME_PATH", current_path)
    loader.write_proposed_priorities([_priority("Proposed priority", 2)], [])

    assert macro_cli._cmd_show(Namespace(proposed=True, current=False)) == 0
    proposed_out = capsys.readouterr().out
    assert "Proposed priority" in proposed_out

    assert macro_cli._cmd_show(Namespace(proposed=False, current=True)) == 0
    current_out = capsys.readouterr().out
    assert "Current priority" in current_out


def test_diff_shows_current_to_proposed_changes(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path / "data"))
    current_path = tmp_path / "current_regime.yaml"
    _write_current_regime(current_path, [_priority("Current priority", 1)])
    monkeypatch.setattr(loader, "DEFAULT_CURRENT_REGIME_PATH", current_path)
    loader.write_proposed_priorities([_priority("Proposed priority", 2)], [])

    result = macro_cli._cmd_diff(Namespace())

    assert result == 0
    out = capsys.readouterr().out
    assert "- theme: Current priority" in out
    assert "+- theme: Proposed priority" in out
