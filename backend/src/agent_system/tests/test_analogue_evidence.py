from __future__ import annotations

import json

import pandas as pd
import pytest
import yaml

from src.agent_system.forecasting.macro_scenario_source import (
    MacroScenarioSourceConfig,
    get_macro_scenario_source,
)
from src.agent_system.forecasting.scenario_classifier import analogue_evidence
from src.agent_system.forecasting.scenario_classifier.analogue_evidence import (
    AnalogueEvidence,
    AnalogueEvidenceError,
    AnalogueWindowState,
    apply_analogue_mixture,
    compact_analogue_report_for_yaml,
    compact_top_match_strings,
    compute_analogue_evidence,
    conditional_timing_summary,
    load_analogue_evidence_config,
    onset_lag_distribution,
    validate_probability_taxonomy_coherence,
)
from src.agent_system.forecasting.scenario_classifier.analogue_matcher import (
    AnalogueMatch,
    AnalogueMatchResult,
    level_feature_columns,
    trend_feature_columns,
)
from src.agent_system.forecasting.scenario_classifier.forward_outcomes import (
    DEFAULT_PRIOR_STRENGTH,
    shrink_neighbor_share,
)


SCENARIOS = (
    "expansion_disinflation",
    "late_cycle_expansion",
    "inflation_shock",
    "stagflation",
    "growth_scare_no_credit",
    "credit_led_recession",
)


def _probabilities() -> dict[str, float]:
    return {
        "expansion_disinflation": 0.20,
        "late_cycle_expansion": 0.30,
        "inflation_shock": 0.10,
        "stagflation": 0.15,
        "growth_scare_no_credit": 0.15,
        "credit_led_recession": 0.10,
    }


def _membership() -> dict[str, bool]:
    return {scenario_id: scenario_id == "credit_led_recession" for scenario_id in SCENARIOS}


def _config_snapshot(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "trailing_window_quarters": 6,
        "prior_strength": DEFAULT_PRIOR_STRENGTH,
        "horizon_quarters": 8,
        "min_pool": 30,
        "stress_advisory_threshold": 0.35,
        "mixture_alpha": 0.30,
        "survival_conditioning": True,
        "scenario_recession_membership": _membership(),
        "source_path": "test",
    }
    payload.update(overrides)
    return payload


def _state(
    quarter: str,
    state: str,
    share: float | None,
    *,
    raw: float | None = None,
    kernel: float = 1.0,
    onset_lag_distribution: dict[str, object] | None = None,
) -> AnalogueWindowState:
    return AnalogueWindowState(
        quarter=quarter,
        state=state,
        share=share,
        share_raw=raw if raw is not None else share,
        n_matches=1 if share is not None else 0,
        evaluable_neighbor_count=1 if share is not None else 0,
        dropped_unresolved_count=0,
        kernel_weight_sum=kernel if share is not None else 0.0,
        pit_candidate_pool_size=30,
        onset_lag_distribution=onset_lag_distribution,
    )


def _evidence(
    *,
    trailing_max: float | None,
    base_rate: float = 0.25,
    current_state: str = "scored",
    spot_share: float | None = None,
    kernel_weight_sum: float = 1.0,
    config_snapshot: dict[str, object] | None = None,
) -> AnalogueEvidence:
    if spot_share is None and trailing_max is not None and current_state == "scored":
        spot_share = trailing_max
    return AnalogueEvidence(
        query_date="2026Q2",
        current_state=current_state,
        spot_share=spot_share,
        trailing_max=trailing_max,
        window_states=(
            _state("2026Q1", current_state, spot_share, kernel=kernel_weight_sum)
            if current_state == "scored"
            else _state("2026Q1", current_state, None, kernel=0.0),
        ),
        base_rate=base_rate,
        kernel_weight_sum=kernel_weight_sum,
        stress_advisory=False,
        config_snapshot=config_snapshot or _config_snapshot(),
    )


