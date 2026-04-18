"""
Discord webhook alerting with cooldown / deduplication.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from ..models import Alert
from ..settings import get_settings
from ..url_utils import resolve_google_news_url, safe_http_url


def _safe_url(url: str | None) -> str:
    """Allow only http/https URLs; return '' for anything else (e.g. javascript:, data:)."""
    return safe_http_url(url)


def _escape_md(text: str) -> str:
    """Escape markdown link-syntax characters in untrusted text."""
    return re.sub(r"([\[\]()])", r"\\\1", text)

logger = logging.getLogger(__name__)

settings = get_settings()

_WEBHOOK_SESSION = requests.Session()
_WEBHOOK_SESSION.headers.update({"Content-Type": "application/json"})

_DISCORD_EMBED_FIELD_VALUE_MAX = 1024
_SAFE_TOP_DRIVERS_FIELD_MAX = 1000
_SAFE_URL_LINE_MAX = 900


def _fingerprint(alert_type: str, risk_bucket: int) -> str:
    """Create a stable fingerprint for cooldown dedup."""
    raw = f"{alert_type}:{risk_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    return text[: max_len - 1] + "..."


def _join_complete_lines_with_limit(lines: list[str], max_len: int) -> str:
    """Join only full lines without cutting links/text mid-line."""
    out: list[str] = []
    used = 0
    for line in lines:
        add_len = len(line) if not out else len(line) + 1  # account for newlines
        if used + add_len > max_len:
            if out:
                out.append("...")
            break
        out.append(line)
        used += add_len
    return "\n".join(out)


def _is_on_cooldown(db: Session, fingerprint: str) -> bool:
    cooldown = timedelta(minutes=settings.alert_cooldown_minutes)
    cutoff = datetime.now(timezone.utc) - cooldown
    existing = (
        db.query(Alert)
        .filter(
            Alert.fingerprint == fingerprint,
            Alert.created_at >= cutoff,
            Alert.sent.is_(True),
        )
        .first()
    )
    return existing is not None


def _build_discord_embed(
    alert_type: str,
    risk_value: float,
    risk_delta: float,
    drivers: list[dict],
) -> dict:
    type_labels = {
        "risk_threshold": "🚨 Risk Threshold Exceeded",
        "delta_spike": "📈 Rapid Escalation Detected",
        "kinetic_cluster": "💥 Kinetic Cluster Alert",
    }
    color_map = {
        "risk_threshold": 0xFF0000,
        "delta_spike": 0xFF8C00,
        "kinetic_cluster": 0x8B0000,
    }

    label = type_labels.get(alert_type, "⚠️ Alert")
    color = color_map.get(alert_type, 0xFF0000)

    driver_lines = []
    for i, d in enumerate(drivers[:3], 1):
        title = _escape_md(d.get("title", "Unknown")[:120])
        source = _escape_md(d.get("publisher", d.get("source_name", "")) or "")
        url = str(d.get("direct_url") or d.get("url") or "")
        url = resolve_google_news_url(url)
        raw_cats = d.get("categories", [])
        if isinstance(raw_cats, list):
            cats = ", ".join(str(c) for c in raw_cats)
        else:
            cats = str(raw_cats)

        # Keep URLs as raw text so Discord auto-linkifies them reliably.
        line = f"**{i}.** {title}"
        if source:
            line += f" — *{source}*"
        if cats:
            line += f" `[{cats}]`"
        driver_lines.append(_truncate(line, 260))

        if url:
            # Avoid truncating URL in the middle (which produces broken links).
            if len(url) <= _SAFE_URL_LINE_MAX:
                driver_lines.append(f"🔗 {url}")

    fields = [
        {
            "name": "Risk Index",
            "value": f"**{risk_value:.1f} / 100**",
            "inline": True,
        },
        {
            "name": "Delta (30 min)",
            "value": f"+{risk_delta:.1f}" if risk_delta >= 0 else f"{risk_delta:.1f}",
            "inline": True,
        },
    ]
    if driver_lines:
        drivers_value = _join_complete_lines_with_limit(driver_lines, _SAFE_TOP_DRIVERS_FIELD_MAX)
        fields.append({
            "name": "Top Drivers",
            "value": drivers_value,
            "inline": False,
        })

    return {
        "embeds": [
            {
                "title": label,
                "color": color,
                "fields": fields,
                "footer": {"text": "GCC Dashboard · U.S.–Iran Conflict Monitor"},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }


def _build_discord_fallback_content(
    alert_type: str,
    risk_value: float,
    risk_delta: float,
    drivers: list[dict],
) -> str:
    type_labels = {
        "risk_threshold": "Risk Threshold Exceeded",
        "delta_spike": "Rapid Escalation Detected",
        "kinetic_cluster": "Kinetic Cluster Alert",
    }
    label = type_labels.get(alert_type, "Alert")
    first = drivers[0] if drivers else {}
    first_title = str(first.get("title", "No driver title"))
    first_source = str(first.get("publisher", first.get("source_name", "")) or "")
    first_part = _truncate(first_title, 160)
    if first_source:
        first_part += f" ({_truncate(first_source, 60)})"
    return (
        f"[GCC Dashboard] {label}\n"
        f"Risk: {risk_value:.1f}/100\n"
        f"Delta (30 min): {risk_delta:+.1f}\n"
        f"Top driver: {first_part}"
    )


def maybe_send_alert(
    db: Session,
    alert_type: str,
    risk_value: float,
    risk_delta: float,
    drivers: list[dict],
) -> bool:
    """
    Send a Discord alert if:
    - webhook URL is configured
    - not on cooldown for this alert_type + risk bucket

    Returns True if alert was sent.
    """
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        logger.debug("No DISCORD_WEBHOOK_URL configured; skipping alert.")
        return False

    # Bucket risk to nearest 5 to avoid fingerprint churn
    risk_bucket = int(risk_value // 5) * 5
    fp = _fingerprint(alert_type, risk_bucket)

    if _is_on_cooldown(db, fp):
        logger.debug("Alert %s fp=%s is on cooldown; skipping.", alert_type, fp)
        return False

    payload = _build_discord_embed(alert_type, risk_value, risk_delta, drivers)

    try:
        resp = _WEBHOOK_SESSION.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        sent = True
    except requests.RequestException as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        details = exc.response.text[:300] if exc.response is not None else ""
        logger.error("Discord webhook failed (status=%s) response=%s", status, details)
        sent = False

        # If embeds are rejected, retry once with a compact plain-text payload.
        if status == 400:
            fallback_payload = {
                "content": _build_discord_fallback_content(
                    alert_type=alert_type,
                    risk_value=risk_value,
                    risk_delta=risk_delta,
                    drivers=drivers,
                )
            }
            try:
                retry = _WEBHOOK_SESSION.post(webhook_url, json=fallback_payload, timeout=10)
                retry.raise_for_status()
                sent = True
                logger.warning("Discord embed rejected; fallback text alert sent.")
            except requests.RequestException as retry_exc:
                retry_status = (
                    retry_exc.response.status_code if retry_exc.response is not None else "unknown"
                )
                retry_details = (
                    retry_exc.response.text[:300] if retry_exc.response is not None else ""
                )
                logger.error(
                    "Discord fallback webhook failed (status=%s) response=%s",
                    retry_status,
                    retry_details,
                )

    # Record in DB (even if send failed, to avoid retry spam)
    record = Alert(
        alert_type=alert_type,
        fingerprint=fp,
        risk_value=risk_value,
        risk_delta=risk_delta,
        drivers_json=drivers[:3],
        sent=sent,
    )
    db.add(record)
    db.commit()

    return sent
