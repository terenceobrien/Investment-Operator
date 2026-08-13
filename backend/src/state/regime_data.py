"""
src/state/regime_data.py

Fetches all raw inputs needed for the five-layer regime scoring system.
Runs ONCE at market close — not intraday.

Returns a RegimeInputs dataclass with every field the scoring system needs.
Missing data is None — the scoring system handles this gracefully.
"""
from __future__ import annotations

import os
import requests
from dataclasses import dataclass, field, asdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class RegimeInputs:
    asof_date: str = ""

    # Layer 1 — Monetary
    net_liquidity:      Optional[float] = None   # WALCL - TGA - RRP (billions)
    net_liquidity_z:    Optional[float] = None   # z-score vs 1yr
    nfci:               Optional[float] = None   # Chicago Fed NFCI
    nfci_inverted:      Optional[float] = None   # -NFCI z-score
    m2_growth_yoy:      Optional[float] = None   # M2 YoY %
    fci_z:              Optional[float] = None   # FCI z-score inverted

    # Layer 2 — Credit
    hy_spread_level:    Optional[float] = None   # bps
    hy_spread_z:        Optional[float] = None
    hy_spread_chg_4w:   Optional[float] = None   # bps
    ig_spread_level:    Optional[float] = None   # bps
    ig_spread_z:        Optional[float] = None
    hyg_tlt_ratio_z:    Optional[float] = None

    # Layer 3 — Volatility
    vix_level:          Optional[float] = None
    vix_z_20d:          Optional[float] = None
    vix_term_slope:     Optional[float] = None   # VIX3M - VIX
    vvix_level:         Optional[float] = None
    vvix_z:             Optional[float] = None
    put_call_ratio:     Optional[float] = None   # generic/SPY-proxy put-call, not Cboe equity PCR
    skew_index:         Optional[float] = None

    # Layer 4 — Breadth
    pct_above_200d:         Optional[float] = None
    avg_dist_from_200d:     Optional[float] = None   # avg % distance of S&P 500 constituents from their 200d MA
    sectors_green:           Optional[int]   = None
    rsp_vs_spy_z:           Optional[float] = None
    adl_slope:              Optional[float] = None

    # Layer 5 — Positioning
    dealer_gamma_z:       Optional[float] = None
    put_call_5d_ma:       Optional[float] = None
    aaii_bull_minus_bear: Optional[float] = None
    cot_net_large_spec_z: Optional[float] = None
    equity_etf_flow_z:    Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ConstituentHistoryResult:
    universe: str
    data: pd.DataFrame
    cache_path: Path
    requested_count: int
    successful_ticker_count: int
    failed_tickers: tuple[str, ...]
    latest_cached_date: Optional[str]
    live_download_attempted: bool
    live_download_succeeded: bool
    cached_fallback_used: bool


@dataclass(frozen=True)
class Breadth200dResult:
    pct_above_200d: Optional[float]
    avg_dist_from_200d: Optional[float]
    valid_count: int


