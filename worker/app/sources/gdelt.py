"""
GDELT 2.1 Doc API ingestion.

Uses the free JSON endpoint – no API key required.
Only article metadata (title, url, domain, seendate) is stored.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import quote_plus

import requests

from ..settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

GDELT_DOC_BASE = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query={query}"
    "&mode=ArtList"
    "&format=json"
    "&maxrecords={maxrecords}"
    "&sort=HybridRel"
    "&timespan=3d"
)

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "GCC-Dashboard/1.0 (monitoring)"})

_MAX_RETRIES = 4
_BASE_BACKOFF_SECONDS = 2


def _retry_delay_seconds(attempt: int, retry_after_header: str | None = None) -> int:
    if retry_after_header:
        try:
            # GDELT may return Retry-After as integer seconds.
            retry_after = int(retry_after_header)
            if retry_after > 0:
                return retry_after
        except ValueError:
            pass
    return _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))


def _get_json_with_backoff(url: str) -> tuple[dict, Counter[str]]:
    last_error: Exception | None = None
    retry_reasons: Counter[str] = Counter()

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = _SESSION.get(url, timeout=30)

            if resp.status_code == 429:
                delay = _retry_delay_seconds(attempt, resp.headers.get("Retry-After"))
                if attempt == _MAX_RETRIES:
                    resp.raise_for_status()
                retry_reasons["http_429"] += 1
                logger.warning(
                    "GDELT rate-limited (429). Retrying in %ss (attempt %d/%d)",
                    delay,
                    attempt,
                    _MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            resp.raise_for_status()
            try:
                return resp.json(), retry_reasons
            except ValueError as exc:
                # GDELT occasionally returns empty/non-JSON bodies during throttling or edge failures.
                content_type = resp.headers.get("Content-Type", "")
                preview = (resp.text or "")[:120].replace("\n", " ")
                raise requests.RequestException(
                    f"Invalid JSON response (status={resp.status_code}, content_type={content_type!r}, body_preview={preview!r})"
                ) from exc
        except requests.RequestException as exc:
            last_error = exc
            if attempt == _MAX_RETRIES:
                break
            if "Invalid JSON response" in str(exc):
                retry_reasons["invalid_json"] += 1
            else:
                retry_reasons["request_error"] += 1
            delay = _retry_delay_seconds(attempt)
            logger.warning(
                "GDELT request error: %s. Retrying in %ss (attempt %d/%d)",
                exc,
                delay,
                attempt,
                _MAX_RETRIES,
            )
            time.sleep(delay)

    if last_error is not None:
        raise last_error
    raise RuntimeError("GDELT request failed without an explicit exception")


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
        query=quote_plus(f"{query} sourcelang:english"),
        maxrecords=min(max_records, 250),
    )
    retry_reasons: Counter[str] = Counter()
    try:
        data, retry_reasons = _get_json_with_backoff(url)
    except Exception as exc:
        if retry_reasons:
            logger.warning(
                "GDELT fetch failed for query=%r after retries=%d reasons=%s: %s",
                query,
                sum(retry_reasons.values()),
                dict(retry_reasons),
                exc,
            )
        else:
            logger.warning("GDELT fetch failed for query=%r: %s", query, exc)
        return

    retry_count = sum(retry_reasons.values())
    if retry_reasons:
        if retry_count >= settings.gdelt_retry_warn_threshold:
            logger.warning(
                "GDELT retry pressure high for query=%r retries=%d threshold=%d reasons=%s",
                query,
                retry_count,
                settings.gdelt_retry_warn_threshold,
                dict(retry_reasons),
            )
        logger.info(
            "GDELT fetch recovered for query=%r after retries=%d reasons=%s",
            query,
            retry_count,
            dict(retry_reasons),
        )

    articles = data.get("articles") or []
    for art in articles:
        yield {
            "source_type": "gdelt",
            "source_name": query,
            "url": art.get("url"),
            "direct_url": art.get("url"),
            "title": art.get("title", ""),
            "snippet": art.get("seendesc", "") or art.get("socialimage", ""),
            "publisher": art.get("domain", ""),
            "published_at": _parse_gdelt_date(art.get("seendate")),
        }