def _library(start: str = "2021Q1", periods: int = 5) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for idx, period in enumerate(pd.period_range(start, periods=periods, freq="Q")):
        row: dict[str, float | str] = {"as_of": str(period)}
        for column in level_feature_columns():
            row[column] = float(idx) / 10.0
        for column in trend_feature_columns():
            row[column] = float(idx) / 100.0
        rows.append(row)
    return pd.DataFrame(rows)


def test_mixture_math_matches_hand_computed_fixture():
    probabilities = _probabilities()
    evidence = _evidence(trailing_max=0.50, base_rate=0.25)

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    expected_analogue = dict(probabilities)
    expected_analogue["credit_led_recession"] = 0.50
    for scenario_id, probability in probabilities.items():
        if scenario_id != "credit_led_recession":
            expected_analogue[scenario_id] = 0.50 * probability / 0.90
    expected_mixed = {
        scenario_id: 0.70 * probabilities[scenario_id] + 0.30 * expected_analogue[scenario_id]
        for scenario_id in probabilities
    }
    assert after["credit_led_recession"] == pytest.approx(
        expected_mixed["credit_led_recession"]
    )
    assert sum(after.values()) == pytest.approx(1.0)
    assert after["expansion_disinflation"] / after["late_cycle_expansion"] == pytest.approx(
        probabilities["expansion_disinflation"] / probabilities["late_cycle_expansion"]
    )
    assert report["analogue_implied"]["credit_led_recession"] == pytest.approx(0.50)
    assert report["mixed_pre_floor"]["credit_led_recession"] == pytest.approx(
        expected_mixed["credit_led_recession"]
    )
    assert report["alpha"] == pytest.approx(0.30)
    assert report["alpha_effective"] == pytest.approx(0.30)
    assert report["per_scenario"]["credit_led_recession"]["delta"] > 0


def test_mixture_preserves_within_group_ratios_with_two_recession_scenarios():
    probabilities = _probabilities()
    membership = _membership()
    membership["growth_scare_no_credit"] = True
    evidence = _evidence(
        trailing_max=0.40,
        base_rate=0.25,
        config_snapshot=_config_snapshot(scenario_recession_membership=membership),
    )

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert sum(after.values()) == pytest.approx(1.0)
    assert after["credit_led_recession"] / after["growth_scare_no_credit"] == pytest.approx(
        probabilities["credit_led_recession"] / probabilities["growth_scare_no_credit"]
    )
    assert report["membership_groups"]["recession"] == [
        "growth_scare_no_credit",
        "credit_led_recession",
    ]


def test_mixture_uniform_fallback_when_recession_group_mass_is_zero():
    probabilities = _probabilities()
    membership = _membership()
    membership["growth_scare_no_credit"] = True
    probabilities["expansion_disinflation"] += probabilities["credit_led_recession"]
    probabilities["late_cycle_expansion"] += probabilities["growth_scare_no_credit"]
    probabilities["credit_led_recession"] = 0.0
    probabilities["growth_scare_no_credit"] = 0.0
    evidence = _evidence(
        trailing_max=0.30,
        base_rate=0.25,
        config_snapshot=_config_snapshot(scenario_recession_membership=membership),
    )

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert report["analogue_implied"]["credit_led_recession"] == pytest.approx(0.15)
    assert report["analogue_implied"]["growth_scare_no_credit"] == pytest.approx(0.15)
    assert after["credit_led_recession"] == pytest.approx(after["growth_scare_no_credit"])
    assert sum(after.values()) == pytest.approx(1.0)


def test_collapsed_credit_tail_gets_restored_by_mixture():
    probabilities = {
        "expansion_disinflation": 0.25,
        "late_cycle_expansion": 0.45,
        "inflation_shock": 0.15,
        "stagflation": 0.08,
        "growth_scare_no_credit": 0.0699,
        "credit_led_recession": 0.0001,
    }
    evidence = _evidence(trailing_max=0.37, base_rate=0.27)

    after, _report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert after["credit_led_recession"] > 0.10
    assert sum(after.values()) == pytest.approx(1.0)


