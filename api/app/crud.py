from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from .models import Item, RiskTimeseries, Alert


# ── Items ──────────────────────────────────────────────────────────────────────

def get_items(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    source_type: Optional[str] = None,
    category: Optional[str] = None,
    since_minutes: Optional[int] = None,
):
    q = db.query(Item)
    if source_type:
        q = q.filter(Item.source_type == source_type)
    if category:
        q = q.filter(Item.categories.contains([category]))
    if since_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        q = q.filter(Item.fetched_at >= cutoff)
    return q.order_by(desc(Item.fetched_at)).offset(offset).limit(limit).all()


# ── Risk timeseries ────────────────────────────────────────────────────────────

def get_latest_risk(db: Session) -> Optional[RiskTimeseries]:
    return (
        db.query(RiskTimeseries)
        .order_by(desc(RiskTimeseries.timestamp))
        .first()
    )


def get_risk_series(
    db: Session, *, hours: int = 6
) -> list[RiskTimeseries]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return (
        db.query(RiskTimeseries)
        .filter(RiskTimeseries.timestamp >= cutoff)
        .order_by(RiskTimeseries.timestamp)
        .all()
    )


# ── Alerts ─────────────────────────────────────────────────────────────────────

def get_recent_alerts(db: Session, *, limit: int = 20) -> list[Alert]:
    return (
        db.query(Alert)
        .order_by(desc(Alert.created_at))
        .limit(limit)
        .all()
    )
