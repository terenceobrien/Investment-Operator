from __future__ import annotations

import pytest

from src.agent_system.forecasting.historical_calibration import (
    calibrate_macro_forecast_with_analogs,
    map_analogue_to_scenario,
)
from src.agent_system.forecasting.macro_forecast_runner import (
    default_scenario_mapping_horizon_for_forecast_horizon,
    format_macro_forecast_report,
    run_macro_forecast,
)
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.schemas.macro_forecast import (
    HistoricalCalibrationConfig,
    HistoricalCalibrationResult,
    MacroForecastResult,
)
from src.state.regime_data import RegimeInputs


SCENARIOS = [
    "reopening_soft_landing",
    "sticky_late_cycle_ai",
    "oil_inflation_tail",
    "late_cycle_risk_off",
    "ai_capex_rollover",
]


def _mock_rolling_result():
    analogues = [
        {
            "date": "2018-12-10",
            "composite_weight": 3.0,
            "similarity_score": 1.0,
            "score_total": 35.0,
            "environment": "Risk-Off",
            "vix_level": 28.0,
            "sectors_green": 2,
            "score_delta": -8.0,
            "forward_returns": {"1d": -1.0, "5d": -3.0, "10d": -4.0, "21d": -6.5, "63d": -7.0, "126d": -8.0, "252d": None},
            "risk_profile": {"max_drawdown_5d": -5.0, "max_upside_5d": 1.0},
            "score_components": {"breadth": 2.0},
            "sector_returns": {"Technology": -1.0, "Energy": -0.5},
        },
        {
            "date": "2020-05-12",
            "composite_weight": 2.0,
            "similarity_score": 2.0,
            "score_total": 62.0,
            "environment": "Risk-On Rotation",
            "vix_level": 18.0,
            "sectors_green": 9,
            "score_delta": 5.0,
            "forward_returns": {"1d": 0.5, "5d": 1.0, "10d": 2.0, "21d": 4.0, "63d": 6.0, "126d": 8.0, "252d": 12.0},
            "risk_profile": {"max_drawdown_5d": -1.0, "max_upside_5d": 3.0},
            "score_components": {"breadth": 8.0},
            "sector_returns": {"Industrials": 1.5, "Technology": 0.8},
        },
        {
            "date": "2023-06-15",
            "composite_weight": 4.0,
            "similarity_score": 1.5,
            "score_total": 58.0,
            "environment": "Mixed / Neutral",
            "vix_level": 17.0,
            "sectors_green": 3,
            "score_delta": 0.0,
            "forward_returns": {"1d": 0.2, "5d": 0.8, "10d": 1.2, "21d": 3.0, "63d": 5.0, "126d": 6.0, "252d": 9.0},
            "risk_profile": {"max_drawdown_5d": -1.5, "max_upside_5d": 2.0},
            "score_components": {"breadth": 3.0},
            "sector_returns": {"Technology": 1.5, "Energy": 0.1},
        },
        {
            "date": "2022-03-01",
            "composite_weight": 1.0,
            "similarity_score": 4.0,
            "score_total": 49.0,
            "environment": "Mixed / Neutral",
            "vix_level": 24.0,
            "sectors_green": 4,
            "score_delta": -1.0,
            "forward_returns": {"1d": 0.0, "5d": -0.4, "10d": 0.2, "21d": -1.0, "63d": -2.0, "126d": None, "252d": None},
            "risk_profile": {"max_drawdown_5d": -2.0, "max_upside_5d": 1.5},
            "score_components": {"breadth": 4.0},
            "sector_returns": {"Energy": 2.5, "Technology": -0.2},
        },
    ]
    return {
        "asof_date": "2026-06-05",
        "lookback_days": 30,
        "half_life": 30,
        "n_unique_analogues": 4,
        "n_pooled": 4,
        "conditions_summary": "Mocked mixed regime; score improving.",
        "analogues": analogues,
        "aggregate_stats": {
            "n_analogues": 4,
            "forward_returns": {
                "1d": {"n": 4, "weight_sum": 10.0, "median": 0.1, "mean": -0.1, "pct_positive": 60.0, "p10": -1.0, "p25": -0.2, "p75": 0.4, "p90": 0.6, "worst": -1.0, "best": 0.5},
                "5d": {"n": 4, "weight_sum": 10.0, "median": 0.2, "mean": -0.4, "pct_positive": 55.0, "p10": -3.0, "p25": -0.8, "p75": 1.0, "p90": 1.2, "worst": -3.0, "best": 1.0},
                "10d": {"n": 4, "weight_sum": 10.0, "median": 0.7, "mean": -0.2, "pct_positive": 65.0, "p10": -4.0, "p25": 0.0, "p75": 1.5, "p90": 2.0, "worst": -4.0, "best": 2.0},
                "21d": {"n": 4, "weight_sum": 10.0, "median": 1.0, "mean": -0.1, "pct_positive": 60.0, "p10": -6.5, "p25": -1.0, "p75": 3.5, "p90": 4.0, "worst": -6.5, "best": 4.0},
                "63d": {"n": 4, "weight_sum": 10.0, "median": 1.0, "mean": 0.2, "pct_positive": 60.0, "p10": -7.0, "p25": -2.0, "p75": 5.5, "p90": 6.0, "worst": -7.0, "best": 6.0},
                "126d": {"n": 3, "weight_sum": 9.0, "median": 3.0, "mean": 2.0, "pct_positive": 66.7, "p10": -8.0, "p25": -1.0, "p75": 7.0, "p90": 8.0, "worst": -8.0, "best": 8.0},
                "252d": {"n": 2, "weight_sum": 6.0, "median": 10.5, "mean": 10.5, "pct_positive": 100.0, "p10": 9.0, "p25": 9.5, "p75": 11.5, "p90": 12.0, "worst": 9.0, "best": 12.0},
            },
            "macro_forward_returns": {
                "21d": {"n": 4, "weight_sum": 10.0, "median": 1.0, "mean": -0.1, "pct_positive": 60.0, "p10": -6.5, "p25": -1.0, "p75": 3.5, "p90": 4.0, "worst": -6.5, "best": 4.0},
                "63d": {"n": 4, "weight_sum": 10.0, "median": 1.0, "mean": 0.2, "pct_positive": 60.0, "p10": -7.0, "p25": -2.0, "p75": 5.5, "p90": 6.0, "worst": -7.0, "best": 6.0},
                "126d": {"n": 3, "weight_sum": 9.0, "median": 3.0, "mean": 2.0, "pct_positive": 66.7, "p10": -8.0, "p25": -1.0, "p75": 7.0, "p90": 8.0, "worst": -8.0, "best": 8.0},
                "252d": {"n": 2, "weight_sum": 6.0, "median": 10.5, "mean": 10.5, "pct_positive": 100.0, "p10": 9.0, "p25": 9.5, "p75": 11.5, "p90": 12.0, "worst": 9.0, "best": 12.0},
            },
            "tactical_forward_returns": {
                "1d": {"n": 4, "weight_sum": 10.0, "median": 0.1, "mean": -0.1, "pct_positive": 60.0, "p10": -1.0, "p25": -0.2, "p75": 0.4, "p90": 0.6, "worst": -1.0, "best": 0.5},
                "5d": {"n": 4, "weight_sum": 10.0, "median": 0.2, "mean": -0.4, "pct_positive": 55.0, "p10": -3.0, "p25": -0.8, "p75": 1.0, "p90": 1.2, "worst": -3.0, "best": 1.0},
                "10d": {"n": 4, "weight_sum": 10.0, "median": 0.7, "mean": -0.2, "pct_positive": 65.0, "p10": -4.0, "p25": 0.0, "p75": 1.5, "p90": 2.0, "worst": -4.0, "best": 2.0},
            },
            "risk_profile": {
                "median_max_drawdown_5d": -1.75,
                "median_max_upside_5d": 1.75,
                "win_rate_21d": 60.0,
                "expected_value_21d": 0.2,
                "win_rate_63d": 60.0,
                "expected_value_63d": 0.3,
                "win_rate_126d": 66.7,
                "expected_value_126d": 1.2,
                "win_rate_252d": 100.0,
                "expected_value_252d": 10.5,
                "drawdown_upside_available_horizons": [],
            },
            "environment_distribution": {"Risk-Off": 3.0, "Risk-On Rotation": 2.0, "Mixed / Neutral": 5.0},
            "available_horizons": ["1d", "5d", "10d", "21d", "63d", "126d", "252d"],
            "missing_horizons": [],
            "horizon_sample_sizes": {"1d": 4, "5d": 4, "10d": 4, "21d": 4, "63d": 4, "126d": 3, "252d": 2},
        },
    }


