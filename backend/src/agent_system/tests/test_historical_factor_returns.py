from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "build_historical_factor_returns.py"
SPEC = importlib.util.spec_from_file_location("build_historical_factor_returns", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def synthetic_prices(periods: int = 180) -> pd.DataFrame:
    index = pd.bdate_range("2020-01-01", periods=periods)
    rng = np.random.default_rng(7)
    data = {}
    for offset, ticker in enumerate(MODULE.required_factor_tickers()):
        returns = rng.normal(0.0003 + offset * 0.00001, 0.01, periods)
        data[ticker] = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame(data, index=index).rename_axis("date")


def test_factor_returns_reuse_production_builder_and_pass_qa() -> None:
    prices = synthetic_prices()
    expected = MODULE.build_factor_returns(prices)
    actual, qa = MODULE.build_and_validate_factor_returns(prices)

    pd.testing.assert_frame_equal(actual, expected)
    assert list(actual.columns) == MODULE.FACTOR_COLUMNS
    assert qa["mkt_max_abs_error_vs_spy_log_return"] <= 1e-12
    assert qa["production_overlap_max_abs_error"] <= 1e-12
    assert qa["orthogonality_max_abs_beta"] <= 1e-10


def test_factor_returns_include_partial_histories_before_common_start() -> None:
    prices = synthetic_prices(240)
    staggered_starts = {
        "SPY": 0,
        "QQQ": 10,
        "SOXX": 20,
        "RSP": 30,
        "IWD": 40,
        "IWM": 50,
        "USMV": 60,
        "MTUM": 70,
        "QUAL": 80,
    }
    for ticker, start in staggered_starts.items():
        prices.loc[prices.index[:start], ticker] = np.nan

    factors, qa = MODULE.build_and_validate_factor_returns(prices)
    production = MODULE.build_factor_returns(prices)

    assert factors.index.min() == prices.index[1]
    assert factors["MKT"].first_valid_index() == prices.index[1]
    assert factors["AI"].first_valid_index() == prices.index[31]
    assert factors["VAL"].first_valid_index() == prices.index[41]
    assert factors["SIZE"].first_valid_index() == prices.index[51]
    assert factors["LOWVOL"].first_valid_index() == prices.index[61]
    assert factors["MOM"].first_valid_index() == prices.index[71]
    assert factors["QUAL"].first_valid_index() == prices.index[81]
    assert factors.loc[: prices.index[30], "AI"].isna().all()
    pd.testing.assert_frame_equal(
        factors.loc[production.index, MODULE.FACTOR_COLUMNS], production
    )
    assert qa["production_overlap_max_abs_error"] == 0.0


def test_extract_adjusted_closes_supports_yfinance_multiindex() -> None:
    dates = pd.date_range("2024-01-02", periods=2, tz="America/New_York")
    columns = pd.MultiIndex.from_product([["Close", "Open"], ["SPY", "QQQ"]])
    raw = pd.DataFrame(
        [[100.0, 200.0, 99.0, 199.0], [101.0, 201.0, 100.0, 200.0]],
        index=dates,
        columns=columns,
    )
    result = MODULE._extract_adjusted_closes(raw, ["SPY", "QQQ"])

    assert list(result.columns) == ["SPY", "QQQ"]
    assert result.index.tz is None
    assert not result.index.has_duplicates
    assert result.iloc[-1].to_dict() == {"SPY": 101.0, "QQQ": 201.0}


def test_merge_price_cache_never_erases_healthy_values() -> None:
    dates = pd.bdate_range("2024-01-02", periods=3)
    cached = pd.DataFrame({"SPY": [100.0, 101.0, 102.0]}, index=dates)
    downloaded = pd.DataFrame({"SPY": [np.nan, 103.0]}, index=dates[1:])

    result = MODULE.merge_price_cache(cached, downloaded)

    assert result.loc[dates[1], "SPY"] == 101.0
    assert result.loc[dates[2], "SPY"] == 103.0


def test_failed_incremental_download_does_not_overwrite_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prices = synthetic_prices(80).reset_index()
    cache_path = tmp_path / "historical_factor_prices.parquet"
    prices.to_parquet(cache_path, index=False)
    original = cache_path.read_bytes()

    def fail_download(*args: object, **kwargs: object) -> pd.DataFrame:
        raise MODULE.HistoricalFactorBuildError("provider unavailable")

    monkeypatch.setattr(MODULE, "download_adjusted_prices", fail_download)
    with pytest.raises(MODULE.HistoricalFactorBuildError, match="provider unavailable"):
        MODULE.load_or_update_price_cache(
            cache_path,
            start_date="2020-01-01",
            end_date="2021-01-01",
            force=False,
        )

    assert cache_path.read_bytes() == original


def test_episode_table_requires_exactly_25_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "episodes.csv"
    frame = pd.DataFrame(
        {
            "episode_id": range(24),
            "peak_date": pd.date_range("2000-01-01", periods=24),
            "trough_date": pd.date_range("2000-02-01", periods=24),
        }
    )
    frame.to_csv(source, index=False)

    with pytest.raises(MODULE.HistoricalFactorBuildError, match="exactly 25"):
        MODULE.discover_episode_table(explicit_path=source, output_dir=tmp_path)


def test_episode_mapping_uses_trading_observations_and_sets_flags() -> None:
    index = pd.bdate_range("2020-01-01", periods=200)
    factors = pd.DataFrame(
        {column: np.arange(200, dtype=float) for column in MODULE.FACTOR_COLUMNS},
        index=index,
    ).rename_axis("date")
    episodes = pd.DataFrame(
        {
            "episode_id": range(1, 26),
            "peak_date": [index[80]] * 25,
            "trough_date": [index[100]] * 25,
        }
    )

    annotated, mapped = MODULE.map_factors_to_episodes(factors, episodes)
    first = mapped[mapped["episode_id"] == 1]

    assert first["relative_day_to_peak"].min() == -60
    assert first["relative_day_to_trough"].max() == 20
    assert first.loc[first["date"] == index[80], "peak_to_trough"].item()
    assert first.loc[first["date"] == index[100], "peak_to_trough"].item()
    assert first["pre_peak"].sum() == 60
    assert first["post_trough"].sum() == 20
    assert annotated["complete_7_factor_window"].all()


def test_episode_with_partial_factor_rows_is_not_complete() -> None:
    index = pd.bdate_range("2020-01-01", periods=200)
    factors = pd.DataFrame(
        {column: np.arange(200, dtype=float) for column in MODULE.FACTOR_COLUMNS},
        index=index,
    ).rename_axis("date")
    factors.loc[index[:90], "QUAL"] = np.nan
    episodes = pd.DataFrame(
        {
            "episode_id": range(1, 26),
            "peak_date": [index[100]] * 25,
            "trough_date": [index[110]] * 25,
        }
    )

    annotated, mapped = MODULE.map_factors_to_episodes(factors, episodes)

    assert mapped["MKT"].notna().any()
    assert mapped["QUAL"].isna().any()
    assert annotated["factor_data_available"].all()
    assert not annotated["complete_7_factor_window"].any()


def test_missing_old_episode_is_retained_and_marked_unavailable() -> None:
    index = pd.bdate_range("2020-01-01", periods=100)
    factors = pd.DataFrame(0.0, index=index, columns=MODULE.FACTOR_COLUMNS).rename_axis("date")
    episodes = pd.DataFrame(
        {
            "episode_id": range(1, 26),
            "peak_date": [pd.Timestamp("1999-01-01")] + [index[20]] * 24,
            "trough_date": [pd.Timestamp("1999-02-01")] + [index[30]] * 24,
        }
    )

    annotated, _ = MODULE.map_factors_to_episodes(factors, episodes)

    old = annotated.loc[annotated["episode_id"] == 1].iloc[0]
    assert not old["factor_data_available"]
    assert not old["complete_7_factor_window"]
    assert "unavailable" in old["factor_coverage_status"]
