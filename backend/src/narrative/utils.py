from __future__ import annotations
from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
from typing import Optional

EASTERN = ZoneInfo("America/New_York")

def published_at_to_eastern_date(dt: datetime) -> date:
    """
    Convert a published_at datetime to a US/Eastern local date bucket.
    If dt is naive, assume UTC.

    Note on start/end semantics:
    - build_narrative_scores treats 'start' and 'end' as inclusive YYYY-MM-DD local dates.
    - The fetch interval used is start 00:00 UTC inclusive to (end + 1 day) 00:00 UTC exclusive,
      but bucket assignment is computed using US/Eastern local date.
    - Output contains weekdays only (Mon-Fri).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(EASTERN)
    return local.date()