from __future__ import annotations

from argparse import Namespace
from datetime import date

import pandas as pd
import pytest

from scripts.run_deep_fundamental import resolve_benchmark_overrides
from src.agent_system.agents.deep_fundamental_agent_prompts import (
    render_deep_fundamental_context,
)
from src.agent_system.schemas.deep_fundamental import (
    BenchmarkSelection,
    CompanyProfile,
    CompetitivePositionAnalysis,
    DeepFundamentalInputMode,
    FinancialTrendSnapshot,
    FinancialTrendAnalysis,
    FundamentalContextPack,
    MarketExpectationAnalysis,
    PressureInflectionAnalysis,
    RegimeSensitivityAnalysis,
    RelativePerformanceContext,
    RelativePerformanceMetrics,
    RelativeReturnWindow,
    VariantView,
)
from src.agent_system.services import deep_fundamental_agent
from src.agent_system.services.benchmark_selector import select_benchmarks
from src.agent_system.services.deep_fundamental_verdict import (
    build_deep_fundamental_scores,
)
from src.agent_system.services.relative_performance_analyzer import (
    RelativePerformanceAnalyzer,
    WINDOW_TRADING_DAYS,
)


@pytest.mark.parametrize(
    ("ticker", "expected_primary", "expected_secondary"),
    [
        ("MU", "SMH", ["SOXX", "QQQ"]),
        ("MSFT", "QQQ", ["XLK", "SPY"]),
        ("AAPL", "QQQ", ["XLK", "SPY"]),
        ("UNH", "XLV", ["SPY"]),
        ("JPM", "XLF", ["KBE", "SPY"]),
        ("ETN", "XLI", ["PAVE", "SPY"]),
    ],
)
def test_benchmark_selector_ticker_overrides(
    ticker: str,
    expected_primary: str,
    expected_secondary: list[str],
):
    selection = select_benchmarks(ticker)

    assert selection.primary_benchmark == expected_primary
    assert selection.secondary_benchmarks == expected_secondary
    assert selection.benchmark_source == "deterministic_mapping"


def test_benchmark_selector_user_override_works():
    selection = select_benchmarks("MU", user_override="QQQ")

    assert selection.primary_benchmark == "QQQ"
    assert selection.benchmark_source == "user_override"
    assert "SMH" in selection.benchmark_reason


def test_benchmark_map_works_for_multi_ticker():
    args = Namespace(benchmark=None, benchmark_map=["MU=SMH", "AAPL=QQQ", "UNH=XLV"])

    overrides = resolve_benchmark_overrides(args, ["MU", "AAPL", "UNH"])

    assert overrides == {"MU": "SMH", "AAPL": "QQQ", "UNH": "XLV"}


def test_relative_return_calculations_are_correct_on_mock_price_series():
    dates = pd.date_range("2025-01-01", periods=280, freq="B")
    stock = _price_series_from_constant_return(100.0, 0.002, dates)
    benchmark = _price_series_from_constant_return(100.0, 0.001, dates)
    analyzer = RelativePerformanceAnalyzer(
        price_fetcher=lambda _symbols, **_kwargs: {"TEST": stock, "SPY": benchmark}
    )

    context = analyzer.analyze(
        ticker="TEST",
        benchmark_selection=BenchmarkSelection(primary_benchmark="SPY"),
        as_of_date=date(2026, 1, 30),
    )

    assert context.primary_metrics is not None
    windows = {window.window: window for window in context.primary_metrics.windows}
    expected_stock_3m = ((1.002 ** WINDOW_TRADING_DAYS["3m"]) - 1) * 100
    expected_benchmark_3m = ((1.001 ** WINDOW_TRADING_DAYS["3m"]) - 1) * 100
    assert windows["3m"].stock_return_pct == pytest.approx(expected_stock_3m, abs=0.01)
    assert windows["3m"].benchmark_return_pct == pytest.approx(
        expected_benchmark_3m,
        abs=0.01,
    )
    assert windows["3m"].excess_return_pct == pytest.approx(
        expected_stock_3m - expected_benchmark_3m,
        abs=0.02,
    )
    assert windows["3m"].relative_ratio_return_pct == pytest.approx(
        ((1.002 / 1.001) ** WINDOW_TRADING_DAYS["3m"] - 1) * 100,
        abs=0.02,
    )


