"""
GDELT 2.1 Doc API ingestion.

Uses the free JSON endpoint – no API key required.
Only article metadata (title, url, domain, seendate) is stored.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
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

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 10  # seconds; doubles each attempt: 10s, 20s, 40s


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
    """Yield raw item dicts from the GDELT 2.1 Doc API.

    Retries up to _RETRY_ATTEMPTS times with exponential backoff on 429
    (rate-limit) and 5xx (server error) responses.
    """
    url = GDELT_DOC_BASE.format(
        query=quote_plus(query),
        maxrecords=min(max_records, 250),
    )

    data = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = _SESSION.get(url, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                logger.warning(
                    "GDELT HTTP %s for query=%r (attempt %d/%d) — retrying in %ds",
                    resp.status_code, query, attempt, _RETRY_ATTEMPTS, wait,
                )
                if attempt < _RETRY_ATTEMPTS:
                    time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as exc:
            wait = _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            logger.warning(
                "GDELT fetch error for query=%r (attempt %d/%d): %s — retrying in %ds",
                query, attempt, _RETRY_ATTEMPTS, exc, wait,
            )
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(wait)

    if data is None:
        logger.error("GDELT fetch failed for query=%r after %d attempts", query, _RETRY_ATTEMPTS)
        return

    _stale_threshold = timedelta(days=7)
    now = datetime.now(timezone.utc)

    articles = data.get("articles") or []
    for art in articles:
        published_at = _parse_gdelt_date(art.get("seendate"))
        # If seendate is older than 7 days, treat as unknown so the UI
        # falls back to fetched_at for time filtering instead of hiding the item.
        if published_at is not None and (now - published_at) > _stale_threshold:
            published_at = None
        yield {
            "source_type": "gdelt",
            "source_name": query,
            "url": art.get("url"),
            "title": art.get("title", ""),
            "snippet": art.get("seendesc", "") or art.get("socialimage", ""),
            "publisher": art.get("domain", ""),
            "published_at": published_at,
        }
