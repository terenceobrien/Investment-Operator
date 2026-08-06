from __future__ import annotations

from pathlib import Path
from typing import Mapping

from src.agent_system.forecasting.macro_forecast_runner import BVARForecastArtifact
from src.agent_system.forecasting.scenario_classifier.analogue_evidence import (
    AnalogueEvidence,
    AnalogueWindowState,
)
from src.agent_system.forecasting.scenario_classifier.analogue_fan import (
    FanResult,
    FanVariableResult,
)
from src.agent_system.forecasting.scenario_classifier.directional_features import (
    DIRECTIONAL_VARIABLES,
)


BEHAVIORAL_IDS = (
    "expansion_disinflation",
    "late_cycle_expansion",
    "inflation_shock",
    "stagflation",
    "growth_scare_no_credit",
    "credit_led_recession",
)


def behavioral_probabilities(
    overrides: Mapping[str, float] | None = None,
) -> dict[str, float]:
    probabilities = {
        "expansion_disinflation": 0.24,
        "late_cycle_expansion": 0.40,
        "inflation_shock": 0.14,
        "stagflation": 0.08,
        "growth_scare_no_credit": 0.10,
        "credit_led_recession": 0.04,
    }
    if overrides:
        probabilities.update({str(key): float(value) for key, value in overrides.items()})
    total = sum(probabilities.values())
    return {key: value / total for key, value in probabilities.items()}


def analogue_evidence_fixture(
    *,
    trailing_max: float | None = 0.37,
    base_rate: float = 0.27,
    current_state: str = "scored",
    stress_advisory: bool = False,
) -> AnalogueEvidence:
    state = AnalogueWindowState(
        quarter="2026Q2",
        state=current_state,
        share=trailing_max if current_state == "scored" else None,
        share_raw=trailing_max if current_state == "scored" else None,
        n_matches=6 if current_state == "scored" else 0,
        evaluable_neighbor_count=5 if current_state == "scored" else 0,
        dropped_unresolved_count=1 if current_state == "scored" else 0,
        kernel_weight_sum=4.0 if current_state == "scored" else 0.0,
        pit_candidate_pool_size=120,
    )
    return AnalogueEvidence(
        query_date="2026Q2",
        current_state=current_state,
        spot_share=trailing_max if current_state == "scored" else None,
        trailing_max=trailing_max,
        window_states=(state,),
        base_rate=base_rate,
        kernel_weight_sum=state.kernel_weight_sum,
        stress_advisory=stress_advisory,
        config_snapshot={
            "trailing_window_quarters": 6,
            "prior_strength": 3.0,
            "horizon_quarters": 8,
            "min_pool": 30,
            "stress_advisory_threshold": 0.35,
            "mixture_alpha": 0.30,
            "survival_conditioning": True,
            "scenario_recession_membership": {
                scenario_id: scenario_id == "credit_led_recession"
                for scenario_id in BEHAVIORAL_IDS
            },
            "source_path": "test",
        },
    )


def bvar_artifact_fixture(
    probabilities: Mapping[str, float] | None = None,
    *,
    path: Path | None = None,
) -> BVARForecastArtifact:
    soft = dict(probabilities or behavioral_probabilities())
    artifact_path = path or Path("forecast_2026Q2_test.json")
    return BVARForecastArtifact(
        soft_probabilities=soft,
        provenance={
            "path": str(artifact_path),
            "generated_at": "2026-07-31T00:00:00Z",
            "asof_quarter": "2026Q2",
            "handoff_fingerprint": "test-fingerprint",
            "model_limitations": {"credit_tail_magnitude": "conservative"},
            "classifier_metadata": {
                "map_version": "behavioral-v1-test",
                "scenario_ids": list(BEHAVIORAL_IDS),
            },
            "warnings": [],
            "soft_probabilities": soft,
            "soft_probability_sum": sum(soft.values()),
        },
        payload={},
        path=artifact_path,
        asof_quarter="2026Q2",
        generated_at="2026-07-31T00:00:00+00:00",
    )


def analogue_fan_fixture() -> FanResult:
    percentiles = {
        "p10": tuple(0.1 for _ in range(8)),
        "p25": tuple(0.2 for _ in range(8)),
        "p50": tuple(0.3 for _ in range(8)),
        "p75": tuple(0.4 for _ in range(8)),
        "p90": tuple(0.5 for _ in range(8)),
    }
    variables = {
        variable: FanVariableResult(
            variable=variable,
            query_anchor_value=0.0,
            units_note="transformed-cache units, same as BVAR signature space",
            percentiles=percentiles,
            effective_n=tuple(4.0 for _ in range(8)),
            median_recession_bound=tuple(0.35 for _ in range(8)),
            median_benign=tuple(0.25 for _ in range(8)),
            subset_notes={"recession_bound": "ok", "benign": "ok"},
        )
        for variable in DIRECTIONAL_VARIABLES
    }
    return FanResult(
        query_date="2026Q2",
        horizon_quarters=8,
        variables=variables,
        metadata={
            "query_date": "2026Q2",
            "horizon_quarters": 8,
            "match_count": 4,
            "units_note": "transformed-cache units, same as BVAR signature space",
        },
    )


def patch_two_source_runner(
    monkeypatch,
    runner_module,
    *,
    probabilities: Mapping[str, float] | None = None,
    evidence: AnalogueEvidence | None = None,
) -> None:
    artifact = bvar_artifact_fixture(probabilities)
    analogue = evidence or analogue_evidence_fixture()
    monkeypatch.setattr(
        runner_module,
        "load_latest_bvar_forecast",
        lambda **_kwargs: artifact,
    )
    monkeypatch.setattr(
        runner_module,
        "compute_analogue_evidence",
        lambda **_kwargs: analogue,
    )
    monkeypatch.setattr(
        runner_module,
        "compute_analogue_fan",
        lambda **_kwargs: analogue_fan_fixture(),
    )
    monkeypatch.setattr(
        runner_module,
        "write_fan_result",
        lambda fan, path=None: Path(path or "analogue_fan_2026Q2.json"),
    )
    monkeypatch.setattr(
        runner_module,
        "render_fan_charts",
        lambda fan, output_dir: {
            "combined_grid": str(Path(output_dir) / "analogue_fan_2026Q2_grid.png"),
            "credit_spread": str(Path(output_dir) / "analogue_fan_2026Q2_credit_spread.png"),
            "curve_slope": str(Path(output_dir) / "analogue_fan_2026Q2_curve_slope.png"),
        },
    )
