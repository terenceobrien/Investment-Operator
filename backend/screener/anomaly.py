from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

VOLUME_Z_THRESHOLD: float = 3.5
PRICE_VELOCITY_THRESHOLD: float = 0.08   # 8% move within the window
MIN_OPEN_INTEREST: float = 50_000.0
LOOKBACK_HOURS: int = 24
WINDOW_MINUTES: int = 15


@dataclass
class AnomalyEvent:
    ts: datetime
    platform: str
    market_id: str
    label: str
    signal: str            # "volume_spike" | "price_velocity" | "cross_market"
    severity: str          # "low" | "medium" | "high"
    yes_price: Optional[float]
    volume_24h: Optional[float]
    open_interest: Optional[float]
    note: str


_CREATE_ALERTS_SQL = """
CREATE TABLE IF NOT EXISTS alerts (
    id            BIGSERIAL    PRIMARY KEY,
    ts            TIMESTAMPTZ  NOT NULL,
    platform      TEXT         NOT NULL,
    market_id     TEXT         NOT NULL,
    label         TEXT         NOT NULL,
    signal        TEXT         NOT NULL,
    severity      TEXT         NOT NULL,
    yes_price     REAL,
    volume_24h    REAL,
    open_interest REAL,
    note          TEXT
);
"""


