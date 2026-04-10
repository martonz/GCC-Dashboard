"""
Deduplication helpers.

Strategy:
  1. If a canonical URL is available → hash(url)
  2. Otherwise → hash(title + source_name + published_at_bucket)
     where published_at_bucket rounds to the nearest 30-minute window
     to tolerate minor timestamp drift.
"""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]


def _bucket_time(dt: datetime | None) -> str:
    """Round datetime to 30-min bucket for dedup stability."""
    if dt is None:
        return "unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    minutes = (dt.hour * 60 + dt.minute) // 30 * 30
    return dt.strftime(f"%Y-%m-%dT{minutes // 60:02d}:{minutes % 60:02d}")


def compute_url_hash(
    url: str | None,
    title: str | None,
    source_name: str | None,
    published_at: datetime | None,
) -> str:
    if url:
        return _sha256(url.strip().lower())
    # Fallback: title + source + time bucket
    text = "|".join([
        (title or "").strip().lower(),
        (source_name or "").strip().lower(),
        _bucket_time(published_at),
    ])
    return _sha256(text)
