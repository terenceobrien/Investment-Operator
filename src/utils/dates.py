from __future__ import annotations
from datetime import datetime, timezone

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def today_iso_local() -> str:
    return datetime.now().strftime("%Y-%m-%d")