def _get_engine():
    from sqlalchemy import create_engine
    url = os.environ["DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def _load_recent_snapshots(engine, hours: int = LOOKBACK_HOURS) -> pd.DataFrame:
    from sqlalchemy import text
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    df = pd.read_sql(
        text("""
            SELECT ts, platform, market_id, label, yes_price, volume_24h, open_interest
            FROM market_snapshots
            WHERE ts >= :since
            ORDER BY market_id, ts
        """),
        engine,
        params={"since": since},
    )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _volume_z_score_signals(df: pd.DataFrame) -> list[AnomalyEvent]:
    events: list[AnomalyEvent] = []

    for (platform, market_id), grp in df.groupby(["platform", "market_id"]):
        grp = grp.sort_values("ts").copy()

        if grp["open_interest"].iloc[-1] < MIN_OPEN_INTEREST:
            continue

        # Incremental volume proxy: forward-diff of volume_24h, floor at 0
        grp["vol_inc"] = grp["volume_24h"].diff().clip(lower=0)

        if len(grp) < 4:
            continue

        cutoff = grp["ts"].iloc[-1] - timedelta(minutes=WINDOW_MINUTES)
        baseline = grp.loc[grp["ts"] < cutoff, "vol_inc"].dropna()
        recent   = grp.loc[grp["ts"] >= cutoff, "vol_inc"].dropna()

        if len(baseline) < 3 or recent.empty:
            continue

        mean = baseline.mean()
        std  = baseline.std()
        if std == 0 or np.isnan(std):
            continue

        current_vol = recent.sum()
        z = (current_vol - mean) / std

        if z >= VOLUME_Z_THRESHOLD:
            row      = grp.iloc[-1]
            severity = "high" if z >= 6.0 else "medium" if z >= 4.5 else "low"
            events.append(AnomalyEvent(
                ts=row["ts"].to_pydatetime(),
                platform=str(platform),
                market_id=str(market_id),
                label=str(row["label"]),
                signal="volume_spike",
                severity=severity,
                yes_price=row["yes_price"],
                volume_24h=row["volume_24h"],
                open_interest=row["open_interest"],
                note=(
                    f"Volume z-score {z:.1f}σ vs 24h baseline "
                    f"(mean={mean:.0f}, std={std:.0f})"
                ),
            ))

    return events


def _price_velocity_signals(df: pd.DataFrame) -> list[AnomalyEvent]:
    events: list[AnomalyEvent] = []

    for (platform, market_id), grp in df.groupby(["platform", "market_id"]):
        grp = grp.sort_values("ts").copy()

        if grp["open_interest"].iloc[-1] < MIN_OPEN_INTEREST:
            continue

        prices = grp[["ts", "yes_price"]].dropna(subset=["yes_price"])
        if len(prices) < 2:
            continue

        cutoff = prices["ts"].iloc[-1] - timedelta(minutes=WINDOW_MINUTES)
        window = prices[prices["ts"] >= cutoff]
        if len(window) < 2:
            continue

        p_start = float(window["yes_price"].iloc[0])
        p_end   = float(window["yes_price"].iloc[-1])
        if p_start == 0:
            continue

        move = abs(p_end - p_start) / p_start
        if move >= PRICE_VELOCITY_THRESHOLD:
            direction = "up" if p_end > p_start else "down"
            severity  = "high" if move >= 0.15 else "medium" if move >= 0.10 else "low"
            row = grp.iloc[-1]
            events.append(AnomalyEvent(
                ts=row["ts"].to_pydatetime(),
                platform=str(platform),
                market_id=str(market_id),
                label=str(row["label"]),
                signal="price_velocity",
                severity=severity,
                yes_price=p_end,
                volume_24h=row["volume_24h"],
                open_interest=row["open_interest"],
                note=(
                    f"Price moved {move * 100:.1f}% {direction} in "
                    f"{WINDOW_MINUTES}min ({p_start:.3f} → {p_end:.3f})"
                ),
            ))

    return events


def _cross_market_cluster(volume_events: list[AnomalyEvent]) -> list[AnomalyEvent]:
    """Emit a cross_market event when 2+ volume spikes land in the same 15-min window."""
    if len(volume_events) < 2:
        return []

    windows: dict[str, list[AnomalyEvent]] = {}
    for ev in volume_events:
        bucket = ev.ts.strftime("%Y-%m-%dT%H:") + f"{(ev.ts.minute // WINDOW_MINUTES) * WINDOW_MINUTES:02d}"
        windows.setdefault(bucket, []).append(ev)

    cluster_events: list[AnomalyEvent] = []
    for _bucket, cluster in windows.items():
        if len(cluster) >= 2:
            labels = ", ".join(e.label for e in cluster)
            cluster_events.append(AnomalyEvent(
                ts=cluster[0].ts,
                platform="multi",
                market_id="cross_market",
                label="Cross-market cluster",
                signal="cross_market",
                severity="high",
                yes_price=None,
                volume_24h=None,
                open_interest=None,
                note=f"{len(cluster)} markets spiked simultaneously: {labels}",
            ))

    return cluster_events


def persist_alerts(events: list[AnomalyEvent], engine=None) -> None:
    if not events:
        return
    if engine is None:
        engine = _get_engine()

    records = [
        {
            "ts":            e.ts,
            "platform":      e.platform,
            "market_id":     e.market_id,
            "label":         e.label,
            "signal":        e.signal,
            "severity":      e.severity,
            "yes_price":     e.yes_price,
            "volume_24h":    e.volume_24h,
            "open_interest": e.open_interest,
            "note":          e.note,
        }
        for e in events
    ]

    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text(_CREATE_ALERTS_SQL))
        conn.execute(
            text("""
                INSERT INTO alerts
                    (ts, platform, market_id, label, signal, severity,
                     yes_price, volume_24h, open_interest, note)
                VALUES
                    (:ts, :platform, :market_id, :label, :signal, :severity,
                     :yes_price, :volume_24h, :open_interest, :note)
            """),
            records,
        )
    logger.info("Persisted %d alert(s)", len(events))


def detect(watchlist: list[dict]) -> list[dict]:
    """Run all anomaly signals against recent DB snapshots. Returns serialisable dicts."""
    engine = _get_engine()
    df = _load_recent_snapshots(engine)
    if df.empty:
        return []

    watch_ids = {(m["platform"], m["id"]) for m in watchlist}
    mask = df.apply(lambda r: (r["platform"], r["market_id"]) in watch_ids, axis=1)
    df = df[mask]
    if df.empty:
        return []

    vol_events   = _volume_z_score_signals(df)
    price_events = _price_velocity_signals(df)
    cross_events = _cross_market_cluster(vol_events)

    all_events = vol_events + price_events + cross_events
    persist_alerts(all_events, engine=engine)

    return [asdict(e) for e in all_events]