def test_calibration_calls_mocked_rolling_composite(monkeypatch):
    called = {}

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        return _mock_rolling_result()

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )
    forecast = run_macro_forecast(make_stub_regime_state())
    config = HistoricalCalibrationConfig(
        enabled=True,
        min_analogue_count=1,
        historical_probability_floor=0.0,
    )

    calibration = calibrate_macro_forecast_with_analogs(
        forecast,
        make_stub_regime_state(),
        config=config,
    )

    assert called["lookback_days"] == config.lookback_days
    assert calibration.enabled is True
    assert calibration.n_analogues == 4
    assert calibration.scenario_calibrations
    assert calibration.top_analogues[0].mapped_scenario_id == "late_cycle_risk_off"
    assert calibration.macro_forward_return_stats["63d"].n == 4
    assert calibration.macro_forward_return_stats["252d"].n == 2
    assert calibration.horizon_sample_sizes["252d"] == 2


def test_analogue_mapping_rules():
    assert map_analogue_to_scenario(
        {"environment": "Risk-Off", "forward_returns": {"21d": -6.0}, "risk_profile": {"max_drawdown_5d": -5.0}},
        SCENARIOS,
    )[0] == "late_cycle_risk_off"
    assert map_analogue_to_scenario(
        {"environment": "Risk-On Rotation", "forward_returns": {"21d": 4.0}, "sectors_green": 8, "vix_level": 18.0},
        SCENARIOS,
    )[0] == "reopening_soft_landing"
    assert map_analogue_to_scenario(
        {"environment": "Mixed / Neutral", "forward_returns": {"21d": 3.0}, "sectors_green": 3, "vix_level": 19.0},
        SCENARIOS,
    )[0] == "sticky_late_cycle_ai"
    assert map_analogue_to_scenario(
        {"environment": "Mixed", "forward_returns": {"21d": -1.0}, "sector_returns": {"Energy": 2.0}},
        SCENARIOS,
    )[0] == "oil_inflation_tail"


