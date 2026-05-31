"""Small JSON file cache for provider responses with explicit TTLs."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_ROOT = Path("data/agent_system/data_cache")


def safe_cache_key(s: str) -> str:
    """Make a filesystem-safe cache key using only alphanumerics, `_`, and `-`."""

    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(s)).strip("_")
    if not value:
        value = hashlib.sha256(str(s).encode("utf-8")).hexdigest()
    if len(value) > 160:
        digest = hashlib.sha256(str(s).encode("utf-8")).hexdigest()[:16]
        value = f"{value[:140]}_{digest}"
    return value


def cache_get(namespace: str, key: str, ttl: timedelta) -> Any | None:
    """
    Return the cached payload if it exists and is fresher than ``ttl``.

    Cache wrapper metadata remains private to this module; callers receive the
    value originally passed to :func:`cache_set`.
    """

    path = CACHE_ROOT / safe_cache_key(namespace) / f"{safe_cache_key(key)}.json"
    if not path.exists():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
        written_at = datetime.fromisoformat(stored["written_at"])
        if written_at.tzinfo is None:
            written_at = written_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - written_at >= ttl:
            return None
        return stored["data"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
        return None


def cache_set(namespace: str, key: str, data: Any) -> None:
    """Write data with a current UTC timestamp, creating directories as needed."""

    path = CACHE_ROOT / safe_cache_key(namespace) / f"{safe_cache_key(key)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    path.write_text(json.dumps(stored, default=str), encoding="utf-8")


def cache_clear(namespace: str | None = None) -> int:
    """Clear cached JSON entries in one namespace or all namespaces."""

    root = CACHE_ROOT / safe_cache_key(namespace) if namespace else CACHE_ROOT
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*.json"):
        path.unlink()
        count += 1
    for directory in sorted(
        (p for p in root.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    return count
