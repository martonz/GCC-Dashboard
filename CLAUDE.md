# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GCC Dashboard is a conflict escalation monitor for U.S.–Iran tensions. It ingests news from Google News RSS and GDELT, scores items by risk category, computes a rolling RiskIndex, and fires Discord alerts when thresholds are crossed. Everything runs as a Docker Compose stack.

## Running the Stack

```bash
# First-time setup
cp .env.example .env
# Edit .env to set DISCORD_WEBHOOK_URL

# Start everything
docker compose up --build

# Dashboard: http://localhost:8501
# API docs:  http://localhost:8000/docs
```

Partial rebuilds (faster iteration):
```bash
docker compose up -d --build worker beat   # after worker code changes
docker compose up -d --build api           # after API code changes
docker compose up -d --build ui            # after UI code changes
docker compose up -d worker beat api ui    # after .env-only changes (no rebuild needed)
```

Logs:
```bash
docker compose logs -f worker
docker compose logs -f --tail=100 worker beat
```

Trigger a risk compute manually:
```bash
docker compose exec -T worker celery -A app.celery_app call app.tasks.compute_risk
```

## Local Development (without Docker)

Requires a running Postgres and Redis. Set `DATABASE_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` in your environment.

```bash
# API
cd api && pip install -r requirements.txt
uvicorn app.main:app --reload

# Worker (two terminals)
cd worker && pip install -r requirements.txt
celery -A app.celery_app worker --loglevel=debug   # terminal 1
celery -A app.celery_app beat --loglevel=debug     # terminal 2

# UI
cd ui && pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

## Architecture

```
Streamlit UI  →  FastAPI (port 8000)  →  PostgreSQL
                                          ↑
                 Celery worker  →  Redis (broker)
                 Celery beat (scheduler)
```

### Service layout

| Dir | Service | Role |
|-----|---------|------|
| `api/` | FastAPI | Read-only HTTP endpoints for the UI |
| `worker/` | Celery worker + beat | Ingestion, risk computation, alerting |
| `ui/` | Streamlit | Dashboard display |

### Worker pipeline (worker/)

1. **Sources** (`worker/app/sources/`): `google_news_rss.py` and `gdelt.py` fetch articles and yield normalized `dict` records.
2. **Tasks** (`worker/app/tasks.py`): `ingest_rss` and `ingest_gdelt` call sources, then upsert via `_save_items`. `compute_risk` aggregates category hits over the rolling window and saves a `RiskTimeseries` row.
3. **Risk scoring** (`worker/app/risk.py`): `classify_item()` keyword-matches title+snippet into categories; `compute_risk_index()` applies the weighted formula (clamped 0–100).
4. **Deduplication** (`worker/app/dedupe.py`): items are keyed by `url_hash` — SHA-256 of the URL, or of `title|source_name|30-min-bucket` if no URL.
5. **Alerting** (`worker/app/alerting/discord.py`): `maybe_send_alert()` checks cooldown+fingerprint before writing to `alerts` table and POSTing to Discord webhook.
6. **Scheduling** (`worker/app/celery_app.py`): RedBeat scheduler; intervals driven by settings (`RSS_INGEST_INTERVAL_MINUTES`, `GDELT_INGEST_INTERVAL_MINUTES`, `RISK_COMPUTE_INTERVAL_MINUTES`).

### API (api/)

Thin read layer over the same DB. No writes. Response schemas in `api/app/main.py`. DB queries in `api/app/crud.py`. Models in `api/app/models.py` (identical structure to `worker/app/models.py`).

### Database tables

- **`items`** — ingested articles; unique on `url_hash`.
- **`risk_timeseries`** — RiskIndex snapshot per compute cycle, with per-category hit counts and top-3 `drivers_json`.
- **`alerts`** — alert attempts with type, fingerprint, risk values, and `sent` boolean.

### Settings

Both `api/app/settings.py` and `worker/app/settings.py` use pydantic-settings loaded from environment variables. The worker settings also parse JSON env vars (`RSS_QUERIES`, `GDELT_QUERIES`, `YOUTUBE_STREAMS`).

## Key Configuration

All configuration lives in `.env` (copy from `.env.example`). The only required override is `DISCORD_WEBHOOK_URL`. All scheduling intervals, alert thresholds, and query lists are tunable there without code changes.

Timezone convention: all DB storage and Celery scheduling is UTC; the Streamlit UI displays in `Asia/Bahrain` (UTC+3).

## UI Smoke Test

After UI changes:
```bash
docker compose up -d --build ui
curl -s -o /dev/null -w "ui_http_status=%{http_code}\n" http://localhost:8501
docker compose logs --tail=60 ui
```
Expected: `ui_http_status=200`, no tracebacks in logs.

## GDELT Throttling

GDELT 429s are retried automatically (4 attempts, exponential backoff). If they persist, reduce pressure in `.env`:
```env
GDELT_INGEST_INTERVAL_MINUTES=10
GDELT_MAX_RECORDS=50
```
Then: `docker compose up -d worker beat` (no rebuild needed for env-only changes).
