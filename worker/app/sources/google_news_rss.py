"""
Google News RSS ingestion.

Builds a feed URL from a search query and parses with feedparser.
Stores article metadata from Google News RSS feeds.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote_plus

import feedparser

from ..url_utils import resolve_google_news_url

logger = logging.getLogger(__name__)

GNEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={query}"
    "&hl=en-US&gl=US&ceid=US:en"
)


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _normalize_whitespace(html.unescape(re.sub(r"<[^>]+>", " ", value)))


def _strip_source_tail(text: str, publisher: str | None = None) -> str:
    cleaned = text.strip(" -|:\u2013\u2014")
    if not cleaned:
        return ""

    if publisher:
        pub = re.escape(publisher.strip())
        cleaned = re.sub(rf"\s*[-|:\u2013\u2014]\s*{pub}\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"\s+{pub}\s*$", "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s*[-|:\u2013\u2014]\s*[A-Z][\w&'()./\- ]{2,60}\s*$", "", cleaned)
    return cleaned.strip()


def normalize_rss_snippet(summary: str | None, title: str | None, publisher: str | None) -> str:
    summary_html = summary or ""
    anchor_text = ""
    m = re.search(r"<a [^>]*>(.*?)</a>", summary_html, flags=re.IGNORECASE | re.DOTALL)
    if m:
        anchor_text = _strip_html(m.group(1))

    summary_text = _strip_html(summary_html)
    title_text = _normalize_whitespace(html.unescape(title or ""))

    candidates = [
        _strip_source_tail(anchor_text, publisher),
        _strip_source_tail(summary_text, publisher),
        _strip_source_tail(title_text, publisher),
    ]
    candidates = [c for c in candidates if c]
    if not candidates:
        return ""

    return max(candidates, key=len)


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

        # Get the article link
        # Note: Google News RSS links are wrapper URLs that redirect through Google's servers.
        # These are the best available links from the RSS feed.
        article_url = entry.get("link", "")
        
        # Clean up the URL to remove any extra parameters that might be added by some RSS parsers
        if article_url and "?" in article_url:
            # Keep only the base Google News article URL up to the first ?
            # The ?oc=5 parameter is the only standard param and is important for the link to work
            parts = article_url.split("?")
            article_url = parts[0] + "?" + "oc=5"

        direct_url = resolve_google_news_url(article_url)

        yield {
            "source_type": "rss",
            "source_name": query,
            "url": article_url,
            "direct_url": direct_url or article_url,
            "title": entry.get("title", ""),
            "snippet": normalize_rss_snippet(
                entry.get("summary", ""),
                entry.get("title", ""),
                publisher,
            ),
            "publisher": publisher or "",
            "published_at": published_at,
        }
