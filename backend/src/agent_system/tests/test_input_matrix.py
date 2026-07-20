from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd

from src.agent_system.diagnostics import input_matrix
from src.agent_system.diagnostics.input_matrix import (
    EXPECTED_INPUT_SPECS,
    InputSpec,
    _historical_column_diagnostics,
    _matching_signals,
    build_input_diagnostic_matrix,
    resolve_current_input_value,
)
from src.agent_system.forecasting.input_signals import build_forecast_input_set
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.state.market_state import MarketState
from src.state.regime_data import RegimeInputs


def _raw_inputs() -> RegimeInputs:
    return RegimeInputs(
        asof_date="2026-06-05",
        net_liquidity_z=0.7,
        hy_spread_level=320,
        hy_spread_z=-0.5,
        vix_level=18.0,
        vix_z_20d=0.2,
        sectors_green=7,
        pct_above_200d=55,
        dealer_gamma_z=0.8,
    )


def _market_state() -> MarketState:
    return MarketState(
        asof_utc="2026-06-05T00:00:00+00:00",
        horizon="3M",
        cross_asset_returns={
            "SPY": 1.0,
            "QQQ": 1.7,
            "IWM": 0.2,
            "RSP": 0.4,
            "HYG": 0.8,
            "TLT": -0.1,
            "GLD": 0.3,
            "USO": 2.0,
            "BTC-USD": 3.0,
        },
        sector_returns={"XLK": 1.0, "XLE": 0.5},
        leadership_top3=[("Technology", 1.0), ("Energy", 0.5), ("Industrials", 0.2)],
        sectors_green=7,
        dispersion=0.4,
        spy_clv=0.6,
        spy_range_pct=0.8,
        spy_vol_z_20d=1.1,
        volume_confirmation=0.7,
        spy_above_vwap=True,
        spy_above_prev_close=True,
        vix_level=18.0,
        vix_z_20d=0.2,
        vix_change_pct_1d=-3.0,
    )


def _history_df() -> pd.DataFrame:
    rows = [
        {
            "date": pd.Timestamp("2026-06-03"),
            "vix_level": 17.5,
            "hy_spread_level": 325.0,
            "net_liquidity_z": 0.2,
            "sparse_col": None,
        },
        {
            "date": pd.Timestamp("2026-06-04"),
            "vix_level": 18.2,
            "hy_spread_level": None,
            "net_liquidity_z": 0.3,
            "sparse_col": None,
        },
        {
            "date": pd.Timestamp("2026-06-05"),
            "vix_level": 18.1,
            "hy_spread_level": 330.0,
            "net_liquidity_z": 0.4,
            "sparse_col": 1.0,
        },
    ]
    return pd.DataFrame(rows)


def _patch_loaders(monkeypatch) -> None:
    monkeypatch.setattr(input_matrix, "_load_regime_for_cli", lambda asof_date=None: make_stub_regime_state())
    monkeypatch.setattr(input_matrix, "_load_regime_inputs_for_cli", lambda asof_date=None: _raw_inputs())
    monkeypatch.setattr(input_matrix, "_load_market_state_for_cli", lambda asof_date=None, horizon="3m": _market_state())
    monkeypatch.setattr(input_matrix, "_load_historical_df", lambda: _history_df())


def test_matrix_includes_all_expected_input_specs(monkeypatch):
    _patch_loaders(monkeypatch)

    matrix = build_input_diagnostic_matrix(save_csv=False, save_xlsx=False, save_json=False)

    assert len(matrix) == len(EXPECTED_INPUT_SPECS)
    assert set(spec.input_id for spec in EXPECTED_INPUT_SPECS).issubset(set(matrix["input_id"]))


def test_current_value_resolver_finds_regime_inputs_value():
    spec = next(spec for spec in EXPECTED_INPUT_SPECS if spec.input_id == "vix_level")

    resolved = resolve_current_input_value(spec, _raw_inputs(), None, None, None)

    assert resolved.value == 18.0
    assert resolved.source_object == "RegimeInputs"
    assert resolved.source_field == "vix_level"


def test_current_value_resolver_falls_back_to_regime_state_alias():
    spec = next(spec for spec in EXPECTED_INPUT_SPECS if spec.input_id == "vix_level")

    resolved = resolve_current_input_value(spec, RegimeInputs(asof_date="2026-06-05"), make_stub_regime_state(), None, None)

    assert resolved.value == 22.0
    assert resolved.source_object == "RegimeState"
    assert resolved.source_alias_used == "vix"


