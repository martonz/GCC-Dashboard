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
    since_days: Optional[int] = None,
    since_minutes: Optional[int] = None,
    time_basis: str = "fetched",
):
    time_col = Item.published_at if time_basis == "published" else Item.fetched_at

    q = db.query(Item)
    if source_type:
        q = q.filter(Item.source_type == source_type)
    if category:
        q = q.filter(Item.categories.contains([category]))
    if since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        q = q.filter(time_col >= cutoff)
    elif since_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        q = q.filter(time_col >= cutoff)
    return q.order_by(desc(time_col)).offset(offset).limit(limit).all()


# ── Risk timeseries ────────────────────────────────────────────────────────────

def get_latest_risk(db: Session) -> Optional[RiskTimeseries]:
    return (
        db.query(RiskTimeseries)
        .order_by(desc(RiskTimeseries.timestamp))
        .first()
    )


def get_risk_series(
    db: Session,
    *,
    hours: int = 6,
    since_days: Optional[int] = None,
) -> list[RiskTimeseries]:
    q = db.query(RiskTimeseries)
    if since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        q = q.filter(RiskTimeseries.timestamp >= cutoff)
    elif hours:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        q = q.filter(RiskTimeseries.timestamp >= cutoff)

    return q.order_by(RiskTimeseries.timestamp).all()


# ── Alerts ─────────────────────────────────────────────────────────────────────

def get_recent_alerts(
    db: Session,
    *,
    limit: int = 20,
    since_days: Optional[int] = None,
    since_minutes: Optional[int] = None,
) -> list[Alert]:
    q = db.query(Alert)
    if since_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        q = q.filter(Alert.created_at >= cutoff)
    elif since_minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        q = q.filter(Alert.created_at >= cutoff)

    return q.order_by(desc(Alert.created_at)).limit(limit).all()
