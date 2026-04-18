from contextlib import asynccontextmanager
from typing import Optional, Literal
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from .auth import require_api_key, warn_if_auth_disabled
from .db import get_db, init_db
from . import crud

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    warn_if_auth_disabled()
    yield


app = FastAPI(
    title="GCC Dashboard API",
    description="Risk monitoring dashboard for U.S.–Iran conflict escalation",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ── Pydantic response schemas ──────────────────────────────────────────────────

class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: str
    source_name: Optional[str]
    url: Optional[str]
    direct_url: Optional[str]
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
def latest_risk(
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    return crud.get_latest_risk(db)


@app.get("/risk/series", response_model=list[RiskOut])
@limiter.limit("60/minute")
def risk_series(
    request: Request,
    hours: int = Query(default=6, ge=1, le=168),
    since_days: Optional[int] = Query(default=None, ge=1, le=30),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    return crud.get_risk_series(db, hours=hours, since_days=since_days)


@app.get("/items", response_model=list[ItemOut])
@limiter.limit("60/minute")
def list_items(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source_type: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    since_days: Optional[int] = Query(default=None, ge=1, le=30),
    since_minutes: Optional[int] = Query(default=None, ge=1),
    time_basis: Literal["fetched", "published"] = Query(default="fetched"),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    # since_days takes precedence when both are provided.
    if since_days is not None:
        since_minutes = None

    return crud.get_items(
        db,
        limit=limit,
        offset=offset,
        source_type=source_type,
        category=category,
        since_days=since_days,
        since_minutes=since_minutes,
        time_basis=time_basis,
    )


@app.get("/alerts", response_model=list[AlertOut])
def list_alerts(
    limit: int = Query(default=20, ge=1, le=100),
    since_days: Optional[int] = Query(default=None, ge=1, le=30),
    db: Session = Depends(get_db),
    _: None = Depends(require_api_key),
):
    return crud.get_recent_alerts(db, limit=limit, since_days=since_days)