def test_beta_adjusted_alpha_calculation_is_correct_on_mock_returns():
    dates = pd.date_range("2025-01-01", periods=180, freq="B")
    benchmark_returns = [0.001 + ((index % 7) - 3) * 0.0004 for index in range(179)]
    stock_returns = [1.5 * value + 0.0002 for value in benchmark_returns]
    benchmark = _price_series_from_returns(100.0, benchmark_returns, dates)
    stock = _price_series_from_returns(100.0, stock_returns, dates)
    analyzer = RelativePerformanceAnalyzer(
        price_fetcher=lambda _symbols, **_kwargs: {"TEST": stock, "QQQ": benchmark}
    )

    context = analyzer.analyze(
        ticker="TEST",
        benchmark_selection=BenchmarkSelection(primary_benchmark="QQQ"),
        as_of_date=date(2026, 1, 30),
    )

    assert context.primary_metrics is not None
    metrics = context.primary_metrics
    windows = {window.window: window for window in metrics.windows}
    assert metrics.rolling_beta_6m == pytest.approx(1.5, abs=0.01)
    assert metrics.beta_adjusted_alpha_6m_pct == pytest.approx(
        windows["6m"].stock_return_pct
        - metrics.rolling_beta_6m * windows["6m"].benchmark_return_pct,
        abs=0.05,
    )


def test_upside_downside_capture_handles_signs_correctly():
    dates = pd.date_range("2025-01-01", periods=129, freq="B")
    benchmark_returns = ([0.01, -0.02, 0.02, -0.01] * 32)[:128]
    stock_returns = ([0.015, -0.01, 0.025, -0.005] * 32)[:128]
    benchmark = _price_series_from_returns(100.0, benchmark_returns, dates)
    stock = _price_series_from_returns(100.0, stock_returns, dates)
    analyzer = RelativePerformanceAnalyzer(
        price_fetcher=lambda _symbols, **_kwargs: {"DEF": stock, "SPY": benchmark}
    )

    context = analyzer.analyze(
        ticker="DEF",
        benchmark_selection=BenchmarkSelection(primary_benchmark="SPY"),
        as_of_date=date(2026, 1, 30),
    )

    assert context.primary_metrics is not None
    expected = pd.DataFrame(
        {"stock": stock_returns, "benchmark": benchmark_returns}
    ).tail(WINDOW_TRADING_DAYS["6m"])
    expected_upside = (
        expected.loc[expected["benchmark"] > 0, "stock"].mean()
        / expected.loc[expected["benchmark"] > 0, "benchmark"].mean()
        * 100
    )
    expected_downside = (
        expected.loc[expected["benchmark"] < 0, "stock"].mean()
        / expected.loc[expected["benchmark"] < 0, "benchmark"].mean()
        * 100
    )
    assert context.primary_metrics.upside_capture_6m == pytest.approx(
        expected_upside,
        abs=0.05,
    )
    assert context.primary_metrics.downside_capture_6m == pytest.approx(
        expected_downside,
        abs=0.05,
    )


def test_analyzer_handles_missing_benchmark_prices_without_crashing():
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    stock = _price_series_from_constant_return(100.0, 0.001, dates)
    analyzer = RelativePerformanceAnalyzer(
        price_fetcher=lambda _symbols, **_kwargs: {"TEST": stock}
    )

    context = analyzer.analyze(
        ticker="TEST",
        benchmark_selection=BenchmarkSelection(primary_benchmark="MISSING"),
        as_of_date=date(2026, 1, 30),
    )

    assert context.overall_label == "insufficient_data"
    assert context.primary_metrics is not None
    assert context.primary_metrics.data_warnings
    assert context.warnings


def test_report_includes_relative_performance_context(monkeypatch):
    context = FundamentalContextPack(
        ticker="TEST",
        as_of_date=date(2026, 6, 26),
        financial_trend=FinancialTrendSnapshot(),
    )
    relative_context = _relative_context(score=78, label="confirmed_relative_leader")

    monkeypatch.setattr(
        deep_fundamental_agent,
        "build_fundamental_context_pack",
        lambda **_kwargs: context,
    )

    class FakeRelativePerformanceAnalyzer:
        def analyze(self, **_kwargs):
            return relative_context

    monkeypatch.setattr(
        deep_fundamental_agent,
        "RelativePerformanceAnalyzer",
        FakeRelativePerformanceAnalyzer,
    )

    report = deep_fundamental_agent.build_deep_fundamental_report(
        ticker="TEST",
        input_mode=DeepFundamentalInputMode.STANDALONE,
        horizon="6m",
        use_llm_synthesis=False,
        use_llm_profile=False,
        use_research_context=False,
    )

    assert report.relative_performance_context == relative_context
    assert "Benchmark-relative view" in report.final_rationale


