"""Small cache-backed market metadata lookups for exposure enrichment."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal


BetaSource = Literal[
    "yfinance_live",
    "yfinance_cached",
    "damodaran_sector",
    "manual_estimate",
]


YFINANCE_SECTOR_TO_DAMODARAN = {
    "Industrials": "Engineering/Construction",
    "Technology": "Software (System & Application)",
    "Financial Services": "Financial Svcs. (Non-bank & Insur",
    "Utilities": "Utility (General)",
    "Energy": "Oil/Gas (Production and Exploratio",
    "Healthcare": "Healthcare Products",
    "Consumer Cyclical": "Retail (Special Lines)",
    "Consumer Defensive": "Food Processing",
    "Real Estate": "R.E.I.T.",
    "Communication Services": "Telecom. Services",
    "Basic Materials": "Chemical (Basic)",
}


class MarketDataCache:
    """Fetch and cache ticker beta/sector metadata with Damodaran fallback."""

    def __init__(
        self,
        cache_path: str = "data/cache/market_data_cache.json",
        damodaran_path: str = "data/reference/damodaran_betas_2026.json",
    ) -> None:
        self.cache_path = Path(cache_path)
        self.damodaran_path = Path(damodaran_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.damodaran_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache = self._load_json(self.cache_path)
        self.damodaran = self._load_json(self.damodaran_path)
        sectors = self.damodaran.get("sectors", {})
        self.damodaran_sectors = sectors if isinstance(sectors, dict) else {}

    def get_beta_and_sector(self, ticker: str) -> tuple[float, str, BetaSource]:
        key = ticker.strip().upper()
        cached = self._fresh_cache_entry(key)
        if cached is not None:
            return cached["beta"], cached["sector"], "yfinance_cached"

        info = self._fetch_yfinance_info(key)
        beta = self._valid_beta(info.get("beta"))
        sector = self._valid_sector(info.get("sector"))
        if beta is not None and sector is not None:
            self._write_cache_entry(key, beta, sector)
            return beta, sector, "yfinance_live"

        damodaran_sector = YFINANCE_SECTOR_TO_DAMODARAN.get(sector or "")
        if damodaran_sector:
            damodaran_beta = self._damodaran_beta(damodaran_sector)
            if damodaran_beta is not None:
                return damodaran_beta, damodaran_sector, "damodaran_sector"

        return 1.0, "Unknown", "manual_estimate"

    def _fresh_cache_entry(self, ticker: str) -> dict[str, Any] | None:
        entries = self.cache.get("tickers", self.cache)
        if not isinstance(entries, dict):
            return None
        entry = entries.get(ticker)
        if not isinstance(entry, dict):
            return None
        beta = self._valid_beta(entry.get("beta"))
        sector = self._valid_sector(entry.get("sector"))
        cached_at = self._parse_timestamp(entry.get("cached_at"))
        if beta is None or sector is None or cached_at is None:
            return None
        if datetime.now(timezone.utc) - cached_at > timedelta(days=7):
            return None
        return {"beta": beta, "sector": sector}

    def _fetch_yfinance_info(self, ticker: str) -> dict[str, Any]:
        try:
            import yfinance as yf

            info = yf.Ticker(ticker).info
            return info if isinstance(info, dict) else {}
        except Exception:
            return {}

    def _write_cache_entry(self, ticker: str, beta: float, sector: str) -> None:
        entries = self.cache.setdefault("tickers", {})
        if not isinstance(entries, dict):
            entries = {}
            self.cache["tickers"] = entries
        entries[ticker] = {
            "beta": beta,
            "sector": sector,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.cache_path.write_text(
                json.dumps(self.cache, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception:
            return

    def _damodaran_beta(self, sector: str) -> float | None:
        entry = self.damodaran_sectors.get(sector)
        if not isinstance(entry, dict):
            return None
        return self._valid_beta(entry.get("beta"))

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _valid_beta(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            beta = float(value)
        except (TypeError, ValueError):
            return None
        if 0.05 <= beta <= 4.0:
            return beta
        return None

    @staticmethod
    def _valid_sector(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        sector = value.strip()
        return sector or None
