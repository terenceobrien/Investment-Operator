from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Watchlist — ~10 high-liquidity macro & geopolitical markets
# Market IDs should be verified against live platforms before deploying;
# Kalshi tickers follow the pattern SERIES-YYMONDD-[T|B]STRIKE and
# Polymarket IDs are integer market IDs from the Gamma API.
# ---------------------------------------------------------------------------
WATCHLIST: list[dict] = [
    # Kalshi — Federal Reserve rate decisions
    {"platform": "kalshi", "id": "FOMC-25JUN18-T4.50", "label": "Fed holds ≥4.50% Jun 2025"},
    {"platform": "kalshi", "id": "FOMC-25JUL30-T4.50", "label": "Fed holds ≥4.50% Jul 2025"},
    # Kalshi — CPI / inflation prints
    {"platform": "kalshi", "id": "INF-25MAY-B3",       "label": "CPI below 3.0% May 2025"},
    {"platform": "kalshi", "id": "INF-25JUN-B3",       "label": "CPI below 3.0% Jun 2025"},
    # Kalshi — Recession & GDP
    {"platform": "kalshi", "id": "RECES-25",           "label": "US recession declared 2025"},
    {"platform": "kalshi", "id": "GDPUS-25Q2-B2",      "label": "US GDP Q2 2025 below 2%"},
    # Polymarket — Macro (integer IDs from Gamma API)
    {"platform": "polymarket", "id": "508109", "label": "US recession by end of 2025"},
    {"platform": "polymarket", "id": "512045", "label": "Fed rate cut before Sep 2025"},
    # Polymarket — Geopolitical (high-liquidity markets)
    {"platform": "polymarket", "id": "497312", "label": "Russia-Ukraine ceasefire by end of 2025"},
    {"platform": "polymarket", "id": "503891", "label": "Taiwan strait military incident 2025"},
]

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_GAMMA_BASE = "https://gamma-api.polymarket.com"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    ts            TIMESTAMPTZ  NOT NULL,
    platform      TEXT         NOT NULL,
    market_id     TEXT         NOT NULL,
    label         TEXT         NOT NULL,
    yes_price     REAL,
    volume_24h    REAL,
    open_interest REAL
);
"""

_CREATE_HYPERTABLE_SQL = (
    "SELECT create_hypertable('market_snapshots', 'ts', if_not_exists => TRUE);"
)


def _get_engine():
    from sqlalchemy import create_engine
    url = os.environ["DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def _ensure_table(engine) -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_CREATE_TABLE_SQL))
        try:
            conn.execute(text(_CREATE_HYPERTABLE_SQL))
        except Exception:
            pass  # TimescaleDB not available — continue without hypertable


def _fetch_kalshi(market_id: str) -> Optional[dict]:
    url = f"{KALSHI_BASE}/markets/{market_id}"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, headers={"accept": "application/json"})
        resp.raise_for_status()
    data = resp.json().get("market", {})
    raw_price = data.get("yes_ask") or data.get("last_price")
    return {
        "yes_price":     float(raw_price) if raw_price is not None else None,
        "volume_24h":    float(data.get("volume_24h") or data.get("volume") or 0),
        "open_interest": float(data.get("open_interest") or 0),
    }


def _fetch_polymarket(market_id: str) -> Optional[dict]:
    import json as _json

    url = f"{POLYMARKET_GAMMA_BASE}/markets/{market_id}"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, headers={"accept": "application/json"})
        resp.raise_for_status()
    data = resp.json()

    # outcomePrices is a JSON-encoded string: '["0.45","0.55"]'
    prices_raw = data.get("outcomePrices", "[]")
    prices = _json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
    yes_price = float(prices[0]) if prices else None

    return {
        "yes_price":     yes_price,
        "volume_24h":    float(data.get("volume24hr") or data.get("volume") or 0),
        "open_interest": float(data.get("openInterest") or data.get("liquidityNum") or 0),
    }


def _fetch_market(market: dict) -> Optional[dict]:
    platform  = market["platform"]
    market_id = market["id"]
    try:
        if platform == "kalshi":
            snap = _fetch_kalshi(market_id)
        elif platform == "polymarket":
            snap = _fetch_polymarket(market_id)
        else:
            logger.warning("Unknown platform: %s", platform)
            return None
        if snap is None:
            return None
        snap.update({
            "platform":  platform,
            "market_id": market_id,
            "label":     market["label"],
            "ts":        datetime.now(timezone.utc),
        })
        return snap
    except Exception as exc:
        logger.warning("Failed to fetch %s/%s: %s", platform, market_id, exc)
        return None


def _write_snapshots(engine, snapshots: list[dict]) -> None:
    if not snapshots:
        return
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(
            text("""
                INSERT INTO market_snapshots
                    (ts, platform, market_id, label, yes_price, volume_24h, open_interest)
                VALUES
                    (:ts, :platform, :market_id, :label, :yes_price, :volume_24h, :open_interest)
            """),
            snapshots,
        )
    logger.info("Wrote %d market snapshots", len(snapshots))


def poll_once(watchlist: list[dict] = WATCHLIST) -> list[dict]:
    """Fetch all watchlist markets in parallel and persist snapshots. Returns written records."""
    engine = _get_engine()
    _ensure_table(engine)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_market, m): m for m in watchlist}
        results: list[dict] = []
        for future in as_completed(futures):
            snap = future.result()
            if snap:
                results.append(snap)

    _write_snapshots(engine, results)
    return results


def run_scheduler(
    watchlist: list[dict] = WATCHLIST,
    interval_seconds: int = 60,
) -> None:
    """Start a blocking APScheduler loop that polls every `interval_seconds`."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()

    def _job() -> None:
        try:
            snaps = poll_once(watchlist)
            logger.info("Poll complete: %d snapshots written", len(snaps))
        except Exception as exc:
            logger.error("Poll job failed: %s", exc)

    scheduler.add_job(_job, "interval", seconds=interval_seconds)
    logger.info(
        "Starting poller (interval=%ds, watchlist=%d markets)",
        interval_seconds,
        len(watchlist),
    )
    scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_scheduler()
