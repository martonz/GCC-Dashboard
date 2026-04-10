from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from .db import get_db, init_db
from . import crud


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="GCC Dashboard API",
    description="Risk monitoring dashboard for U.S.–Iran conflict escalation",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Pydantic response schemas ──────────────────────────────────────────────────

class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_name: Optional[str]
    url: Optional[str]
    title: Optional[str]
    snippet: Optional[str]
    publisher: Optional[str]
    published_at: Optional[datetime]
    fetched_at: Optional[datetime]
    categories: list
    risk_score: float


class RiskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: datetime
    risk_index: float
    kinetic_hits: int
    shipping_hits: int
    nuclear_hits: int
    casualty_hits: int
    deescalation_hits: int
    item_count: int
    drivers_json: list


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    alert_type: str
    fingerprint: str
    risk_value: float
    risk_delta: float
    drivers_json: list
    sent: bool


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/risk/latest", response_model=Optional[RiskOut])
def latest_risk(db: Session = Depends(get_db)):
    return crud.get_latest_risk(db)


@app.get("/risk/series", response_model=list[RiskOut])
def risk_series(
    hours: int = Query(default=6, ge=1, le=168),
    db: Session = Depends(get_db),
):
    return crud.get_risk_series(db, hours=hours)


@app.get("/items", response_model=list[ItemOut])
def list_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source_type: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    since_minutes: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return crud.get_items(
        db,
        limit=limit,
        offset=offset,
        source_type=source_type,
        category=category,
        since_minutes=since_minutes,
    )


@app.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return crud.get_recent_alerts(db, limit=limit)