def test_mixture_numerical_floor_is_uniform_guard():
    probabilities = _probabilities()
    probabilities["expansion_disinflation"] += probabilities["stagflation"]
    probabilities["stagflation"] = 0.0
    evidence = _evidence(trailing_max=0.10, base_rate=0.10)

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert report["floor_applied"]["stagflation"] is True
    assert after["stagflation"] > 0.0
    assert sum(after.values()) == pytest.approx(1.0)


def test_s_equals_bvar_group_mass_produces_no_movement():
    probabilities = _probabilities()
    evidence = _evidence(trailing_max=0.10, base_rate=0.10)

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert after == pytest.approx(probabilities)
    assert report["movement_total_abs"] == pytest.approx(0.0)


def test_thin_set_shrinkage_forces_no_movement_when_kernel_weight_is_zero():
    probabilities = _probabilities()
    base_rate = 0.27
    shrunk = shrink_neighbor_share(
        1.0,
        0.0,
        base_rate=base_rate,
        prior_strength=DEFAULT_PRIOR_STRENGTH,
    )
    evidence = _evidence(
        trailing_max=shrunk,
        base_rate=base_rate,
        kernel_weight_sum=0.0,
    )
    probabilities["expansion_disinflation"] -= base_rate - probabilities["credit_led_recession"]
    probabilities["credit_led_recession"] = base_rate

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert shrunk == pytest.approx(base_rate)
    assert after == pytest.approx(probabilities)
    assert report["movement_total_abs"] == pytest.approx(0.0)


def test_full_window_abstention_leaves_distribution_unchanged():
    probabilities = _probabilities()
    evidence = _evidence(
        trailing_max=None,
        current_state="unprecedented_state",
        spot_share=None,
        kernel_weight_sum=0.0,
    )

    after, report = apply_analogue_mixture(probabilities, evidence, alpha=0.30)

    assert after == pytest.approx(probabilities)
    assert report["applied"] is False
    assert report["reason"] == "full_window_abstention"
    assert report["alpha_effective"] == 0.0


def test_stress_advisory_rules(monkeypatch):
    config = _config_snapshot(trailing_window_quarters=3, stress_advisory_threshold=0.35)
    monkeypatch.setattr(analogue_evidence, "compute_analogue_base_rate", lambda *_args, **_kwargs: 0.25)

    def compute_with(states: dict[str, AnalogueWindowState]) -> AnalogueEvidence:
        monkeypatch.setattr(
            analogue_evidence,
            "_score_window_quarter",
            lambda period, **_kwargs: states[str(period)],
        )
        return compute_analogue_evidence(
            "2021Q4",
            config=config,
            library=_library(),
            validate_library_current=False,
        )

    fires = compute_with(
        {
            "2021Q2": _state("2021Q2", "scored", 0.20),
            "2021Q3": _state("2021Q3", "scored", 0.36),
            "2021Q4": _state("2021Q4", "unprecedented_state", None),
        }
    )
    whole_window_abstained = compute_with(
        {
            "2021Q2": _state("2021Q2", "unprecedented_state", None),
            "2021Q3": _state("2021Q3", "unprecedented_state", None),
            "2021Q4": _state("2021Q4", "unprecedented_state", None),
        }
    )
    current_scored = compute_with(
        {
            "2021Q2": _state("2021Q2", "scored", 0.40),
            "2021Q3": _state("2021Q3", "scored", 0.36),
            "2021Q4": _state("2021Q4", "scored", 0.10),
        }
    )

    assert fires.stress_advisory is True
    assert whole_window_abstained.stress_advisory is False
    assert current_scored.stress_advisory is False


