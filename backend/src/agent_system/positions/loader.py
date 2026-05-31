"""Discovery helpers for the Fidelity positions drop directory."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from src.agent_system.positions.parser import parse_fidelity_csv
from src.agent_system.positions.types import PositionsSnapshot


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_AGENT_DATA_DIR = PROJECT_ROOT / "data" / "agent_system"


def data_root() -> Path:
    """Return the canonical agent-system data directory."""
    return Path(os.getenv("AGENT_SYSTEM_DATA_DIR", str(DEFAULT_AGENT_DATA_DIR)))


POSITIONS_DROP_DIR = data_root() / "positions"


def positions_drop_dir() -> Path:
    """Return the positions drop directory, honoring AGENT_SYSTEM_DATA_DIR."""
    return data_root() / "positions"


def load_latest_positions() -> PositionsSnapshot | None:
    """
    Find the most recent Fidelity CSV in the positions drop directory.

    Returns None when no CSV is present.
    """
    drop_dir = positions_drop_dir()
    if not drop_dir.exists():
        return None
    csv_files = [path for path in drop_dir.glob("*.csv") if path.is_file()]
    if not csv_files:
        return None
    latest = max(csv_files, key=lambda path: path.stat().st_mtime)
    return parse_fidelity_csv(latest)


def positions_freshness_warning(snapshot: PositionsSnapshot) -> str | None:
    """Return an informational warning if the positions file is stale."""
    now = datetime.now(timezone.utc)
    age = now - snapshot.file_mtime
    hours = age.total_seconds() / 3600
    if hours <= 24:
        return None
    if hours <= 24 * 7:
        return f"Positions file is {int(round(hours))} hours old; prices may be stale."
    days = int(round(hours / 24))
    return f"Positions file is {days} days old; consider downloading a fresh export."
