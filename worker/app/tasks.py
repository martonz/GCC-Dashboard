"""
Celery tasks:
  - ingest_rss: fetch from Google News RSS feeds
  - ingest_gdelt: fetch from GDELT 2.1 Doc API
  - compute_risk: compute RiskIndex and fire alerts
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .celery_app import app
from .db import SessionLocal, init_db
from .dedupe import compute_url_hash
from .models import Item, RiskTimeseries
from .risk import classify_item, item_risk_score, compute_risk_index
from .settings import get_settings
from .sources.google_news_rss import fetch_rss
from .sources.gdelt import fetch_gdelt
from .alerting.discord import maybe_send_alert

logger = logging.getLogger(__name__)
settings = get_settings()


def _ensure_db():
    init_db()


# ── Ingestion helpers ──────────────────────────────────────────────────────────

def _save_items(raw_items: list[dict]) -> int:
    """Upsert items into DB; return count of newly inserted rows."""
    if not raw_items:
        return 0

    _ensure_db()
    db = SessionLocal()
    saved = 0
    try:
        for raw in raw_items:
            url_hash = compute_url_hash(
                raw.get("url"),
                raw.get("title"),
                raw.get("source_name"),
                raw.get("published_at"),
            )
            categories = classify_item(
                raw.get("title", ""),
                raw.get("snippet", ""),
            )
            score = item_risk_score(categories)

            insert_stmt = (
                pg_insert(Item)
                .values(
                    source_type=raw["source_type"],
                    source_name=raw.get("source_name", ""),
                    url=raw.get("url"),
                    direct_url=raw.get("direct_url") or raw.get("url"),
                    url_hash=url_hash,
                    title=raw.get("title", ""),
                    snippet=raw.get("snippet", ""),
                    publisher=raw.get("publisher", ""),
                    published_at=raw.get("published_at"),
                    fetched_at=datetime.now(timezone.utc),
                    categories=categories,
                    risk_score=score,
                )
            )
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=["url_hash"],
                set_={
                    "direct_url": func.coalesce(Item.direct_url, insert_stmt.excluded.direct_url),
                },
                where=Item.direct_url.is_(None),
            )
            result = db.execute(stmt)
            saved += result.rowcount

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Error saving items")
    finally:
        db.close()

    return saved


# ── Tasks ──────────────────────────────────────────────────────────────────────

@app.task(name="app.tasks.ingest_rss", bind=True, max_retries=2)
def ingest_rss(self):
    queries = settings.get_rss_queries()
    all_items: list[dict] = []
    for query in queries:
        try:
            items = list(fetch_rss(query))
            all_items.extend(items)
            logger.info("RSS query=%r yielded %d items", query, len(items))
        except Exception as exc:
            logger.warning("RSS ingestion failed for %r: %s", query, exc)

    saved = _save_items(all_items)
    logger.info("RSS ingestion: %d new items saved (total fetched: %d)", saved, len(all_items))
    return {"saved": saved, "fetched": len(all_items)}


@app.task(name="app.tasks.ingest_gdelt", bind=True, max_retries=2)
def ingest_gdelt(self):
    queries = settings.get_gdelt_queries()
    all_items: list[dict] = []
    for query in queries:
        try:
            items = list(fetch_gdelt(query, max_records=settings.gdelt_max_records))
            all_items.extend(items)
            logger.info("GDELT query=%r yielded %d items", query, len(items))
        except Exception as exc:
            logger.warning("GDELT ingestion failed for %r: %s", query, exc)

    saved = _save_items(all_items)
    logger.info("GDELT ingestion: %d new items saved (total fetched: %d)", saved, len(all_items))
    return {"saved": saved, "fetched": len(all_items)}


@app.task(name="app.tasks.compute_risk", bind=True)
def compute_risk(self):
    _ensure_db()
    db = SessionLocal()
    try:
        window = timedelta(minutes=settings.risk_window_minutes)
        cutoff = datetime.now(timezone.utc) - window
        items: list[Item] = (
            db.query(Item)
            .filter(Item.published_at.isnot(None))
            .filter(Item.published_at >= cutoff)
            .all()
        )

        kinetic = shipping = nuclear = casualties = deescalation = 0
        domains_kinetic: set[str] = set()
        top_items: list[dict] = []

        for item in items:
            cats: list[str] = item.categories or []
            if "kinetic" in cats:
                kinetic += 1
                domain = (item.publisher or "").strip().lower() or (item.url or "")[:50]
                domains_kinetic.add(domain)
            if "shipping" in cats:
                shipping += 1
            if "nuclear" in cats:
                nuclear += 1
            if "casualties" in cats:
                casualties += 1
            if "deescalation" in cats:
                deescalation += 1
            if cats and item.risk_score > 0:
                top_items.append({
                    "title": item.title,
                    "publisher": item.publisher,
                    "url": item.url,
                    "direct_url": item.direct_url or item.url,
                    "categories": cats,
                    "risk_score": item.risk_score,
                    "source_name": item.source_name,
                })

        risk_index = compute_risk_index(kinetic, shipping, nuclear, casualties, deescalation)

        # Top 3 drivers by risk_score desc
        top_items.sort(key=lambda x: x["risk_score"], reverse=True)
        drivers = top_items[:3]

        ts = RiskTimeseries(
            timestamp=datetime.now(timezone.utc),
            risk_index=risk_index,
            kinetic_hits=kinetic,
            shipping_hits=shipping,
            nuclear_hits=nuclear,
            casualty_hits=casualties,
            deescalation_hits=deescalation,
            item_count=len(items),
            drivers_json=drivers,
        )
        db.add(ts)
        db.commit()
        db.refresh(ts)

        logger.info(
            "Risk computed: %.1f (k=%d s=%d n=%d c=%d d=%d items=%d)",
            risk_index, kinetic, shipping, nuclear, casualties, deescalation, len(items),
        )

        # ── Alert evaluation ───────────────────────────────────────────────────
        _evaluate_alerts(db, risk_index, kinetic, len(domains_kinetic), drivers)

        return {"risk_index": risk_index, "item_count": len(items)}
    except Exception:
        db.rollback()
        logger.exception("Error computing risk")
    finally:
        db.close()


def _evaluate_alerts(
    db,
    risk_index: float,
    kinetic_hits: int,
    distinct_kinetic_domains: int,
    drivers: list[dict],
):
    """Check alert conditions and dispatch Discord notifications if needed."""
    # 1) Risk threshold
    if risk_index >= settings.alert_risk_threshold:
        maybe_send_alert(
            db,
            alert_type="risk_threshold",
            risk_value=risk_index,
            risk_delta=_compute_delta(db, risk_index),
            drivers=drivers,
        )

    # 2) Delta spike – compare with 30 minutes ago
    delta = _compute_delta(db, risk_index)
    if delta >= settings.alert_delta_threshold:
        maybe_send_alert(
            db,
            alert_type="delta_spike",
            risk_value=risk_index,
            risk_delta=delta,
            drivers=drivers,
        )

    # 3) Kinetic cluster – 3+ hits from distinct domains, only when net risk is positive
    if (
        risk_index >= settings.alert_kinetic_min_risk
        and kinetic_hits >= settings.alert_kinetic_hits
        and distinct_kinetic_domains >= 3
    ):
        maybe_send_alert(
            db,
            alert_type="kinetic_cluster",
            risk_value=risk_index,
            risk_delta=delta,
            drivers=drivers,
        )


def _compute_delta(db, current_risk: float) -> float:
    """Compute risk delta vs 30 minutes ago."""
    from .models import RiskTimeseries
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
    past = (
        db.query(RiskTimeseries)
        .filter(RiskTimeseries.timestamp <= cutoff)
        .order_by(RiskTimeseries.timestamp.desc())
        .first()
    )
    if past is None:
        return 0.0
    return current_risk - past.risk_index
