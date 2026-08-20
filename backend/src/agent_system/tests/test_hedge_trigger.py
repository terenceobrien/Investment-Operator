from __future__ import annotations

from src.risk.hedge_trigger import (
    evaluate_breadth_state,
    evaluate_combined_state,
    evaluate_credit_state,
    evaluate_volatility_state,
)


def _base_breadth(**overrides):
    metrics = {
        "dispersion_20d": 0.05,
        "pct_new_lows_252d": 1.0,
        "pct_above_20dma": 65.0,
        "pct_above_50dma": 62.0,
        "pct_above_200dma": 58.0,
        "pct_above_20dma_chg_5d": 0.0,
        "pct_above_50dma_chg_10d": 0.0,
        "pct_above_200dma_chg_10d": 0.0,
        "sectors_50dma_declining_10d": 2,
        "sectors_50dma_declining_10d_unit": "count",
        "latest_observation_date": "2026-08-20",
    }
    metrics.update(overrides)
    return metrics


def _base_credit(**overrides):
    metrics = {
        "baa10y": 2.5,
        "baa_aaa": 0.8,
        "baa10y_chg_10d": 0.01,
        "baa_aaa_chg_10d": 0.01,
        "hy_oas": None,
        "ig_oas": None,
        "latest_observation_date": "2026-08-20",
    }
    metrics.update(overrides)
    return metrics


def _base_vol(**overrides):
    metrics = {
        "vix": 16.0,
        "vix_chg_5d": 0.5,
        "vvix": 85.0,
        "latest_observation_date": "2026-08-20",
    }
    metrics.update(overrides)
    return metrics


def test_breadth_no_bhr_conditions_firing():
    state = evaluate_breadth_state(_base_breadth())
    assert state["bhr_active"] is False
    assert state["signals_firing"] == 0
    assert state["state_label"] == "normal"


def test_breadth_exactly_one_bhr_condition_firing():
    state = evaluate_breadth_state(_base_breadth(pct_new_lows_252d=4.87))
    assert state["bhr_active"] is True
    assert state["signals_firing"] == 1
    assert state["metrics"]["pct_new_lows_252d"]["trigger"] is True


def test_breadth_multiple_bhr_conditions_firing():
    state = evaluate_breadth_state(
        _base_breadth(
            dispersion_20d=0.13,
            pct_above_50dma_chg_10d=-25.0,
            sectors_50dma_declining_10d=10,
        )
    )
    assert state["bhr_active"] is True
    assert state["signals_firing"] == 3
    assert state["state_label"] == "severe"


def test_breadth_threshold_equality_counts_as_firing():
    cases = [
        ("dispersion_20d", 0.1243),
        ("pct_new_lows_252d", 4.87),
        ("pct_above_20dma_chg_5d", -25.1),
        ("pct_above_50dma_chg_10d", -21.4),
        ("pct_above_200dma_chg_10d", -10.1),
        ("sectors_50dma_declining_10d", 10),
    ]
    for key, value in cases:
        state = evaluate_breadth_state(_base_breadth(**{key: value}))
        assert state["metrics"][key]["trigger"] is True


def test_breadth_sector_percentage_threshold_equality_counts_as_firing():
    state = evaluate_breadth_state(
        _base_breadth(
            sectors_50dma_declining_10d=10 / 11 * 100,
            sectors_50dma_declining_10d_unit="percent",
        )
    )
    assert state["metrics"]["sectors_50dma_declining_10d"]["trigger"] is True


def test_credit_level_trigger():
    state = evaluate_credit_state(_base_credit(baa10y=3.08))
    assert state["credit_stress"] is True
    assert state["triggers"]["baa10y"] is True


def test_credit_velocity_trigger():
    state = evaluate_credit_state(_base_credit(baa_aaa_chg_10d=0.05))
    assert state["credit_stress"] is True
    assert state["triggers"]["baa_aaa_chg_10d"] is True


def test_credit_no_trigger():
    state = evaluate_credit_state(_base_credit())
    assert state["credit_stress"] is False
    assert state["conditions_firing"] == 0


def test_credit_missing_optional_hy_ig_data():
    state = evaluate_credit_state(_base_credit(hy_oas=None, ig_oas=None))
    assert state["status"] == "available"
    assert state["credit_stress"] is False
    assert state["metrics"]["hy_oas"]["value"] is None
    assert state["metrics"]["ig_oas"]["value"] is None


def test_credit_threshold_equality_counts_as_firing():
    cases = [
        ("baa10y", 3.08),
        ("baa_aaa", 1.24),
        ("baa10y_chg_10d", 0.09),
        ("baa_aaa_chg_10d", 0.05),
    ]
    for key, value in cases:
        state = evaluate_credit_state(_base_credit(**{key: value}))
        assert state["triggers"][key] is True


def test_vol_vix_level_trigger():
    state = evaluate_volatility_state(_base_vol(vix=27.0))
    assert state["vol_stress"] is True
    assert state["triggers"]["vix"] is True


def test_vol_vix_change_trigger():
    state = evaluate_volatility_state(_base_vol(vix_chg_5d=2.37))
    assert state["vol_stress"] is True
    assert state["triggers"]["vix_chg_5d"] is True


def test_vol_vvix_trigger():
    state = evaluate_volatility_state(_base_vol(vvix=110.1))
    assert state["vol_stress"] is True
    assert state["triggers"]["vvix"] is True


def test_vol_missing_vvix_with_valid_vix():
    state = evaluate_volatility_state(_base_vol(vvix=None))
    assert state["status"] == "partial"
    assert state["vol_stress"] is False
    assert state["data_quality"]["vvix_available"] is False


def test_combined_bhr_only_stage_1():
    breadth = evaluate_breadth_state(_base_breadth(pct_new_lows_252d=5.0))
    credit = evaluate_credit_state(_base_credit())
    vol = evaluate_volatility_state(_base_vol())
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 1
    assert state["combined_trigger"] is False


def test_combined_bhr_credit_stage_2():
    breadth = evaluate_breadth_state(_base_breadth(pct_new_lows_252d=5.0))
    credit = evaluate_credit_state(_base_credit(baa10y=3.2))
    vol = evaluate_volatility_state(_base_vol())
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 2
    assert state["combined_trigger"] is True


def test_combined_bhr_vol_stage_2():
    breadth = evaluate_breadth_state(_base_breadth(pct_new_lows_252d=5.0))
    credit = evaluate_credit_state(_base_credit())
    vol = evaluate_volatility_state(_base_vol(vix=30.0))
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 2
    assert state["combined_trigger"] is True


def test_combined_multi_family_stage_3():
    breadth = evaluate_breadth_state(_base_breadth(pct_new_lows_252d=5.0))
    credit = evaluate_credit_state(_base_credit(baa10y=3.2))
    vol = evaluate_volatility_state(_base_vol(vix=30.0))
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 3
    assert state["combined_trigger"] is True


def test_combined_credit_without_bhr_stays_normal():
    breadth = evaluate_breadth_state(_base_breadth())
    credit = evaluate_credit_state(_base_credit(baa10y=3.2))
    vol = evaluate_volatility_state(_base_vol())
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 0
    assert state["combined_trigger"] is False


def test_combined_vol_without_bhr_stays_normal():
    breadth = evaluate_breadth_state(_base_breadth())
    credit = evaluate_credit_state(_base_credit())
    vol = evaluate_volatility_state(_base_vol(vix=30.0))
    state = evaluate_combined_state(breadth, credit, vol)
    assert state["stage"] == 0
    assert state["combined_trigger"] is False

