"""
source_loader.py

Reads backend/config/narrative_sources.csv and returns a list of
(BaseSource, metadata_dict) pairs ready to be passed to
items_from_sources() in bundle.py.

Each enabled row gets its own RssSource instance (one feed per instance)
so that per-source metadata — tier, channel, paywall — is preserved when
the bundler processes each source's items independently.

LocalFileSource is instantiated for rows whose URL starts with file:// or
has no URL scheme (bare path).  No Wave-1 rows use this path, but the
loader supports it for future local-document ingest.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import List, Tuple

from .sources.base import BaseSource
from .sources.rss import RssSource
from .sources.local_file import LocalFileSource
from src.agent_system.paths import narrative_raw_dir

logger = logging.getLogger("narrative.source_loader")

EXPECTED_HEADERS = {"Enabled", "Tier", "Channel", "Source Name", "URL", "Paywall", "Notes"}
_TRUTHY = {"true", "1", "yes", "t", "y"}

_UA = "HelixNarrative/0.1 (+https://example.com)"


def _is_truthy(val: str) -> bool:
    return val.strip().lower() in _TRUTHY


def _is_local_url(url: str) -> bool:
    """Return True if url looks like a local filesystem path rather than HTTP(S)."""
    url = url.strip()
    return url.startswith("file://") or ("://" not in url and url != "")


def load_sources_from_csv(path: Path) -> List[Tuple[BaseSource, dict]]:
    """
    Read the CSV at *path*, skip disabled rows, and return a list of
    (source_instance, metadata_dict) tuples.

    metadata_dict keys: Tier, Channel, Source Name, Paywall (bool), Notes.

    Raises ValueError if the CSV is missing any expected header column.
    """
    path = Path(path)
    results: List[Tuple[BaseSource, dict]] = []

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        actual_headers = set(reader.fieldnames or [])
        missing = EXPECTED_HEADERS - actual_headers
        if missing:
            raise ValueError(
                f"narrative_sources.csv is missing expected columns: {sorted(missing)}. "
                f"Found: {sorted(actual_headers)}"
            )

        for row in reader:
            if not _is_truthy(row.get("Enabled", "false")):
                continue

            url = row["URL"].strip()
            source_name = row["Source Name"].strip()
            paywall = _is_truthy(row.get("Paywall", "false"))

            meta: dict = {
                "Tier": row["Tier"].strip(),
                "Channel": row["Channel"].strip(),
                "Source Name": source_name,
                "Paywall": paywall,
                "Notes": row.get("Notes", "").strip(),
            }

            if _is_local_url(url):
                # Strip file:// scheme if present; treat bare path as directory
                directory = url.replace("file://", "").strip() or str(narrative_raw_dir(create=False))
                source: BaseSource = LocalFileSource(directory=directory)
                logger.info("Registered LocalFileSource: %s -> %s", source_name, directory)
            else:
                source = RssSource(
                    feeds=[{"name": source_name, "url": url}],
                    user_agent=_UA,
                )
                logger.info("Registered RssSource: %s -> %s", source_name, url)

            results.append((source, meta))

    logger.info(
        "load_sources_from_csv: loaded %d enabled source(s) from %s", len(results), path
    )
    return results
