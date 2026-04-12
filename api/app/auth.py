"""
API key authentication dependency.

If API_KEY is set in the environment, every protected endpoint requires
the caller to pass it via the `X-API-Key` header.
If API_KEY is empty, authentication is disabled (logs a warning on startup).
"""
from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from .settings import get_settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Depends(_api_key_header)) -> None:
    settings = get_settings()
    if not settings.api_key:
        return  # auth disabled — no key configured
    if key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key",
        )


def warn_if_auth_disabled() -> None:
    """Call once at startup to surface a warning when auth is off."""
    if not get_settings().api_key:
        logger.warning(
            "API_KEY is not set — all endpoints are publicly accessible. "
            "Set API_KEY in .env to enable authentication."
        )