def test_scenario_mapping_uses_63d_by_default_and_warns_on_fallback():
    warnings: list[str] = []
    scenario_id, _, rationale = map_analogue_to_scenario(
        {"environment": "Risk-Off", "forward_returns": {"63d": -6.0, "21d": 1.0}},
        SCENARIOS,
    )

    assert scenario_id == "late_cycle_risk_off"
    assert "selected mapping horizon 63d return" in rationale

    scenario_id, _, rationale = map_analogue_to_scenario(
        {"environment": "Risk-Off", "forward_returns": {"21d": -6.0}},
        SCENARIOS,
        scenario_mapping_horizon="63d",
        warnings=warnings,
    )

    assert scenario_id == "late_cycle_risk_off"
    assert "fallback 21d return because 63d return unavailable" in rationale
    assert any("used fallback 21d return" in warning for warning in warnings)
    assert default_scenario_mapping_horizon_for_forecast_horizon("3m") == "63d"
    assert default_scenario_mapping_horizon_for_forecast_horizon("1m") == "21d"
    assert default_scenario_mapping_horizon_for_forecast_horizon("6m") == "126d"
    assert default_scenario_mapping_horizon_for_forecast_horizon("1y") == "252d"


def test_scenario_mapping_excludes_covid_contaminated_63d_rows(monkeypatch):
    called = {}

    analogues = [
        {
            "date": "2020-01-15",
            "composite_weight": 5.0,
            "similarity_score": 1.0,
            "score_total": 58.0,
            "environment": "Risk-Off",
            "vix_level": 18.0,
            "sectors_green": 2,
            "score_delta": -1.0,
            "forward_returns": {"21d": 1.0, "63d": -18.0, "126d": -20.0, "252d": -15.0},
            "risk_profile": {},
            "score_components": {},
            "sector_returns": {},
        },
        {
            "date": "2020-05-12",
            "composite_weight": 2.0,
            "similarity_score": 2.0,
            "score_total": 62.0,
            "environment": "Risk-On Rotation",
            "vix_level": 18.0,
            "sectors_green": 9,
            "score_delta": 5.0,
            "forward_returns": {"21d": 4.0, "63d": 6.0, "126d": 8.0, "252d": 12.0},
            "risk_profile": {},
            "score_components": {},
            "sector_returns": {},
        },
    ]

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        return {
            "asof_date": "2026-06-05",
            "analogue_version": "v1_broad_state",
            "n_unique_analogues": 2,
            "n_pooled": 2,
            "conditions_summary": "shock fixture",
            "analogues": analogues,
            "aggregate_stats": {
                "n_analogues": 2,
                "forward_returns": {
                    horizon: {"n": 2, "weight_sum": 7.0, "median": 0.0, "mean": 0.0, "pct_positive": 50.0, "p10": -1.0, "p25": -0.5, "p75": 0.5, "p90": 1.0, "worst": -1.0, "best": 1.0}
                    for horizon in ["1d", "5d", "10d", "21d", "63d", "126d", "252d"]
                },
                "risk_profile": {},
                "environment_distribution": {},
                "available_horizons": ["1d", "5d", "10d", "21d", "63d", "126d", "252d"],
                "missing_horizons": [],
                "horizon_sample_sizes": {"63d": 2},
            },
        }

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )

    forecast = run_macro_forecast(make_stub_regime_state())
    calibration = calibrate_macro_forecast_with_analogs(
        forecast,
        make_stub_regime_state(),
        config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
            scenario_mapping_horizon="63d",
        ),
    )

    assert called["exclude_shock_windows"] is True
    assert "2020-01-15" in calibration.shock_window_diagnostics["scenario_mapping_excluded_dates"]
    assert calibration.shock_window_diagnostics["historical_probabilities_changed"] is True
    risk_off = next(item for item in calibration.scenario_calibrations if item.scenario_id == "late_cycle_risk_off")
    assert risk_off.n_supporting_analogues == 0


