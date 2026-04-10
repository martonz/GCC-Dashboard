from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Text, Boolean, JSON,
    UniqueConstraint,
)
from .db import Base


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(32), nullable=False)   # rss | gdelt
    source_name = Column(String(256))
    url = Column(Text, unique=True, nullable=True)
    url_hash = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(Text)
    snippet = Column(Text)
    publisher = Column(String(256))
    published_at = Column(DateTime(timezone=True), nullable=True)
    fetched_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    categories = Column(JSON, default=list)   # list of matched category names
    risk_score = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("url_hash", name="uq_items_url_hash"),
    )


class RiskTimeseries(Base):
    __tablename__ = "risk_timeseries"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    risk_index = Column(Float, nullable=False)
    kinetic_hits = Column(Integer, default=0)
    shipping_hits = Column(Integer, default=0)
    nuclear_hits = Column(Integer, default=0)
    casualty_hits = Column(Integer, default=0)
    deescalation_hits = Column(Integer, default=0)
    item_count = Column(Integer, default=0)
    drivers_json = Column(JSON, default=list)   # top 3 driving items


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
    alert_type = Column(String(64))   # risk_threshold | delta_spike | kinetic_cluster
    fingerprint = Column(String(128), index=True)
    risk_value = Column(Float)
    risk_delta = Column(Float)
    drivers_json = Column(JSON, default=list)
    sent = Column(Boolean, default=False)