def test_final_synthesis_prompt_includes_benchmark_relative_context():
    relative_context = _relative_context(score=74, label="improving_relative_inflection")

    prompt = render_deep_fundamental_context(
        ticker="MU",
        horizon="6m",
        user_supplied_thesis=None,
        company_profile=CompanyProfile(ticker="MU"),
        fundamental_context=None,
        macro_context=None,
        theme_context=None,
        relative_performance_context=relative_context,
        basic_screen_result=None,
    )

    assert "# Relative performance context" in prompt
    assert "Benchmark-Relative View" in prompt
    assert "better use of capital" in prompt
    assert "SMH" in prompt


def test_scoring_includes_relative_strength_dimension():
    scores = build_deep_fundamental_scores(
        company_profile=CompanyProfile(ticker="TEST", business_model="Good business"),
        financial_trend_analysis=FinancialTrendAnalysis(
            improving_indicators=["latest quarter revenue run-rate is above LTM"]
        ),
        pressure_inflection_analysis=PressureInflectionAnalysis(
            inflection_catalysts=["margin recovery"]
        ),
        competitive_position_analysis=CompetitivePositionAnalysis(),
        regime_sensitivity_analysis=RegimeSensitivityAnalysis(),
        market_expectation_analysis=MarketExpectationAnalysis(),
        variant_view=VariantView(variant_view_strength="medium"),
        relative_performance_context=_relative_context(
            score=82,
            label="confirmed_relative_leader",
        ),
    )

    assert scores.relative_strength_benchmark_alpha >= 70
    assert scores.final_underwriting_score > 50


def _relative_context(score: float, label: str) -> RelativePerformanceContext:
    return RelativePerformanceContext(
        benchmark_selection=BenchmarkSelection(
            primary_benchmark="SMH",
            secondary_benchmarks=["SOXX", "QQQ"],
        ),
        primary_metrics=RelativePerformanceMetrics(
            ticker="TEST",
            benchmark="SMH",
            as_of_date="2026-01-30",
            windows=[
                RelativeReturnWindow(
                    window="1m",
                    stock_return_pct=4.0,
                    benchmark_return_pct=2.0,
                    excess_return_pct=2.0,
                    relative_ratio_return_pct=1.9,
                ),
                RelativeReturnWindow(
                    window="3m",
                    stock_return_pct=18.0,
                    benchmark_return_pct=9.0,
                    excess_return_pct=9.0,
                    relative_ratio_return_pct=8.3,
                ),
                RelativeReturnWindow(
                    window="6m",
                    stock_return_pct=30.0,
                    benchmark_return_pct=12.0,
                    excess_return_pct=18.0,
                    relative_ratio_return_pct=16.1,
                ),
                RelativeReturnWindow(window="12m"),
            ],
            rolling_beta_6m=1.2,
            beta_adjusted_alpha_6m_pct=9.2,
            correlation_6m=0.8,
            upside_capture_6m=125.0,
            downside_capture_6m=85.0,
            relative_trend="improving",
            relative_performance_label=label,
            interpretation=(
                "TEST is outperforming the relevant benchmark with positive "
                "beta-adjusted alpha."
            ),
        ),
        overall_label=label,
        score_0_to_100=score,
        summary=(
            "TEST is outperforming the relevant benchmark with positive "
            "beta-adjusted alpha."
        ),
    )


def _price_series_from_constant_return(
    start_price: float,
    daily_return: float,
    dates: pd.DatetimeIndex,
) -> pd.Series:
    values = [start_price]
    for _index in range(1, len(dates)):
        values.append(values[-1] * (1.0 + daily_return))
    return pd.Series(values, index=dates, dtype=float)


def _price_series_from_returns(
    start_price: float,
    daily_returns: list[float],
    dates: pd.DatetimeIndex,
) -> pd.Series:
    values = [start_price]
    for daily_return in daily_returns:
        values.append(values[-1] * (1.0 + daily_return))
    return pd.Series(values[: len(dates)], index=dates, dtype=float)
