from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional, List, Tuple

import os
import pandas as pd
import requests
from dotenv import load_dotenv
from fredapi import Fred

load_dotenv()

_FRED_BASE = "https://api.stlouisfed.org/fred"

# Simple in-process caches to avoid repeated metadata calls
_SERIES_TO_RELEASE_CACHE: Dict[str, Tuple[int, str]] = {}   # series_id -> (release_id, release_name)
_RELEASE_DATES_CACHE: Dict[Tuple[int, str, str], List[str]] = {}  # (release_id, start, end) -> [YYYY-MM-DD,...]


def _fred_client() -> Fred:
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("Missing FRED_API_KEY in environment/.env")
    return Fred(api_key=key)


def _fred_get(endpoint: str, params: Dict) -> Dict:
    """
    Calls FRED REST API endpoints that fredapi doesn't cover (release calendar metadata).
    """
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("Missing FRED_API_KEY in environment/.env")

    url = f"{_FRED_BASE}/{endpoint}"
    p = dict(params)
    p["api_key"] = key
    p["file_type"] = "json"

    r = requests.get(url, params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def _series_release(series_id: str) -> Tuple[int, str]:
    """
    Returns (release_id, release_name) for a given FRED series.
    Cached.
    """
    series_id = series_id.strip().upper()
    if series_id in _SERIES_TO_RELEASE_CACHE:
        return _SERIES_TO_RELEASE_CACHE[series_id]

    j = _fred_get("series/release", {"series_id": series_id})
    releases = j.get("releases", [])
    if not releases:
        raise RuntimeError(f"No release metadata found for series {series_id}")

    # FRED usually returns a single release object for this endpoint
    rid = int(releases[0]["id"])
    name = str(releases[0]["name"])
    _SERIES_TO_RELEASE_CACHE[series_id] = (rid, name)
    return rid, name


def _release_dates(release_id: int, start: date, end: date) -> List[str]:
    """
    Returns list of release dates (YYYY-MM-DD) for a release_id between start and end.
    Cached.
    """
    key = (release_id, start.isoformat(), end.isoformat())
    if key in _RELEASE_DATES_CACHE:
        return _RELEASE_DATES_CACHE[key]

    j = _fred_get(
        "release/dates",
        {
            "release_id": int(release_id),
            "realtime_start": start.isoformat(),
            "realtime_end": end.isoformat(),
            "include_release_dates_with_no_data": "true",
        },
    )
    dates = [d["date"] for d in j.get("release_dates", []) if "date" in d]
    _RELEASE_DATES_CACHE[key] = dates
    return dates


def _latest_and_prev(series_id: str) -> Tuple[Optional[pd.Timestamp], Optional[float], Optional[float]]:
    """
    Returns (latest_index, latest_value, previous_value) from FRED series observations.
    """
    fred = _fred_client()
    s = fred.get_series(series_id)  # pandas Series indexed by datetime
    if s is None or len(s) == 0:
        return None, None, None

    s = s.dropna()
    if len(s) == 0:
        return None, None, None

    latest_idx = pd.to_datetime(s.index[-1])
    latest_val = float(s.iloc[-1])

    prev_val = None
    if len(s) >= 2:
        prev_val = float(s.iloc[-2])

    return latest_idx, latest_val, prev_val


def fetch_today_releases(
    indicator_map: Dict[str, str],
    as_of: Optional[date] = None,
) -> pd.DataFrame:
    """
    Returns a dataframe of *your tracked indicators* that have a scheduled release date today
    (based on FRED release calendars), plus latest/previous values if available.
    """
    today = as_of or date.today()

    rows = []
    for name, sid in indicator_map.items():
        series_id = sid.strip().upper()

        try:
            release_id, release_name = _series_release(series_id)
            dates = _release_dates(release_id, today, today)
            is_release_today = today.isoformat() in dates
        except Exception as e:
            # If release metadata fails, we still include a row with an error note (optional)
            rows.append(
                {
                    "indicator": name,
                    "series_id": series_id,
                    "release": None,
                    "scheduled_today": False,
                    "latest": None,
                    "previous": None,
                    "change": None,
                    "obs_date": None,
                    "note": f"release lookup failed: {e}",
                }
            )
            continue

        if not is_release_today:
            continue

        obs_date, latest, previous = _latest_and_prev(series_id)
        change = None
        if latest is not None and previous is not None:
            change = latest - previous

        rows.append(
            {
                "indicator": name,
                "series_id": series_id,
                "release": release_name,
                "scheduled_today": True,
                "latest": latest,
                "previous": previous,
                "change": change,
                "obs_date": obs_date.date().isoformat() if obs_date is not None else None,
                "note": "",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=["indicator", "series_id", "release", "scheduled_today", "latest", "previous", "change", "obs_date", "note"]
        )

    # Nice ordering
    df = df.sort_values(["release", "indicator"]).reset_index(drop=True)
    return df


def fetch_latest_updates(
    series_map: Dict[str, str],
) -> pd.DataFrame:
    """
    For liquidity-type trackers: show latest obs date + change vs previous obs.
    (Not a 'calendar event', but a 'what updated most recently' panel.)
    """
    rows = []
    for name, sid in series_map.items():
        series_id = sid.strip().upper()
        obs_date, latest, previous = _latest_and_prev(series_id)
        change = None
        if latest is not None and previous is not None:
            change = latest - previous

        rows.append(
            {
                "series": name,
                "series_id": series_id,
                "latest": latest,
                "previous": previous,
                "change": change,
                "obs_date": obs_date.date().isoformat() if obs_date is not None else None,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["series", "series_id", "latest", "previous", "change", "obs_date"])
    return df.sort_values("series").reset_index(drop=True)


def fetch_release_calendar(
    indicator_map: Dict[str, str],
    days_ahead: int = 7,
    as_of: Optional[date] = None,
    include_latest: bool = True,
) -> pd.DataFrame:
    """
    Returns a simple calendar view for your tracked indicators for the next N days.
    Date granularity only (times are not provided reliably by FRED).
    """
    start = as_of or date.today()
    end = start + timedelta(days=days_ahead)

    # Build release_id sets and map back to indicators
    release_to_indicators: Dict[int, List[Tuple[str, str]]] = {}
    release_names: Dict[int, str] = {}

    latest_cache: Dict[str, Dict] = {}
    if include_latest:
        for _, sid in indicator_map.items():
            series_id = sid.strip().upper()
            obs_date, latest, previous = _latest_and_prev(series_id)
            latest_cache[series_id] = {
                "latest": latest,
                "previous": previous,
                "change": (latest - previous) if (latest is not None and previous is not None) else None,
                "obs_date": obs_date.date().isoformat() if obs_date is not None else None,
            }

    for name, sid in indicator_map.items():
        series_id = sid.strip().upper()
        try:
            rid, rname = _series_release(series_id)
        except Exception:
            continue
        release_names[rid] = rname
        release_to_indicators.setdefault(rid, []).append((name, series_id))

    rows = []
    for rid, items in release_to_indicators.items():
        try:
            dates = _release_dates(rid, start, end)
        except Exception:
            continue

        for d in dates:
            # d is YYYY-MM-DD
            for (indicator_name, series_id) in items:
                rows.append(
                    {
                        "date": d,
                        "release": release_names.get(rid),
                        "indicator": indicator_name,
                        "series_id": series_id,
                    }
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["date", "release", "indicator", "series_id"])

    if include_latest:
        return pd.DataFrame(columns=["date", "release", "indicator", "series_id", "latest", "previous", "change", "obs_date"])

    df = df.sort_values(["date", "release", "indicator"]).reset_index(drop=True)
    return df