def test_historical_and_blended_probabilities_sum_and_formula(monkeypatch):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            deterministic_weight=0.70,
            historical_weight=0.30,
            min_analogue_count=1,
            historical_probability_floor=0.0,
        ),
    )
    calibration = result.historical_calibration
    assert calibration is not None

    historical_sum = sum(item.historical_probability for item in calibration.scenario_calibrations)
    blended_sum = sum(result.scenario_probabilities.values())
    assert historical_sum == pytest.approx(1.0)
    assert blended_sum == pytest.approx(1.0)
    for item in calibration.scenario_calibrations:
        expected = 0.70 * item.deterministic_probability + 0.30 * item.historical_probability
        assert item.blended_probability == pytest.approx(expected)
        assert result.scenario_probabilities[item.scenario_id] == pytest.approx(item.blended_probability)


def test_detailed_analogues_use_forecast_input_set_and_store_diagnostics(monkeypatch):
    called = {}

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        payload = _mock_rolling_result()
        payload.update(
            {
                "analogue_version": "v2_detailed",
                "v1_weight": 0.4,
                "v2_weight": 0.6,
                "candidate_pool_n": 300,
                "average_detailed_similarity": 82.0,
                "average_blended_similarity": 79.0,
                "group_similarity_summary": {
                    "volatility": {
                        "avg_similarity": 88.0,
                        "features_used": 3,
                        "features_missing": 0,
                        "coverage": 1.0,
                    }
                },
                "feature_coverage_summary": {"average_coverage": 0.9},
                "strongest_match_groups": ["volatility"],
                "weakest_match_groups": ["credit"],
                "missing_important_features": [],
                "effective_sample_size": 25,
            }
        )
        return payload

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )

    result = run_macro_forecast(
        make_stub_regime_state(),
        raw_inputs=RegimeInputs(
            asof_date="2026-06-05",
            hy_spread_level=330,
            hy_spread_z=-0.4,
            vix_level=18.5,
            vix_z_20d=-0.2,
            vix_term_slope=2.4,
            vvix_z=0.3,
            put_call_ratio=0.9,
            skew_index=132,
            sectors_green=6,
            dealer_gamma_z=0.5,
        ),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
            use_detailed_analogues=True,
        ),
    )

    calibration = result.historical_calibration
    assert calibration is not None
    assert called["use_detailed_similarity"] is True
    assert "vix_level" in called["current_features"]
    assert any(spec.feature_id == "vix_level" for spec in called["feature_specs"])
    assert calibration.analogue_version == "v2_detailed"
    assert calibration.detailed_analogue_diagnostics["effective_sample_size"] == 25
    assert calibration.detailed_analogue_diagnostics["group_similarity_summary"]["volatility"]["avg_similarity"] == 88.0
    assert calibration.detailed_analogue_diagnostics["current_features_count"] > 0
    assert "vix_level" in calibration.detailed_analogue_diagnostics["raw_signals_used_for_similarity"]


