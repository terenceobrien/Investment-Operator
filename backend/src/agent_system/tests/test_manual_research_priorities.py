from __future__ import annotations

import pytest

from src.agent_system.forecasting.macro_scenario_source import (
    MacroScenarioSourceError,
    load_manual_research_priorities,
)
from src.agent_system.schemas.common import EvidenceSourceType


def _write_manual_priority_file(path, *, body: str | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        body
        or """
priorities:
  - theme: Manual breadth rotation
    rationale: Breadth is deteriorating under narrow index leadership.
    edge_hypothesis: The market is underpricing the persistence of dispersion after breadth breaks down.
    sub_questions:
      - Which defensives are seeing improving revisions?
      - Which crowded leaders are losing breadth support?
    priority_rank: 1
    expected_edge_decay: months
""".lstrip(),
        encoding="utf-8",
    )
    return path


def test_load_manual_research_priorities_valid_file_injects_defaults(tmp_path):
    path = _write_manual_priority_file(tmp_path / "manual_research_priorities.yaml")

    priorities = load_manual_research_priorities(path)

    assert len(priorities) == 1
    priority = priorities[0]
    assert priority.theme == "Manual breadth rotation"
    assert priority.source == "operator_manual"
    assert priority.source_macro_forecast_id is None
    evidence = priority.supporting_evidence[0]
    assert evidence.source_type == EvidenceSourceType.DERIVED
    assert evidence.claim == "Manual research priority: Manual breadth rotation"
    assert evidence.computation == "operator manual entry"
    assert evidence.upstream_claims == ["manual_research_priorities.yaml"]


def test_load_manual_research_priorities_accepts_shorthand_derived_evidence(tmp_path):
    path = _write_manual_priority_file(
        tmp_path / "manual_research_priorities.yaml",
        body="""
priorities:
  - theme: Manual credit watch
    rationale: Credit spreads are still tight but moving the wrong way.
    edge_hypothesis: The market is pricing credit tightness as benign even though the direction of travel is worsening.
    sub_questions:
      - Which balance-sheet-sensitive equities are underreacting?
    priority_rank: 2
    expected_edge_decay: weeks
    supporting_evidence:
      - claim: Spread trend supports the manual credit watch.
        supports: true
        computation: operator read of credit spread trend
        upstream_claims:
          - manual dashboard review
""".lstrip(),
    )

    priority = load_manual_research_priorities(path)[0]

    assert priority.source == "operator_manual"
    assert priority.supporting_evidence[0].source_type == EvidenceSourceType.DERIVED
    assert priority.supporting_evidence[0].claim == "Spread trend supports the manual credit watch."


def test_load_manual_research_priorities_missing_required_field_names_file_index_and_field(tmp_path):
    path = _write_manual_priority_file(
        tmp_path / "manual_research_priorities.yaml",
        body="""
priorities:
  - theme: Missing edge
    rationale: This entry is intentionally malformed.
    sub_questions: []
    priority_rank: 1
    expected_edge_decay: months
""".lstrip(),
    )

    with pytest.raises(MacroScenarioSourceError) as excinfo:
        load_manual_research_priorities(path)

    message = str(excinfo.value)
    assert str(path) in message
    assert "entry 0" in message
    assert "edge_hypothesis" in message


def test_load_manual_research_priorities_empty_and_missing_files_fail_loud(tmp_path):
    empty_path = _write_manual_priority_file(
        tmp_path / "manual_research_priorities.yaml",
        body="priorities: []\n",
    )
    with pytest.raises(MacroScenarioSourceError, match="empty priorities list"):
        load_manual_research_priorities(empty_path)

    missing_path = tmp_path / "missing.yaml"
    with pytest.raises(MacroScenarioSourceError) as excinfo:
        load_manual_research_priorities(missing_path)

    message = str(excinfo.value)
    assert str(missing_path) in message
    assert "resolution_source=explicit_path" in message
