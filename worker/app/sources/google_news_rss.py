"""
Google News RSS ingestion.

Builds a feed URL from a search query and parses with feedparser.
Only metadata is stored (title, snippet, url, publisher, published_at).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote_plus

import feedparser

logger = logging.getLogger(__name__)

GNEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={query}"
    "&hl=en-US&gl=US&ceid=US:en"
)


def fetch_rss(query: str) -> Iterator[dict]:
    """Yield raw item dicts from a Google News RSS feed."""
    url = GNEWS_RSS_BASE.format(query=quote_plus(query))
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("RSS fetch failed for query=%r: %s", query, exc)
        return

    for entry in feed.entries:
        published_at: datetime | None = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass

        # Google News RSS wraps the real publisher in the source tag
        publisher = getattr(getattr(entry, "source", None), "title", None)

        yield {
            "source_type": "rss",
            "source_name": query,
            "url": entry.get("link"),
            "title": entry.get("title", ""),
            "snippet": entry.get("summary", ""),
            "publisher": publisher or "",
            "published_at": published_at,
        }