def test_detailed_analogues_fall_back_when_no_raw_current_features(monkeypatch):
    called = {}

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        return _mock_rolling_result()

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )

    forecast = run_macro_forecast(make_stub_regime_state())
    input_set = forecast.forecast_input_set.model_copy_validate(
        {
            "raw_component_signals": [],
            "all_signals": [
                signal.model_copy_validate({"used_in_historical_similarity": False})
                for signal in forecast.forecast_input_set.all_signals
                if signal.role != "raw_component"
            ],
        }
    )
    calibration = calibrate_macro_forecast_with_analogs(
        forecast,
        make_stub_regime_state(),
        forecast_input_set=input_set,
        config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
            use_detailed_analogues=True,
        ),
    )

    assert called["use_detailed_similarity"] is False
    assert calibration.analogue_version == "v1_broad_state"
    assert calibration.detailed_analogue_diagnostics["current_features_count"] == 0
    assert any("falling back to V1 broad-state analogues" in warning for warning in calibration.warnings)


def test_insufficient_analogues_fallback_keeps_deterministic_probabilities(monkeypatch):
    result_payload = _mock_rolling_result()
    result_payload["analogues"] = result_payload["analogues"][:1]
    result_payload["aggregate_stats"]["n_analogues"] = 1
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: result_payload,
    )
    deterministic = run_macro_forecast(make_stub_regime_state())
    calibrated = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=20,
            fallback_to_display_only=True,
            historical_probability_floor=0.0,
        ),
    )

    assert calibrated.scenario_probabilities == pytest.approx(deterministic.scenario_probabilities)
    assert calibrated.historical_calibration is not None
    assert calibrated.historical_calibration.warnings