def test_survival_conditioned_trailing_max_can_shift_binding_quarter(monkeypatch):
    config = _config_snapshot(trailing_window_quarters=3, survival_conditioning=True)
    monkeypatch.setattr(analogue_evidence, "compute_analogue_base_rate", lambda *_args, **_kwargs: 0.25)
    onset_distribution = {
        "horizon_quarters": 8,
        "histogram": {
            "0": 0.0,
            "1": 0.40,
            "2": 0.40,
            "3": 0.20,
            "4": 0.0,
            "5": 0.0,
            "6": 0.0,
            "7": 0.0,
            "8": 0.0,
        },
        "effective_n": 10.0,
    }
    states = {
        "2025Q4": _state("2025Q4", "scored", 0.80, onset_lag_distribution=onset_distribution),
        "2026Q1": _state("2026Q1", "scored", 0.20, onset_lag_distribution=onset_distribution),
        "2026Q2": _state("2026Q2", "scored", 0.50, onset_lag_distribution=onset_distribution),
    }
    monkeypatch.setattr(
        analogue_evidence,
        "_score_window_quarter",
        lambda period, **_kwargs: states[str(period)],
    )

    evidence = compute_analogue_evidence(
        "2026Q2",
        config=config,
        library=_library(start="2025Q4", periods=3),
        validate_library_current=False,
    )

    old_state = evidence.window_states[0]
    spot_state = evidence.window_states[-1]
    assert old_state.conditioned_share == pytest.approx(0.80 * 0.20 / (1.0 - 0.80 * 0.80))
    assert spot_state.conditioned_share == pytest.approx(0.50)
    assert evidence.trailing_max_unconditioned == pytest.approx(0.80)
    assert evidence.trailing_max_conditioned == pytest.approx(0.50)
    assert evidence.s_used == pytest.approx(0.50)
    assert evidence.binding_quarter == "2026Q2"
    assert evidence.s_source == "survival_conditioned_trailing_max"


def test_survival_conditioning_false_uses_unconditioned_trailing_max(monkeypatch):
    config = _config_snapshot(trailing_window_quarters=3, survival_conditioning=False)
    monkeypatch.setattr(analogue_evidence, "compute_analogue_base_rate", lambda *_args, **_kwargs: 0.25)
    onset_distribution = {
        "horizon_quarters": 8,
        "histogram": {
            "0": 0.0,
            "1": 0.40,
            "2": 0.40,
            "3": 0.20,
            "4": 0.0,
            "5": 0.0,
            "6": 0.0,
            "7": 0.0,
            "8": 0.0,
        },
        "effective_n": 10.0,
    }
    states = {
        "2025Q4": _state("2025Q4", "scored", 0.80, onset_lag_distribution=onset_distribution),
        "2026Q1": _state("2026Q1", "scored", 0.20, onset_lag_distribution=onset_distribution),
        "2026Q2": _state("2026Q2", "scored", 0.50, onset_lag_distribution=onset_distribution),
    }
    monkeypatch.setattr(
        analogue_evidence,
        "_score_window_quarter",
        lambda period, **_kwargs: states[str(period)],
    )

    evidence = compute_analogue_evidence(
        "2026Q2",
        config=config,
        library=_library(start="2025Q4", periods=3),
        validate_library_current=False,
    )

    assert evidence.trailing_max_unconditioned == pytest.approx(0.80)
    assert evidence.trailing_max_conditioned == pytest.approx(0.50)
    assert evidence.s_used == pytest.approx(0.80)
    assert evidence.trailing_max == pytest.approx(0.80)
    assert evidence.binding_quarter == "2025Q4"
    assert evidence.s_source == "unconditioned_trailing_max"


