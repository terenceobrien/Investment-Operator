"""Tests for market-data bundle technical calculations."""
from __future__ import annotations

import logging
import os
from concurrent.futures.process import BrokenProcessPool

import pandas as pd
import pytest

from src.agent_system.data import market
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


def _patch_history(monkeypatch, history: pd.DataFrame | Exception):
    def fake_fetch(_ticker: str) -> list[dict]:
        if isinstance(history, Exception):
            raise history
        return market._rows_from_frame(history)

    monkeypatch.setattr(market, "_fetch_market_history_isolated", fake_fetch)


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


class _FakeFuture:
    def __init__(self, result):
        self._result = result
        self.timeout = None
        self.cancelled = False

    def result(self, timeout=None):
        self.timeout = timeout
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def cancel(self):
        self.cancelled = True


class _FakeExecutor:
    def __init__(self, future: _FakeFuture | None = None):
        self.future = future
        self.submissions: list[tuple[object, str]] = []
        self.shutdown_kwargs = None

    def submit(self, fn, key: str):
        self.submissions.append((fn, key))
        return self.future

    def shutdown(self, **kwargs):
        self.shutdown_kwargs = kwargs


class _SubmitRaisesExecutor:
    def __init__(self, exc: Exception):
        self.exc = exc
        self.shutdown_kwargs = None

    def submit(self, _fn, _key: str):
        raise self.exc

    def shutdown(self, **kwargs):
        self.shutdown_kwargs = kwargs


def test_market_history_subprocess_crash_degrades_to_empty_bundle(monkeypatch, caplog):
    fake_executor = _FakeExecutor(
        _FakeFuture(BrokenProcessPool("native crash in yfinance history"))
    )
    monkeypatch.setattr(market, "_market_history_executor", fake_executor)

    with caplog.at_level(logging.WARNING, logger="agent_system.data.market"):
        bundle = get_market_data("CRASH", force_refresh=True)

    assert bundle.fetch_success is False
    assert bundle.fetch_errors == ["No market history returned"]
    assert market._market_history_executor is None
    assert fake_executor.shutdown_kwargs == {"wait": False, "cancel_futures": True}
    assert "market history subprocess crashed for CRASH" in caplog.text


def test_market_history_broken_pool_on_submit_is_discarded(monkeypatch, caplog):
    fake_executor = _SubmitRaisesExecutor(BrokenProcessPool("pool already broken"))
    monkeypatch.setattr(market, "_market_history_executor", fake_executor)

    with caplog.at_level(logging.WARNING, logger="agent_system.data.market"):
        bundle = get_market_data("BROKEN", force_refresh=True)

    assert bundle.fetch_success is False
    assert market._market_history_executor is None
    assert fake_executor.shutdown_kwargs == {"wait": False, "cancel_futures": True}
    assert "market history subprocess crashed for BROKEN" in caplog.text


def test_market_history_executor_uses_spawn_context_and_bounded_workers(monkeypatch):
    created: dict[str, object] = {}

    class FakeProcessPoolExecutor:
        def __init__(self, *, max_workers: int, mp_context):
            created["max_workers"] = max_workers
            created["mp_context"] = mp_context

        def shutdown(self, **_kwargs):
            pass

    def fake_get_context(method: str):
        created["method"] = method
        return "spawn-context"

    monkeypatch.setenv("MARKET_HISTORY_FETCH_MAX_WORKERS", "6")
    monkeypatch.setattr(market, "_market_history_executor", None)
    monkeypatch.setattr(market.multiprocessing, "get_context", fake_get_context)
    monkeypatch.setattr(market, "ProcessPoolExecutor", FakeProcessPoolExecutor)

    executor = market._get_market_history_executor()

    assert created == {
        "method": "spawn",
        "max_workers": 6,
        "mp_context": "spawn-context",
    }
    assert isinstance(executor, FakeProcessPoolExecutor)
    market._discard_market_history_executor(executor)


def test_market_history_executor_reuses_dedicated_pool(monkeypatch):
    created: list[object] = []

    class FakeProcessPoolExecutor:
        def __init__(self, *, max_workers: int, mp_context):
            created.append(self)

        def shutdown(self, **_kwargs):
            pass

    monkeypatch.setattr(market, "_market_history_executor", None)
    monkeypatch.setattr(market.multiprocessing, "get_context", lambda _method: object())
    monkeypatch.setattr(market, "ProcessPoolExecutor", FakeProcessPoolExecutor)

    first = market._get_market_history_executor()
    second = market._get_market_history_executor()

    assert first is second
    assert created == [first]
    market._discard_market_history_executor(first)


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
