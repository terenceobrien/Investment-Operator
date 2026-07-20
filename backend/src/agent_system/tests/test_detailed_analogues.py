from __future__ import annotations

import pandas as pd

from src.analysis import analogues
from src.analysis.detailed_analogue_similarity import (
    FeatureSpec,
    build_current_feature_vector_for_analogues,
    compute_detailed_similarity,
    diagnose_forecast_input_set_for_analogue_features,
    feature_specs_from_forecast_input_set,
)
from src.analysis import rolling_composite
from src.analysis.rolling_composite import _summarize_detailed_groups, _effective_sample_size
from src.agent_system.forecasting.input_signals import build_forecast_input_set
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.state.regime_data import RegimeInputs


def _raw_inputs() -> RegimeInputs:
    return RegimeInputs(
        asof_date="2026-06-05",
        net_liquidity_z=0.5,
        hy_spread_level=320,
        hy_spread_z=-0.6,
        vix_level=18.0,
        vix_z_20d=-0.4,
        vix_term_slope=3.0,
        vvix_z=0.1,
        put_call_ratio=0.8,
        skew_index=135,
        sectors_green=7,
        rsp_vs_spy_z=0.4,
        dealer_gamma_z=0.8,
    )


def _history_df() -> pd.DataFrame:
    rows = [
        {
            "date": "2020-01-02",
            "signal_time": "close",
            "environment": "Mixed / Neutral",
            "score_total": 55.0,
            "confidence": 70.0,
            "vix_level": 18.2,
            "vix_z_20d": -0.3,
            "vix_term_slope": 2.8,
            "sectors_green": 7,
            "score_delta": 0.2,
            "spy_close": 100.0,
            "layer_monetary": 5.0,
            "layer_credit": 6.0,
            "layer_volatility": 7.0,
            "layer_breadth": 6.5,
            "layer_positioning": 6.0,
            "hy_spread_level": 325.0,
            "hy_spread_z": -0.5,
            "fwd_ret_cc_1d": 0.001,
            "fwd_ret_cc_5d": 0.004,
            "fwd_ret_cc_10d": 0.008,
            "fwd_ret_cc_21d": 0.02,
            "fwd_ret_cc_63d": 0.05,
            "fwd_ret_cc_126d": 0.06,
            "fwd_ret_cc_252d": 0.10,
        },
        {
            "date": "2020-02-03",
            "signal_time": "close",
            "environment": "Mixed / Neutral",
            "score_total": 56.0,
            "confidence": 69.0,
            "vix_level": 35.0,
            "vix_z_20d": 2.5,
            "vix_term_slope": -3.0,
            "sectors_green": 2,
            "score_delta": -6.0,
            "spy_close": 101.0,
            "layer_monetary": 4.0,
            "layer_credit": 4.0,
            "layer_volatility": 2.0,
            "layer_breadth": 2.5,
            "layer_positioning": 3.0,
            "hy_spread_level": 600.0,
            "hy_spread_z": 2.0,
            "fwd_ret_cc_1d": -0.001,
            "fwd_ret_cc_5d": -0.004,
            "fwd_ret_cc_10d": -0.008,
            "fwd_ret_cc_21d": -0.02,
            "fwd_ret_cc_63d": -0.05,
            "fwd_ret_cc_126d": -0.06,
            "fwd_ret_cc_252d": -0.10,
        },
    ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df


def test_current_feature_vector_uses_forecast_input_set_raw_signals():
    input_set = build_forecast_input_set(make_stub_regime_state(), raw_inputs=_raw_inputs())

    features = build_current_feature_vector_for_analogues(input_set, regime_state=make_stub_regime_state())
    specs = feature_specs_from_forecast_input_set(input_set)

    assert features["vix_level"] == 18.0
    assert features["hy_spread_level"] == 320
    assert features["layer_volatility"] is not None
    assert any(spec.feature_id == "vix_level" and spec.group == "volatility" for spec in specs)
    diagnostics = diagnose_forecast_input_set_for_analogue_features(input_set)
    assert diagnostics["current_features_count"] > 0
    assert "vix_level" in diagnostics["raw_signals_used_for_similarity"]


def test_detailed_similarity_rewards_closer_raw_input_values():
    current = {"vix_level": 18.0, "hy_spread_level": 320.0}
    specs = [
        FeatureSpec("vix_level", "vix_level", "volatility"),
        FeatureSpec("hy_spread_level", "hy_spread_level", "credit", clip_z=500.0),
    ]

    close = compute_detailed_similarity(current, {"vix_level": 18.2, "hy_spread_level": 325.0}, specs)
    far = compute_detailed_similarity(current, {"vix_level": 35.0, "hy_spread_level": 600.0}, specs)
    missing = compute_detailed_similarity(current, {"vix_level": None}, specs)

    assert close.overall_similarity > far.overall_similarity
    assert missing.features_missing
    assert missing.overall_similarity >= 0


def test_v2_analogue_lookup_blends_v1_and_detailed_similarity(monkeypatch):
    df = _history_df()
    monkeypatch.setattr(analogues, "_load_df", lambda: df)

    result = analogues.get_historical_analogues_v2(
        current_features={"vix_level": 18.0, "hy_spread_level": 320.0},
        environment="Mixed / Neutral",
        score_total=55.0,
        vix_level=18.0,
        sectors_green=7,
        score_delta=0.0,
        feature_specs=[
            FeatureSpec("vix_level", "vix_level", "volatility"),
            FeatureSpec("hy_spread_level", "hy_spread_level", "credit", clip_z=500.0),
        ],
        top_n=2,
        candidate_pool_n=2,
        v1_weight=0.4,
        v2_weight=0.6,
    )

    assert result["analogue_version"] == "v2_detailed"
    assert result["analogues"][0]["date"] == "2020-01-02"
    assert result["analogues"][0]["blended_similarity"] > result["analogues"][1]["blended_similarity"]
    assert result["group_similarity_summary"]


def test_rolling_v2_summary_helpers_report_groups_and_ess():
    analogues_payload = [
        {
            "composite_weight": 2.0,
            "group_match_summary": {"group_results": [{"group": "volatility", "similarity": 80.0, "features_used": 2, "features_missing": 0}]},
        },
        {
            "composite_weight": 1.0,
            "group_match_summary": {"group_results": [{"group": "volatility", "similarity": 60.0, "features_used": 1, "features_missing": 1}]},
        },
    ]

    summary = _summarize_detailed_groups(analogues_payload)

    assert _effective_sample_size(analogues_payload) > 1.0
    assert summary["volatility"]["avg_similarity"] == 73.33
    assert summary["volatility"]["features_used"] == 3


def test_rolling_composite_current_lookup_weight_is_anchored(monkeypatch):
    dates = pd.to_datetime(["2026-06-03", "2026-06-04", "2026-06-05"])
    df = pd.DataFrame(
        {
            "date": dates,
            "environment": ["Mixed / Neutral", "Mixed / Neutral", "Mixed / Neutral"],
            "score_total": [50.0, 51.0, 52.0],
            "vix_level": [18.0, 17.0, 16.0],
            "sectors_green": [5, 6, 7],
            "score_delta": [0.0, 1.0, 1.0],
        }
    )

    def fake_lookup_for_date(*args, **kwargs):
        lookup_date = args[0]
        return [
            {
                "date": f"analogue-{lookup_date}",
                "environment": "Mixed / Neutral",
                "score_total": 50.0,
                "forward_returns": {"1d": 0.1, "5d": 0.2, "10d": 0.3, "21d": 0.4, "63d": 0.5, "126d": 0.6, "252d": 0.7},
                "risk_profile": {},
            }
        ]

    monkeypatch.setattr(rolling_composite, "_load_df", lambda: df)
    monkeypatch.setattr(rolling_composite, "_lookup_for_date", fake_lookup_for_date)

    result = rolling_composite.get_rolling_composite(
        asof_date="2026-06-05",
        lookback_days=3,
        half_life=1,
        top_n_per_lookup=1,
        pool_top_n=3,
    )

    weights = result["lookup_weights"]
    assert weights[-1]["date"] == "2026-06-05"
    assert weights[-1]["weight"] == 1.0
    assert weights[0]["weight"] < weights[1]["weight"] < weights[2]["weight"]
