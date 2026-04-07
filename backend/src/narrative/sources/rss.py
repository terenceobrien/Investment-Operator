from __future__ import annotations
from typing import List, Optional, Union, Dict
from datetime import datetime, timezone
from urllib.parse import urlparse
import logging
import hashlib

import feedparser

from .http import make_session
from .base import BaseSource, RawTextItem

logger = logging.getLogger("narrative.sources.rss")


def _make_id_from_parts(link: Optional[str], pub: Optional[str], title: Optional[str]) -> str:
    base = (link or "") + "|" + (pub or "") + "|" + (title or "")
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _parse_struct_time_to_dt(st) -> Optional[datetime]:
    # st is a time.struct_time as returned by feedparser entry.published_parsed
    if not st:
        return None
    try:
        # feedparser provides UTC normalized struct_time for feeds; map to UTC datetime
        return datetime(
            st.tm_year, st.tm_mon, st.tm_mday, st.tm_hour, st.tm_min, st.tm_sec, tzinfo=timezone.utc
        )
    except Exception:
        return None


class RssSource(BaseSource):
    """
    RSS/Atom source adapter. Feeds can be:
      - list of URL strings
      - list of dicts: {"name": "Feed Name", "url": "https://..."}
    """

    def __init__(self, feeds: List[Union[str, Dict]], user_agent: str = "narrative-rss/1.0", timeout: int = 15):
        parsed = []
        for f in feeds:
            if isinstance(f, str):
                parsed.append({"name": None, "url": f})
            elif isinstance(f, dict):
                parsed.append({"name": f.get("name"), "url": f.get("url")})
            else:
                raise ValueError("feed entries must be str or dict")
        self.feeds = parsed
        self.user_agent = user_agent
        self.timeout = timeout

    def fetch(self, start: Optional[datetime] = None, end: Optional[datetime] = None) -> List[RawTextItem]:
        session = make_session()
        headers = {"User-Agent": self.user_agent}
        items: List[RawTextItem] = []
        seen_ids = set()
        for feed in self.feeds:
            url = feed["url"]
            try:
                resp = session.get(url, timeout=self.timeout, headers=headers)
            except Exception as e:
                logger.warning("Failed to fetch feed %s: %s", url, e)
                continue
            if resp is None or getattr(resp, "status_code", None) != 200:
                logger.warning("Non-200 response for feed %s: %s", url, getattr(resp, "status_code", None))
                continue
            parsed = feedparser.parse(resp.content)
            feed_name = feed.get("name") or (parsed.feed.get("title") if parsed and parsed.feed else None)
            # fallback to hostname
            try:
                hostname = urlparse(url).hostname or "unknown"
            except Exception:
                hostname = "unknown"
            source_name = feed_name or hostname
            for entry in parsed.entries:
                # id
                entry_id = entry.get("id") or entry.get("guid")
                link = entry.get("link")
                pub_dt = _parse_struct_time_to_dt(entry.get("published_parsed") or entry.get("updated_parsed"))
                if pub_dt is None:
                    # try to use published string if present via feedparser; else fallback to now UTC
                    try:
                        # feedparser may keep 'published' string; use hash stability though
                        pub_str = entry.get("published") or entry.get("updated") or ""
                        # we don't attempt heavy parsing; assume UTC if unknown
                        pub_dt = datetime.now(timezone.utc) if not pub_str else datetime.now(timezone.utc)
                    except Exception:
                        pub_dt = datetime.now(timezone.utc)
                if not entry_id:
                    entry_id = _make_id_from_parts(link, entry.get("published") or entry.get("updated"), entry.get("title"))
                # dedupe by id preliminary
                if entry_id in seen_ids:
                    continue
                seen_ids.add(entry_id)
                title = entry.get("title")
                body = entry.get("summary") or entry.get("description") or ""
                url_field = link
                metadata = {
                    "feed_url": url,
                }
                # include small safe metadata
                if entry.get("tags"):
                    try:
                        metadata["tags"] = [t.get("term") or t.get("label") for t in entry.get("tags")]
                    except Exception:
                        pass
                # construct RawTextItem; rely on pydantic to validate
                try:
                    r = RawTextItem(
                        id=str(entry_id),
                        source=str(source_name),
                        published_at=pub_dt,
                        title=title,
                        body=body,
                        url=url_field,
                        tickers=None,
                        metadata=metadata,
                    )
                except Exception as e:
                    logger.debug("Skipping entry from %s due to validation error: %s", url, e)
                    continue
                # apply start/end filtering (start inclusive, end exclusive)
                if start and r.published_at < start:
                    continue
                if end and r.published_at >= end:
                    continue
                items.append(r)
        # deterministic ordering
        items.sort(key=lambda it: (it.published_at.isoformat(), it.id))
        return items