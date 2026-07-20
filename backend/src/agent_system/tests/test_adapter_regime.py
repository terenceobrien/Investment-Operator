"""
Tests for the dataclass-to-Pydantic RegimeState adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.agent_system.adapters.regime import RegimeAdapterError, adapt_regime_state
from src.agent_system.schemas.forward import ForwardContext, MarketEvent
from src.agent_system.schemas.regime import (
    EdgeDecayHorizon,
    RegimeLayerStatus,
    RegimeState as PydanticRegimeState,
)
from src.state.regime_state import RegimeState as DataclassRegimeState


BASE_CURATION_YAML = """
regime_id: "supply_shock_inflation"
regime_label: "Supply-shock inflation / late-cycle tightening"
regime_call_confidence: 0.72
headline: "Oil-driven inflation pressure is tightening financial conditions."
summary: "Broad beta is fragile while select AI infrastructure can still work."
risk_summary: "Narrow leadership can be mistaken for a clean risk-on regime."
key_drivers:
  - name: "Oil supply shock"
    status: "bearish for broad beta / bullish for energy"
    explanation: "Elevated oil keeps inflation risk alive."
portfolio_implications:
  - "Favor energy and short duration."
best_positioned:
  - "Energy / oil beta"
most_vulnerable:
  - "Small caps"
falsifiers:
  - condition: "Oil falls below $70 and stays for 5+ sessions"
    observable_in: "price_action"
    check_frequency: "daily"
seed_research_priorities:
  - theme: "AI power/grid beneficiaries"
    rationale: "Tight policy hurts broad beta but data-center power demand remains durable."
    edge_hypothesis: "Market attention is concentrated in semiconductors while grid demand duration is underappreciated."
    sub_questions:
      - "Which names have direct exposure to data-center power equipment demand?"
    priority_rank: 1
    expected_edge_decay: "quarters"
"""


def _write_yaml(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "current_regime.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def _make_dataclass_state(**overrides) -> DataclassRegimeState:
    state = DataclassRegimeState(
        asof_date="2026-05-21",
        asof_utc=datetime(2026, 5, 21, 21, 0, tzinfo=timezone.utc).isoformat(),
        layer_monetary=3.4,
        layer_credit=7.0,
        layer_volatility=5.0,
        layer_breadth=3.0,
        layer_positioning=6.0,
        layer_signals={
            "monetary": ["Liquidity tightening"],
            "credit": ["Credit stress contained"],
            "volatility": ["VIX neutral"],
            "breadth": ["Breadth weak"],
            "positioning": ["Positioning balanced"],
        },
        score_total=43.0,
        environment="Late-cycle tightening with narrow AI leadership",
        environment_drivers=["Oil shock", "Fed repricing"],
        confidence=78.0,
        layer_agreement=0.72,
        horizon="default",
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_adapt_regime_state_with_production_current_regime_yaml():
    state = _make_dataclass_state()
    adapted = adapt_regime_state(state)

    assert isinstance(adapted, PydanticRegimeState)
    assert adapted.regime_id == "two_sided_oil_shock_late_cycle_ai"
    assert adapted.research_priorities


def test_layer_scores_translate_field_by_field(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.layers.monetary.score == 3.4
    assert adapted.layers.monetary.signals == ["Liquidity tightening"]
    assert adapted.layers.breadth.score == 3.0


def test_status_derivation(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.layers.credit.status == RegimeLayerStatus.BULLISH
    assert adapted.layers.breadth.status == RegimeLayerStatus.BEARISH
    assert adapted.layers.volatility.status == RegimeLayerStatus.NEUTRAL


def test_data_quality_zero_when_layer_score_is_none(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(layer_monetary=None),
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.layers.monetary.score == 5.0
    assert adapted.layers.monetary.data_quality == 0.0
    assert adapted.layers.monetary.status == RegimeLayerStatus.NEUTRAL


def test_weights_translate_from_dataclass_dict(tmp_path):
    state = _make_dataclass_state()
    state.weights = {
        "monetary": 0.2,
        "credit": 0.2,
        "volatility": 0.2,
        "breadth": 0.2,
        "positioning": 0.2,
    }

    adapted = adapt_regime_state(
        state,
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.weights.credit == 0.2
    assert adapted.weights.positioning == 0.2


def test_curated_fields_populate_from_yaml(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.regime_label == "Supply-shock inflation / late-cycle tightening"
    assert adapted.headline.startswith("Oil-driven")
    assert adapted.key_drivers[0].name == "Oil supply shock"
    assert adapted.best_positioned == ["Energy / oil beta"]


def test_seed_research_priorities_produce_valid_objects(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert len(adapted.research_priorities) == 1
    assert adapted.research_priorities[0].theme == "AI power/grid beneficiaries"
    assert adapted.research_priorities[0].expected_edge_decay == EdgeDecayHorizon.QUARTERS
    assert adapted.research_priorities[0].supporting_evidence
    assert (
        adapted.research_priorities[0]
        .supporting_evidence[0]
        .claim.startswith("Seed research priority from current_regime.yaml")
    )


def test_scenario_probabilities_populate_from_current_regime_yaml(tmp_path):
    yaml_with_probabilities = BASE_CURATION_YAML + """