def test_market_state_derived_values_are_calculated():
    spec = next(spec for spec in EXPECTED_INPUT_SPECS if spec.input_id == "hyg_minus_tlt")

    resolved = resolve_current_input_value(spec, None, None, _market_state(), None)

    assert resolved.value == 0.9
    assert resolved.source_object == "MarketState"
    assert resolved.source_field == "cross_asset_returns.HYG-TLT"


def test_historical_column_diagnostics_detect_missing_and_sparse_columns():
    df = _history_df()

    missing = _historical_column_diagnostics(df, "does_not_exist")
    sparse = _historical_column_diagnostics(df, "sparse_col")

    assert missing["historical_column_exists"] is False
    assert missing["missing_historical_reason"] == "historical_column_missing"
    assert sparse["historical_column_exists"] is True
    assert sparse["missing_historical_reason"] == "historical_column_sparse"
    assert sparse["historical_non_null_pct"] < 0.60


def test_forecast_input_set_matching_by_id_feature_and_historical_column():
    input_set = build_forecast_input_set(make_stub_regime_state(), raw_inputs=_raw_inputs(), market_state=_market_state())

    by_input_id = next(spec for spec in EXPECTED_INPUT_SPECS if spec.input_id == "vix_level")
    by_historical_column = InputSpec(
        input_id="alias_input",
        label="Alias",
        group="Credit",
        parent_layer="credit",
        input_scope="core_macro",
        role="raw_component",
        expected_source_objects=("RegimeInputs",),
        possible_source_fields=("alias_input",),
        historical_column="hy_spread_level",
        required_for_deterministic=True,
        required_for_historical_similarity=True,
    )

    assert _matching_signals(by_input_id, input_set)
    assert _matching_signals(by_historical_column, input_set)


def test_sparse_history_classified_once_not_used_and_missing(monkeypatch):
    _patch_loaders(monkeypatch)
    sparse_df = _history_df().rename(columns={"vix_level": "vix_level_original", "sparse_col": "vix_level"})
    monkeypatch.setattr(input_matrix, "_load_historical_df", lambda: sparse_df)

    matrix = build_input_diagnostic_matrix(save_csv=False, save_xlsx=False, save_json=False)
    row = matrix[matrix["input_id"] == "vix_level"].iloc[0]

    assert row["coverage_status"] == "active_sparse_history"
    assert row["missing_historical_reason"] == "historical_column_sparse"
    assert bool(row["included_in_analogue_v2"]) is True


def test_xlsx_output_has_required_sheets(monkeypatch, tmp_path):
    _patch_loaders(monkeypatch)

    matrix = build_input_diagnostic_matrix(output_dir=str(tmp_path), save_csv=False, save_xlsx=True, save_json=False)
    xlsx_path = Path(matrix.attrs["output_paths"]["xlsx"])

    assert xlsx_path.exists()
    with zipfile.ZipFile(xlsx_path) as zf:
        workbook_xml = zf.read("xl/workbook.xml").decode("utf-8")
    for sheet_name in [
        "All Inputs",
        "Missing Current",
        "Missing Historical",
        "Sparse Historical",
        "Active Deterministic",
        "Active Historical Similarity",
        "Group Summary",
    ]:
        assert sheet_name in workbook_xml


def test_group_summary_exposes_coverage_counts(monkeypatch):
    _patch_loaders(monkeypatch)

    matrix = build_input_diagnostic_matrix(save_csv=False, save_xlsx=False, save_json=False)
    group_summary = matrix.attrs["group_summary"]
    volatility = group_summary[group_summary["group"] == "Volatility"].iloc[0]

    assert volatility["expected_count"] >= 7
    assert volatility["available_current_count"] >= 2
    assert "coverage_pct" in group_summary.columns


def test_cli_no_arg_run_saves_csv_xlsx_json(monkeypatch, tmp_path, capsys):
    _patch_loaders(monkeypatch)
    monkeypatch.setattr(input_matrix, "DEFAULT_OUTPUT_DIR", str(tmp_path))

    exit_code = input_matrix.main(["--output-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Input diagnostic complete." in captured.out
    files = list(tmp_path.iterdir())
    assert any(path.suffix == ".csv" for path in files)
    assert any(path.suffix == ".xlsx" for path in files)
    json_paths = [path for path in files if path.suffix == ".json"]
    assert json_paths
    payload = json.loads(json_paths[0].read_text(encoding="utf-8"))
    assert "inputs" in payload
    assert "group_summary" in payload
