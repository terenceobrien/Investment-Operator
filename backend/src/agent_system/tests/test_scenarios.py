"""Tests for standalone scenario generation, persistence, and scoring."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent_system.llm.client import StructuredOutputError
from src.agent_system.orchestration.stub_agents import (
    construct_trade_idea,
    make_stub_fundamental_analysis,
    make_stub_narrative_analysis,
    make_stub_regime_state,
    make_stub_thematic_map,
)
from src.agent_system.rules.conviction import evaluate_conviction
from src.agent_system.scenarios import __main__ as scenario_cli
from src.agent_system.scenarios.cli_helpers import find_trade_by_ticker
from src.agent_system.scenarios.generator import ScenarioGenerationError, propose_scenarios
from src.agent_system.scenarios.loader import (
    current_path,
    load_current_scenarios,
    load_proposed_scenarios,
    proposed_path,
    write_scenario_set,
)
from src.agent_system.scenarios.scorer import (
    _ScenarioScoreBatch,
    score_trade_against_scenarios,
)
from src.agent_system.scenarios.types import (
    FactorImplications,
    Scenario,
    ScenarioScore,
    ScenarioSet,
    TradeScenarioAnalysis,
    compute_robustness,
    compute_trade_scenario_metrics,
)
from src.agent_system.schemas.common import Conviction, ConvictionRating
from src.agent_system.schemas.trade import TradeIdea
from src.agent_system.storage.repository import save_schema


def _scenario(
    scenario_id: str,
    probability: float,
    *,
    label: str | None = None,
) -> Scenario:
    return Scenario(
        id=scenario_id,
        label=label or f"{scenario_id} scenario",
        probability=probability,
        description=(
            "This scenario is specific enough to validate the scenario schema "
            "and includes a complete set of factor implications for scoring."
        ),
        factor_implications=FactorImplications(
            rates="Rates drift lower",
            equities="Equities grind higher",
            dollar="Dollar softens",
            credit="Credit spreads stay contained",
            commodities="Commodities are mixed",
        ),
        catalysts_that_confirm=["Catalyst confirming scenario"],
        catalysts_that_invalidate=["Catalyst invalidating scenario"],
    )


def _scenario_set() -> ScenarioSet:
    return ScenarioSet(
        generated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        regime_id_basis="test_regime",
        horizon_months=6,
        scenarios=[
            _scenario("base", 0.50, label="Base case scenario"),
            _scenario("bull", 0.30, label="Bull case scenario"),
            _scenario("tail", 0.20, label="Tail risk scenario"),
        ],
    )


def _trade():
    regime = make_stub_regime_state()
    candidate = make_stub_thematic_map(regime).candidates[0]
    fundamental = make_stub_fundamental_analysis(candidate)
    narrative = make_stub_narrative_analysis(candidate)
    conviction = evaluate_conviction(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
    )
    trade = construct_trade_idea(
        candidate=candidate,
        fundamental=fundamental,
        narrative=narrative,
        regime=regime,
        conviction=conviction,
    )
    return trade.model_copy(update={"id": "trade_1"})


def _trade_for_storage(
    *,
    ticker: str = "ETN",
    trade_id: str = "trade_1",
    created_at: datetime | None = None,
) -> TradeIdea:
    update = {"underlying": ticker, "id": trade_id}
    if created_at is not None:
        update["created_at"] = created_at
    return _trade().model_copy_validate(update)


def _rejected_trade(
    *,
    ticker: str = "ETN",
    trade_id: str = "rejected_1",
    created_at: datetime | None = None,
) -> TradeIdea:
    accepted = _trade_for_storage(
        ticker=ticker,
        trade_id=trade_id,
        created_at=created_at,
    )
    payload = accepted.model_dump()
    payload.update(
        {
            "combined_conviction": Conviction(
                rating=ConvictionRating.WEAK,
                rule_applied="test_rejection",
                weakest_link="thematic",
                reasoning="Rejected by test fixture.",
            ),
            "expression": None,
            "proposed_sizing": None,
            "expected_holding_period": None,
            "thesis_review_cadence": None,
            "next_review_trigger": None,
            "trade_falsifiers": [],
            "invalidation_price": None,
            "invalidation_thesis": None,
            "rejection_reason": "Rejected test trade.",
            "rejection_stage": "construction",
            "rejection_rule_fired": "test_rejection",
        }
    )
    return TradeIdea.model_validate(payload)


def _write_trade_record(
    path: Path,
    trade: TradeIdea,
    *,
    cycle_id: str | None = None,
    cycle_id_in_payload: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = trade.model_dump(mode="json")
    if cycle_id_in_payload and cycle_id is not None:
        payload["cycle_id"] = cycle_id
    row = {
        "id": trade.id,
        "schema_type": "TradeIdea",
        "schema_version": trade.schema_version,
        "created_at": trade.created_at.isoformat(),
        "cycle_id": None if cycle_id_in_payload else cycle_id,
        "ticker": trade.underlying,
        "payload_json": payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_scenario_set_probability_sum_validation():
    with pytest.raises(ValueError, match="sum"):
        ScenarioSet(
            generated_at=datetime.now(timezone.utc),
            horizon_months=6,
            scenarios=[
                _scenario("a", 0.20),
                _scenario("b", 0.20),
                _scenario("c", 0.20),
            ],
        )


def test_scenario_set_unique_ids_validation():
    with pytest.raises(ValueError, match="unique"):
        ScenarioSet(
            generated_at=datetime.now(timezone.utc),
            horizon_months=6,
            scenarios=[
                _scenario("dup", 0.40),
                _scenario("dup", 0.30),
                _scenario("tail", 0.30),
            ],
        )


def test_scenario_field_validation_requires_factor_keys():
    with pytest.raises(ValueError, match="factor_implications"):
        Scenario(
            id="bad",
            label="Bad factor scenario",
            probability=0.30,
            description=(
                "This scenario intentionally omits required factor keys so the "
                "validator can prove the output is structurally useful."
            ),
            factor_implications={"rates": "lower"},
        )


def test_factor_implications_requires_all_five_fields():
    with pytest.raises(ValueError):
        FactorImplications(
            rates="Rates drift lower",
            equities="Equities grind higher",
            dollar="Dollar softens",
            credit="Credit spreads stay contained",
        )

    factors = FactorImplications(
        rates="Rates drift lower",
        equities="Equities grind higher",
        dollar="Dollar softens",
        credit="Credit spreads stay contained",
        commodities="Commodities are mixed",
    )

    assert factors.commodities == "Commodities are mixed"


def test_scenario_field_validation_probability_bounds():
    with pytest.raises(ValueError):
        _scenario("bad_probability", 1.20)


def test_trade_scenario_analysis_metrics_fixed_input():
    scenario_set = _scenario_set()
    scores = [
        ScenarioScore(scenario_id="base", expected_pnl_pct=0.10, confidence="high", reasoning="Base case pays modestly."),
        ScenarioScore(scenario_id="bull", expected_pnl_pct=0.35, confidence="medium", reasoning="Bull case pays strongly."),
        ScenarioScore(scenario_id="tail", expected_pnl_pct=-0.20, confidence="medium", reasoning="Tail case loses money."),
    ]
    metrics = compute_trade_scenario_metrics(scores, scenario_set)
    analysis = TradeScenarioAnalysis(
        created_at=datetime.now(timezone.utc),
        trade_id="trade_1",
        scenario_set_horizon_months=scenario_set.horizon_months,
        scenario_scores=scores,
        **metrics,
    )

    assert analysis.expected_return == pytest.approx(0.115)
    assert analysis.worst_case_pnl_pct == pytest.approx(-0.20)
    assert analysis.best_case_pnl_pct == pytest.approx(0.35)
    assert analysis.scenarios_positive == 2


def test_compute_robustness_known_inputs():
    assert compute_robustness(0.20, -0.05) == pytest.approx(
        (0.20 - 0.10) / 1.05
    )
    assert compute_robustness(0.30, -0.50) == pytest.approx(
        (0.30 - 1.00) / 1.50
    )
    assert compute_robustness(-0.10, -0.30) == pytest.approx(
        (-0.10 - 0.60) / 1.30
    )


def test_propose_scenarios_with_mocked_llm(monkeypatch):
    scenario_set = _scenario_set()

    def fake_parse_structured(**_kwargs):
        return scenario_set

    monkeypatch.setattr(
        "src.agent_system.scenarios.generator.parse_structured",
        fake_parse_structured,
    )

    result = asyncio.run(propose_scenarios(make_stub_regime_state()))

    assert result == scenario_set


def test_propose_scenarios_invalid_output_retries_then_raises(monkeypatch):
    calls = {"count": 0}

    def fake_parse_structured(**_kwargs):
        calls["count"] += 1
        raise StructuredOutputError("invalid scenario set")

    monkeypatch.setattr(
        "src.agent_system.scenarios.generator.parse_structured",
        fake_parse_structured,
    )

    with pytest.raises(ScenarioGenerationError, match="3 attempts"):
        asyncio.run(propose_scenarios(make_stub_regime_state()))
    assert calls["count"] == 3


def test_score_trade_against_scenarios_with_mocked_llm(monkeypatch):
    scenario_set = _scenario_set()
    batch = _ScenarioScoreBatch(
        scenario_scores=[
            ScenarioScore(scenario_id="base", expected_pnl_pct=0.10, confidence="high", reasoning="Base case produces a positive trade payoff."),
            ScenarioScore(scenario_id="bull", expected_pnl_pct=0.40, confidence="medium", reasoning="Bull case produces a strongly positive payoff."),
            ScenarioScore(scenario_id="tail", expected_pnl_pct=-0.25, confidence="low", reasoning="Tail case produces a negative trade payoff."),
        ]
    )

    monkeypatch.setattr(
        "src.agent_system.scenarios.scorer.parse_structured",
        lambda **_kwargs: batch,
    )

    analysis = asyncio.run(score_trade_against_scenarios(_trade(), scenario_set))

    assert analysis.trade_id == "trade_1"
    assert analysis.expected_return == pytest.approx(0.12)
    assert analysis.worst_case_pnl_pct == pytest.approx(-0.25)
    assert analysis.best_case_pnl_pct == pytest.approx(0.40)
    assert analysis.scenarios_positive == 2
    assert analysis.fallback_used is False


def test_score_trade_against_scenarios_llm_failure_returns_neutral(monkeypatch):
    scenario_set = _scenario_set()

    def fake_parse_structured(**_kwargs):
        raise StructuredOutputError("scoring failed")

    monkeypatch.setattr(
        "src.agent_system.scenarios.scorer.parse_structured",
        fake_parse_structured,
    )

    analysis = asyncio.run(score_trade_against_scenarios(_trade(), scenario_set))

    assert analysis.fallback_used is True
    assert analysis.expected_return == 0
    assert all(score.expected_pnl_pct == 0 for score in analysis.scenario_scores)
    assert all(score.confidence == "low" for score in analysis.scenario_scores)


def test_find_trade_by_ticker_returns_most_recent_match(tmp_path):
    records = tmp_path / "schema_records.jsonl"
    older = _trade_for_storage(
        ticker="ETN",
        trade_id="older",
        created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    newer = _trade_for_storage(
        ticker="ETN",
        trade_id="newer",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    _write_trade_record(records, older)
    _write_trade_record(records, newer)

    result = find_trade_by_ticker("ETN", storage_path=records)

    assert result is not None
    assert result.id == "newer"


def test_find_trade_by_ticker_filters_out_rejected_trades(tmp_path):
    records = tmp_path / "schema_records.jsonl"
    rejected = _rejected_trade(
        ticker="ETN",
        trade_id="rejected",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    _write_trade_record(records, rejected)

    assert find_trade_by_ticker("ETN", storage_path=records) is None


def test_find_trade_by_ticker_returns_none_when_ticker_missing(tmp_path):
    records = tmp_path / "schema_records.jsonl"
    _write_trade_record(records, _trade_for_storage(ticker="ETN"))

    assert find_trade_by_ticker("VST", storage_path=records) is None


def test_find_trade_by_ticker_filters_by_cycle_id(tmp_path):
    records = tmp_path / "schema_records.jsonl"
    cycle_a = _trade_for_storage(
        ticker="ETN",
        trade_id="cycle_a",
        created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    cycle_b = _trade_for_storage(
        ticker="ETN",
        trade_id="cycle_b",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    _write_trade_record(records, cycle_a, cycle_id="cycle_a")
    _write_trade_record(records, cycle_b, cycle_id="cycle_b", cycle_id_in_payload=True)

    assert (
        find_trade_by_ticker("ETN", cycle_id="cycle_a", storage_path=records).id
        == "cycle_a"
    )
    assert (
        find_trade_by_ticker("ETN", cycle_id="cycle_b", storage_path=records).id
        == "cycle_b"
    )


def test_cli_propose_writes_proposed_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        scenario_cli,
        "_select_regime_state",
        lambda: (make_stub_regime_state(), "stub", None),
    )

    async def fake_propose_scenarios(**_kwargs):
        return _scenario_set()

    monkeypatch.setattr(scenario_cli, "propose_scenarios", fake_propose_scenarios)

    result = asyncio.run(
        scenario_cli._cmd_propose(
            SimpleNamespace(horizon_months=6, n_scenarios=3)
        )
    )

    assert result == 0
    assert proposed_path().exists()
    assert load_proposed_scenarios() == _scenario_set()


def test_cli_promote_moves_proposed_to_current_and_archives_prior(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    old_set = _scenario_set()
    new_set = _scenario_set().model_copy(
        update={"generated_at": datetime(2026, 5, 31, tzinfo=timezone.utc)}
    )
    write_scenario_set(current_path(), old_set)
    write_scenario_set(proposed_path(), new_set)

    result = scenario_cli._cmd_promote(SimpleNamespace())

    assert result == 0
    assert not proposed_path().exists()
    assert load_current_scenarios() == new_set
    archives = list((tmp_path / "scenarios" / "archive").glob("scenarios_*.yaml"))
    assert len(archives) == 1


def test_cli_promote_fails_on_invalid_proposed_file(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    current = _scenario_set()
    write_scenario_set(current_path(), current)
    proposed_path().parent.mkdir(parents=True, exist_ok=True)
    proposed_path().write_text(
        "generated_at: '2026-05-30T00:00:00Z'\nhorizon_months: 6\nscenarios: []\n",
        encoding="utf-8",
    )

    result = scenario_cli._cmd_promote(SimpleNamespace())

    assert result == 1
    assert proposed_path().exists()
    assert load_current_scenarios() == current


def test_cli_show_and_diff_do_not_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    write_scenario_set(current_path(), _scenario_set())
    write_scenario_set(
        proposed_path(),
        _scenario_set().model_copy(
            update={"generated_at": datetime(2026, 5, 31, tzinfo=timezone.utc)}
        ),
    )

    assert scenario_cli._cmd_show(SimpleNamespace(proposed=False)) == 0
    assert scenario_cli._cmd_show(SimpleNamespace(proposed=True)) == 0
    assert scenario_cli._cmd_diff(SimpleNamespace()) == 0


def test_cli_score_subcommand_scores_and_persists_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_SYSTEM_DATA_DIR", str(tmp_path))
    scenario_set = _scenario_set()
    write_scenario_set(current_path(), scenario_set)
    trade = _trade_for_storage(ticker="ETN", trade_id="trade_score")
    save_schema(trade)
    scores = [
        ScenarioScore(
            scenario_id="base",
            expected_pnl_pct=0.10,
            confidence="high",
            reasoning="Base case produces a positive trade payoff.",
        ),
        ScenarioScore(
            scenario_id="bull",
            expected_pnl_pct=0.35,
            confidence="medium",
            reasoning="Bull case produces a strongly positive payoff.",
        ),
        ScenarioScore(
            scenario_id="tail",
            expected_pnl_pct=-0.20,
            confidence="low",
            reasoning="Tail risk produces a negative payoff.",
        ),
    ]
    analysis = TradeScenarioAnalysis(
        created_at=datetime.now(timezone.utc),
        trade_id="trade_score",
        scenario_set_horizon_months=scenario_set.horizon_months,
        scenario_scores=scores,
        **compute_trade_scenario_metrics(scores, scenario_set),
    )

    async def fake_score_trade_against_scenarios(_trade, _scenario_set):
        return analysis

    monkeypatch.setattr(
        scenario_cli,
        "score_trade_against_scenarios",
        fake_score_trade_against_scenarios,
    )

    result = asyncio.run(
        scenario_cli._cmd_score(SimpleNamespace(ticker="ETN", cycle_id=None))
    )

    assert result == 0
    rows = [
        json.loads(line)
        for line in (tmp_path / "schema_records.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(row["schema_type"] == "TradeScenarioAnalysis" for row in rows)