def test_rankings_recomputed_from_blended_probabilities(monkeypatch):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
        ),
    )

    assert result.probability_mode == "historically_calibrated"
    assert result.scenario_probabilities_deterministic is not None
    assert result.scenario_probabilities_blended == result.scenario_probabilities
    for theme in result.theme_rankings:
        assert sum(item.contribution for item in theme.scenario_contributions) == pytest.approx(theme.macro_support_score)
        for contribution in theme.scenario_contributions:
            assert contribution.scenario_probability == pytest.approx(result.scenario_probabilities[contribution.scenario_id])


def test_report_includes_historical_calibration_section(monkeypatch):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
        ),
    )
    report = format_macro_forecast_report(result)

    assert "3. Historical Analogue Calibration" in report
    assert "Historical Analogue Probability" in report
    assert "Historical Macro Forward Return Stats" in report
    assert report.index("Historical Macro Forward Return Stats") < report.index("Historical Tactical Forward Return Stats")
    assert "1M / 21D" in report
    assert "3M / 63D" in report
    assert "6M / 126D" in report
    assert "1Y / 252D" in report
    assert "Scenario Calibration:" in report
    assert "Mapped to oil/inflation tail" in report
    assert "median_max_drawdown_21d" not in report


def test_historical_calibration_source_has_no_llm_calls():
    source = __import__(
        "pathlib"
    ).Path("backend/src/agent_system/forecasting/historical_calibration.py").read_text(encoding="utf-8")
    for forbidden in ["OpenAI", "parse_structured", "llm_client", "assert_llm_calls_allowed"]:
        assert forbidden not in source


def test_macro_forecast_without_historical_calibration_remains_compatible():
    result = run_macro_forecast(make_stub_regime_state())
    payload = result.model_dump(mode="json")
    payload.pop("historical_calibration", None)
    payload.pop("scenario_probabilities_deterministic", None)
    payload.pop("scenario_probabilities_blended", None)
    payload.pop("probability_mode", None)

    parsed = MacroForecastResult.model_validate(payload)

    assert parsed.historical_calibration is None
    assert parsed.probability_mode == "deterministic"


def test_existing_historical_calibration_output_with_short_horizons_still_loads():
    payload = {
        "enabled": True,
        "method": "rolling_composite",
        "asof_date": "2026-06-05",
        "conditions_summary": "legacy",
        "n_analogues": 4,
        "forward_return_stats": {
            "1d": {"horizon": "1d", "n": 4, "median": 0.1},
            "5d": {"horizon": "5d", "n": 4, "median": 0.2},
            "10d": {"horizon": "10d", "n": 4, "median": 0.3},
            "21d": {"horizon": "21d", "n": 4, "median": 1.0},
        },
        "risk_profile": {},
        "environment_distribution": {},
        "top_analogues": [],
        "scenario_calibrations": [],
        "blended_scenario_probabilities": {},
        "confidence": 0.5,
        "warnings": [],
        "methodology_notes": [],
    }

    result = HistoricalCalibrationResult.model_validate(payload)

    assert result.forward_return_stats["21d"].median == 1.0
    assert result.tactical_forward_return_stats["1d"].n == 4
    assert result.macro_forward_return_stats["21d"].n == 4
    assert result.horizon_sample_sizes["21d"] == 4


def test_legacy_mapping_rationale_derives_short_fields():
    match = HistoricalCalibrationResult.model_validate(
        {
            "enabled": True,
            "method": "rolling_composite",
            "asof_date": "2026-06-05",
            "n_analogues": 1,
            "risk_profile": {},
            "environment_distribution": {},
            "top_analogues": [
                {
                    "date": "2020-03-23",
                    "mapped_scenario_id": "late_cycle_risk_off",
                    "mapping_rationale": "Fallback mapped to risk-off because selected mapping horizon 63d return was negative.",
                }
            ],
            "scenario_calibrations": [],
            "blended_scenario_probabilities": {},
            "confidence": 0.5,
        }
    ).top_analogues[0]

    assert match.mapping_rationale_full == match.mapping_rationale
    assert match.mapping_rationale_short in {"Fallback negative", "Risk-off return"}
