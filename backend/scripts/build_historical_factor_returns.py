#!/usr/bin/env python3
"""Build research-ready historical returns for Helix's production factor model.

This script deliberately delegates factor construction to ``risk/factor_model.py``.
It only owns adjusted-price retrieval/caching, QA, and mapping the resulting
factor returns to an already-defined set of 25 hedge research episodes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
PRODUCTION_FACTOR_DIR = REPO_ROOT / "risk"
PRODUCTION_FACTOR_PATH = PRODUCTION_FACTOR_DIR / "factor_model.py"

# risk/ is the production script package in this repository (run_factors.py
# imports factor_model from this directory directly).
if str(PRODUCTION_FACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(PRODUCTION_FACTOR_DIR))

from factor_model import (  # noqa: E402
    AI_LONG,
    AI_SHORT,
    FACTOR_ETFS,
    _residualize,
    build_factor_returns,
    required_factor_tickers,
)


FACTOR_COLUMNS = ["MKT", "AI", "MOM", "QUAL", "VAL", "SIZE", "LOWVOL"]
DEFAULT_OUTPUT_DIR = BACKEND_ROOT / "data" / "risk"
DEFAULT_START_DATE = "1990-01-01"
EPISODE_COUNT = 25
PRE_PEAK_OBSERVATIONS = 60
POST_TROUGH_OBSERVATIONS = 20


class HistoricalFactorBuildError(RuntimeError):
    """Raised when a fail-loud research-data invariant is violated."""


def _normalize_date_index(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted, timezone-naive, unique daily index without filling gaps."""

    result = frame.copy()
    index = pd.to_datetime(result.index, errors="coerce", utc=True)
    valid = ~index.isna()
    result = result.loc[valid]
    result.index = index[valid].tz_convert(None).normalize()
    result.index.name = "date"
    result = result.loc[~result.index.duplicated(keep="last")].sort_index()
    if result.index.has_duplicates:
        raise HistoricalFactorBuildError("duplicate dates remain after normalization")
    return result


def _extract_adjusted_closes(download: pd.DataFrame, tickers: Iterable[str]) -> pd.DataFrame:
    """Extract auto-adjusted Close fields from either yfinance column layout."""

    wanted = list(tickers)
    if download is None or download.empty:
        return pd.DataFrame(columns=wanted, dtype=float)

    if isinstance(download.columns, pd.MultiIndex):
        level0 = {str(value) for value in download.columns.get_level_values(0)}
        level1 = {str(value) for value in download.columns.get_level_values(1)}
        if "Close" in level0:
            close = download.xs("Close", axis=1, level=0, drop_level=True)
        elif "Close" in level1:
            close = download.xs("Close", axis=1, level=1, drop_level=True)
        else:
            raise HistoricalFactorBuildError("yfinance result has no Close field")
    else:
        if len(wanted) != 1 or "Close" not in download.columns:
            raise HistoricalFactorBuildError(
                "single-level yfinance result is only valid for a one-ticker download"
            )
        close = download[["Close"]].rename(columns={"Close": wanted[0]})

    if isinstance(close, pd.Series):
        close = close.to_frame(name=wanted[0])
    close.columns = [str(column).upper() for column in close.columns]
    close = close.reindex(columns=wanted).apply(pd.to_numeric, errors="coerce")
    return _normalize_date_index(close)


def download_adjusted_prices(
    tickers: Iterable[str],
    *,
    start_date: str,
    end_date: str,
    attempts: int = 3,
) -> pd.DataFrame:
    """Download adjusted daily closes in one batch, with bounded retries."""

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - environment-specific
        raise HistoricalFactorBuildError("yfinance is required for this script") from exc

    wanted = list(tickers)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            raw = yf.download(
                wanted,
                start=start_date,
                end=end_date,
                auto_adjust=True,
                actions=False,
                group_by="column",
                threads=True,
                progress=False,
            )
            prices = _extract_adjusted_closes(raw, wanted)
            missing = [ticker for ticker in wanted if prices[ticker].dropna().empty]
            if missing:
                raise HistoricalFactorBuildError(
                    f"required yfinance ticker downloads are empty: {missing}"
                )
            return prices
        except Exception as exc:  # retry provider and response-shape failures
            last_error = exc
            if attempt < attempts:
                time.sleep(float(attempt))
    raise HistoricalFactorBuildError(
        f"factor ETF download failed after {attempts} attempts: {last_error}"
    ) from last_error


