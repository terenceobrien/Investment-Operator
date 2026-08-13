from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.state import regime_data as rd
from src.state.regime_layers import score_breadth


def _constituent_cache_rows(
    tickers: list[str],
    dates: pd.DatetimeIndex,
    start_price: float = 100.0,
) -> pd.DataFrame:
    rows = []
    for offset, ticker in enumerate(tickers):
        for i, dt in enumerate(dates):
            rows.append(
                {
                    "date": dt,
                    "ticker": ticker,
                    "yahoo_symbol": rd.yahoo_symbol(ticker),
                    "adjusted_close": start_price + offset + i * 0.1,
                }
            )
    return pd.DataFrame(rows)


def _write_universe(root: Path, filename: str = "sp500.csv", tickers: list[str] | None = None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tickers = tickers or ["AAA", "BBB"]
    pd.DataFrame({"ticker": tickers, "company_name": tickers}).to_csv(
        root / filename,
        index=False,
    )


def test_constituent_200d_breadth_excludes_missing_and_stays_bounded():
    dates = pd.bdate_range("2025-01-01", periods=201)
    prices = pd.DataFrame(
        {
            "AAA": np.linspace(100, 130, len(dates)),
            "BBB": np.linspace(130, 100, len(dates)),
            "SHORT": [np.nan] * 151 + list(np.linspace(20, 25, 50)),
        },
        index=dates,
    )

    result = rd.calculate_200d_breadth(prices)

    assert result.valid_count == 2
    assert result.pct_above_200d == pytest.approx(50.0)
    assert 0.0 <= result.pct_above_200d <= 100.0
    assert result.avg_dist_from_200d == pytest.approx(
        (
            ((prices["AAA"].iloc[-1] / prices["AAA"].rolling(200).mean().iloc[-1]) - 1) * 100
            + ((prices["BBB"].iloc[-1] / prices["BBB"].rolling(200).mean().iloc[-1]) - 1) * 100
        )
        / 2
    )


def test_rsp_vs_spy_z_preserves_existing_ratio_zscore(monkeypatch):
    dates = pd.bdate_range("2025-01-01", periods=260)
    spy = pd.Series(np.linspace(100, 120, len(dates)), index=dates)
    rsp = pd.Series(np.linspace(95, 125, len(dates)), index=dates)

    def fake_yf_close(ticker: str, **_kwargs):
        return {"SPY": spy, "RSP": rsp}.get(ticker, pd.Series(dtype=float))

    monkeypatch.setattr(rd, "_yf_close", fake_yf_close)

    expected = rd._z_score((rsp / spy).dropna(), window=252)
    assert rd.calculate_rsp_vs_spy_z() == pytest.approx(expected)


def test_normalized_constituent_adl_and_20_observation_slope():
    dates = pd.bdate_range("2025-01-01", periods=21)
    prices = pd.DataFrame(
        {
            "AAA": np.arange(100, 121, dtype=float),
            "BBB": np.repeat(50.0, len(dates)),
        },
        index=dates,
    )

    adl = rd.calculate_advance_decline_line(prices)

    assert len(adl) == 20
    assert adl.iloc[-1] == pytest.approx(10.0)
    assert rd.calculate_adl_slope(adl, window=20) == pytest.approx(0.5)

    older_noise = pd.Series([1000.0, -1000.0], index=pd.bdate_range("2024-12-30", periods=2))
    linear_recent = pd.Series(
        [10.0 + 2.0 * i for i in range(20)],
        index=pd.bdate_range("2025-01-01", periods=20),
    )
    assert rd.calculate_adl_slope(pd.concat([older_noise, linear_recent]), window=20) == pytest.approx(2.0)


def test_sectors_green_uses_only_sector_etfs(monkeypatch):
    dates = pd.bdate_range("2026-01-01", periods=2)
    called: list[str] = []

    def fake_yf_close(ticker: str, **_kwargs):
        called.append(ticker)
        if ticker in set(rd.SECTOR_ETFS[:4]):
            return pd.Series([10.0, 11.0], index=dates)
        return pd.Series([11.0, 10.0], index=dates)

    monkeypatch.setattr(rd, "_yf_close", fake_yf_close)
    monkeypatch.setattr(rd, "_latest_completed_daily_bar_date", lambda _asof_date=None: dates[-1])

    assert rd.calculate_sectors_green() == 4
    assert called == rd.SECTOR_ETFS


def test_fetch_breadth_uses_sp500_constituents_without_new_public_outputs(monkeypatch):
    dates = pd.bdate_range("2025-01-01", periods=220)
    history = _constituent_cache_rows(["AAA", "BBB"], dates)
    requested: list[str] = []

    def fake_history(universe: str, **_kwargs):
        requested.append(universe)
        return rd.ConstituentHistoryResult(
            universe=universe,
            data=history,
            cache_path=Path("unused.parquet"),
            requested_count=2,
            successful_ticker_count=2,
            failed_tickers=(),
            latest_cached_date=str(dates[-1].date()),
            live_download_attempted=False,
            live_download_succeeded=False,
            cached_fallback_used=False,
        )

    monkeypatch.setattr(rd, "get_constituent_history", fake_history)
    monkeypatch.setattr(rd, "calculate_rsp_vs_spy_z", lambda asof_date=None: 0.25)

    inputs = rd.RegimeInputs(asof_date="2025-11-04")
    rd._fetch_breadth(inputs, sectors_green=7, asof_date="2025-11-04")

    assert requested == ["sp500"]
    assert inputs.pct_above_200d is not None
    assert inputs.avg_dist_from_200d is not None
    assert inputs.adl_slope is not None
    assert inputs.sectors_green == 7
    assert set(score_breadth(**{
        "pct_above_200d": inputs.pct_above_200d,
        "avg_dist_from_200d": inputs.avg_dist_from_200d,
        "sectors_green": inputs.sectors_green,
        "rsp_vs_spy_z": inputs.rsp_vs_spy_z,
        "adl_slope": inputs.adl_slope,
    }).inputs) == {
        "pct_above_200d",
        "avg_dist_from_200d",
        "sectors_green",
        "rsp_vs_spy_z",
        "adl_slope",
    }


def test_constituent_cache_updates_incrementally(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    universe_root = tmp_path / "universe"
    _write_universe(universe_root, tickers=["AAA", "BBB"])

    cache_dates = pd.bdate_range("2024-10-01", "2026-01-09")
    cache_path = rd._constituent_cache_path("sp500", cache_root)
    rd._write_constituent_cache(_constituent_cache_rows(["AAA", "BBB"], cache_dates), cache_path)

    calls = []

    def fake_fetch(tickers, start, end, batch_size=100):
        calls.append((tickers, pd.Timestamp(start), pd.Timestamp(end), batch_size))
        update = _constituent_cache_rows(["AAA", "BBB"], pd.DatetimeIndex([pd.Timestamp("2026-01-12")]))
        return update, []

    monkeypatch.setattr(rd, "fetch_constituent_prices", fake_fetch)

    result = rd.update_constituent_cache(
        "sp500",
        asof_date="2026-01-12",
        cache_root=cache_root,
        universe_root=universe_root,
    )

    assert result.live_download_attempted is True
    assert result.live_download_succeeded is True
    assert calls
    assert calls[0][1] == pd.Timestamp("2026-01-10")
    assert calls[0][1] > pd.Timestamp("2024-10-19")
    assert result.latest_cached_date == "2026-01-12"


def test_empty_download_does_not_destroy_valid_cache(tmp_path, monkeypatch):
    cache_root = tmp_path / "cache"
    universe_root = tmp_path / "universe"
    _write_universe(universe_root, tickers=["AAA", "BBB"])

    cache_dates = pd.bdate_range("2024-10-01", "2026-01-09")
    cache_path = rd._constituent_cache_path("sp500", cache_root)
    original = _constituent_cache_rows(["AAA", "BBB"], cache_dates)
    rd._write_constituent_cache(original, cache_path)

    monkeypatch.setattr(
        rd,
        "fetch_constituent_prices",
        lambda *_args, **_kwargs: (pd.DataFrame(columns=rd.CONSTITUENT_CACHE_COLUMNS), ["AAA", "BBB"]),
    )

    result = rd.update_constituent_cache(
        "sp500",
        asof_date="2026-01-12",
        cache_root=cache_root,
        universe_root=universe_root,
    )
    after = pd.read_parquet(cache_path)

    assert result.cached_fallback_used is True
    assert len(after) == len(original)
    assert after["date"].max() == pd.Timestamp("2026-01-09")


def test_universe_loader_and_yahoo_symbol_mapping(tmp_path):
    universe_root = tmp_path / "universe"
    _write_universe(universe_root, tickers=["BRK.B", "BF.B", "AAPL", "AAPL"])
    _write_universe(universe_root, filename="nasdaq100.csv", tickers=["GOOG"])

    assert rd.load_constituent_list("sp500", universe_root=universe_root) == ["BRK.B", "BF.B", "AAPL"]
    assert rd.load_constituent_list("S&P 500", universe_root=universe_root) == ["BRK.B", "BF.B", "AAPL"]
    assert rd.load_constituent_list("nasdaq100", universe_root=universe_root) == ["GOOG"]
    assert rd.yahoo_symbol("BRK.B") == "BRK-B"
    assert rd.yahoo_symbol("BF.B") == "BF-B"
