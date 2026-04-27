from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from screener.poller import WATCHLIST, poll_once
from screener.anomaly import AnomalyEvent, detect, persist_alerts

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_engine():
    from sqlalchemy import create_engine
    url = os.environ["DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def _send_slack(events: list[dict]) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook or not events:
        return

    lines = [f"*Prediction Market Anomaly Alert* — {len(events)} signal(s) detected"]
    for e in events:
        price_str = f"{e['yes_price']:.3f}" if e.get("yes_price") is not None else "N/A"
        lines.append(
            f"• *{e['label']}* [{e['platform']}]  "
            f"`{e['signal']}`  severity={e['severity']}  "
            f"price={price_str}  |  {e['note']}"
        )

    payload = {"text": "\n".join(lines)}
    try:
        with httpx.Client(timeout=5) as client:
            client.post(webhook, json=payload)
    except Exception as exc:
        logger.warning("Slack webhook failed: %s", exc)


# ---------------------------------------------------------------------------
# GET /api/screener/alerts
# ---------------------------------------------------------------------------

@router.get("/api/screener/alerts")
def get_alerts(
    hours: int = Query(48, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
):
    """Return recent anomaly alerts from the DB, newest first."""
    from sqlalchemy import text
    engine = _get_engine()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT ts, platform, market_id, label, signal, severity,
                           yes_price, volume_24h, open_interest, note
                    FROM alerts
                    WHERE ts >= :since
                    ORDER BY ts DESC
                    LIMIT :limit
                """),
                {"since": since, "limit": limit},
            ).mappings().all()
        return {"alerts": [dict(r) for r in rows], "n": len(rows)}
    except Exception as exc:
        raise HTTPException(500, f"Database error: {exc}")


# ---------------------------------------------------------------------------
# GET /api/screener/markets
# ---------------------------------------------------------------------------

@router.get("/api/screener/markets")
def get_markets():
    """Return the watchlist enriched with the most recent snapshot for each market."""
    from sqlalchemy import text
    engine = _get_engine()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT DISTINCT ON (platform, market_id)
                        platform, market_id, label,
                        yes_price, volume_24h, open_interest, ts
                    FROM market_snapshots
                    ORDER BY platform, market_id, ts DESC
                """),
            ).mappings().all()
        snap_by_key = {(r["platform"], r["market_id"]): dict(r) for r in rows}
    except Exception:
        snap_by_key = {}

    result = []
    for m in WATCHLIST:
        key  = (m["platform"], m["id"])
        snap = snap_by_key.get(key, {})
        result.append({
            "platform":      m["platform"],
            "market_id":     m["id"],
            "label":         m["label"],
            "yes_price":     snap.get("yes_price"),
            "volume_24h":    snap.get("volume_24h"),
            "open_interest": snap.get("open_interest"),
            "last_updated":  str(snap["ts"]) if snap.get("ts") else None,
        })

    return {"markets": result}


# ---------------------------------------------------------------------------
# POST /api/screener/run
# ---------------------------------------------------------------------------

@router.post("/api/screener/run")
async def run_screener(background_tasks: BackgroundTasks):
    """Trigger a background poll → detect → persist → (optional) Slack cycle."""

    def _cycle() -> None:
        try:
            poll_once(WATCHLIST)
            events = detect(WATCHLIST)
            if events:
                _send_slack(events)
            logger.info("Screener cycle complete: %d anomaly event(s)", len(events))
        except Exception as exc:
            logger.error("Screener cycle failed: %s", exc)

    background_tasks.add_task(_cycle)
    return {"status": "running", "message": "Poll + detect cycle started in background"}


# ---------------------------------------------------------------------------
# GET /api/screener/market/{market_id}
# ---------------------------------------------------------------------------

@router.get("/api/screener/market/{market_id}")
def get_market_series(
    market_id: str,
    platform: str = Query("kalshi", enum=["kalshi", "polymarket"]),
    hours: int = Query(24, ge=1, le=720),
):
    """Return the full price/volume time-series for a single market (for sparklines)."""
    from sqlalchemy import text
    engine = _get_engine()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("""
                    SELECT ts, yes_price, volume_24h, open_interest
                    FROM market_snapshots
                    WHERE market_id = :market_id
                      AND platform  = :platform
                      AND ts        >= :since
                    ORDER BY ts ASC
                """),
                {"market_id": market_id, "platform": platform, "since": since},
            ).mappings().all()
        series = [dict(r) for r in rows]
        return {
            "market_id": market_id,
            "platform":  platform,
            "hours":     hours,
            "series":    series,
            "n":         len(series),
        }
    except Exception as exc:
        raise HTTPException(500, f"Database error: {exc}")
