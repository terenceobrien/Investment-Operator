from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

from src.agent_system.forecasting import macro_forecast_runner
from src.agent_system.forecasting.macro_forecast_runner import run_macro_forecast
from src.agent_system.orchestration.stub_agents import make_stub_regime_state
from src.agent_system.reporting.macro_forecast_docx import _decimal, _pct, _signed, _text, generate_macro_forecast_docx
from src.agent_system.schemas.macro_forecast import HistoricalCalibrationConfig, MacroForecastResult
from src.state.regime_data import RegimeInputs


def _result_from_json_fixture(tmp_path: Path) -> MacroForecastResult:
    result = run_macro_forecast(make_stub_regime_state())
    fixture_path = tmp_path / "macro_forecast_result.json"
    fixture_path.write_text(result.model_dump_json(), encoding="utf-8")
    return MacroForecastResult.model_validate_json(fixture_path.read_text(encoding="utf-8"))


def _document_text(path: Path) -> str:
    document = Document(path)
    chunks: list[str] = []
    chunks.extend(paragraph.text for paragraph in document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            chunks.extend(cell.text for cell in row.cells)
    return "\n".join(chunks)


def _raw_inputs_fixture() -> RegimeInputs:
    return RegimeInputs(
        asof_date="2026-06-05",
        net_liquidity_z=0.6,
        hy_spread_level=320,
        pct_above_200d=48,
        vix_level=18,
        vix_z_20d=0.3,
    )


def _patch_cli_data_loaders(monkeypatch, *, raw_inputs: RegimeInputs | None = None) -> None:
    monkeypatch.setattr(
        macro_forecast_runner,
        "_load_regime_for_cli",
        lambda asof_date=None: make_stub_regime_state(),
    )
    monkeypatch.setattr(
        macro_forecast_runner,
        "_load_regime_inputs_for_cli",
        lambda asof_date=None: raw_inputs if raw_inputs is not None else _raw_inputs_fixture(),
    )
    monkeypatch.setattr(
        macro_forecast_runner,
        "_load_market_state_for_cli",
        lambda asof_date=None, horizon="3m": None,
    )


def _table_rows(path: Path, first_header: str) -> list[list[str]]:
    document = Document(path)
    for table in document.tables:
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        if rows and rows[0] and rows[0][0] == first_header:
            return rows
    raise AssertionError(f"table with first header {first_header!r} not found")


def _stat(n: int, weight_sum: float, median: float):
    return {
        "n": n,
        "weight_sum": weight_sum,
        "median": median,
        "mean": median,
        "pct_positive": 60.0,
        "p10": median - 2.0,
        "p25": median - 1.0,
        "p75": median + 1.0,
        "p90": median + 2.0,
        "worst": median - 3.0,
        "best": median + 3.0,
    }


def _mock_macro_horizon_rolling_result():
    analogues = [
        {
            "date": "2020-03-23",
            "composite_weight": 2.0,
            "similarity_score": 1.0,
            "score_total": 35.0,
            "environment": "Risk-Off",
            "vix_level": 40.0,
            "sectors_green": 1,
            "score_delta": -8.0,
            "forward_returns": {"1d": 1.0, "5d": 2.0, "10d": 3.0, "21d": 4.0, "63d": 8.0, "126d": 12.0, "252d": None},
            "risk_profile": {"max_drawdown_5d": -3.0, "max_upside_5d": 5.0},
            "score_components": {},
            "sector_returns": {},
        },
        {
            "date": "2022-06-16",
            "composite_weight": 1.0,
            "similarity_score": 2.0,
            "score_total": 42.0,
            "environment": "Risk-Off",
            "vix_level": 32.0,
            "sectors_green": 2,
            "score_delta": -4.0,
            "forward_returns": {"1d": -1.0, "5d": -2.0, "10d": -3.0, "21d": -4.0, "63d": -8.0, "126d": -12.0, "252d": -18.0},
            "risk_profile": {"max_drawdown_5d": -4.0, "max_upside_5d": 2.0},
            "score_components": {},
            "sector_returns": {},
        },
    ]
    forward = {
        "1d": _stat(2, 3.0, 0.0),
        "5d": _stat(2, 3.0, 0.0),
        "10d": _stat(2, 3.0, 0.0),
        "21d": _stat(2, 3.0, 0.0),
        "63d": _stat(2, 3.0, 0.0),
        "126d": _stat(2, 3.0, 0.0),
        "252d": _stat(1, 1.0, -18.0),
    }
    return {
        "asof_date": "2026-06-05",
        "n_unique_analogues": 2,
        "n_pooled": 2,
        "conditions_summary": "macro horizon fixture",
        "analogues": analogues,
        "aggregate_stats": {
            "n_analogues": 2,
            "forward_returns": forward,
            "macro_forward_returns": {key: forward[key] for key in ["21d", "63d", "126d", "252d"]},
            "tactical_forward_returns": {key: forward[key] for key in ["1d", "5d", "10d"]},
            "risk_profile": {
                "median_max_drawdown_5d": -3.5,
                "median_max_upside_5d": 3.5,
                "median_max_drawdown_21d": -3.5,
                "median_max_upside_21d": 3.5,
                "win_rate_63d": 66.7,
                "expected_value_63d": 2.0,
                "drawdown_upside_available_horizons": [],
            },
            "environment_distribution": {"Risk-Off": 3.0},
            "available_horizons": ["1d", "5d", "10d", "21d", "63d", "126d", "252d"],
            "missing_horizons": [],
            "horizon_sample_sizes": {key: int(value["n"]) for key, value in forward.items()},
        },
    }


def _mock_detailed_rolling_result():
    payload = _mock_macro_horizon_rolling_result()
    payload.update(
        {
            "analogue_version": "v2_detailed",
            "v1_weight": 0.4,
            "v2_weight": 0.6,
            "candidate_pool_n": 300,
            "average_detailed_similarity": 81.2,
            "average_blended_similarity": 78.4,
            "group_similarity_summary": {
                "volatility": {
                    "avg_similarity": 86.0,
                    "features_used": 4,
                    "features_missing": 0,
                    "coverage": 1.0,
                    "top_features_used": ["vix_level", "vix_z_20d", "put_call_ratio"],
                    "top_features_missing": ["vix_term_slope"],
                },
                "credit": {
                    "avg_similarity": 72.5,
                    "features_used": 3,
                    "features_missing": 1,
                    "coverage": 0.75,
                    "top_features_used": ["hy_spread_level", "hy_spread_z"],
                    "top_features_missing": ["hy_spread_chg_4w"],
                },
            },
            "feature_coverage_summary": {"average_coverage": 0.875},
            "strongest_match_groups": ["volatility"],
            "weakest_match_groups": ["credit"],
            "missing_important_features": [],
            "effective_sample_size": 22,
        }
    )
    for analogue in payload["analogues"]:
        analogue.update(
            {
                "v1_similarity": 70.0,
                "detailed_similarity": 84.0,
                "blended_similarity": 78.4,
                "strongest_matching_groups": ["volatility"],
                "weakest_matching_groups": ["credit"],
                "feature_coverage": {"coverage": 0.875},
            }
        )
    return payload


def test_generate_macro_forecast_docx_creates_nonempty_file_from_fixture_json(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = tmp_path / "macro_forecast.docx"

    generated = generate_macro_forecast_docx(result, output_path)

    assert generated == output_path
    assert generated.exists()
    assert generated.stat().st_size > 10_000


def test_docx_contains_expected_section_headings(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    text = _document_text(output_path)

    for heading in [
        "HELIX INTEL",
        "Macro Forecast Report",
        "Forecast Interpretation",
        "Scenario Probabilities",
        "Visual Summary",
        "Scenario Probability Math",
        "Historical Analogue Calibration",
        "Forecast Input Set",
        "Raw Input Coverage Summary",
        "Layer Summary Signals",
        "Raw Component Signals",
        "Composite Signals",
        "Market/Tape Signals",
        "Regime-Specific Drivers",
        "Scenario Falsifiers",
        "Dedupe / Weighting Notes",
        "Monetary Composite Detail",
        "Theme Rankings - Macro Support Score",
        "Sector & Instrument Rankings",
        "Factor Rankings",
        "Probability Shifters / Watchlist",
        "Recommended Research Priorities",
        "Input Signal Detail",
        "Methodology Notes",
    ]:
        assert heading in text


def test_docx_historical_section_prioritizes_macro_horizons(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_macro_horizon_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
        ),
    )
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast_historical.docx")
    text = _document_text(output_path)

    assert "Historical Macro Forward Return Stats" in text
    assert "Historical Tactical Forward Return Stats" in text
    assert text.index("Historical Macro Forward Return Stats") < text.index("Historical Tactical Forward Return Stats")
    assert "Historical Risk Profile by Horizon" in text
    assert "Historical Tactical Risk Snapshot" in text
    assert "Shock Window Diagnostics" in text
    assert "covid_crash" in text
    assert "Full input diagnostic matrix saved to:" in text
    for label in ["1M / 21D", "3M / 63D", "6M / 126D", "1Y / 252D"]:
        assert label in text
    assert "Longer horizons naturally have lower sample sizes" in text
    assert "median_max_drawdown_21d" not in text
    assert "Mapping Rationale" not in text
    assert "Map Tag" in text


def test_docx_includes_detailed_analogue_match_quality(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_detailed_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
            use_detailed_analogues=True,
        ),
    )
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast_detailed.docx")
    text = _document_text(output_path)

    assert "Detailed Analogue Match Quality" in text
    assert "V1 broad-state weight" in text
    assert "V2 detailed-input weight" in text
    assert "Effective sample size" in text
    assert "volatility" in text
    assert "V1" in text
    assert "V2" in text
    assert "Blend" in text
    assert "Used Feature IDs" in text
    assert "vix_level" in text


def test_docx_inserts_summary_and_historical_charts(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_detailed_rolling_result(),
    )
    result = run_macro_forecast(
        make_stub_regime_state(),
        historical_calibration_config=HistoricalCalibrationConfig(
            enabled=True,
            min_analogue_count=1,
            historical_probability_floor=0.0,
            use_detailed_analogues=True,
        ),
    )
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast_charts.docx")
    document = Document(output_path)
    text = _document_text(output_path)

    assert "Scenario Probability Chart" in text
    assert "Historical Macro Return Profile Chart" in text
    assert len(document.inline_shapes) >= 3


def test_docx_raw_input_coverage_and_compact_scenario_math(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast_inputs.docx")
    text = _document_text(output_path)

    assert "Raw Input Coverage Summary" in text
    assert "total_raw_signals_expected" in text
    assert "total_raw_signals_available" in text
    assert "total_raw_signals_used_in_probability_update" in text
    assert "Contributor Breakdown" in text
    assert "Layer Summary Contributors" not in text
    assert "Raw Component Contributors" not in text


def test_docx_uses_review_style_colors_and_spacing(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    document = Document(output_path)

    title_run = document.paragraphs[0].runs[0]
    subtitle_run = document.paragraphs[1].runs[0]
    assert title_run.text == "HELIX INTEL"
    assert str(title_run.font.color.rgb) == "1F4E79"
    assert title_run.font.size.pt == 26
    assert subtitle_run.text == "Macro Forecast Report"
    assert str(subtitle_run.font.color.rgb) == "2E75B6"

    section = next(paragraph for paragraph in document.paragraphs if paragraph.text == "Forecast Interpretation")
    section_run = section.runs[0]
    assert str(section_run.font.color.rgb) == "1F4E79"
    assert section.paragraph_format.space_before.pt >= 15
    assert section.paragraph_format.space_after.pt >= 6

    scenario_table = next(table for table in document.tables if table.rows[0].cells[0].text == "Scenario")
    header_cell = scenario_table.rows[0].cells[0]
    shading = header_cell._tc.tcPr.find(qn("w:shd"))
    assert shading is not None
    assert shading.get(qn("w:fill")) == "1F4E79"
    assert str(header_cell.paragraphs[0].runs[0].font.color.rgb) == "FFFFFF"


def test_docx_scenario_probability_table_includes_all_scenarios(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    rows = _table_rows(output_path, "Scenario")
    table_text = "\n".join("\n".join(row) for row in rows)
    display_names = {
        "reopening_soft_landing": "Reopening / Soft Landing",
        "sticky_late_cycle_ai": "Sticky Late Cycle AI",
        "oil_inflation_tail": "Oil Inflation Tail",
        "late_cycle_risk_off": "Late Cycle Risk-Off",
        "ai_capex_rollover": "AI Capex Rollover",
    }

    for scenario_id in result.scenario_probabilities:
        assert display_names.get(scenario_id, scenario_id.replace("_", " ").title()) in table_text


def test_docx_theme_ranking_table_includes_macro_support_score_and_no_overlay_columns(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    rows = _table_rows(output_path, "Rank")
    headers = rows[0]

    assert "Theme" in headers
    assert "Macro Support Score" in headers
    assert "Scenario Contribution Breakdown" in headers
    assert "Interpretation" in headers
    assert "Crowding Adj" not in headers
    assert "Valuation Adj" not in headers
    assert "Narrative Adj" not in headers
    assert "Overlay Adj" not in headers
    assert "Overlay Confidence" not in headers
    assert "Final Score" not in headers


def test_docx_input_table_marks_monetary_components_display_only(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    rows = _table_rows(output_path, "Component")
    headers = rows[0]
    used_index = headers.index("Used in Math?")
    display_only_index = headers.index("Display Only?")
    exclusion_index = headers.index("Exclusion Reason")
    rows_by_signal = {row[0]: row for row in rows[1:]}

    monetary_layer = rows_by_signal["Monetary layer"]
    fed_path_name = next(name for name in rows_by_signal if "Fed path" in name)

    assert monetary_layer[used_index] == "no"
    assert monetary_layer[display_only_index] == "yes"
    assert "avoid double-counting" in monetary_layer[exclusion_index]
    assert rows_by_signal[fed_path_name][used_index] == "no"
    assert rows_by_signal[fed_path_name][display_only_index] == "yes"


def test_docx_methodology_notes_include_formulas(tmp_path):
    result = _result_from_json_fixture(tmp_path)
    output_path = generate_macro_forecast_docx(result, tmp_path / "macro_forecast.docx")
    text = _document_text(output_path)

    for formula in [
        "raw_score_s = prior_score_s + Σ input_contribution_i,s",
        "input_contribution_i,s = direction_sign × base_strength_i,s × confidence_i × signal_multiplier_i",
        "pre_floor_probability_s = softmax(raw_score_s)",
        "final_probability_s = apply_floors_and_caps(pre_floor_probability_s)",
        "macro_support_score_t = Σ scenario_probability_s × theme_exposure_score_t,s",
        "theme_contribution_t,s = scenario_probability_s × theme_exposure_score_t,s",
        "ranking_score_t = macro_support_score_t",
        "sector_score = Σ theme_macro_support_score_t × sector_theme_weight_t",
        "factor_score = Σ theme_macro_support_score_t × factor_theme_weight_t",
    ]:
        assert formula in text
    assert "Macro forecast theme rankings intentionally exclude valuation, crowding, narrative maturity" in text


def test_macro_forecast_cli_minimal_run_saves_docx_and_json(monkeypatch, tmp_path, capsys):
    _patch_cli_data_loaders(monkeypatch)
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_detailed_rolling_result(),
    )

    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--reports-dir",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    asof_date = make_stub_regime_state().asof_date
    docx_path = tmp_path / f"macro_forecast_{asof_date}_math_audit_review.docx"
    json_path = tmp_path / f"macro_forecast_{asof_date}.json"
    yaml_path = tmp_path / f"current_regime_{asof_date}.yaml"
    assert docx_path.exists()
    assert json_path.exists()
    assert yaml_path.exists()
    assert "Forecast complete." in captured.out
    assert f"DOCX report saved to: {docx_path}" in captured.out
    assert f"JSON forecast saved to: {json_path}" in captured.out
    assert f"Current regime YAML saved to: {yaml_path}" in captured.out
    assert f"Thematic agent current-regime YAML saved to: {yaml_path}" in _document_text(docx_path)
    assert "Input mode: hybrid_raw_inputs" in captured.out
    assert "Volatility inputs: included" in captured.out
    assert "Historical analogues: v2_detailed" in captured.out
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["probability_mode"] == "historically_calibrated"
    assert payload["historical_calibration"]["analogue_version"] == "v2_detailed"
    assert payload["outputs"]["docx_path"] == str(docx_path)
    assert payload["outputs"]["json_path"] == str(json_path)
    assert payload["outputs"]["current_regime_yaml_path"] == str(yaml_path)


def test_macro_forecast_cli_disable_flags(monkeypatch, tmp_path, capsys):
    _patch_cli_data_loaders(monkeypatch)
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_detailed_rolling_result(),
    )

    docx_path = tmp_path / "disabled_docx.docx"
    json_path = tmp_path / "disabled_docx.json"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--json-output",
            str(json_path),
            "--docx-output",
            str(docx_path),
            "--no-current-regime-yaml",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert not docx_path.exists()
    assert json_path.exists()
    assert "DOCX report disabled by --no-docx" in captured.out
    assert "Current regime YAML disabled by --no-current-regime-yaml" in captured.out

    docx_path = tmp_path / "disabled_json.docx"
    json_path = tmp_path / "disabled_json.json"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-json",
            "--docx-output",
            str(docx_path),
            "--json-output",
            str(json_path),
            "--no-current-regime-yaml",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert docx_path.exists()
    assert not json_path.exists()
    assert "JSON forecast disabled by --no-json" in captured.out


def test_macro_forecast_cli_historical_disable_and_v1_fallback(monkeypatch, tmp_path, capsys):
    _patch_cli_data_loaders(monkeypatch)

    deterministic_json = tmp_path / "deterministic.json"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--json-output",
            str(deterministic_json),
            "--no-historical-calibration",
            "--no-current-regime-yaml",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Probability mode: deterministic" in captured.out
    payload = json.loads(deterministic_json.read_text(encoding="utf-8"))
    assert payload["probability_mode"] == "deterministic"

    called = {}

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        return _mock_macro_horizon_rolling_result()

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )
    v1_json = tmp_path / "v1.json"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--json-output",
            str(v1_json),
            "--no-detailed-analogues",
            "--no-current-regime-yaml",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert called["use_detailed_similarity"] is False
    assert "Historical analogues: v1_broad_state" in captured.out


def test_macro_forecast_cli_advanced_overrides(monkeypatch, tmp_path, capsys):
    called = {}
    _patch_cli_data_loaders(monkeypatch)

    def fake_get_rolling_composite(**kwargs):
        called.update(kwargs)
        return _mock_detailed_rolling_result()

    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        fake_get_rolling_composite,
    )

    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--no-json",
            "--input-mode",
            "layer_only",
            "--historical-weight",
            "0.25",
            "--deterministic-weight",
            "0.75",
            "--analogue-candidate-pool-n",
            "123",
            "--no-current-regime-yaml",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Input mode: layer_only" in captured.out
    assert called["candidate_pool_n"] == 123


def test_macro_forecast_cli_current_regime_output_and_disable(monkeypatch, tmp_path, capsys):
    _patch_cli_data_loaders(monkeypatch)
    monkeypatch.setattr(
        "src.analysis.rolling_composite.get_rolling_composite",
        lambda **_: _mock_detailed_rolling_result(),
    )

    requested = tmp_path / "handoff.yaml"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--no-json",
            "--current-regime-output",
            str(requested),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert requested.exists()
    assert f"Current regime YAML saved to: {requested}" in captured.out

    disabled = tmp_path / "disabled.yaml"
    exit_code = macro_forecast_runner.main(
        [
            "--default-scenarios",
            "--no-docx",
            "--no-json",
            "--current-regime-output",
            str(disabled),
            "--no-current-regime-yaml",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert not disabled.exists()
    assert "Current regime YAML disabled by --no-current-regime-yaml" in captured.out


def test_docx_renderer_does_not_import_or_call_llm_wrappers():
    source = Path("backend/src/agent_system/reporting/macro_forecast_docx.py").read_text(encoding="utf-8")

    for forbidden in [
        "OpenAI",
        "parse_structured",
        "assert_llm_calls_allowed",
        "llm_client",
    ]:
        assert forbidden not in source


def test_docx_display_helpers_use_two_decimals_and_short_dates():
    assert _decimal(1.2345) == "1.23"
    assert _signed(-1.2345) == "-1.23"
    assert _pct(0.12345) == "12.35%"
    assert _text("2026-06-05") == "06/05/26"