def merge_price_cache(cached: pd.DataFrame, downloaded: pd.DataFrame) -> pd.DataFrame:
    """Prefer fresh non-null values while retaining healthy cached observations."""

    cached = _normalize_date_index(cached)
    downloaded = _normalize_date_index(downloaded)
    merged = downloaded.combine_first(cached).sort_index()
    merged.index.name = "date"
    return merged


def _atomic_parquet(frame: pd.DataFrame, path: Path, *, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=index)
    os.replace(temporary, path)


def _atomic_csv(frame: pd.DataFrame, path: Path, *, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=index)
    os.replace(temporary, path)


def load_or_update_price_cache(
    cache_path: Path,
    *,
    start_date: str,
    end_date: str,
    force: bool,
) -> pd.DataFrame:
    """Bootstrap or incrementally refresh the adjusted-close price cache."""

    tickers = required_factor_tickers()
    cached = pd.DataFrame(columns=tickers, dtype=float)
    download_start = start_date

    if cache_path.exists() and not force:
        stored = pd.read_parquet(cache_path)
        if "date" not in stored.columns:
            raise HistoricalFactorBuildError(f"price cache has no date column: {cache_path}")
        cached = stored.set_index("date").reindex(columns=tickers)
        cached = _normalize_date_index(cached)
        if not cached.empty:
            # Seven calendar days overlap catches provider corrections while avoiding
            # a full-history request on every run.
            download_start = max(
                pd.Timestamp(start_date), cached.index.max() - pd.Timedelta(days=7)
            ).date().isoformat()

    downloaded = download_adjusted_prices(
        tickers,
        start_date=download_start,
        end_date=end_date,
    )
    prices = merge_price_cache(cached, downloaded).reindex(columns=tickers)

    missing = [ticker for ticker in tickers if prices[ticker].dropna().empty]
    if missing:
        raise HistoricalFactorBuildError(f"required price histories are empty: {missing}")
    if prices.index.has_duplicates:
        raise HistoricalFactorBuildError("historical factor price cache has duplicate dates")

    output = prices.reset_index()
    _atomic_parquet(output, cache_path)
    return prices