def test_no_timing_evidence_fallback_keeps_share_unchanged(monkeypatch):
    config = _config_snapshot(trailing_window_quarters=1, survival_conditioning=True)
    monkeypatch.setattr(analogue_evidence, "compute_analogue_base_rate", lambda *_args, **_kwargs: 0.25)
    monkeypatch.setattr(
        analogue_evidence,
        "_score_window_quarter",
        lambda period, **_kwargs: _state(
            str(period),
            "scored",
            0.70,
            onset_lag_distribution={
                "horizon_quarters": 8,
                "histogram": {str(lag): 0.0 for lag in range(0, 9)},
                "effective_n": 0.0,
            },
        ),
    )

    evidence = compute_analogue_evidence(
        "2021Q1",
        config=config,
        library=_library(start="2021Q1", periods=1),
        validate_library_current=False,
    )

    state = evidence.window_states[0]
    assert state.no_timing_evidence is True
    assert state.conditioned_share == pytest.approx(0.70)
    assert evidence.s_used == pytest.approx(0.70)


def test_top_matches_are_serialized_ordered_and_compact(monkeypatch):
    config = _config_snapshot(trailing_window_quarters=1, min_pool=1)
    monkeypatch.setattr(analogue_evidence, "compute_analogue_base_rate", lambda *_args, **_kwargs: 0.25)
    match_dates = [
        "2006Q4",
        "2000Q4",
        "1990Q2",
        "1995Q1",
        "1996Q1",
        "1997Q1",
        "1998Q1",
        "1999Q1",
        "2000Q1",
        "2000Q2",
        "1989Q4",
        "1988Q4",
    ]
    matches = tuple(
        AnalogueMatch(
            analogue_date=date,
            distance=float(idx) / 10.0,
            level_distance=float(idx) / 10.0,
            trend_distance=float(idx) / 10.0,
            kernel_weight=float(len(match_dates) - idx),
        )
        for idx, date in enumerate(match_dates)
    )

    def fake_match(query_date, **_kwargs):
        return AnalogueMatchResult(str(pd.Period(query_date, freq="Q")), matches, {})

    monkeypatch.setattr(analogue_evidence, "match_analogues", fake_match)

    evidence = compute_analogue_evidence(
        "2007Q4",
        config=config,
        library=_library(start="1980Q1", periods=112),
        validate_library_current=False,
    )
    state = evidence.window_states[0]

    assert len(state.top_matches) == 10
    assert [match.kernel_weight for match in state.top_matches] == sorted(
        [match.kernel_weight for match in state.top_matches],
        reverse=True,
    )
    assert state.top_matches[0].neighbor_quarter == "2006Q4"
    assert state.top_matches[0].resolved is False
    assert state.top_matches[0].recession_bound is None
    assert state.top_matches[1].recession_bound is True
    assert state.top_matches[1].onset_lag_quarters == 1
    compact = compact_top_match_strings(state)
    assert len(compact) == 5
    assert compact[0].startswith("2006Q4 (w=12.00, unresolved")
    assert "rec, lag 1" in compact[1]


