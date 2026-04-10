"""
GDELT 2.1 Doc API ingestion.

Uses the free JSON endpoint – no API key required.
Only article metadata (title, url, domain, seendate) is stored.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

GDELT_DOC_BASE = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query={query}"
    "&mode=ArtList"
    "&format=json"
    "&maxrecords={maxrecords}"
    "&sort=HybridRel"
)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "GCC-Dashboard/1.0 (monitoring)"})


def _parse_gdelt_date(s: str | None) -> datetime | None:
    if not s:
        return None
    # GDELT seendate format: "20260410T123000Z"
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def fetch_gdelt(query: str, max_records: int = 100) -> Iterator[dict]:
    """Yield raw item dicts from the GDELT 2.1 Doc API."""
    url = GDELT_DOC_BASE.format(
        query=quote_plus(query),
        maxrecords=min(max_records, 250),
    )
    try:
        resp = _SESSION.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("GDELT fetch failed for query=%r: %s", query, exc)
        return

    articles = data.get("articles") or []
    for art in articles:
        yield {
            "source_type": "gdelt",
            "source_name": query,
            "url": art.get("url"),
            "title": art.get("title", ""),
            "snippet": art.get("seendesc", "") or art.get("socialimage", ""),
            "publisher": art.get("domain", ""),
            "published_at": _parse_gdelt_date(art.get("seendate")),
        }