SECTOR_ETFS = ["XLK", "XLF", "XLV", "XLY", "XLP", "XLE", "XLI", "XLB", "XLU", "XLRE", "XLC"]
CONSTITUENT_UNIVERSE_FILES = {
    "sp500": "sp500.csv",
    "nasdaq100": "nasdaq100.csv",
}
CONSTITUENT_BOOTSTRAP_CALENDAR_DAYS = 450
CONSTITUENT_CACHE_COLUMNS = ["date", "ticker", "yahoo_symbol", "adjusted_close"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_last(series: pd.Series) -> Optional[float]:
    try:
        v = series.dropna().iloc[-1]
        return float(v) if np.isfinite(float(v)) else None
    except Exception:
        return None


def _z_score(series: pd.Series, window: int = 252) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 20:
            return None
        rolling = s.rolling(window, min_periods=20)
        mu = rolling.mean().iloc[-1]
        sd = rolling.std().iloc[-1]
        if sd == 0 or not np.isfinite(sd):
            return None
        return float((s.iloc[-1] - mu) / sd)
    except Exception:
        return None


def _pct_change_yoy(series: pd.Series) -> Optional[float]:
    try:
        s = series.dropna()
        if len(s) < 252:
            return None
        latest = s.iloc[-1]
        year_ago = s.iloc[-252]
        if year_ago == 0:
            return None
        return float((latest / year_ago - 1) * 100)
    except Exception:
        return None


# ── FRED fetcher ──────────────────────────────────────────────────────────────

def _fred(
    series_id: str,
    periods: int = 520,
    asof_date: Optional[str] = None,
) -> pd.Series:
    """Fetch a FRED series. Returns empty Series on failure.

    If asof_date is provided, truncate the series to that date inclusive before
    taking the trailing observation window.
    """
    try:
        def _lazy_fred():
            from fredapi import Fred
            api_key = os.environ.get("FRED_API_KEY", "")
            return Fred(api_key=api_key)

        fred = _lazy_fred()
        data = fred.get_series(series_id)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        data = data.dropna()
        if asof_date is not None:
            data = data[data.index <= pd.Timestamp(asof_date)]
        return data.tail(periods)
    except Exception as e:
        print(f"FRED fetch failed for {series_id}: {e}")
        return pd.Series(dtype=float)


# ── yfinance fetcher ──────────────────────────────────────────────────────────

def _yf_close(
    ticker: str,
    period: str = "2y",
    asof_date: Optional[str] = None,
) -> pd.Series:
    """Fetch closing prices via yfinance.

    If asof_date is provided, fetch a wider historical window and truncate to
    that date inclusive.
    """
    try:
        import yfinance as yf
        if asof_date is not None:
            asof_ts = pd.Timestamp(asof_date)
            start = (asof_ts - pd.Timedelta(days=365 * 3)).strftime("%Y-%m-%d")
            # yfinance treats end as exclusive, so add one calendar day and
            # still explicitly trim below to keep the fetch point-in-time.
            end = (asof_ts + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            data = yf.download(
                ticker,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        else:
            data = yf.download(ticker, period=period, progress=False,
                               auto_adjust=True, threads=False)
        if data is None or data.empty:
            return pd.Series(dtype=float)
        closes = data["Close"].squeeze().dropna()
        if asof_date is not None:
            asof_ts = pd.Timestamp(asof_date)
            if getattr(closes.index, "tz", None) is not None:
                asof_ts = asof_ts.tz_localize(closes.index.tz)
            closes = closes[closes.index <= asof_ts]
        return closes
    except Exception as e:
        print(f"yfinance fetch failed for {ticker}: {e}")
        return pd.Series(dtype=float)


# ── Constituent breadth helpers ───────────────────────────────────────────────

def _constituent_cache_root(cache_root: Optional[Path] = None) -> Path:
    if cache_root is not None:
        root = Path(cache_root)
    else:
        from src.agent_system.paths import cache_dir

        root = cache_dir(create=True) / "breadth"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _constituent_cache_path(universe: str, cache_root: Optional[Path] = None) -> Path:
    universe_key = _normalize_universe(universe)
    return _constituent_cache_root(cache_root) / f"{universe_key}_prices.parquet"


def _normalize_universe(universe: str) -> str:
    key = str(universe).strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    aliases = {
        "sp": "sp500",
        "s&p500": "sp500",
        "sp500": "sp500",
        "sandp500": "sp500",
        "nasdaq": "nasdaq100",
        "ndx": "nasdaq100",
        "nasdaq100": "nasdaq100",
    }
    if key not in aliases:
        raise ValueError(
            f"Unsupported constituent universe '{universe}'. "
            f"Expected one of {sorted(CONSTITUENT_UNIVERSE_FILES)}."
        )
    return aliases[key]


def load_constituent_list(
    universe: str = "sp500",
    universe_root: Optional[Path] = None,
) -> list[str]:
    """Load canonical constituent tickers from backend/data/universe.

    The files represent current membership. That is appropriate for current/live
    breadth readings, but it is not a point-in-time historical S&P 500 database;
    using these same members historically would introduce survivorship bias.
    """
    universe_key = _normalize_universe(universe)
    if universe_root is None:
        from src.agent_system.paths import universe_dir

        root = universe_dir(create=False)
    else:
        root = Path(universe_root)
    path = root / CONSTITUENT_UNIVERSE_FILES[universe_key]
    if not path.exists():
        raise FileNotFoundError(f"Constituent universe file not found: {path}")

    frame = pd.read_csv(path)
    if "ticker" not in frame.columns:
        raise ValueError(f"Expected 'ticker' column in constituent universe file: {path}")
    tickers = (
        frame["ticker"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
    )
    return list(dict.fromkeys(ticker for ticker in tickers if ticker))


def yahoo_symbol(ticker: str) -> str:
    """Map canonical Helix/index tickers to Yahoo-compatible symbols."""
    return str(ticker).strip().upper().replace(".", "-")


def _latest_completed_daily_bar_date(asof_date: Optional[str] = None) -> pd.Timestamp:
    if asof_date is not None:
        return pd.Timestamp(asof_date).normalize().tz_localize(None)

    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = pd.Timestamp(now_et.date())
    after_daily_bar_settle = now_et.weekday() < 5 and now_et.time() >= time(18, 0)
    if after_daily_bar_settle:
        return today
    return pd.Timestamp(today - pd.offsets.BDay(1)).normalize()


def _empty_constituent_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=CONSTITUENT_CACHE_COLUMNS)


def _clean_constituent_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_constituent_cache()
    missing = [col for col in CONSTITUENT_CACHE_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"Constituent price frame missing columns: {missing}")

    clean = frame[CONSTITUENT_CACHE_COLUMNS].copy()
    clean["date"] = pd.to_datetime(clean["date"], errors="coerce").dt.tz_localize(None)
    clean["ticker"] = clean["ticker"].astype(str).str.strip().str.upper()
    clean["yahoo_symbol"] = clean["yahoo_symbol"].astype(str).str.strip().str.upper()
    clean["adjusted_close"] = pd.to_numeric(clean["adjusted_close"], errors="coerce")
    clean = clean.dropna(subset=["date", "ticker", "adjusted_close"])
    clean = clean[clean["adjusted_close"] > 0]
    if clean.empty:
        return _empty_constituent_cache()
    clean["date"] = clean["date"].dt.normalize()
    clean = (
        clean.drop_duplicates(["date", "ticker"], keep="last")
        .sort_values(["date", "ticker"])
        .reset_index(drop=True)
    )
    return clean


def load_constituent_cache(
    universe: str = "sp500",
    cache_root: Optional[Path] = None,
) -> pd.DataFrame:
    path = _constituent_cache_path(universe, cache_root)
    if not path.exists():
        return _empty_constituent_cache()
    try:
        return _clean_constituent_prices(pd.read_parquet(path))
    except Exception as e:
        print(f"    constituent cache read failed for {path}: {e}")
        return _empty_constituent_cache()


def _write_constituent_cache(frame: pd.DataFrame, path: Path) -> None:
    clean = _clean_constituent_prices(frame)
    if clean.empty:
        raise ValueError("Refusing to write empty constituent cache.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        clean.to_parquet(tmp_path, index=False)
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _download_adjusted_close_for_symbol(
    data: pd.DataFrame,
    symbol: str,
) -> pd.Series:
    if data is None or data.empty:
        return pd.Series(dtype=float)

    columns = getattr(data, "columns", None)
    if isinstance(columns, pd.MultiIndex):
        if symbol in columns.get_level_values(0):
            sub = data[symbol]
        elif symbol in columns.get_level_values(1):
            sub = data.xs(symbol, axis=1, level=1)
        else:
            return pd.Series(dtype=float)
    else:
        sub = data

    field = "Adj Close" if "Adj Close" in sub.columns else "Close" if "Close" in sub.columns else None
    if field is None:
        return pd.Series(dtype=float)
    series = pd.to_numeric(sub[field].squeeze(), errors="coerce").dropna()
    if series.empty:
        return pd.Series(dtype=float)
    series.index = pd.to_datetime(series.index, errors="coerce").tz_localize(None).normalize()
    return series.dropna()


def fetch_constituent_prices(
    tickers: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
    batch_size: int = 100,
) -> tuple[pd.DataFrame, list[str]]:
    """Fetch adjusted closes in Yahoo batches; failures return as ticker symbols."""
    if not tickers:
        return _empty_constituent_cache(), []

    import yfinance as yf

    rows: list[pd.DataFrame] = []
    failed: set[str] = set()
    symbol_map = {ticker: yahoo_symbol(ticker) for ticker in tickers}
    ordered = list(symbol_map.items())

    for offset in range(0, len(ordered), batch_size):
        batch = ordered[offset : offset + batch_size]
        yahoo_symbols = [symbol for _, symbol in batch]
        try:
            data = yf.download(
                yahoo_symbols,
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                progress=False,
                auto_adjust=False,
                threads=True,
                group_by="ticker",
            )
        except Exception as e:
            print(f"    yfinance batch failed ({offset + 1}-{offset + len(batch)}): {e}")
            failed.update(ticker for ticker, _ in batch)
            continue

        for ticker, symbol in batch:
            closes = _download_adjusted_close_for_symbol(data, symbol)
            if closes.empty:
                failed.add(ticker)
                continue
            rows.append(
                pd.DataFrame(
                    {
                        "date": closes.index,
                        "ticker": ticker,
                        "yahoo_symbol": symbol,
                        "adjusted_close": closes.to_numpy(dtype=float),
                    }
                )
            )

    if not rows:
        return _empty_constituent_cache(), sorted(failed)
    downloaded = _clean_constituent_prices(pd.concat(rows, ignore_index=True))
    successful = set(downloaded["ticker"].unique())
    failed.update(ticker for ticker in tickers if ticker not in successful)
    return downloaded, sorted(failed)


def update_constituent_cache(
    universe: str = "sp500",
    *,
    asof_date: Optional[str] = None,
    cache_root: Optional[Path] = None,
    universe_root: Optional[Path] = None,
    bootstrap_calendar_days: int = CONSTITUENT_BOOTSTRAP_CALENDAR_DAYS,
) -> ConstituentHistoryResult:
    """Load/update constituent adjusted-close history with safe cached fallback."""
    universe_key = _normalize_universe(universe)
    tickers = load_constituent_list(universe_key, universe_root=universe_root)
    cache_path = _constituent_cache_path(universe_key, cache_root)
    cached = load_constituent_cache(universe_key, cache_root=cache_root)
    latest_needed = _latest_completed_daily_bar_date(asof_date)
    bootstrap_start = latest_needed - pd.Timedelta(days=bootstrap_calendar_days)

    if cached.empty:
        download_start = bootstrap_start
    else:
        cache_dates = pd.to_datetime(cached["date"])
        cache_min = cache_dates.min().normalize()
        cache_max = cache_dates.max().normalize()
        if cache_min > bootstrap_start:
            download_start = bootstrap_start
        elif cache_max < latest_needed:
            download_start = cache_max + pd.Timedelta(days=1)
        else:
            download_start = None

    live_download_attempted = download_start is not None
    live_download_succeeded = False
    cached_fallback_used = False
    failed_tickers: list[str] = []
    merged = cached

    if live_download_attempted:
        download_end = latest_needed + pd.Timedelta(days=1)
        downloaded = _empty_constituent_cache()
        try:
            downloaded, failed_tickers = fetch_constituent_prices(
                tickers,
                pd.Timestamp(download_start).normalize(),
                pd.Timestamp(download_end).normalize(),
            )
        except Exception as e:
            print(f"    constituent history download failed for {universe_key}: {e}")
            failed_tickers = tickers.copy()

        if not downloaded.empty:
            live_download_succeeded = True
            if cached.empty:
                merged = downloaded
            else:
                merged = _clean_constituent_prices(
                    pd.concat([cached, downloaded], ignore_index=True)
                )
            try:
                _write_constituent_cache(merged, cache_path)
            except Exception as e:
                print(f"    constituent cache write failed for {cache_path}: {e}")
        elif not cached.empty:
            cached_fallback_used = True
            print(
                f"    using cached {universe_key} constituent data after empty/failed download"
            )
        else:
            print(f"    no usable {universe_key} constituent data available")

    if not merged.empty:
        merged = merged[merged["ticker"].isin(tickers)].copy()
        if asof_date is not None:
            asof_ts = pd.Timestamp(asof_date).normalize()
            merged = merged[pd.to_datetime(merged["date"]) <= asof_ts].copy()

    latest_cached_date = None
    successful_count = 0
    if not merged.empty:
        latest_cached_date = pd.to_datetime(merged["date"]).max().strftime("%Y-%m-%d")
        successful_count = int(merged["ticker"].nunique())
        if not failed_tickers:
            loaded = set(merged["ticker"].unique())
            failed_tickers = sorted(ticker for ticker in tickers if ticker not in loaded)

    return ConstituentHistoryResult(
        universe=universe_key,
        data=merged,
        cache_path=cache_path,
        requested_count=len(tickers),
        successful_ticker_count=successful_count,
        failed_tickers=tuple(sorted(set(failed_tickers))),
        latest_cached_date=latest_cached_date,
        live_download_attempted=live_download_attempted,
        live_download_succeeded=live_download_succeeded,
        cached_fallback_used=cached_fallback_used,
    )


def get_constituent_history(
    universe: str = "sp500",
    *,
    asof_date: Optional[str] = None,
    cache_root: Optional[Path] = None,
    universe_root: Optional[Path] = None,
) -> ConstituentHistoryResult:
    return update_constituent_cache(
        universe,
        asof_date=asof_date,
        cache_root=cache_root,
        universe_root=universe_root,
    )


def _constituent_price_matrix(history: pd.DataFrame) -> pd.DataFrame:
    clean = _clean_constituent_prices(history)
    if clean.empty:
        return pd.DataFrame(dtype=float)
    matrix = clean.pivot(index="date", columns="ticker", values="adjusted_close")
    matrix.index = pd.to_datetime(matrix.index).tz_localize(None).normalize()
    return matrix.sort_index()


def calculate_200d_breadth(prices: pd.DataFrame, window: int = 200) -> Breadth200dResult:
    if prices is None or prices.empty:
        return Breadth200dResult(None, None, 0)
    ma = prices.rolling(window, min_periods=window).mean()
    latest_date = prices.index.max()
    current = prices.loc[latest_date]
    ma_latest = ma.loc[latest_date]
    valid = current.notna() & ma_latest.notna() & ma_latest.ne(0)
    valid_count = int(valid.sum())
    if valid_count == 0:
        return Breadth200dResult(None, None, 0)
    above = current[valid] > ma_latest[valid]
    distances = (current[valid] - ma_latest[valid]) / ma_latest[valid] * 100.0
    return Breadth200dResult(
        pct_above_200d=float(above.mean() * 100.0),
        avg_dist_from_200d=float(distances.mean()),
        valid_count=valid_count,
    )


def calculate_pct_above_200d(prices: pd.DataFrame, window: int = 200) -> tuple[Optional[float], int]:
    result = calculate_200d_breadth(prices, window=window)
    return result.pct_above_200d, result.valid_count


def calculate_avg_distance_200d(prices: pd.DataFrame, window: int = 200) -> tuple[Optional[float], int]:
    result = calculate_200d_breadth(prices, window=window)
    return result.avg_dist_from_200d, result.valid_count


def calculate_advance_decline_line(prices: pd.DataFrame) -> pd.Series:
    """Return normalized constituent ADL from stock-level advances/declines.

    The score thresholds were built around an 11-sector ADL proxy. A raw
    500-stock ADL slope would be a different unit and much larger magnitude, so
    daily net advances are normalized by valid constituent count before the ADL
    is accumulated. This keeps the input comparable through time and compatible
    with the existing Layer 4 scoring scale.
    """
    if prices is None or prices.empty:
        return pd.Series(dtype=float)
    changes = prices.diff()
    valid = prices.notna() & prices.shift(1).notna()
    advances = changes.gt(0) & valid
    declines = changes.lt(0) & valid
    valid_count = valid.sum(axis=1).replace(0, np.nan)
    normalized_net_advances = (advances.sum(axis=1) - declines.sum(axis=1)) / valid_count
    return normalized_net_advances.dropna().cumsum()


def calculate_adl_slope(adl: pd.Series, window: int = 20) -> Optional[float]:
    recent = pd.to_numeric(adl, errors="coerce").dropna().tail(window)
    if len(recent) < window:
        return None
    x = np.arange(len(recent))
    slope, _ = np.polyfit(x, recent.to_numpy(dtype=float), 1)
    return float(slope)


def calculate_rsp_vs_spy_z(asof_date: Optional[str] = None) -> Optional[float]:
    rsp = _yf_close("RSP", asof_date=asof_date)
    spy = _yf_close("SPY", asof_date=asof_date)
    if rsp.empty or spy.empty:
        return None
    ratio = (rsp / spy).dropna()
    return _z_score(ratio, window=252)


def calculate_sectors_green(asof_date: Optional[str] = None) -> Optional[int]:
    green_count = 0
    valid_count = 0
    latest_allowed = _latest_completed_daily_bar_date(asof_date)
    for etf in SECTOR_ETFS:
        closes = _yf_close(etf, asof_date=asof_date)
        if not closes.empty:
            close_dates = pd.to_datetime(closes.index).tz_localize(None).normalize()
            closes = closes.loc[close_dates <= latest_allowed]
        if len(closes) < 2:
            continue
        valid_count += 1
        if closes.iloc[-1] > closes.iloc[-2]:
            green_count += 1
    return green_count if valid_count else None


def _valid_advance_decline_count(prices: pd.DataFrame) -> int:
    if prices is None or prices.empty:
        return 0
    latest_date = prices.index.max()
    valid = prices.notna() & prices.shift(1).notna()
    return int(valid.loc[latest_date].sum()) if latest_date in valid.index else 0


def _print_breadth_snapshot(
    inputs: RegimeInputs,
    history_result: ConstituentHistoryResult,
    valid_ma200_count: int,
    valid_ad_count: int,
) -> None:
    print("    Breadth constituent universe:")
    print(f"      S&P 500 requested: {history_result.requested_count}")
    print(f"      Successfully loaded: {history_result.successful_ticker_count}")
    print(f"      Valid MA200: {valid_ma200_count}")
    print(f"      Valid A/D: {valid_ad_count}")
    print(f"      Latest cached market data: {history_result.latest_cached_date or 'n/a'}")
    print(
        "      Download status: "
        f"attempted={history_result.live_download_attempted}, "
        f"succeeded={history_result.live_download_succeeded}, "
        f"cached_fallback={history_result.cached_fallback_used}"
    )
    if history_result.failed_tickers:
        sample = ", ".join(history_result.failed_tickers[:20])
        suffix = "..." if len(history_result.failed_tickers) > 20 else ""
        print(f"      Failed/missing tickers: {sample}{suffix}")

    print(f"    pct_above_200d: {inputs.pct_above_200d if inputs.pct_above_200d is not None else 'n/a'}")
    print(f"    avg_dist_from_200d: {inputs.avg_dist_from_200d if inputs.avg_dist_from_200d is not None else 'n/a'}")
    print(f"    rsp_vs_spy_z: {inputs.rsp_vs_spy_z if inputs.rsp_vs_spy_z is not None else 'n/a'}")
    print(f"    adl_slope: {inputs.adl_slope if inputs.adl_slope is not None else 'n/a'}")
    print(f"    sectors_green: {inputs.sectors_green if inputs.sectors_green is not None else 'n/a'}")
    try:
        from src.state.regime_layers import score_breadth

        layer = score_breadth(
            pct_above_200d=inputs.pct_above_200d,
            avg_dist_from_200d=inputs.avg_dist_from_200d,
            sectors_green=inputs.sectors_green,
            rsp_vs_spy_z=inputs.rsp_vs_spy_z,
            adl_slope=inputs.adl_slope,
        )
        print(f"    Layer 4 score: {layer.score:.2f}")
    except Exception as e:
        print(f"    Layer 4 score snapshot unavailable: {e}")


# ── Layer 1: Monetary ─────────────────────────────────────────────────────────

def _fetch_monetary(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching monetary & liquidity data...")

    # Net liquidity = Fed balance sheet - TGA - RRP
    walcl = _fred("WALCL", asof_date=asof_date)      # Fed balance sheet (millions)
    tga   = _fred("WTREGEN", asof_date=asof_date)    # Treasury General Account (millions)
    rrp   = _fred("RRPONTSYD", asof_date=asof_date)  # Overnight reverse repo (billions)

    if not walcl.empty and not tga.empty and not rrp.empty:
        try:
            walcl_b = walcl / 1000  # millions -> billions
            tga_b = tga / 1000  # millions -> billions
            # Align to weekly frequency
            combined = pd.concat([walcl_b, tga_b, rrp], axis=1).ffill().dropna()
            combined.columns = ["walcl", "tga", "rrp"]
            print(combined.tail(3))          # <- add this
            print("walcl_b last:", walcl_b.iloc[-1], walcl_b.index[-1])
            print("tga_b last:", tga_b.iloc[-1], tga_b.index[-1])
            print("rrp last:", rrp.iloc[-1], rrp.index[-1])
            net_liq = combined["walcl"] - combined["tga"] - combined["rrp"]
            inputs.net_liquidity = _safe_last(net_liq)
            z = _z_score(net_liq, window=52)
            inputs.net_liquidity_z = z
            print(f"    net_liquidity=${inputs.net_liquidity:.0f}B  z={z}")
        except Exception as e:
            print(f"    net_liquidity calc failed: {e}")

    # NFCI — Chicago Fed National Financial Conditions Index
    nfci = _fred("NFCI", asof_date=asof_date)
    if not nfci.empty:
        inputs.nfci = _safe_last(nfci)
        # Inverted z-score: negative NFCI (easy) = positive score
        z = _z_score(nfci)
        inputs.nfci_inverted = -z if z is not None else None
        print(f"    nfci={inputs.nfci}  inverted_z={inputs.nfci_inverted}")

    # M2 growth YoY
    m2 = _fred("M2SL", asof_date=asof_date)
    if not m2.empty:
        try:
            s = m2.dropna()
            if len(s) >= 13:
                inputs.m2_growth_yoy = round(float((s.iloc[-1] / s.iloc[-13] - 1) * 100), 2)
                print(f"    m2_growth_yoy={inputs.m2_growth_yoy:.1f}%")
        except Exception:
            pass


# ── Layer 2: Credit ───────────────────────────────────────────────────────────

def _fetch_credit(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching credit & stress data...")

    # HY spreads (BAMLH0A0HYM2 = ICE BofA HY OAS in %)
    hy = _fred("BAMLH0A0HYM2", asof_date=asof_date)
    if not hy.empty:
        hy_bps = hy * 100  # convert % to bps
        inputs.hy_spread_level = _safe_last(hy_bps)
        inputs.hy_spread_z = _z_score(hy_bps, window=504)  # 2yr

        # 4-week change
        try:
            s = hy_bps.dropna()
            if len(s) >= 20:
                inputs.hy_spread_chg_4w = float(s.iloc[-1] - s.iloc[-20])
        except Exception:
            pass
        print(f"    hy_spread={inputs.hy_spread_level}bps  z={inputs.hy_spread_z}  chg4w={inputs.hy_spread_chg_4w}")

    # IG spreads (BAMLC0A0CM = ICE BofA IG OAS in %)
    ig = _fred("BAMLC0A0CM", asof_date=asof_date)
    if not ig.empty:
        ig_bps = ig * 100
        inputs.ig_spread_level = _safe_last(ig_bps)
        inputs.ig_spread_z = _z_score(ig_bps, window=504)
        print(f"    ig_spread={inputs.ig_spread_level}bps  z={inputs.ig_spread_z}")

    # HYG/TLT ratio z-score via yfinance
    hyg = _yf_close("HYG", asof_date=asof_date)
    tlt = _yf_close("TLT", asof_date=asof_date)
    if not hyg.empty and not tlt.empty:
        try:
            ratio = (hyg / tlt).dropna()
            inputs.hyg_tlt_ratio_z = _z_score(ratio, window=252)
            print(f"    hyg_tlt_ratio_z={inputs.hyg_tlt_ratio_z}")
        except Exception:
            pass


# ── Layer 3: Volatility ───────────────────────────────────────────────────────

def _fetch_volatility(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching volatility structure data...")

    vix   = _yf_close("^VIX",  period="1y", asof_date=asof_date)
    vix3m = _yf_close("^VIX3M", period="1y", asof_date=asof_date)
    vvix  = _yf_close("^VVIX", period="1y", asof_date=asof_date)
    skew  = _yf_close("^SKEW", period="1y", asof_date=asof_date)

    if not vix.empty:
        inputs.vix_level = _safe_last(vix)
        inputs.vix_z_20d = _z_score(vix, window=20)
        print(f"    vix={inputs.vix_level}  z={inputs.vix_z_20d}")

    if not vix.empty and not vix3m.empty:
        try:
            aligned = pd.concat([vix, vix3m], axis=1).dropna()
            aligned.columns = ["vix", "vix3m"]
            slope = aligned["vix3m"] - aligned["vix"]
            inputs.vix_term_slope = _safe_last(slope)
            print(f"    vix_term_slope={inputs.vix_term_slope} (VIX3M-VIX)")
        except Exception:
            pass

    if not vvix.empty:
        inputs.vvix_level = _safe_last(vvix)
        inputs.vvix_z = _z_score(vvix, window=252)
        print(f"    vvix={inputs.vvix_level}  z={inputs.vvix_z}")

    if not skew.empty:
        inputs.skew_index = _safe_last(skew)
        print(f"    skew={inputs.skew_index}")


# ── Layer 4: Breadth ──────────────────────────────────────────────────────────

def _fetch_breadth(
    inputs: RegimeInputs,
    sectors_green: Optional[int] = None,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching breadth & participation data...")

    if sectors_green is None:
        try:
            sectors_green = calculate_sectors_green(asof_date=asof_date)
            label = "historical" if asof_date is not None else "fallback"
            print(f"    sectors_green ({label})={sectors_green}/11")
        except Exception as e:
            print(f"    sectors_green compute failed: {e}")

    inputs.sectors_green = sectors_green

    # RSP vs SPY ratio z-score
    try:
        inputs.rsp_vs_spy_z = calculate_rsp_vs_spy_z(asof_date=asof_date)
        if inputs.rsp_vs_spy_z is not None:
            print(f"    rsp_vs_spy_z={inputs.rsp_vs_spy_z}")
    except Exception as e:
        print(f"    rsp_vs_spy_z compute failed: {e}")

    history_result: Optional[ConstituentHistoryResult] = None
    valid_ma200_count = 0
    valid_ad_count = 0

    # Stock-level breadth from current S&P 500 constituents. This is a live/current
    # data-quality upgrade, not a point-in-time historical membership database.
    try:
        history_result = get_constituent_history("sp500", asof_date=asof_date)
        prices = _constituent_price_matrix(history_result.data)

        breadth_200d = calculate_200d_breadth(prices)
        valid_ma200_count = breadth_200d.valid_count
        if breadth_200d.pct_above_200d is not None:
            inputs.pct_above_200d = round(breadth_200d.pct_above_200d, 1)
        if breadth_200d.avg_dist_from_200d is not None:
            inputs.avg_dist_from_200d = round(breadth_200d.avg_dist_from_200d, 2)

        valid_ad_count = _valid_advance_decline_count(prices)
        adl = calculate_advance_decline_line(prices)
        inputs.adl_slope = calculate_adl_slope(adl, window=20)

        print(
            f"    avg_dist_from_200d={inputs.avg_dist_from_200d}%  "
            f"pct_above_200d={inputs.pct_above_200d}%"
        )
        if inputs.adl_slope is not None:
            print(f"    adl_slope (normalized constituent ADL, 20d)={inputs.adl_slope:+.3f}")
    except Exception as e:
        print(f"    constituent breadth compute failed: {e}")

    if history_result is not None:
        _print_breadth_snapshot(
            inputs,
            history_result,
            valid_ma200_count=valid_ma200_count,
            valid_ad_count=valid_ad_count,
        )


# ── Layer 5: Positioning ──────────────────────────────────────────────────────

def _fetch_cboe_pcr(asof_date: Optional[str] = None) -> Optional[float]:
    """
    Compute a generic SPY-options put/call proxy via yfinance.
    Uses the 3 nearest-dated expirations for liquid volume.
    CBOE's CDN (cdn.cboe.com) enforces Cloudflare and blocks programmatic access;
    SPY options data from yfinance is a proxy, not Cboe's official equity PCR.
    Returns the current-session put/call ratio, or None on failure.
    """
    if asof_date is not None:
        print(
            "    cboe_pcr: skipped for historical backfill "
            "(option chains are point-in-time only)"
        )
        return None

    try:
        import yfinance as yf
        spy = yf.Ticker("SPY")
        expirations = spy.options
        if not expirations:
            print("    cboe_pcr: no SPY options expirations available")
            return None

        total_put_vol  = 0.0
        total_call_vol = 0.0
        used = 0
        for exp in expirations[:3]:
            try:
                chain = spy.option_chain(exp)
                total_call_vol += float(chain.calls["volume"].fillna(0).sum())
                total_put_vol  += float(chain.puts["volume"].fillna(0).sum())
                used += 1
            except Exception:
                continue

        if total_call_vol == 0 or used == 0:
            print("    cboe_pcr: zero call volume or no valid chains")
            return None

        result = total_put_vol / total_call_vol
        print(f"    spy_options_put_call_proxy={result:.3f} ({used} expirations)")
        return result
    except Exception as e:
        print(f"    cboe_pcr: failed — {e}")
        return None


def _fetch_cftc_cot(asof_date: Optional[str] = None) -> Optional[float]:
    """
    Fetch CFTC Commitment of Traders — large speculator net position in S&P 500 futures.
    Source: CFTC public reporting Socrata API, dataset jun7-fc8e (legacy COT).
    Contract: E-MINI S&P 500 (cftc_contract_market_code = 13874A).
    Returns z-score vs 2-year rolling window, or None on failure.
    Updates weekly (released every Friday for prior Tuesday data).
    """
    try:
        url = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
        where = "cftc_contract_market_code='13874A'"
        if asof_date is not None:
            where += f" AND report_date_as_yyyy_mm_dd <= '{asof_date}'"
        params = {
            "$where": where,
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "120",
        }
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()

        records = resp.json()
        if not isinstance(records, list) or not records:
            print(f"    cftc_cot: unexpected response ({type(records).__name__}, len={len(records) if isinstance(records, list) else '?'})")
            return None

        rows = []
        for rec in records:
            try:
                date_str  = rec.get("report_date_as_yyyy_mm_dd")
                long_pos  = rec.get("noncomm_positions_long_all")
                short_pos = rec.get("noncomm_positions_short_all")
                if not date_str or long_pos is None or short_pos is None:
                    continue
                date = pd.to_datetime(date_str, utc=True)
                net  = float(long_pos) - float(short_pos)
                rows.append({"date": date, "net": net})
            except Exception:
                continue

        if len(rows) < 20:
            print(f"    cftc_cot: too few valid rows ({len(rows)})")
            return None

        df_cot = (
            pd.DataFrame(rows)
            .sort_values("date")
            .reset_index(drop=True)
        )
        net_series = df_cot.set_index("date")["net"]

        # z-score vs ~2-year rolling window (weekly COT: 104 observations ≈ 2 years)
        z = _z_score(net_series, window=104)
        if z is None:
            print("    cftc_cot: z-score computation failed (insufficient history)")
            return None

        print(f"    cftc_cot_large_spec_z={z:.3f} (COT data, weekly)")
        return z
    except Exception as e:
        print(f"    cftc_cot: failed — {e}")
        return None


def _fetch_positioning(
    inputs: RegimeInputs,
    asof_date: Optional[str] = None,
) -> None:
    print("  Fetching positioning & sentiment data...")

    # Put/call ratio proxy from SPY options via yfinance; official Cboe equity/total/index
    # series are intentionally treated as separate inputs by the forecast audit.
    cboe_pcr = _fetch_cboe_pcr(asof_date=asof_date)
    if cboe_pcr is not None:
        inputs.put_call_ratio = cboe_pcr
        inputs.put_call_5d_ma = cboe_pcr
    else:
        print("    cboe_pcr: failed or unavailable for historical date")

    # COT large speculator positioning from CFTC
    cot_z = _fetch_cftc_cot(asof_date=asof_date)
    if cot_z is not None:
        inputs.cot_net_large_spec_z = cot_z
    else:
        print("    cftc_cot: failed — skipping")

    # AAII sentiment (weekly, point-in-time correct via local XLS lookup)
    try:
        from src.state.sentiment_data import get_aaii_asof

        aaii_value = get_aaii_asof(asof_date=asof_date)
        if aaii_value is not None:
            inputs.aaii_bull_minus_bear = aaii_value
            print(f"    aaii_bull_minus_bear={aaii_value:+.1f}pp")
        else:
            print("    aaii_bull_minus_bear: no reading available on or before asof")
    except Exception as e:
        print(f"    aaii_bull_minus_bear: failed — {e}")

    print("    dealer_gamma: requires SpotGamma API — skipping")

    populated = sum(
        1
        for v in [
            inputs.put_call_ratio,
            inputs.cot_net_large_spec_z,
            inputs.aaii_bull_minus_bear,
        ]
        if v is not None
    )
    print(f"    Positioning inputs populated: {populated}/3")


# ── Main fetch function ───────────────────────────────────────────────────────

def fetch_regime_inputs(
    sectors_green: Optional[int] = None,
    asof_date: Optional[str] = None,
) -> RegimeInputs:
    """
    Fetch all regime inputs from FRED and yfinance.
    Call this ONCE at market close.

    Args:
        sectors_green: Pass from your existing market_state build
        asof_date: Override date string (defaults to today)

    Returns:
        RegimeInputs with all available data populated
    """
    inputs = RegimeInputs(
        asof_date=asof_date or datetime.utcnow().strftime("%Y-%m-%d")
    )

    print(f"\nFetching regime inputs for {inputs.asof_date}...")

    try:
        _fetch_monetary(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Monetary fetch error: {e}")

    try:
        _fetch_credit(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Credit fetch error: {e}")

    try:
        _fetch_volatility(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Volatility fetch error: {e}")

    try:
        _fetch_breadth(inputs, sectors_green=sectors_green, asof_date=asof_date)
    except Exception as e:
        print(f"  Breadth fetch error: {e}")

    try:
        _fetch_positioning(inputs, asof_date=asof_date)
    except Exception as e:
        print(f"  Positioning fetch error: {e}")

    print(f"Done. Fields populated: {sum(1 for v in asdict(inputs).values() if v is not None)}/{len(asdict(inputs))}")
    return inputs
