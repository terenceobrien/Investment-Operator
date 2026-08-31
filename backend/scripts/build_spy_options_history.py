#!/usr/bin/env python3
"""Build a lightweight historical SPY put-options panel from Massive.

The output uses actual Massive daily option aggregate bars. It does not
synthesize option prices, forward-fill missing option dates, or calculate
Greeks/IV. DTE is calendar days: expiration_date - aggregate_date.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_PATH = REPO_ROOT / "backend" / "data" / "options" / "spy_options_history.parquet"
UNDERLYING = "SPY"
OPTION_TYPE = "put"
# 729 days back gives a 730-calendar-date inclusive window, which fits plans
# that enforce "2 years" as a hard aggregate-data boundary.
DEFAULT_LOOKBACK_DAYS = 729
MAX_DTE = 120
MIN_MONEYNESS = 0.50
MAX_MONEYNESS = 1.10
TARGET_ENTRY_DTES = (30, 45)
TARGET_SHORT_MONEYNESS = (0.85, 0.90, 0.95)
SPREAD_WING_DOLLARS = 5.0
REFERENCE_STRIKE_CUSHION = 2.5
CHECKPOINT_CONTRACTS = 25
CHECKPOINT_NEW_ROWS = 25_000
MASSIVE_BASE_URL = "https://api.massive.com"
API_KEY_ENV_CANDIDATES = ("MASSIVE_API_KEY", "POLYGON_API_KEY")

FINAL_COLUMNS = [
    "date",
    "option_ticker",
    "underlying",
    "expiration",
    "strike",
    "option_type",
    "dte",
    "underlying_close",
    "moneyness",
    "option_open",
    "option_high",
    "option_low",
    "option_close",
    "option_volume",
]


class BuildError(RuntimeError):
    """Raised when the dataset cannot be built or validated."""


class MassiveAPIError(BuildError):
    """Raised for sanitized Massive API errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OptionContract:
    option_ticker: str
    underlying: str
    expiration: date
    strike: float
    option_type: str