scenario_probabilities:
  sticky_late_cycle_ai: 0.42
  reopening_soft_landing: 0.28
  oil_inflation_tail: 0.14
  late_cycle_risk_off: 0.11
  ai_capex_rollover: 0.05
"""
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, yaml_with_probabilities),
    )

    assert adapted.scenario_probabilities["sticky_late_cycle_ai"] == pytest.approx(0.42)
    assert adapted.scenario_probability_source == "current_regime_yaml"


def test_absent_seed_research_priorities_returns_empty_list(tmp_path):
    yaml_without_seed = BASE_CURATION_YAML.split("seed_research_priorities:")[0]
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, yaml_without_seed),
    )

    assert adapted.research_priorities == []


def test_falsifiers_translate_and_malformed_entries_are_skipped(tmp_path):
    yaml_with_bad_falsifier = BASE_CURATION_YAML.replace(
        '  - condition: "Oil falls below $70 and stays for 5+ sessions"\n'
        '    observable_in: "price_action"\n'
        '    check_frequency: "daily"\n',
        '  - condition: "Oil falls below $70 and stays for 5+ sessions"\n'
        '    observable_in: "price_action"\n'
        '    check_frequency: "daily"\n'
        '  - condition: "Malformed entry without enums"\n'
        '    observable_in: "bad_observable"\n'
        '    check_frequency: "daily"\n',
    )
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        curation_config_path=_write_yaml(tmp_path, yaml_with_bad_falsifier),
    )

    assert len(adapted.falsifiers) == 1
    assert adapted.falsifiers[0].condition.startswith("Oil falls")


def test_forward_context_none_attaches_as_none(tmp_path):
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        forward_context=None,
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.forward_context is None


def test_forward_context_attaches(tmp_path):
    forward_context = ForwardContext(
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
    adapted = adapt_regime_state(
        _make_dataclass_state(),
        forward_context=forward_context,
        curation_config_path=_write_yaml(tmp_path, BASE_CURATION_YAML),
    )

    assert adapted.forward_context is not None
    assert adapted.forward_context.upcoming_catalysts[0].name == "FOMC June Meeting"


def test_malformed_yaml_raises_regime_adapter_error(tmp_path):
    with pytest.raises(RegimeAdapterError):
        adapt_regime_state(
            _make_dataclass_state(),
            curation_config_path=_write_yaml(tmp_path, "regime_id: ["),
        )


def test_missing_required_curation_field_raises(tmp_path):
    missing_regime_id = BASE_CURATION_YAML.replace(
        'regime_id: "supply_shock_inflation"\n',
        "",
    )
    with pytest.raises(RegimeAdapterError):
        adapt_regime_state(
            _make_dataclass_state(),
            curation_config_path=_write_yaml(tmp_path, missing_regime_id),
        )
