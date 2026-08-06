"""Theme basket return pricer backed by cached adjusted close histories."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.agent_system.paths import price_history_cache_dir, reference_data_dir

logger = logging.getLogger(__name__)

RISK_FREE_63D_RETURN = 0.0025
RISK_FREE_VOLATILITY = 0.005
CACHE_MAX_AGE_DAYS = 7


class ThemeBasketPricer:
    def __init__(
        self,
        theme_exposure_matrix_path: str | None = None,
        cache_dir: str | None = None,
    ):
        self.theme_exposure_matrix_path = Path(theme_exposure_matrix_path) if theme_exposure_matrix_path else (
            reference_data_dir(create=False) / "theme_exposure_matrix.json"
        )
        self.cache_dir = Path(cache_dir) if cache_dir else price_history_cache_dir(create=False)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.theme_matrix = self._load_theme_exposure_matrix()
        self.theme_exposure_matrix = self.theme_matrix

    def get_basket_return(
        self,
        theme: str,
        asof_date: str,
        horizon_days: int = 63,
    ) -> dict:
        """Returns {'basket_return': float, 'n_tickers_used': int, 'tickers_missing_data': list[str], 'tickers_used': list[str]}"""
        if self._normalize_theme(theme) == "cash_short_duration":
            return {
                "basket_return": self._risk_free_return(horizon_days),
                "n_tickers_used": 1,
                "tickers_missing_data": [],
                "tickers_used": ["cash_short_duration"],
            }

        tickers = self._theme_tickers(theme)
        tickers_used: list[str] = []
        tickers_missing_data: list[str] = []
        returns: list[float] = []

        for ticker in tickers:
            try:
                prices = self._get_ticker_prices(ticker)
            except Exception as exc:
                logger.warning("Failed to load prices for %s: %s", ticker, exc)
                tickers_missing_data.append(ticker)
                continue

            price_now = self._price_on_or_after(prices, asof_date)
            future_date = self._add_days(asof_date, horizon_days)
            price_future = self._price_on_or_after(prices, future_date)
            if price_now is None or price_future is None or price_now <= 0:
                tickers_missing_data.append(ticker)
                continue

            returns.append((price_future / price_now) - 1.0)
            tickers_used.append(ticker)

        basket_return = float(np.mean(returns)) if returns else None
        return {
            "basket_return": basket_return,
            "n_tickers_used": len(tickers_used),
            "tickers_missing_data": tickers_missing_data,
            "tickers_used": tickers_used,
        }

    def get_basket_distribution(
        self,
        theme: str,
        dates: list[str],
        horizon_days: int = 63,
    ) -> dict:
        """Returns {'mean': float, 'median': float, 'volatility': float, 'p10': float, 'p25': float, 'p75': float, 'p90': float, 'n_dates': int, 'n_dates_with_data': int}"""
        if self._normalize_theme(theme) == "cash_short_duration":
            value = self._risk_free_return(horizon_days)
            return {
                "mean": value,
                "median": value,
                "volatility": RISK_FREE_VOLATILITY,
                "p10": value,
                "p25": value,
                "p75": value,
                "p90": value,
                "n_dates": len(dates),
                "n_dates_with_data": len(dates),
            }

        returns: list[float] = []
        for date in dates:
            result = self.get_basket_return(theme, date, horizon_days=horizon_days)
            value = result.get("basket_return")
            if value is not None:
                returns.append(float(value))

        if not returns:
            return {
                "mean": None,
                "median": None,
                "volatility": None,
                "p10": None,
                "p25": None,
                "p75": None,
                "p90": None,
                "n_dates": len(dates),
                "n_dates_with_data": 0,
            }

        values = np.array(returns, dtype=float)
        return {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "volatility": float(np.std(values)),
            "p10": float(np.percentile(values, 10)),
            "p25": float(np.percentile(values, 25)),
            "p75": float(np.percentile(values, 75)),
            "p90": float(np.percentile(values, 90)),
            "n_dates": len(dates),
            "n_dates_with_data": len(returns),
        }

    def prefetch_universe(
        self,
        tickers: list[str],
        start_date: str = "2000-01-01",
    ) -> dict:
        """Bulk fetch prices for a list of tickers. Returns {'fetched': int, 'failed': list[str], 'cached': int}."""
        fetched = 0
        cached = 0
        failed: list[str] = []
        for ticker in tickers:
            cache_path = self._cache_path(ticker)
            was_cached = self._is_cache_fresh(cache_path)
            try:
                if was_cached:
                    self._get_ticker_prices(ticker)
                    cached += 1
                else:
                    self._fetch_and_cache_ticker_prices(ticker, start_date=start_date)
                    fetched += 1
            except Exception as exc:
                logger.warning("Failed to prefetch %s: %s", ticker, exc)
                failed.append(ticker)
        return {"fetched": fetched, "failed": failed, "cached": cached}

    def _get_ticker_prices(self, ticker: str) -> dict[str, float]:
        """Internal: load from cache, fetch from yfinance if missing or stale."""
        cache_path = self._cache_path(ticker)
        if self._is_cache_fresh(cache_path):
            cached = self._load_cache(cache_path)
            prices = cached.get("prices", {})
            if isinstance(prices, dict):
                return {str(k): float(v) for k, v in prices.items() if isinstance(v, (int, float))}

        return self._fetch_and_cache_ticker_prices(ticker, start_date="2000-01-01")

    def _load_theme_exposure_matrix(self) -> dict[str, Any]:
        if not self.theme_exposure_matrix_path.exists():
            logger.warning("Theme exposure matrix not found at %s", self.theme_exposure_matrix_path)
            return {}
        with self.theme_exposure_matrix_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError(f"Theme exposure matrix must contain a JSON object: {self.theme_exposure_matrix_path}")
        if isinstance(raw.get("themes"), dict):
            return dict(raw["themes"])
        if "themes" not in raw:
            return {str(key): value for key, value in raw.items() if key != "metadata"}
        return {}

    def _theme_tickers(self, theme: str) -> list[str]:
        theme_key = self._normalize_theme(theme)
        matrix = self.theme_matrix

        basket = matrix.get(theme_key)
        if basket is None:
            for key, value in matrix.items():
                if self._normalize_theme(str(key)) == theme_key:
                    basket = value
                    break

        if not isinstance(basket, dict):
            return []
        return sorted(str(ticker).upper() for ticker in basket)

    def _fetch_and_cache_ticker_prices(self, ticker: str, *, start_date: str) -> dict[str, float]:
        import yfinance as yf

        normalized = ticker.strip().upper()
        history = yf.Ticker(normalized).history(start=start_date, auto_adjust=True)
        if history is None or history.empty or "Close" not in history.columns:
            raise ValueError(f"yfinance returned no close history for {normalized}")

        close = history["Close"].dropna()
        prices = {
            idx.date().isoformat(): float(value)
            for idx, value in close.items()
            if value is not None and np.isfinite(float(value))
        }
        if not prices:
            raise ValueError(f"yfinance returned empty close history for {normalized}")

        payload = {
            "ticker": normalized,
            "last_fetched": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "first_date": min(prices),
            "last_date": max(prices),
            "prices": prices,
        }
        self._cache_path(normalized).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return prices

    def _cache_path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker.strip().upper()}.json"

    def _load_cache(self, cache_path: Path) -> dict[str, Any]:
        with cache_path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError(f"Price cache must contain a JSON object: {cache_path}")
        return payload

    def _is_cache_fresh(self, cache_path: Path) -> bool:
        if not cache_path.exists():
            return False
        try:
            payload = self._load_cache(cache_path)
            fetched_at = self._parse_utc(payload.get("last_fetched"))
        except Exception:
            return False
        return datetime.now(timezone.utc) - fetched_at < timedelta(days=CACHE_MAX_AGE_DAYS)

    def _price_on_or_after(self, prices: dict[str, float], date_text: str) -> float | None:
        target = datetime.fromisoformat(date_text).date()
        for key in sorted(prices):
            if datetime.fromisoformat(key).date() >= target:
                value = prices.get(key)
                return float(value) if value is not None else None
        return None

    def _risk_free_return(self, horizon_days: int) -> float:
        return RISK_FREE_63D_RETURN * (float(horizon_days) / 63.0)

    def _add_days(self, date_text: str, days: int) -> str:
        return (datetime.fromisoformat(date_text).date() + timedelta(days=int(days))).isoformat()

    def _parse_utc(self, value: Any) -> datetime:
        if not isinstance(value, str) or not value:
            raise ValueError("missing cache timestamp")
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _normalize_theme(self, theme: str) -> str:
        return theme.strip().lower().replace(" ", "_").replace("-", "_")
