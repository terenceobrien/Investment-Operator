"""Tests for market-data bundle technical calculations."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from src.agent_system.data.market import get_market_data


def _history_from_closes(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    close = pd.Series(closes, index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=index,
    )


class _Ticker:
    def __init__(self, history: pd.DataFrame | Exception):
        self._history = history

    def history(self, **_kwargs):
        if isinstance(self._history, Exception):
            raise self._history
        return self._history


def _patch_history(monkeypatch, history: pd.DataFrame | Exception):
    monkeypatch.setattr(
        "src.agent_system.data.market.yf.Ticker",
        lambda _ticker: _Ticker(history),
    )


def test_sma_and_atr_are_computed_on_known_series(monkeypatch):
    _patch_history(monkeypatch, _history_from_closes(list(range(1, 221))))

    bundle = get_market_data("TST", force_refresh=True)

    assert bundle.fetch_success is True
    assert bundle.bars_count == 220
    assert bundle.current_price == pytest.approx(220.0)
    assert bundle.technicals is not None
    assert bundle.technicals.sma_50 == pytest.approx(195.5)
    assert bundle.technicals.sma_200 == pytest.approx(120.5)
    assert bundle.technicals.atr_14 == pytest.approx(2.0)
    assert bundle.technicals.atr_pct == pytest.approx(2.0 / 220.0)


def test_trend_regime_uptrend_downtrend_and_range(monkeypatch):
    _patch_history(monkeypatch, _history_from_closes(list(range(1, 221))))
    uptrend = get_market_data("UP", force_refresh=True)

    _patch_history(monkeypatch, _history_from_closes(list(range(220, 0, -1))))
    downtrend = get_market_data("DOWN", force_refresh=True)

    _patch_history(monkeypatch, _history_from_closes([100.0] * 220))
    rangebound = get_market_data("RANGE", force_refresh=True)

    assert uptrend.technicals is not None
    assert uptrend.technicals.trend_regime == "uptrend"
    assert downtrend.technicals is not None
    assert downtrend.technicals.trend_regime == "downtrend"
    assert rangebound.technicals is not None
    assert rangebound.technicals.trend_regime == "range"


def test_insufficient_bars_leave_sma_200_and_trend_none(monkeypatch):
    _patch_history(monkeypatch, _history_from_closes(list(range(1, 101))))

    bundle = get_market_data("SHORT", force_refresh=True)

    assert bundle.fetch_success is True
    assert bundle.technicals is not None
    assert bundle.technicals.sma_50 is not None
    assert bundle.technicals.sma_200 is None
    assert bundle.technicals.trend_regime is None


def test_empty_or_failed_fetch_returns_failed_bundle(monkeypatch):
    _patch_history(monkeypatch, pd.DataFrame())
    empty = get_market_data("EMPTY", force_refresh=True)

    _patch_history(monkeypatch, RuntimeError("provider down"))
    failed = get_market_data("FAIL", force_refresh=True)

    assert empty.fetch_success is False
    assert empty.fetch_errors
    assert failed.fetch_success is False
    assert "provider down" in failed.fetch_errors[0]


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
@pytest.mark.parametrize("ticker", ["AAPL", "POWL"])
def test_integration_market_data_success(ticker):
    bundle = get_market_data(ticker, force_refresh=True)

    assert bundle.fetch_success is True
    assert bundle.bars_count >= 200
    assert bundle.technicals is not None
    assert bundle.technicals.sma_50 is not None
    assert bundle.technicals.sma_200 is not None
    assert bundle.technicals.atr_14 is not None


@pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS") != "1",
    reason="Set INTEGRATION_TESTS=1 to run provider integration tests.",
)
def test_integration_bad_ticker_graceful_failure():
    bundle = get_market_data("XXXFAKE", force_refresh=True)

    assert bundle.fetch_success is False
    assert bundle.fetch_errors