def test_onset_lag_distribution_and_conditional_timing():
    matches = (
        AnalogueMatch("2000Q4", 0.1, 0.1, 0.1, 2.0),
        AnalogueMatch("2000Q3", 0.1, 0.1, 0.1, 1.0),
        AnalogueMatch("2001Q2", 0.1, 0.1, 0.1, 3.0),
        AnalogueMatch("1995Q1", 0.1, 0.1, 0.1, 4.0),
    )

    dist = onset_lag_distribution(
        matches,
        "2003Q4",
        horizon_quarters=8,
        max_known_quarter="2003Q4",
    )

    assert dist["histogram"]["0"] == pytest.approx(3.0 / 6.0)
    assert dist["histogram"]["1"] == pytest.approx(2.0 / 6.0)
    assert dist["histogram"]["2"] == pytest.approx(1.0 / 6.0)
    assert sum(dist["histogram"].values()) == pytest.approx(1.0)
    assert dist["in_recession_at_match"]["count"] == 1
    assert dist["in_recession_at_match"]["kernel_weight"] == pytest.approx(3.0)
    assert dist["effective_n"] == pytest.approx(6.0)
    assert dist["positive_lag_weight_sum"] == pytest.approx(3.0)
    assert dist["lag0_kernel_weight"] == pytest.approx(3.0)
    assert dist["low_n"] is True

    real_fixture_share = 0.5278429148428068
    real_fixture_spent = 0.7790003675571177
    real_fixture_remaining = 0.22099963244288232
    conditional = conditional_timing_summary(
        {
            "horizon_quarters": 8,
            "histogram": {
                "0": 0.0,
                "1": 0.20,
                "2": 0.20,
                "3": 0.20,
                "4": real_fixture_spent - 0.60,
                "5": 0.0,
                "6": 0.0,
                "7": real_fixture_remaining,
                "8": 0.0,
            },
        },
        current_query="2001Q4",
        trailing_max_quarter="2000Q4",
        share_shrunk=real_fixture_share,
    )
    assert conditional["elapsed_quarters"] == 4
    assert conditional["spent_mass"] == pytest.approx(real_fixture_spent)
    assert conditional["remaining_mass"] == pytest.approx(real_fixture_remaining)
    assert conditional["conditional_share"] == pytest.approx(
        (real_fixture_share * real_fixture_remaining)
        / (1.0 - real_fixture_share * real_fixture_spent)
    )
    assert conditional["conditional_share"] == pytest.approx(0.198, abs=0.001)

    spot_conditional = conditional_timing_summary(
        {
            "horizon_quarters": 8,
            "histogram": {"0": 0.5, **{str(lag): 0.5 / 8.0 for lag in range(1, 9)}},
        },
        current_query="2000Q4",
        trailing_max_quarter="2000Q4",
        share_shrunk=0.40,
    )
    assert spot_conditional["elapsed_quarters"] == 0
    assert spot_conditional["spent_mass"] == pytest.approx(0.0)
    assert spot_conditional["remaining_mass"] == pytest.approx(1.0)
    assert spot_conditional["conditional_share"] == pytest.approx(0.40)

    exhausted = conditional_timing_summary(
        {
            "horizon_quarters": 8,
            "histogram": {"0": 0.20, "1": 0.80, **{str(lag): 0.0 for lag in range(2, 9)}},
        },
        current_query="2001Q1",
        trailing_max_quarter="2000Q4",
        share_shrunk=0.40,
    )
    assert exhausted["remaining_mass"] == pytest.approx(0.0)
    assert exhausted["conditional_share"] == pytest.approx(0.0)

    lag0_spent = conditional_timing_summary(
        {
            "horizon_quarters": 8,
            "histogram": {"0": 0.25, "1": 0.25, "2": 0.50, **{str(lag): 0.0 for lag in range(3, 9)}},
        },
        current_query="2001Q1",
        trailing_max_quarter="2000Q4",
        share_shrunk=0.40,
    )
    assert lag0_spent["spent_mass"] == pytest.approx(0.50)
    assert lag0_spent["remaining_mass"] == pytest.approx(0.50)


def test_compact_yaml_report_uses_top_match_strings_and_fan_artifact_only():
    state = _state("2026Q2", "scored", 0.40)
    state = state.__class__(
        **{
            **state.to_dict(),
            "top_matches": (
                analogue_evidence.AnalogueTopMatch(
                    neighbor_quarter="2000Q4",
                    distance=0.1,
                    kernel_weight=0.83,
                    resolved=True,
                    recession_bound=True,
                    onset_lag_quarters=1,
                ),
            ),
            "onset_lag_distribution": None,
        }
    )
    report = {
        "enabled": True,
        "evidence": {
            "query_date": "2026Q2",
            "current_state": "scored",
            "spot_share": 0.40,
            "trailing_max": 0.40,
            "trailing_max_quarter": "2026Q2",
            "base_rate": 0.25,
            "kernel_weight_sum": 1.0,
            "stress_advisory": False,
            "window_states": [state.to_dict()],
            "trailing_max_onset_lag_distribution": {
                "horizon_quarters": 8,
                "histogram": {str(idx): 0.0 for idx in range(1, 9)},
                "effective_n": 4.0,
                "low_n": True,
                "conditional_timing": {"elapsed_quarters": 0, "conditional_share": 0.40},
            },
        },
        "analogue_fan": {"variables": {"credit_spread": {"large": [1, 2, 3]}}},
    }

    compact = compact_analogue_report_for_yaml(
        report,
        fan_artifact_path="data/agent_system/reports/fan.json",
    )

    top_matches = compact["evidence"]["window_states"][0]["top_matches"]
    assert top_matches == ["2000Q4 (w=0.83, rec, lag 1)"]
    assert "conditional_timing" in compact["evidence"]["window_states"][0]
    assert compact["evidence"]["trailing_max_onset_lag_distribution"]["conditional_timing"][
        "conditional_share"
    ] == pytest.approx(0.40)
    assert compact["analogue_fan"] == {
        "artifact_path": "data/agent_system/reports/fan.json",
        "note": "Full analogue fan arrays are stored in the JSON artifact, not embedded in current-regime YAML.",
    }