class MassiveClient:
    """Tiny Massive REST client with retry/backoff and basic metrics."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = MASSIVE_BASE_URL,
        timeout: float = 30.0,
        max_attempts: int = 6,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = requests.Session()
        self.request_count = 0
        self.rate_limit_events = 0
        self.retry_events = 0
        self.total_wait_seconds = 0.0
        self.min_interval_seconds = parse_float_env("MASSIVE_MIN_REQUEST_INTERVAL_SECONDS", 0.0)
        self._last_request_at: float | None = None

    def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        url = path_or_url
        if url.startswith("http://") or url.startswith("https://"):
            if "apiKey=" not in url and "apiKey" not in request_params:
                request_params["apiKey"] = self.api_key
        else:
            url = f"{self.base_url}/{path_or_url.lstrip('/')}"
            request_params["apiKey"] = self.api_key

        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            self.request_count += 1
            try:
                response = self.session.get(url, params=request_params, timeout=self.timeout)
                self._last_request_at = time.monotonic()
                if response.status_code == 429:
                    self.rate_limit_events += 1
                    self.min_interval_seconds = max(self.min_interval_seconds, 12.0)
                    wait = self._retry_wait(response, attempt)
                    self._sleep(wait, "rate limit")
                    continue
                if response.status_code in {408, 409, 425, 500, 502, 503, 504}:
                    self.retry_events += 1
                    wait = self._retry_wait(response, attempt)
                    self._sleep(wait, f"temporary HTTP {response.status_code}")
                    continue
                if response.status_code >= 400:
                    raise MassiveAPIError(
                        self._format_http_error(response),
                        status_code=response.status_code,
                    )
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                self.retry_events += 1
                wait = self._retry_wait(None, attempt)
                self._sleep(wait, f"network retry: {exc.__class__.__name__}")
            except ValueError as exc:
                    raise MassiveAPIError("Massive returned a non-JSON response") from exc

        raise MassiveAPIError(
            f"Massive request failed after {self.max_attempts} attempts: {last_error}"
        ) from last_error

    def iter_results(
        self, path: str, params: dict[str, Any] | None = None
    ) -> Iterable[dict[str, Any]]:
        next_url: str | None = path
        next_params: dict[str, Any] | None = dict(params or {})
        while next_url:
            payload = self.get(next_url, next_params)
            for item in payload.get("results") or []:
                yield item
            next_url = payload.get("next_url")
            next_params = None

    def _retry_wait(self, response: requests.Response | None, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        if retry_after:
            try:
                return min(120.0, max(1.0, float(retry_after)))
            except ValueError:
                pass
        backoff = min(120.0, 2.0**attempt)
        return backoff + random.uniform(0.0, 1.0)

    def _sleep(self, wait_seconds: float, reason: str) -> None:
        self.total_wait_seconds += wait_seconds
        print(f"Massive wait: {wait_seconds:.1f}s ({reason})", flush=True)
        time.sleep(wait_seconds)

    def _throttle(self) -> None:
        if self.min_interval_seconds <= 0 or self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        wait_seconds = self.min_interval_seconds - elapsed
        if wait_seconds > 0:
            self._sleep(wait_seconds, "client throttle")

    @staticmethod
    def _format_http_error(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = (
            payload.get("error")
            or payload.get("message")
            or payload.get("status")
            or response.text[:300]
        )
        return f"Massive HTTP {response.status_code}: {message}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build backend/data/options/spy_options_history.parquet from Massive."
    )
    parser.add_argument("--start-date", help="Inclusive start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Inclusive end date, YYYY-MM-DD.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore any existing Parquet and rebuild the requested window.",
    )
    return parser.parse_args()


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    for env_path in (REPO_ROOT / ".env", REPO_ROOT / ".env.local"):
        if env_path.exists():
            load_dotenv(env_path, override=False)


def get_api_key() -> tuple[str, str]:
    load_dotenv_files()
    for env_name in API_KEY_ENV_CANDIDATES:
        value = os.getenv(env_name)
        if value:
            return env_name, value
    raise BuildError("Missing Massive API key. Set MASSIVE_API_KEY in the environment.")


def parse_float_env(env_name: str, default: float) -> float:
    raw = os.getenv(env_name)
    if not raw:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError as exc:
        raise BuildError(f"{env_name} must be numeric if set") from exc


def parse_date(value: str, *, label: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BuildError(f"{label} must use YYYY-MM-DD format: {value}") from exc


def resolve_window(args: argparse.Namespace) -> tuple[date, date]:
    end = parse_date(args.end_date, label="--end-date") if args.end_date else date.today()
    start = (
        parse_date(args.start_date, label="--start-date")
        if args.start_date
        else end - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )
    if start > end:
        raise BuildError(f"start date {start} is after end date {end}")
    return start, end


def normalize_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.date


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temporary, index=False)
    os.replace(temporary, path)


def normalize_dataset(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=FINAL_COLUMNS)

    result = frame.copy()
    result["date"] = normalize_date_series(result["date"])
    result["expiration"] = normalize_date_series(result["expiration"])
    result["option_ticker"] = result["option_ticker"].astype(str)
    result["underlying"] = result["underlying"].astype(str).str.upper()
    result["option_type"] = result["option_type"].astype(str).str.lower()

    numeric_columns = [
        "strike",
        "dte",
        "underlying_close",
        "moneyness",
        "option_open",
        "option_high",
        "option_low",
        "option_close",
        "option_volume",
    ]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result = result.dropna(subset=["date", "expiration", "option_ticker"])
    result["dte"] = result["dte"].round().astype("Int64")
    result = result[FINAL_COLUMNS]
    result = result.drop_duplicates(["date", "option_ticker"], keep="last")
    result = result.sort_values(["date", "expiration", "strike", "option_ticker"])
    return result.reset_index(drop=True)


def load_existing_dataset(path: Path, *, refresh: bool) -> pd.DataFrame:
    if refresh or not path.exists():
        return pd.DataFrame(columns=FINAL_COLUMNS)
    existing = pd.read_parquet(path)
    missing = [column for column in FINAL_COLUMNS if column not in existing.columns]
    if missing:
        raise BuildError(f"Existing dataset is missing columns: {missing}")
    return normalize_dataset(existing[FINAL_COLUMNS])


def extract_close_column(download: pd.DataFrame) -> pd.Series:
    if download is None or download.empty:
        return pd.Series(dtype=float)
    if isinstance(download.columns, pd.MultiIndex):
        if ("Close", UNDERLYING) in download.columns:
            return download[("Close", UNDERLYING)]
        if (UNDERLYING, "Close") in download.columns:
            return download[(UNDERLYING, "Close")]
        close = download.xs("Close", axis=1, level=-1, drop_level=False)
        return close.iloc[:, 0]
    if "Close" not in download.columns:
        return pd.Series(dtype=float)
    return download["Close"]


def download_spy_closes(start: date, end: date, *, attempts: int = 3) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise BuildError("yfinance is required for SPY adjusted closes") from exc

    last_error: Exception | None = None
    # yfinance end is exclusive, while this script's CLI end date is inclusive.
    yf_end = end + timedelta(days=1)
    for attempt in range(1, attempts + 1):
        try:
            raw = yf.download(
                UNDERLYING,
                start=start.isoformat(),
                end=yf_end.isoformat(),
                auto_adjust=True,
                actions=False,
                progress=False,
                threads=False,
            )
            close = pd.to_numeric(extract_close_column(raw), errors="coerce").dropna()
            if close.empty:
                raise BuildError("yfinance returned no usable SPY closes")
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(close.index, errors="coerce").date,
                    "underlying_close": close.astype(float).to_numpy(),
                }
            )
            frame = frame.dropna(subset=["date", "underlying_close"])
            frame = frame.drop_duplicates("date", keep="last").sort_values("date")
            if frame.empty:
                raise BuildError("SPY close frame is empty after normalization")
            return frame.reset_index(drop=True)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                wait = float(attempt)
                print(f"yfinance wait: {wait:.1f}s (retry {attempt}/{attempts})", flush=True)
                time.sleep(wait)
    raise BuildError(f"SPY close download failed after {attempts} attempts: {last_error}") from last_error


def add_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def standard_monthly_expirations(start: date, end: date) -> list[date]:
    expirations: list[date] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        fifteenth = date(cursor.year, cursor.month, 15)
        third_friday = fifteenth + timedelta(days=(4 - fifteenth.weekday()) % 7)
        if start <= third_friday <= end:
            expirations.append(third_friday)
        cursor = add_month(cursor)
    return expirations


def closest_entry_rows(expiration: date, spy_closes: pd.DataFrame) -> list[pd.Series]:
    candidates = spy_closes.copy()
    candidates["dte"] = (
        pd.to_datetime(expiration) - pd.to_datetime(candidates["date"])
    ).dt.days
    candidates = candidates.loc[candidates["dte"].between(21, 60)].copy()
    if candidates.empty:
        return []

    rows: list[pd.Series] = []
    used_dates: set[date] = set()
    for target_dte in TARGET_ENTRY_DTES:
        candidates["distance"] = (candidates["dte"] - target_dte).abs()
        closest = candidates.sort_values(["distance", "date"]).iloc[0]
        if closest["date"] in used_dates:
            continue
        rows.append(closest)
        used_dates.add(closest["date"])
    return rows


def reference_strike_range(entry_rows: list[pd.Series]) -> tuple[float, float]:
    targets: list[float] = []
    for row in entry_rows:
        close = float(row["underlying_close"])
        for moneyness in TARGET_SHORT_MONEYNESS:
            targets.append(close * moneyness)
            targets.append(close * moneyness - SPREAD_WING_DOLLARS)
    if not targets:
        raise BuildError("Cannot build a reference strike range without entry rows")
    return (
        max(0.01, min(targets) - REFERENCE_STRIKE_CUSHION),
        max(targets) + REFERENCE_STRIKE_CUSHION,
    )


def parse_contract_metadata(item: dict[str, Any]) -> OptionContract:
    try:
        ticker = str(item["ticker"])
        underlying = str(item.get("underlying_ticker", "")).upper()
        contract_type = str(item.get("contract_type", "")).lower()
        expiration = parse_date(str(item["expiration_date"]), label="expiration_date")
        strike = float(item["strike_price"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildError(f"Malformed Massive contract metadata: {item}") from exc

    return OptionContract(
        option_ticker=ticker,
        underlying=underlying,
        expiration=expiration,
        strike=strike,
        option_type=contract_type,
    )


def query_contracts_for_expiration(
    client: MassiveClient,
    *,
    expiration: date,
    min_strike: float,
    max_strike: float,
) -> list[OptionContract]:
    seen: set[str] = set()
    contracts: list[OptionContract] = []
    for expired in ("true", "false"):
        params = {
            "underlying_ticker": UNDERLYING,
            "contract_type": OPTION_TYPE,
            "expiration_date": expiration.isoformat(),
            "strike_price.gte": round(min_strike, 2),
            "strike_price.lte": round(max_strike, 2),
            "expired": expired,
            "order": "asc",
            "limit": 1000,
            "sort": "strike_price",
        }
        for item in client.iter_results("/v3/reference/options/contracts", params):
            contract = parse_contract_metadata(item)
            if contract.option_ticker in seen:
                continue
            if contract.underlying != UNDERLYING or contract.option_type != OPTION_TYPE:
                continue
            if contract.expiration != expiration or contract.strike <= 0:
                continue
            contracts.append(contract)
            seen.add(contract.option_ticker)
    contracts.sort(key=lambda c: (c.strike, c.option_ticker))
    return contracts


def nearest_contract(
    contracts: list[OptionContract],
    target_strike: float,
    *,
    max_strike: float | None = None,
) -> OptionContract | None:
    candidates = [
        contract
        for contract in contracts
        if max_strike is None or contract.strike < max_strike
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (abs(c.strike - target_strike), c.strike))


def discover_contracts(
    client: MassiveClient,
    *,
    start: date,
    end: date,
    spy_closes: pd.DataFrame,
) -> list[OptionContract]:
    expiration_end = end + timedelta(days=max(TARGET_ENTRY_DTES) + 7)
    expirations = standard_monthly_expirations(start, expiration_end)
    print(f"Monthly expirations considered: {len(expirations):,}")

    selected: dict[str, OptionContract] = {}
    for expiration in expirations:
        entry_rows = closest_entry_rows(expiration, spy_closes)
        if not entry_rows:
            continue
        min_strike, max_strike = reference_strike_range(entry_rows)
        candidates = query_contracts_for_expiration(
            client,
            expiration=expiration,
            min_strike=min_strike,
            max_strike=max_strike,
        )
        if not candidates:
            continue
        for entry_row in entry_rows:
            underlying_close = float(entry_row["underlying_close"])
            for moneyness in TARGET_SHORT_MONEYNESS:
                short_target = underlying_close * moneyness
                short_contract = nearest_contract(candidates, short_target)
                if short_contract is None:
                    continue
                selected[short_contract.option_ticker] = short_contract

                wing_target = short_contract.strike - SPREAD_WING_DOLLARS
                wing_contract = nearest_contract(
                    candidates,
                    wing_target,
                    max_strike=short_contract.strike,
                )
                if wing_contract is not None:
                    selected[wing_contract.option_ticker] = wing_contract

    contracts = sorted(
        selected.values(),
        key=lambda c: (c.expiration, c.strike, c.option_ticker),
    )
    return contracts


def existing_date_bounds(existing: pd.DataFrame) -> dict[str, tuple[date, date]]:
    if existing.empty:
        return {}
    grouped = existing.groupby("option_ticker")["date"].agg(["min", "max"])
    return {
        str(ticker): (bounds["min"], bounds["max"])
        for ticker, bounds in grouped.iterrows()
        if pd.notna(bounds["min"]) and pd.notna(bounds["max"])
    }


def existing_key_set(existing: pd.DataFrame) -> set[tuple[date, str]]:
    if existing.empty:
        return set()
    return set(zip(existing["date"], existing["option_ticker"], strict=False))


def missing_windows_for_contract(
    contract: OptionContract,
    *,
    start: date,
    end: date,
    bounds: dict[str, tuple[date, date]],
    latest_saved_date: date | None,
) -> list[tuple[date, date]]:
    fetch_start = max(start, contract.expiration - timedelta(days=MAX_DTE))
    fetch_end = min(end, contract.expiration)
    if fetch_start > fetch_end:
        return []

    existing_bounds = bounds.get(contract.option_ticker)
    if existing_bounds is None:
        return [(fetch_start, fetch_end)]

    if latest_saved_date is not None and fetch_end <= latest_saved_date:
        return []

    _existing_min, existing_max = existing_bounds
    # Without a sidecar manifest, a leading gap is indistinguishable from dates
    # where the option simply did not trade. Resume by extending forward only.
    windows: list[tuple[date, date]] = []
    if existing_max < fetch_end:
        windows.append((max(fetch_start, existing_max + timedelta(days=1)), fetch_end))
    return [(window_start, window_end) for window_start, window_end in windows if window_start <= window_end]


def aggregate_bars_to_frame(
    payload: dict[str, Any],
    contract: OptionContract,
    spy_closes: pd.DataFrame,
    existing_keys: set[tuple[date, str]],
) -> pd.DataFrame:
    bars = payload.get("results") or []
    if not bars:
        return pd.DataFrame(columns=FINAL_COLUMNS)

    rows: list[dict[str, Any]] = []
    for bar in bars:
        timestamp_ms = bar.get("t")
        if timestamp_ms is None:
            continue
        bar_date = (
            pd.to_datetime(timestamp_ms, unit="ms", utc=True)
            .tz_convert("America/New_York")
            .date()
        )
        if (bar_date, contract.option_ticker) in existing_keys:
            continue
        rows.append(
            {
                "date": bar_date,
                "option_ticker": contract.option_ticker,
                "underlying": contract.underlying,
                "expiration": contract.expiration,
                "strike": contract.strike,
                "option_type": contract.option_type,
                "option_open": bar.get("o"),
                "option_high": bar.get("h"),
                "option_low": bar.get("l"),
                "option_close": bar.get("c"),
                "option_volume": bar.get("v"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=FINAL_COLUMNS)

    frame = pd.DataFrame(rows)
    frame["date"] = normalize_date_series(frame["date"])
    frame["expiration"] = normalize_date_series(frame["expiration"])
    frame = frame.merge(spy_closes, on="date", how="left")
    frame["dte"] = (
        pd.to_datetime(frame["expiration"]) - pd.to_datetime(frame["date"])
    ).dt.days
    frame["moneyness"] = frame["strike"] / frame["underlying_close"]

    for column in [
        "strike",
        "dte",
        "underlying_close",
        "moneyness",
        "option_open",
        "option_high",
        "option_low",
        "option_close",
        "option_volume",
    ]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    ohlc_columns = ["option_open", "option_high", "option_low", "option_close"]
    has_no_price_data = frame[ohlc_columns].isna().all(axis=1) & frame["option_volume"].isna()
    frame = frame.loc[~has_no_price_data]
    frame = frame.dropna(subset=["underlying_close", "dte", *ohlc_columns])
    frame = frame.loc[
        (frame["option_type"] == OPTION_TYPE)
        & (frame["dte"] >= 0)
        & (frame["dte"] <= MAX_DTE)
        & (frame["underlying_close"] > 0)
        & (frame["strike"] > 0)
        & (frame["moneyness"] >= MIN_MONEYNESS)
        & (frame["moneyness"] <= MAX_MONEYNESS)
        & (frame[ohlc_columns] > 0).all(axis=1)
        & (frame["option_low"] <= frame["option_high"])
    ]

    return normalize_dataset(frame)


def fetch_contract_bars(
    client: MassiveClient,
    contract: OptionContract,
    *,
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    encoded_ticker = quote(contract.option_ticker, safe="")
    path = (
        f"/v2/aggs/ticker/{encoded_ticker}/range/1/day/"
        f"{window_start.isoformat()}/{window_end.isoformat()}"
    )
    return client.get(
        path,
        {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
        },
    )


def is_timeframe_plan_error(exc: MassiveAPIError) -> bool:
    return exc.status_code == 403 and "timeframe" in str(exc).lower()


def combine_frames(existing: pd.DataFrame, new_chunks: list[pd.DataFrame]) -> pd.DataFrame:
    frames = [frame for frame in [existing, *new_chunks] if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=FINAL_COLUMNS)
    return normalize_dataset(pd.concat(frames, ignore_index=True))


def print_progress(
    *,
    processed: int,
    total: int,
    current_rows: int,
    new_rows_since_start: int,
    client: MassiveClient,
) -> None:
    remaining = max(0, total - processed)
    print(
        "Progress: "
        f"contracts_processed={processed:,} "
        f"contracts_remaining={remaining:,} "
        f"rows_current_dataset={current_rows:,} "
        f"rows_collected_this_run={new_rows_since_start:,} "
        f"api_requests={client.request_count:,} "
        f"rate_limits={client.rate_limit_events:,} "
        f"retry_wait_seconds={client.total_wait_seconds:.1f}",
        flush=True,
    )


def validate_dataset(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    errors: list[str] = []
    if not path.exists():
        errors.append(f"file does not exist: {path}")
    if frame.empty:
        errors.append("dataset is empty")
    if not frame.empty and frame["option_ticker"].nunique() < 1:
        errors.append("no SPY put contracts found")
    if not frame.empty and frame.duplicated(["date", "option_ticker"]).any():
        errors.append("duplicate date + option_ticker rows found")
    if not frame.empty and not (frame["option_type"] == OPTION_TYPE).all():
        errors.append("non-put option_type rows found")
    if not frame.empty and not (frame["underlying"] == UNDERLYING).all():
        errors.append("non-SPY underlying rows found")
    if not frame.empty and not (pd.to_numeric(frame["strike"], errors="coerce") > 0).all():
        errors.append("strike <= 0 found")
    if not frame.empty and not (pd.to_numeric(frame["dte"], errors="coerce") >= 0).all():
        errors.append("dte < 0 found")
    if not frame.empty and not (pd.to_numeric(frame["underlying_close"], errors="coerce") > 0).all():
        errors.append("underlying_close <= 0 found")

    ohlc_columns = ["option_open", "option_high", "option_low", "option_close"]
    if not frame.empty:
        ohlc = frame[ohlc_columns].apply(pd.to_numeric, errors="coerce")
        if (ohlc < 0).any().any():
            errors.append("negative option OHLC values found")
        if (frame["option_low"] > frame["option_high"]).any():
            errors.append("option_low > option_high found")
        if (pd.to_datetime(frame["expiration"]) < pd.to_datetime(frame["date"])).any():
            errors.append("expiration before date found")

    if errors:
        raise BuildError("Dataset validation failed:\n- " + "\n- ".join(errors))

    file_size = path.stat().st_size if path.exists() else 0
    return {
        "first_date": min(frame["date"]).isoformat(),
        "last_date": max(frame["date"]).isoformat(),
        "total_rows": int(len(frame)),
        "unique_contracts": int(frame["option_ticker"].nunique()),
        "unique_expirations": int(frame["expiration"].nunique()),
        "median_dte": float(pd.to_numeric(frame["dte"], errors="coerce").median()),
        "min_strike": float(pd.to_numeric(frame["strike"], errors="coerce").min()),
        "max_strike": float(pd.to_numeric(frame["strike"], errors="coerce").max()),
        "file_size_bytes": int(file_size),
    }


def print_summary(summary: dict[str, Any], frame: pd.DataFrame, path: Path) -> None:
    print("\nValidation summary")
    print(f"  first date: {summary['first_date']}")
    print(f"  last date: {summary['last_date']}")
    print(f"  total rows: {summary['total_rows']:,}")
    print(f"  unique contracts: {summary['unique_contracts']:,}")
    print(f"  unique expirations: {summary['unique_expirations']:,}")
    print(f"  median DTE: {summary['median_dte']:.1f}")
    print(f"  min/max strike: {summary['min_strike']:.2f} / {summary['max_strike']:.2f}")
    print(f"  file size: {summary['file_size_bytes'] / 1_000_000:.2f} MB")
    print(f"  dataset: {path}")
    print("  DTE convention: calendar days (expiration - date)")

    sample = frame.loc[
        (pd.to_numeric(frame["dte"], errors="coerce").between(30, 45))
        & (pd.to_numeric(frame["moneyness"], errors="coerce").between(0.85, 0.95))
    ].copy()
    if sample.empty:
        print("\nSample 30-45 DTE / 5%-15% OTM puts: none found")
        return

    sample = sample.sort_values(["date", "expiration", "strike"]).head(12)
    display_columns = [
        "date",
        "option_ticker",
        "expiration",
        "strike",
        "dte",
        "underlying_close",
        "moneyness",
        "option_close",
        "option_volume",
    ]
    print("\nSample 30-45 DTE / 5%-15% OTM puts")
    print(sample[display_columns].to_string(index=False))


def run() -> dict[str, Any]:
    args = parse_args()
    start, end = resolve_window(args)
    api_key_env, api_key = get_api_key()
    client = MassiveClient(api_key)

    print(f"Massive API key env var: {api_key_env}")
    print(f"Requested window: {start.isoformat()} through {end.isoformat()} inclusive")
    print(f"Output path: {OUTPUT_PATH}")
    print("DTE convention: calendar days (expiration - date)")

    existing = load_existing_dataset(OUTPUT_PATH, refresh=args.refresh)
    if existing.empty:
        print("Existing dataset: none")
    else:
        print(
            "Existing dataset: "
            f"{len(existing):,} rows, "
            f"{existing['option_ticker'].nunique():,} contracts, "
            f"{min(existing['date'])} through {max(existing['date'])}"
        )

    spy_closes = download_spy_closes(start, end)
    print(
        "SPY closes: "
        f"{len(spy_closes):,} trading days, "
        f"close range ${spy_closes['underlying_close'].min():.2f}-"
        f"${spy_closes['underlying_close'].max():.2f}"
    )
    print(
        "Contract selection: standard monthly expirations, "
        f"entry DTE targets {TARGET_ENTRY_DTES}, "
        f"short moneyness targets {TARGET_SHORT_MONEYNESS}, "
        f"${SPREAD_WING_DOLLARS:.0f} lower put wing"
    )

    contracts = discover_contracts(
        client,
        start=start,
        end=end,
        spy_closes=spy_closes,
    )
    if not contracts:
        raise BuildError("No Massive SPY put contracts matched the requested filters")
    print(f"Contracts selected for aggregate download: {len(contracts):,}")

    bounds = existing_date_bounds(existing)
    existing_keys = existing_key_set(existing)
    latest_saved_date = max(existing["date"]) if not existing.empty else None
    new_chunks: list[pd.DataFrame] = []
    new_rows_since_checkpoint = 0
    new_rows_since_start = 0
    current_rows = len(existing)

    for index, contract in enumerate(contracts, start=1):
        windows = missing_windows_for_contract(
            contract,
            start=start,
            end=end,
            bounds=bounds,
            latest_saved_date=latest_saved_date,
        )
        for window_start, window_end in windows:
            try:
                payload = fetch_contract_bars(
                    client,
                    contract,
                    window_start=window_start,
                    window_end=window_end,
                )
            except MassiveAPIError as exc:
                if not is_timeframe_plan_error(exc) or window_end != end:
                    raise
                fallback_end = window_end - timedelta(days=1)
                if fallback_end < window_start:
                    print(
                        "Skipping unavailable latest Massive timeframe: "
                        f"{contract.option_ticker} {window_start} through {window_end}",
                        flush=True,
                    )
                    continue
                print(
                    "Retrying without unavailable latest Massive timeframe: "
                    f"{contract.option_ticker} {window_start} through {fallback_end}",
                    flush=True,
                )
                payload = fetch_contract_bars(
                    client,
                    contract,
                    window_start=window_start,
                    window_end=fallback_end,
                )
            chunk = aggregate_bars_to_frame(payload, contract, spy_closes, existing_keys)
            if chunk.empty:
                continue

            new_chunks.append(chunk)
            for key in zip(chunk["date"], chunk["option_ticker"], strict=False):
                existing_keys.add(key)
            bounds[contract.option_ticker] = (
                min(bounds.get(contract.option_ticker, (window_start, window_end))[0], window_start),
                max(bounds.get(contract.option_ticker, (window_start, window_end))[1], window_end),
            )
            new_rows = len(chunk)
            new_rows_since_checkpoint += new_rows
            new_rows_since_start += new_rows
            current_rows += new_rows
            chunk_latest = max(chunk["date"])
            latest_saved_date = (
                chunk_latest
                if latest_saved_date is None
                else max(latest_saved_date, chunk_latest)
            )

        if index == 1 or index % 25 == 0 or index == len(contracts):
            print_progress(
                processed=index,
                total=len(contracts),
                current_rows=current_rows,
                new_rows_since_start=new_rows_since_start,
                client=client,
            )

        should_checkpoint = (
            new_chunks
            and (index % CHECKPOINT_CONTRACTS == 0 or new_rows_since_checkpoint >= CHECKPOINT_NEW_ROWS)
        )
        if should_checkpoint:
            existing = combine_frames(existing, new_chunks)
            atomic_write_parquet(existing, OUTPUT_PATH)
            print(f"Checkpoint written: {len(existing):,} rows -> {OUTPUT_PATH}", flush=True)
            new_chunks = []
            new_rows_since_checkpoint = 0
            current_rows = len(existing)
            latest_saved_date = max(existing["date"]) if not existing.empty else None

    final = combine_frames(existing, new_chunks)
    atomic_write_parquet(final, OUTPUT_PATH)
    final = pd.read_parquet(OUTPUT_PATH)
    final = normalize_dataset(final)
    summary = validate_dataset(final, OUTPUT_PATH)
    print_summary(summary, final, OUTPUT_PATH)

    summary.update(
        {
            "api_key_env": api_key_env,
            "massive_requests": client.request_count,
            "rate_limit_events": client.rate_limit_events,
            "retry_events": client.retry_events,
            "total_wait_seconds": client.total_wait_seconds,
        }
    )
    return summary


def main() -> int:
    try:
        run()
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the script to resume from the last checkpoint.", file=sys.stderr)
        return 130
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
