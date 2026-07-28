from __future__ import annotations

from functools import lru_cache
from urllib.parse import parse_qs, urlparse

import requests

_URL_RESOLVE_SESSION = requests.Session()
_URL_RESOLVE_SESSION.headers.update(
    {"User-Agent": "Mozilla/5.0 (compatible; GCC-Dashboard/1.0)"}
)


def safe_http_url(url: str | None) -> str:
    if not url:
        return ""
    return url if url.startswith(("https://", "http://")) else ""


def _extract_consent_continue_url(url: str) -> str | None:
    """If the URL is a consent.google.com redirect, extract the continue= target URL."""
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if (parsed.netloc or "").lower() != "consent.google.com":
        return None
    qs = parse_qs(parsed.query)
    continue_urls = qs.get("continue")
    if continue_urls:
        return continue_urls[0]
    return None


def is_google_news_redirect(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.netloc or "").lower()
    return host in {"news.google.com", "www.news.google.com"} and parsed.path.startswith("/rss/articles/")


@lru_cache(maxsize=1024)
def resolve_google_news_url(url: str) -> str:
    """Best-effort resolution of Google News wrapper URLs to publisher article URLs."""
    safe = safe_http_url(url)
    if not safe:
        return ""

    # If the URL already points to a consent page, extract the real target.
    real_url = _extract_consent_continue_url(safe)
    if real_url:
        return safe_http_url(real_url) or ""

    if not is_google_news_redirect(safe):
        return safe

    try:
        resp = _URL_RESOLVE_SESSION.get(safe, allow_redirects=True, timeout=6)
        resolved = safe_http_url(resp.url)
        if resolved:
            # The final redirect may still be a consent page; extract the real URL.
            real_url = _extract_consent_continue_url(resolved)
            if real_url:
                return safe_http_url(real_url) or ""
            if not is_google_news_redirect(resolved):
                return resolved
    except requests.RequestException:
        pass

    return safe