def test_config_validation_requires_exact_membership_map(tmp_path):
    valid = load_analogue_evidence_config()
    assert set(valid.scenario_recession_membership) == set(SCENARIOS)

    missing = _config_snapshot()
    missing_membership = dict(missing["scenario_recession_membership"])
    missing_membership.pop("credit_led_recession")
    missing["scenario_recession_membership"] = missing_membership
    missing_path = tmp_path / "missing.yaml"
    missing_path.write_text(yaml.safe_dump(missing), encoding="utf-8")

    with pytest.raises(AnalogueEvidenceError, match="missing"):
        load_analogue_evidence_config(missing_path)

    unknown = _config_snapshot()
    unknown_membership = dict(unknown["scenario_recession_membership"])
    unknown_membership["unknown_scenario"] = False
    unknown["scenario_recession_membership"] = unknown_membership
    unknown_path = tmp_path / "unknown.yaml"
    unknown_path.write_text(yaml.safe_dump(unknown), encoding="utf-8")

    with pytest.raises(AnalogueEvidenceError, match="unknown"):
        load_analogue_evidence_config(unknown_path)

    missing_survival_flag = _config_snapshot()
    missing_survival_flag.pop("survival_conditioning")
    missing_survival_path = tmp_path / "missing_survival.yaml"
    missing_survival_path.write_text(
        yaml.safe_dump(missing_survival_flag),
        encoding="utf-8",
    )

    with pytest.raises(AnalogueEvidenceError, match="survival_conditioning"):
        load_analogue_evidence_config(missing_survival_path)


def test_probability_taxonomy_coherence_fires_on_desync():
    with pytest.raises(AnalogueEvidenceError, match="desync"):
        validate_probability_taxonomy_coherence(
            {"expansion_disinflation": 1.0},
            SCENARIOS,
            stage="test",
        )


def test_service_integration_disabled_records_noop_report(tmp_path):
    probabilities = {scenario_id: 1.0 / len(SCENARIOS) for scenario_id in SCENARIOS}
    forecast_path = tmp_path / "forecast_2026Q2_test.json"
    forecast_path.write_text(
        json.dumps(
            {
                "asof_quarter": "2026Q2",
                "generated_at": "2026-07-31T00:00:00Z",
                "scenario_probabilities": probabilities,
                "scenario_probabilities_soft": probabilities,
            }
        ),
        encoding="utf-8",
    )

    source = get_macro_scenario_source(
        cycle_date="2026-07-31",
        config=MacroScenarioSourceConfig(
            macro_forecast_source="ensemble",
            bvar_cache_dir=tmp_path,
            analogue_evidence_enabled=False,
        ),
    )

    assert source.scenario_probabilities == pytest.approx(probabilities)
    report = source.provenance["analogue_evidence"]
    assert report["enabled"] is False
    assert report["applied"] is False
    assert report["probabilities_after"] == pytest.approx(probabilities)