def build_and_validate_factor_returns(prices: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the union-history panel while preserving production overlap exactly.

    Production ``build_factor_returns`` intentionally requires every ETF on every
    output date. For research history, each factor is first calculated on its own
    maximal dependency window using the same production residualizer. The fully
    specified common window is then replaced with the exact production output.
    """

    needed = required_factor_tickers()
    log_returns = np.log(prices[needed] / prices[needed].shift(1))
    union_index = log_returns.dropna(how="all").index
    factors = pd.DataFrame(index=union_index, columns=FACTOR_COLUMNS, dtype=float)

    # MKT has no cross-factor dependency and therefore starts with SPY history.
    factors["MKT"] = log_returns["SPY"].reindex(union_index)

    ai_dependencies = ["SPY", *AI_LONG, *AI_SHORT]
    ai_inputs = log_returns[ai_dependencies].dropna(how="any")
    if not ai_inputs.empty:
        ai_raw = sum(weight * ai_inputs[ticker] for ticker, weight in AI_LONG.items())
        ai_raw -= sum(weight * ai_inputs[ticker] for ticker, weight in AI_SHORT.items())
        factors.loc[ai_inputs.index, "AI"] = _residualize(
            ai_raw.to_numpy(dtype=float), ai_inputs["SPY"].to_numpy(dtype=float)
        )

    # A style observation requires its ETF return plus contemporaneous MKT and AI.
    # No prices or factor values are forward-filled across missing observations.
    for factor, ticker in FACTOR_ETFS.items():
        if factor == "MKT":
            continue
        style_inputs = pd.concat(
            [log_returns[ticker].rename("target"), factors[["MKT", "AI"]]], axis=1
        ).dropna(how="any")
        if style_inputs.empty:
            continue
        bases = style_inputs[["MKT", "AI"]].to_numpy(dtype=float)
        factors.loc[style_inputs.index, factor] = _residualize(
            style_inputs["target"].to_numpy(dtype=float), bases
        )

    # This call remains the authority for every date where the complete production
    # model exists. Overwriting guarantees byte-level numerical parity on overlap.
    production_factors = build_factor_returns(prices)
    factors.loc[production_factors.index, FACTOR_COLUMNS] = production_factors
    factors = factors.sort_index()

    if list(factors.columns) != FACTOR_COLUMNS:
        raise HistoricalFactorBuildError(
            f"unexpected production factor columns: {list(factors.columns)}"
        )
    if factors.index.has_duplicates:
        raise HistoricalFactorBuildError("factor-return output has duplicate dates")
    for factor in FACTOR_COLUMNS:
        available = factors[factor].dropna()
        if available.empty:
            raise HistoricalFactorBuildError(f"factor-return output has no {factor} history")
        if not np.isfinite(available.to_numpy(dtype=float)).all():
            raise HistoricalFactorBuildError(
                f"factor-return output contains non-finite {factor} values"
            )

    expected_mkt = log_returns["SPY"].dropna()
    actual_mkt = factors.loc[expected_mkt.index, "MKT"]
    mkt_error = float(np.max(np.abs(actual_mkt.to_numpy() - expected_mkt.to_numpy())))
    if mkt_error > 1e-12:
        raise HistoricalFactorBuildError(
            f"MKT differs from the available SPY log return (max error {mkt_error:.3e})"
        )

    production_error = float(
        np.max(
            np.abs(
                factors.loc[production_factors.index, FACTOR_COLUMNS].to_numpy()
                - production_factors.to_numpy()
            )
        )
    )
    if production_error > 1e-12:
        raise HistoricalFactorBuildError(
            "partial-history panel differs from production factors on the common "
            f"window (max error {production_error:.3e})"
        )

    def betas(target: str, bases: list[str]) -> dict[str, float]:
        x = np.column_stack(
            [
                np.ones(len(production_factors)),
                production_factors[bases].to_numpy(dtype=float),
            ]
        )
        coefficients, *_ = np.linalg.lstsq(
            x, production_factors[target].to_numpy(dtype=float), rcond=None
        )
        return {base: float(value) for base, value in zip(bases, coefficients[1:])}

    orthogonality = {"AI": betas("AI", ["MKT"])}
    for factor in FACTOR_COLUMNS[2:]:
        orthogonality[factor] = betas(factor, ["MKT", "AI"])
    max_abs_beta = max(
        abs(value) for factor_betas in orthogonality.values() for value in factor_betas.values()
    )
    if max_abs_beta > 1e-10:
        raise HistoricalFactorBuildError(
            f"production factor orthogonality QA failed (max beta {max_abs_beta:.3e})"
        )

    qa = {
        "mkt_max_abs_error_vs_spy_log_return": mkt_error,
        "production_overlap_max_abs_error": production_error,
        "production_common_start": production_factors.index.min().date().isoformat(),
        "factor_first_valid_dates": {
            factor: factors[factor].first_valid_index().date().isoformat()
            for factor in FACTOR_COLUMNS
        },
        "orthogonality_betas": orthogonality,
        "orthogonality_max_abs_beta": max_abs_beta,
    }
    return factors, qa


def _read_episode_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            for key in ("episodes", "data", "records"):
                if isinstance(payload.get(key), list):
                    payload = payload[key]
                    break
        return pd.DataFrame(payload)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise HistoricalFactorBuildError(f"unsupported episode table format: {path}")


def _normalize_episode_table(frame: pd.DataFrame, source_path: Path) -> pd.DataFrame:
    episodes = frame.copy()
    aliases = {
        "id": "episode_id",
        "event_id": "episode_id",
        "start_date": "threat_start_date",
        "warning_start_date": "threat_start_date",
    }
    for old, new in aliases.items():
        if new not in episodes.columns and old in episodes.columns:
            episodes = episodes.rename(columns={old: new})

    if "episode_id" not in episodes.columns:
        raise HistoricalFactorBuildError(
            f"episode table has no episode_id (or recognized ID alias): {source_path}"
        )
    if len(episodes) != EPISODE_COUNT:
        raise HistoricalFactorBuildError(
            f"episode table must contain exactly {EPISODE_COUNT} rows; "
            f"found {len(episodes)} in {source_path}"
        )
    if episodes["episode_id"].isna().any() or episodes["episode_id"].duplicated().any():
        raise HistoricalFactorBuildError("episode IDs must be non-null and unique")

    for column in episodes.columns:
        if column == "date" or column.endswith("_date"):
            episodes[column] = pd.to_datetime(episodes[column], errors="coerce").dt.normalize()
    return episodes


def discover_episode_table(
    *,
    explicit_path: Path | None,
    output_dir: Path,
) -> tuple[pd.DataFrame, Path]:
    """Locate an existing canonical 25-episode table; never invent episodes."""

    if explicit_path is not None:
        candidates = [explicit_path]
    else:
        patterns = (
            "*hedge*episode*.parquet",
            "*hedge*episode*.csv",
            "*drawdown*episode*.parquet",
            "*drawdown*episode*.csv",
            "*episode*.json",
        )
        candidates: list[Path] = []
        roots = [output_dir, BACKEND_ROOT / "data", REPO_ROOT / "research", REPO_ROOT / "risk"]
        target = (output_dir / "hedge_drawdown_episodes_25.parquet").resolve()
        for root in roots:
            if not root.exists():
                continue
            for pattern in patterns:
                candidates.extend(path for path in root.rglob(pattern) if path.resolve() != target)

    errors: list[str] = []
    for candidate in sorted(set(path.resolve() for path in candidates)):
        if not candidate.exists():
            errors.append(f"missing: {candidate}")
            continue
        try:
            return _normalize_episode_table(_read_episode_table(candidate), candidate), candidate
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    details = "\n  - ".join(errors) if errors else "no candidate episode tables found"
    raise HistoricalFactorBuildError(
        "The canonical 25 hedge episodes could not be recovered. Helix contains no "
        "saved episode table or reusable episode-generation helper, so this script "
        "will not regenerate a potentially different list. Supply the exact prior "
        "artifact with --episodes-path. Checked:\n  - " + details
    )


def map_factors_to_episodes(
    factors: pd.DataFrame,
    episodes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build peak-60 through trough+20 episode windows on the factor calendar."""

    if "peak_date" not in episodes.columns:
        raise HistoricalFactorBuildError("episode table needs peak_date for episode mapping")
    if "trough_date" not in episodes.columns:
        raise HistoricalFactorBuildError("episode table needs trough_date for episode mapping")

    calendar = pd.DatetimeIndex(factors.index).sort_values()
    annotated = episodes.copy()
    mapped_frames: list[pd.DataFrame] = []
    statuses: list[str] = []
    complete_flags: list[bool] = []
    available_flags: list[bool] = []

    for _, episode in episodes.iterrows():
        peak = pd.Timestamp(episode["peak_date"]) if pd.notna(episode["peak_date"]) else pd.NaT
        trough = (
            pd.Timestamp(episode["trough_date"])
            if pd.notna(episode["trough_date"])
            else pd.NaT
        )
        if pd.isna(peak) or pd.isna(trough):
            statuses.append("unavailable: missing peak_date or trough_date")
            complete_flags.append(False)
            available_flags.append(False)
            continue
        if peak < calendar.min():
            statuses.append("unavailable: episode predates factor history")
            complete_flags.append(False)
            available_flags.append(False)
            continue
        if peak > calendar.max():
            statuses.append("unavailable: episode is after factor history")
            complete_flags.append(False)
            available_flags.append(False)
            continue

        peak_position = int(calendar.searchsorted(peak, side="left"))
        trough_position = int(calendar.searchsorted(trough, side="left"))
        if peak_position >= len(calendar) or trough_position >= len(calendar):
            statuses.append("unavailable: episode is after factor history")
            complete_flags.append(False)
            available_flags.append(False)
            continue
        if calendar[trough_position] < peak or trough_position < peak_position:
            statuses.append("unavailable: invalid peak/trough ordering")
            complete_flags.append(False)
            available_flags.append(False)
            continue

        start_position = max(0, peak_position - PRE_PEAK_OBSERVATIONS)
        end_position = min(len(calendar) - 1, trough_position + POST_TROUGH_OBSERVATIONS)
        window = factors.iloc[start_position : end_position + 1].copy().reset_index()
        window = window.rename(columns={window.columns[0]: "date"})
        window.insert(0, "episode_id", episode["episode_id"])
        positions = np.arange(start_position, end_position + 1)
        window["relative_day_to_peak"] = positions - peak_position
        window["relative_day_to_trough"] = positions - trough_position
        window["pre_peak"] = window["date"] < peak
        window["peak_to_trough"] = (window["date"] >= peak) & (window["date"] <= trough)
        window["post_trough"] = window["date"] > trough
        mapped_frames.append(window)

        full_factor_coverage = window[FACTOR_COLUMNS].notna().all(axis=1).all()
        complete = (
            peak_position >= PRE_PEAK_OBSERVATIONS
            and trough_position + POST_TROUGH_OBSERVATIONS < len(calendar)
            and peak >= calendar.min()
            and trough <= calendar.max()
            and full_factor_coverage
        )
        available_flags.append(True)
        complete_flags.append(bool(complete))
        statuses.append("complete" if complete else "partial factor-history window")

    annotated["factor_data_available"] = available_flags
    annotated["complete_7_factor_window"] = complete_flags
    annotated["factor_coverage_status"] = statuses

    columns = [
        "episode_id",
        "date",
        "relative_day_to_peak",
        "relative_day_to_trough",
        *FACTOR_COLUMNS,
        "pre_peak",
        "peak_to_trough",
        "post_trough",
    ]
    if mapped_frames:
        mapped = pd.concat(mapped_frames, ignore_index=True).reindex(columns=columns)
    else:
        mapped = pd.DataFrame(columns=columns)
    return annotated, mapped


def render_methodology(
    *,
    prices: pd.DataFrame,
    factors: pd.DataFrame,
    episode_source: Path,
    episodes: pd.DataFrame,
    qa: dict[str, Any],
) -> str:
    inception_rows = "\n".join(
        f"| {ticker} | {prices[ticker].first_valid_index().date().isoformat()} |"
        for ticker in required_factor_tickers()
    )
    mapping_rows = "\n".join(
        f"| {factor} | {ticker} |" for factor, ticker in FACTOR_ETFS.items()
    )
    common_price_start = prices.dropna(how="any").index.min().date().isoformat()
    first_factor_dates = qa["factor_first_valid_dates"]
    factor_coverage_rows = "\n".join(
        f"| {factor} | {first_factor_dates[factor]} |"
        for factor in FACTOR_COLUMNS
    )
    unavailable = episodes.loc[~episodes["complete_7_factor_window"], "episode_id"].tolist()
    return f"""# Historical Factor Returns Methodology

## Production Reuse

Factor returns are built by importing and calling `build_factor_returns()` from
`{PRODUCTION_FACTOR_PATH.relative_to(REPO_ROOT)}`. No factor transformation is
reimplemented in this research script. Complete-model production differences:
**none**. Earlier partial-history rows are a research-only extension and are null
for factors whose required inputs are not yet available.

Prices are yfinance daily `Close` values requested with `auto_adjust=True`, matching
the production factor runner. Missing prices are not forward-filled.

The exported return panel uses the union of factor histories. MKT begins with SPY.
AI begins when SPY, SOXX, QQQ, and RSP returns are all available. Each style factor
begins when its ETF return plus MKT and AI are available. Partial-history factors use
the production `_residualize()` function over their maximal valid dependency window.
On and after the complete-model overlap, values are replaced with the exact output
of production `build_factor_returns()`, preserving production numerical parity.

## ETF Mapping

| Factor | ETF |
|---|---|
{mapping_rows}

AI raw spread: `{AI_LONG}` long and `{AI_SHORT}` short. AI is residualized against
MKT. MOM, QUAL, VAL, SIZE, and LOWVOL are then residualized against `[MKT, AI]`,
with the ordering and intercept behavior defined exclusively by production code.

## Coverage

| Ticker | First adjusted price |
|---|---|
{inception_rows}

- First date with all required ETF prices: {common_price_start}
- First date with any factor return: {factors.index.min().date().isoformat()}
- First complete production-factor date: {qa['production_common_start']}
- Last factor-return date: {factors.index.max().date().isoformat()}
- Factor observations: {len(factors):,}

| Factor | First available return |
|---|---|
{factor_coverage_rows}

## Hedge Episodes

- Canonical source: `{episode_source}`
- Episode count: {len(episodes)} (strictly required to equal {EPISODE_COUNT})
- Complete seven-factor ±window coverage: {int(episodes['complete_7_factor_window'].sum())}
- Episodes without complete coverage: {unavailable or 'none'}
- Daily mapping window: 60 factor trading observations before peak through 20
  factor trading observations after trough.
- The episode table is reused as supplied. This script does not define, optimize,
  or independently regenerate drawdown episodes.

## QA

- MKT max absolute error versus aligned SPY log return: {qa['mkt_max_abs_error_vs_spy_log_return']:.3e}
- Complete-window max absolute error versus production: {qa['production_overlap_max_abs_error']:.3e}
- Maximum absolute residual factor beta: {qa['orthogonality_max_abs_beta']:.3e}
- Factor columns: {', '.join(FACTOR_COLUMNS)}

This pass performs data preparation only. It computes no conditional factor shock,
quantile, crash average, regime classification, or replacement production stress vector.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--episodes-path", type=Path)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument(
        "--end-date",
        default=(date.today() + timedelta(days=1)).isoformat(),
        help="Exclusive yfinance end date (default: tomorrow).",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild the full price cache.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Production factor model: {PRODUCTION_FACTOR_PATH}")
    print("Recovering canonical hedge episodes...")
    episodes, episode_source = discover_episode_table(
        explicit_path=args.episodes_path.resolve() if args.episodes_path else None,
        output_dir=output_dir,
    )
    print(f"Recovered {len(episodes)} episodes from {episode_source}")

    prices_path = output_dir / "historical_factor_prices.parquet"
    returns_path = output_dir / "historical_factor_returns.parquet"
    returns_csv_path = output_dir / "historical_factor_returns.csv"
    episodes_path = output_dir / "hedge_drawdown_episodes_25.parquet"
    episodes_csv_path = output_dir / "hedge_drawdown_episodes_25.csv"
    episode_daily_path = output_dir / "factor_episode_daily.parquet"
    methodology_path = output_dir / "historical_factor_returns_methodology.md"

    print(f"Updating adjusted-price cache for: {', '.join(required_factor_tickers())}")
    prices = load_or_update_price_cache(
        prices_path,
        start_date=args.start_date,
        end_date=args.end_date,
        force=args.force,
    )
    factors, qa = build_and_validate_factor_returns(prices)
    annotated_episodes, episode_daily = map_factors_to_episodes(factors, episodes)

    factor_output = factors.reset_index().rename(columns={factors.index.name or "index": "date"})
    _atomic_parquet(factor_output, returns_path)
    _atomic_csv(factor_output, returns_csv_path)
    _atomic_parquet(annotated_episodes, episodes_path)
    _atomic_csv(annotated_episodes, episodes_csv_path)
    _atomic_parquet(episode_daily, episode_daily_path)
    methodology_path.write_text(
        render_methodology(
            prices=prices,
            factors=factors,
            episode_source=episode_source,
            episodes=annotated_episodes,
            qa=qa,
        ),
        encoding="utf-8",
    )

    print("\nHistorical factor-return build complete")
    print(f"Factor tickers: {', '.join(required_factor_tickers())}")
    print("Ticker inception dates:")
    for ticker in required_factor_tickers():
        print(f"  {ticker}: {prices[ticker].first_valid_index().date().isoformat()}")
    print(f"Common price start: {prices.dropna(how='any').index.min().date().isoformat()}")
    print(f"Any-factor period: {factors.index.min().date()} -> {factors.index.max().date()}")
    print(f"Complete production-factor start: {qa['production_common_start']}")
    print(f"Daily union observations: {len(factors):,}")
    print("Factor return first-valid dates:")
    for factor, first_date in qa["factor_first_valid_dates"].items():
        print(f"  {factor}: {first_date}")
    print(f"Hedge episodes recovered: {len(annotated_episodes)} (exactly 25: yes)")
    print(
        "Episodes with complete seven-factor coverage: "
        f"{int(annotated_episodes['complete_7_factor_window'].sum())}/{EPISODE_COUNT}"
    )
    for _, row in annotated_episodes.loc[
        ~annotated_episodes["complete_7_factor_window"]
    ].iterrows():
        print(f"  unavailable/partial {row['episode_id']}: {row['factor_coverage_status']}")
    print(f"MKT parity max error: {qa['mkt_max_abs_error_vs_spy_log_return']:.3e}")
    print(f"Production overlap max error: {qa['production_overlap_max_abs_error']:.3e}")
    print(f"Orthogonality max absolute beta: {qa['orthogonality_max_abs_beta']:.3e}")
    print("Complete-window production methodology differences: NONE")
    print("Pre-common history: partial factor rows added where dependencies are available")
    print("Outputs:")
    for path in (
        prices_path,
        returns_path,
        returns_csv_path,
        episodes_path,
        episodes_csv_path,
        episode_daily_path,
        methodology_path,
    ):
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HistoricalFactorBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
