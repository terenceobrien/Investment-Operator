from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.agent_system.orchestration.run_research_cycle import run_stub_research_cycle
from src.agent_system.orchestration.stub_agents import (
    build_stub_trade_for_candidate,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.trade import TradeIdea


def test_run_stub_research_cycle_persists_accepted_and_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    summary = run_stub_research_cycle()

    assert summary["accepted"] >= 1
    assert summary["rejected"] >= 1
    assert summary["trade_ideas_saved"] == summary["decision_log_entries"]
    assert "ETN" in summary["accepted_underlyings"]
    assert (tmp_path / "schema_records.jsonl").exists()
    assert (tmp_path / "decision_log.jsonl").exists()


def test_fixture_style_trade_ideas_are_schema_valid():
    regime = make_stub_regime_state()
    thematic_map = make_stub_thematic_map(regime)
    etn = next(c for c in thematic_map.candidates if c.ticker == "ETN")
    smh = next(c for c in thematic_map.candidates if c.ticker == "SMH")

    accepted = build_stub_trade_for_candidate(etn, regime)
    rejected = build_stub_trade_for_candidate(smh, regime)

    assert accepted.expression is not None
    assert len(accepted.trade_falsifiers) >= 3
    assert rejected.expression is None
    assert rejected.rejection_reason is not None


def test_tradeidea_validation_rejects_pass_with_expression():
    regime = make_stub_regime_state()
    thematic_map = make_stub_thematic_map(regime)
    etn = next(c for c in thematic_map.candidates if c.ticker == "ETN")
    accepted = build_stub_trade_for_candidate(etn, regime)
    pass_conviction = Conviction(
        rating=ConvictionRating.PASS,
        rule_applied="test_pass_rule",
        weakest_link="thematic",
        reasoning="A pass-rated idea must not carry a trade expression.",
    )

    with pytest.raises(ValidationError):
        TradeIdea(
            underlying="ETN",
            combined_conviction=pass_conviction,
            expression=accepted.expression,
            proposed_sizing=None,
            rejection_reason="This should fail because expression is present.",
            rejection_stage="thematic",
        )


def test_fixture_json_files_are_valid_examples():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    expected = {
        "accepted_etn_trade.json",
        "candidate_no_variant_pass.json",
        "strong_company_no_fundamental_variant_pass.json",
        "crowded_mature_narrative_weak.json",
        "rejected_trade_idea.json",
        "accepted_trade_idea.json",
    }
    for name in expected:
        path = fixture_dir / name
        assert path.exists(), name
        assert json.loads(path.read_text(encoding="utf-8"))
