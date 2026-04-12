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


def _safe_url(url: str | None) -> str:
    """Allow only http/https URLs; return '' for anything else (e.g. javascript:, data:)."""
    if not url:
        return ""
    return url if url.startswith(("https://", "http://")) else ""


def _escape_md(text: str) -> str:
    """Escape markdown link-syntax characters in untrusted text."""
    return re.sub(r"([\[\]()])", r"\\\1", text)

logger = logging.getLogger(__name__)

settings = get_settings()

_WEBHOOK_SESSION = requests.Session()
_WEBHOOK_SESSION.headers.update({"Content-Type": "application/json"})


def _fingerprint(alert_type: str, risk_bucket: int) -> str:
    """Create a stable fingerprint for cooldown dedup."""
    raw = f"{alert_type}:{risk_bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


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
        url = _safe_url(d.get("url", ""))
        cats = ", ".join(d.get("categories", []))
        line = f"**{i}.** [{title}]({url})" if url else f"**{i}.** {title}"
        if source:
            line += f" — *{source}*"
        if cats:
            line += f" `[{cats}]`"
        driver_lines.append(line)

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
        fields.append({
            "name": "Top Drivers",
            "value": "\n".join(driver_lines),
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
