"""Benchmark-relative price performance analytics for deep fundamentals."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from src.agent_system.schemas.deep_fundamental import (
    BenchmarkSelection,
    RelativePerformanceContext,
    RelativePerformanceMetrics,
    RelativeReturnWindow,
)


PriceFetcher = Callable[..., dict[str, pd.Series]]

WINDOW_TRADING_DAYS = {
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "12m": 252,
}


class RelativePerformanceAnalyzer:
    """Compute stock performance relative to a selected benchmark ETF."""

    def __init__(self, price_fetcher: PriceFetcher | None = None) -> None:
        self.price_fetcher = price_fetcher or _fetch_adjusted_closes_yfinance

    def analyze(
        self,
        *,
        ticker: str,
        benchmark_selection: BenchmarkSelection,
        as_of_date: date | str | None = None,
        lookback_days: int = 400,
        include_secondary: bool = True,
    ) -> RelativePerformanceContext:
        clean_ticker = ticker.upper().strip()
        primary = benchmark_selection.primary_benchmark.upper().strip()
        secondary = [
            benchmark.upper().strip()
            for benchmark in benchmark_selection.secondary_benchmarks
            if benchmark.strip()
        ]
        benchmarks = [primary, *(secondary if include_secondary else [])]
        symbols = _dedupe([clean_ticker, *benchmarks])
        as_of_text = _as_of_text(as_of_date)
        warnings: list[str] = []

        try:
            prices = self.price_fetcher(
                symbols,
                as_of_date=as_of_date,
                lookback_days=lookback_days,
            )
        except Exception as exc:
            warnings.append(
                f"Relative performance price fetch failed: {exc.__class__.__name__}: {exc}"
            )
            return RelativePerformanceContext(
                benchmark_selection=benchmark_selection,
                primary_metrics=None,
                overall_label="insufficient_data",
                score_0_to_100=None,
                summary=(
                    f"Relative performance versus {primary} could not be computed "
                    "because price data was unavailable."
                ),
                warnings=warnings,
            )

        primary_metrics = self._metrics_for_benchmark(
            ticker=clean_ticker,
            benchmark=primary,
            prices=prices,
            as_of_text=as_of_text,
        )
        if primary_metrics.data_warnings:
            warnings.extend(primary_metrics.data_warnings)

        score = _score_metrics(primary_metrics)
        label = _label_metrics(primary_metrics, score)
        interpretation = _interpret_metrics(primary_metrics, label)
        primary_metrics = primary_metrics.model_copy(
            update={
                "relative_performance_label": label,
                "interpretation": interpretation,
            }
        )

        secondary_metrics: list[RelativePerformanceMetrics] = []
        for benchmark in secondary if include_secondary else []:
            metrics = self._metrics_for_benchmark(
                ticker=clean_ticker,
                benchmark=benchmark,
                prices=prices,
                as_of_text=as_of_text,
            )
            secondary_score = _score_metrics(metrics)
            secondary_label = _label_metrics(metrics, secondary_score)
            metrics = metrics.model_copy(
                update={
                    "relative_performance_label": secondary_label,
                    "interpretation": _interpret_metrics(metrics, secondary_label),
                }
            )
            secondary_metrics.append(metrics)
            warnings.extend(metrics.data_warnings)

        if label == "insufficient_data":
            score = None

        return RelativePerformanceContext(
            benchmark_selection=benchmark_selection,
            primary_metrics=primary_metrics,
            secondary_metrics=secondary_metrics,
            overall_label=label,
            score_0_to_100=score,
            summary=interpretation,
            warnings=_dedupe(warnings),
        )

    def _metrics_for_benchmark(
        self,
        *,
        ticker: str,
        benchmark: str,
        prices: dict[str, pd.Series],
        as_of_text: str | None,
    ) -> RelativePerformanceMetrics:
        stock = _clean_price_series(prices.get(ticker))
        bench = _clean_price_series(prices.get(benchmark))
        data_warnings: list[str] = []

        if stock.empty:
            data_warnings.append(f"No usable adjusted close history for {ticker}.")
        if bench.empty:
            data_warnings.append(f"No usable adjusted close history for benchmark {benchmark}.")

        windows = [RelativeReturnWindow(window=window) for window in WINDOW_TRADING_DAYS]
        if stock.empty or bench.empty:
            return RelativePerformanceMetrics(
                ticker=ticker,
                benchmark=benchmark,
                as_of_date=as_of_text,
                windows=windows,
                relative_trend="insufficient_data",
                relative_performance_label="insufficient_data",
                data_warnings=data_warnings,
            )

        aligned = pd.concat(
            [stock.rename("stock"), bench.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        aligned = aligned[(aligned["stock"] > 0) & (aligned["benchmark"] > 0)]
        if len(aligned) < 2:
            data_warnings.append(
                f"Insufficient overlapping price history for {ticker} versus {benchmark}."
            )
            return RelativePerformanceMetrics(
                ticker=ticker,
                benchmark=benchmark,
                as_of_date=as_of_text,
                windows=windows,
                relative_trend="insufficient_data",
                relative_performance_label="insufficient_data",
                data_warnings=data_warnings,
            )

        ratio = aligned["stock"] / aligned["benchmark"]
        computed_windows: list[RelativeReturnWindow] = []
        for window, days in WINDOW_TRADING_DAYS.items():
            stock_return = _period_return_pct(aligned["stock"], days)
            benchmark_return = _period_return_pct(aligned["benchmark"], days)
            ratio_return = _period_return_pct(ratio, days)
            if stock_return is None or benchmark_return is None:
                data_warnings.append(
                    f"Insufficient data for {window} relative return versus {benchmark}."
                )
            computed_windows.append(
                RelativeReturnWindow(
                    window=window,
                    stock_return_pct=stock_return,
                    benchmark_return_pct=benchmark_return,
                    excess_return_pct=(
                        stock_return - benchmark_return
                        if stock_return is not None and benchmark_return is not None
                        else None
                    ),
                    relative_ratio_return_pct=ratio_return,
                )
            )

        returns_6m = aligned.pct_change().dropna().tail(WINDOW_TRADING_DAYS["6m"])
        beta = None
        alpha_6m = None
        correlation = None
        upside_capture = None
        downside_capture = None
        if len(returns_6m) >= 40:
            stock_returns = returns_6m["stock"]
            benchmark_returns = returns_6m["benchmark"]
            benchmark_variance = _finite_float(benchmark_returns.var())
            if benchmark_variance is not None and benchmark_variance > 0:
                beta = _finite_float(stock_returns.cov(benchmark_returns) / benchmark_variance)
            else:
                data_warnings.append(f"Benchmark return variance is zero for {benchmark}.")
            stock_std = _finite_float(stock_returns.std())
            benchmark_std = _finite_float(benchmark_returns.std())
            if (
                stock_std is not None
                and stock_std > 0
                and benchmark_std is not None
                and benchmark_std > 0
            ):
                correlation = _finite_float(stock_returns.corr(benchmark_returns))
            upside_capture = _capture_ratio(stock_returns, benchmark_returns, up_days=True)
            downside_capture = _capture_ratio(stock_returns, benchmark_returns, up_days=False)

            stock_6m = _window_by_name(computed_windows, "6m").stock_return_pct
            benchmark_6m = _window_by_name(computed_windows, "6m").benchmark_return_pct
            if beta is not None and stock_6m is not None and benchmark_6m is not None:
                alpha_6m = stock_6m - (beta * benchmark_6m)
        else:
            data_warnings.append(
                f"Insufficient 6m daily returns for beta/capture metrics versus {benchmark}."
            )

        stock_tail = aligned["stock"].tail(WINDOW_TRADING_DAYS["6m"] + 1)
        benchmark_tail = aligned["benchmark"].tail(WINDOW_TRADING_DAYS["6m"] + 1)
        max_drawdown_stock = _max_drawdown_pct(stock_tail)
        max_drawdown_benchmark = _max_drawdown_pct(benchmark_tail)
        trend, above_50dma, above_200dma = _relative_trend(ratio)

        return RelativePerformanceMetrics(
            ticker=ticker,
            benchmark=benchmark,
            as_of_date=as_of_text,
            windows=computed_windows,
            rolling_beta_6m=_round_or_none(beta, 4),
            beta_adjusted_alpha_6m_pct=_round_or_none(alpha_6m, 2),
            correlation_6m=_round_or_none(correlation, 4),
            upside_capture_6m=_round_or_none(upside_capture, 2),
            downside_capture_6m=_round_or_none(downside_capture, 2),
            max_drawdown_stock_6m_pct=_round_or_none(max_drawdown_stock, 2),
            max_drawdown_benchmark_6m_pct=_round_or_none(max_drawdown_benchmark, 2),
            relative_ratio_above_50dma=above_50dma,
            relative_ratio_above_200dma=above_200dma,
            relative_trend=trend,
            data_warnings=_dedupe(data_warnings),
        )


def _fetch_adjusted_closes_yfinance(
    symbols: list[str],
    *,
    as_of_date: date | str | None = None,
    lookback_days: int = 400,
) -> dict[str, pd.Series]:
    import yfinance as yf

    end_date = _coerce_date(as_of_date) or date.today()
    start_date = end_date - timedelta(days=max(lookback_days, 30))
    prices: dict[str, pd.Series] = {}
    for symbol in symbols:
        try:
            history = yf.download(
                symbol,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
                progress=False,
                threads=False,
                timeout=8,
            )
        except TypeError:
            history = yf.download(
                symbol,
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception:
            prices[symbol.upper().strip()] = pd.Series(dtype="float64")
            continue
        if history is None or history.empty:
            prices[symbol.upper().strip()] = pd.Series(dtype="float64")
            continue
        prices[symbol.upper().strip()] = _extract_close_series(history, symbol)
    return prices


def _score_metrics(metrics: RelativePerformanceMetrics) -> float | None:
    if metrics.relative_trend == "insufficient_data":
        return None
    window_map = {window.window: window for window in metrics.windows}
    three_month = window_map.get("3m")
    six_month = window_map.get("6m")
    if (
        three_month is None
        or six_month is None
        or three_month.excess_return_pct is None
        or six_month.excess_return_pct is None
    ):
        return None

    score = 50.0
    score += _cap(three_month.excess_return_pct * 1.1, -18, 18)
    score += _cap(six_month.excess_return_pct * 1.0, -24, 24)

    one_year = window_map.get("12m")
    if one_year is not None and one_year.excess_return_pct is not None:
        score += _cap(one_year.excess_return_pct * 0.35, -8, 8)

    if metrics.beta_adjusted_alpha_6m_pct is not None:
        score += _cap(metrics.beta_adjusted_alpha_6m_pct * 1.1, -20, 20)

    if metrics.relative_trend == "improving":
        score += 12
    elif metrics.relative_trend == "deteriorating":
        score -= 12

    if metrics.upside_capture_6m is not None:
        if metrics.upside_capture_6m >= 110:
            score += 5
        elif metrics.upside_capture_6m < 80:
            score -= 4
    if metrics.downside_capture_6m is not None:
        if metrics.downside_capture_6m <= 75:
            score += 6
        elif metrics.downside_capture_6m > 120:
            score -= 7
    if (
        metrics.upside_capture_6m is not None
        and metrics.downside_capture_6m is not None
        and metrics.upside_capture_6m < 80
        and metrics.downside_capture_6m > 100
    ):
        score -= 6

    if (
        metrics.max_drawdown_stock_6m_pct is not None
        and metrics.max_drawdown_benchmark_6m_pct is not None
    ):
        drawdown_spread = (
            metrics.max_drawdown_stock_6m_pct
            - metrics.max_drawdown_benchmark_6m_pct
        )
        score += _cap(drawdown_spread * 0.6, -8, 8)

    return _round_or_none(_clamp(score), 1)


def _label_metrics(
    metrics: RelativePerformanceMetrics,
    score: float | None,
) -> str:
    if score is None or metrics.relative_trend == "insufficient_data":
        return "insufficient_data"

    excess_3m = _window_by_name(metrics.windows, "3m").excess_return_pct
    excess_6m = _window_by_name(metrics.windows, "6m").excess_return_pct
    alpha = metrics.beta_adjusted_alpha_6m_pct

    if (
        excess_6m is not None
        and excess_6m > 0
        and metrics.downside_capture_6m is not None
        and metrics.downside_capture_6m <= 75
        and (
            metrics.upside_capture_6m is None
            or metrics.upside_capture_6m <= 110
            or (metrics.rolling_beta_6m is not None and metrics.rolling_beta_6m <= 0.9)
        )
        and (
            metrics.max_drawdown_stock_6m_pct is None
            or metrics.max_drawdown_benchmark_6m_pct is None
            or metrics.max_drawdown_stock_6m_pct >= metrics.max_drawdown_benchmark_6m_pct
        )
    ):
        return "defensive_relative_outperformer"

    if (
        score >= 70
        and excess_6m is not None
        and excess_6m > 3
        and (alpha is None or alpha > 0)
        and metrics.relative_trend in {"improving", "sideways"}
    ):
        return "confirmed_relative_leader"

    if metrics.relative_trend == "improving" and score >= 50:
        return "improving_relative_inflection"

    if (
        score <= 40
        or (
            metrics.relative_trend == "deteriorating"
            and excess_6m is not None
            and excess_6m < 0
        )
    ):
        return "deteriorating_relative_laggard"

    if (
        excess_3m is not None
        and excess_6m is not None
        and abs(excess_3m) <= 3
        and abs(excess_6m) <= 5
        and (alpha is None or abs(alpha) <= 3)
    ):
        return "benchmark_like"

    return "benchmark_like" if score < 60 else "improving_relative_inflection"


def _interpret_metrics(metrics: RelativePerformanceMetrics, label: str) -> str:
    benchmark = metrics.benchmark
    excess_3m = _window_by_name(metrics.windows, "3m").excess_return_pct
    excess_6m = _window_by_name(metrics.windows, "6m").excess_return_pct
    alpha = metrics.beta_adjusted_alpha_6m_pct
    trend = metrics.relative_trend or "unknown"

    if label == "confirmed_relative_leader":
        return (
            f"The stock has outperformed {benchmark} over 3m and 6m with "
            f"{_fmt_signed(alpha)} beta-adjusted alpha and a {trend} relative trend."
        )
    if label == "defensive_relative_outperformer":
        return (
            f"The stock has positive excess return versus {benchmark} with favorable "
            "downside capture, so relative strength appears defensive rather than "
            "pure high-beta participation."
        )
    if label == "benchmark_like":
        return (
            f"The company may be fundamentally interesting, but shares have behaved "
            f"benchmark-like versus {benchmark}: 3m excess return is "
            f"{_fmt_signed(excess_3m)} and 6m excess return is {_fmt_signed(excess_6m)}."
        )
    if label == "deteriorating_relative_laggard":
        return (
            f"Relative performance versus {benchmark} is weak: 6m excess return is "
            f"{_fmt_signed(excess_6m)} and the relative trend is {trend}."
        )
    if label == "improving_relative_inflection":
        return (
            f"Relative performance versus {benchmark} is not yet confirmed leadership, "
            f"but the {trend} relative trend and 6m excess return of "
            f"{_fmt_signed(excess_6m)} may indicate an early inflection."
        )
    return (
        f"Relative performance versus {benchmark} could not be assessed with enough "
        "overlapping price history."
    )


def _clean_price_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    if isinstance(series, pd.DataFrame):
        if "Close" in series.columns:
            series = series["Close"]
        elif "Adj Close" in series.columns:
            series = series["Adj Close"]
        else:
            return pd.Series(dtype="float64")
    clean = pd.to_numeric(series, errors="coerce").dropna()
    clean = clean[clean > 0]
    try:
        clean = clean.groupby(clean.index).last()
        clean = clean.sort_index()
    except Exception:
        pass
    return clean.astype("float64")


def _extract_close_series(history: pd.DataFrame, symbol: str) -> pd.Series:
    if isinstance(history.columns, pd.MultiIndex):
        upper_symbol = symbol.upper().strip()
        if upper_symbol in history.columns.get_level_values(0):
            frame = history[upper_symbol]
            if "Close" in frame.columns:
                return _clean_price_series(frame["Close"])
            if "Adj Close" in frame.columns:
                return _clean_price_series(frame["Adj Close"])
        for column_name in ("Close", "Adj Close"):
            if column_name in history.columns.get_level_values(0):
                selected = history[column_name]
                if isinstance(selected, pd.DataFrame) and upper_symbol in selected.columns:
                    return _clean_price_series(selected[upper_symbol])
                if isinstance(selected, pd.Series):
                    return _clean_price_series(selected)
        return pd.Series(dtype="float64")

    if "Close" in history.columns:
        return _clean_price_series(history["Close"])
    if "Adj Close" in history.columns:
        return _clean_price_series(history["Adj Close"])
    return pd.Series(dtype="float64")


def _period_return_pct(series: pd.Series, days: int) -> float | None:
    if len(series) <= days:
        return None
    start = _finite_float(series.iloc[-days - 1])
    end = _finite_float(series.iloc[-1])
    if start is None or end is None or start <= 0:
        return None
    return _round_or_none(((end / start) - 1.0) * 100.0, 2)


def _capture_ratio(
    stock_returns: pd.Series,
    benchmark_returns: pd.Series,
    *,
    up_days: bool,
) -> float | None:
    mask = benchmark_returns > 0 if up_days else benchmark_returns < 0
    if not bool(mask.any()):
        return None
    average_benchmark = _finite_float(benchmark_returns[mask].mean())
    average_stock = _finite_float(stock_returns[mask].mean())
    if average_benchmark is None or average_stock is None or average_benchmark == 0:
        return None
    return (average_stock / average_benchmark) * 100.0


def _max_drawdown_pct(series: pd.Series) -> float | None:
    clean = _clean_price_series(series)
    if clean.empty:
        return None
    running_max = clean.cummax()
    drawdown = (clean / running_max - 1.0) * 100.0
    return _finite_float(drawdown.min())


def _relative_trend(ratio: pd.Series) -> tuple[str, bool | None, bool | None]:
    clean = _clean_price_series(ratio)
    if len(clean) < 50:
        return "insufficient_data", None, None

    sma_50 = clean.rolling(50).mean()
    current = _finite_float(clean.iloc[-1])
    current_50 = _finite_float(sma_50.iloc[-1])
    above_50 = (
        bool(current > current_50)
        if current is not None and current_50 is not None
        else None
    )

    above_200 = None
    if len(clean) >= 200:
        sma_200 = clean.rolling(200).mean()
        current_200 = _finite_float(sma_200.iloc[-1])
        above_200 = (
            bool(current > current_200)
            if current is not None and current_200 is not None
            else None
        )

    prior_offset = 21 if len(sma_50.dropna()) >= 22 else 1
    prior_50 = _finite_float(sma_50.iloc[-1 - prior_offset])
    rising_50 = (
        bool(current_50 > prior_50)
        if current_50 is not None and prior_50 is not None
        else None
    )
    if above_50 is True and rising_50 is True:
        trend = "improving"
    elif above_50 is False and rising_50 is False:
        trend = "deteriorating"
    else:
        trend = "sideways"
    return trend, above_50, above_200


def _window_by_name(
    windows: list[RelativeReturnWindow],
    name: str,
) -> RelativeReturnWindow:
    for window in windows:
        if window.window == name:
            return window
    return RelativeReturnWindow(window=name)


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _round_or_none(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    value = _finite_float(value)
    return round(value, digits) if value is not None else None


def _cap(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))


def _fmt_signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_of_text(value: date | str | None) -> str | None:
    parsed = _coerce_date(value)
    if parsed is not None:
        return parsed.isoformat()
    return str(value) if value else None


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    clean_values: list[str] = []
    for value in values:
        clean = str(value).strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        clean_values.append(clean)
    return clean_values
