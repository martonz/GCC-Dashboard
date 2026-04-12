from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import FastAPI, Depends, HTTPException, Query, Security, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from .db import get_db, init_db
from .settings import get_settings
from . import crud


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


settings = get_settings()

# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])

# ── API key auth ───────────────────────────────────────────────────────────────
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: Optional[str] = Security(_api_key_header)) -> str:
    if key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return key


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
    allow_origins=["http://localhost:8501", "http://ui:8501"],
    allow_methods=["GET"],
    allow_headers=["X-API-Key"],
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
@limiter.limit("60/minute")
def latest_risk(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    return crud.get_latest_risk(db)


@app.get("/risk/series", response_model=list[RiskOut])
@limiter.limit("60/minute")
def risk_series(
    request: Request,
    hours: int = Query(default=6, ge=1, le=168),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    return crud.get_risk_series(db, hours=hours)


@app.get("/items", response_model=list[ItemOut])
@limiter.limit("30/minute")
def list_items(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    source_type: Optional[str] = Query(default=None),
    category: Optional[Literal[
        "kinetic", "shipping", "nuclear", "casualties", "deescalation"
    ]] = Query(default=None),
    since_minutes: Optional[int] = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
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
@limiter.limit("60/minute")
def list_alerts(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: str = Depends(require_api_key),
):
    return crud.get_recent_alerts(db, limit=limit)
