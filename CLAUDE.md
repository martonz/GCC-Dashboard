# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

GCC Dashboard monitors U.S.–Iran conflict escalation risk. It ingests news from Google News RSS and GDELT 2.1 API, classifies articles into risk categories, computes a RiskIndex (0–100) every 5 minutes, and sends Discord alerts when thresholds are exceeded. A Streamlit dashboard and FastAPI REST API expose the data.

## Running the Project

```bash
# Copy and configure environment (set DISCORD_WEBHOOK_URL at minimum)
cp .env.example .env

# Build and start all services
docker compose up --build

# Dashboard: http://localhost:8501
# API docs:  http://localhost:8000/docs

# Stop without losing data
docker compose down

# Stop and wipe all data
docker compose down -v
```

**Local dev (requires Postgres on :5432 and Redis on :6379):**
```bash
# API
cd api && pip install -r requirements.txt
uvicorn app.main:app --reload

# Worker + Beat scheduler
cd worker && pip install -r requirements.txt
celery -A app.celery_app worker --beat --loglevel=debug

# UI
cd ui && pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

There is no test suite. No linter is configured.

## Architecture

Three services share one PostgreSQL database; Redis is the Celery broker/backend.

```
Streamlit UI (8501) → FastAPI (8000) → PostgreSQL (5432)
                                              ↑
                      Celery Worker ──────────┘
                      (+ Beat scheduler)
                            ↑
                        Redis (6379)
```

### Services

| Dir | Purpose |
|-----|---------|
| `api/` | FastAPI REST API — exposes `/health`, `/risk/latest`, `/risk/series`, `/items`, `/alerts` |
| `worker/` | Celery worker + Beat — runs ingest, risk computation, and alerting tasks |
| `ui/` | Streamlit dashboard — polls API every 30 s, renders gauge, chart, item tabs, YouTube embeds |

### Database Tables (defined independently in both `api/app/models.py` and `worker/app/models.py`)

- **`items`** — ingested articles; deduplicated on `url_hash` (SHA256 of URL, or title+source+30-min bucket)
- **`risk_timeseries`** — computed RiskIndex snapshots with category hit counts (`drivers_json`)
- **`alerts`** — fired alerts with cooldown dedup on `fingerprint` (alert_type + risk_bucket)

Tables are auto-created on API startup via `init_db()` in `api/app/main.py`.

### Celery Beat Schedule (defined in `worker/app/celery_app.py`)

| Task | Default Interval | What It Does |
|------|-----------------|-------------|
| `ingest_rss` | 2 min | Fetches Google News RSS, classifies, deduplicates, upserts |
| `ingest_gdelt` | 5 min | Fetches GDELT 2.1 Doc API, same pipeline |
| `compute_risk` | 5 min | Counts category hits in rolling window, scores, checks alert conditions |

### Risk Computation Window

`compute_risk` (`worker/app/tasks.py`) counts category hits using `published_at` as the recency signal — articles published within `RISK_WINDOW_MINUTES` (default 60) are included. Items where `published_at` is NULL fall back to `fetched_at`. This means the risk index reflects genuinely recent news rather than when articles were fetched.

### Risk Scoring Formula (`worker/app/risk.py`)

```
RiskIndex = clamp(0, 100,
  10
  + 8 × kinetic_hits
  + 6 × shipping_hits
  + 7 × nuclear_hits
  + 5 × casualty_hits
  - 4 × deescalation_hits
)
```

Category keywords and weights live in the `CATEGORIES` dict in `worker/app/risk.py`.

### Alert Conditions (`worker/app/tasks.py` + `worker/app/alerting/discord.py`)

Three independent conditions trigger Discord webhook POSTs:
1. **risk_threshold** — RiskIndex ≥ `ALERT_RISK_THRESHOLD` (default 70)
2. **delta_spike** — RiskIndex rose ≥ `ALERT_DELTA_THRESHOLD` (default 20) in last 30 min
3. **kinetic_cluster** — ≥ `ALERT_KINETIC_HITS` (default 3) kinetic hits from ≥ 3 distinct domains

All alerts have a per-fingerprint cooldown (`ALERT_COOLDOWN_MINUTES`, default 30) tracked in the `alerts` table.

## Configuration

All tuneable parameters live in `.env` and are loaded via Pydantic `Settings` classes in each service's `app/settings.py`. Key variables:

| Variable | Default | Effect |
|----------|---------|--------|
| `DISCORD_WEBHOOK_URL` | — | Required for Discord alerts |
| `ALERT_RISK_THRESHOLD` | 70 | Risk score that triggers threshold alert |
| `ALERT_DELTA_THRESHOLD` | 20 | Score rise that triggers spike alert |
| `ALERT_KINETIC_HITS` | 3 | Kinetic hits needed for cluster alert |
| `ALERT_COOLDOWN_MINUTES` | 30 | Per-fingerprint alert cooldown |
| `RISK_WINDOW_MINUTES` | 60 | Rolling window for hit counting |
| `RSS_INGEST_INTERVAL_MINUTES` | 2 | Beat schedule for RSS ingestion |
| `GDELT_INGEST_INTERVAL_MINUTES` | 5 | Beat schedule for GDELT ingestion |
| `RISK_COMPUTE_INTERVAL_MINUTES` | 5 | Beat schedule for risk computation |
| `RSS_QUERIES` | JSON array | Search terms for Google News RSS |
| `GDELT_QUERIES` | JSON array | Search terms for GDELT API |
| `YOUTUBE_STREAMS` | JSON array | YouTube live stream links shown in UI |

## Security Model

All four required secrets must be set in `.env` before starting — there are no insecure defaults:

| Variable | Purpose |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | Database credentials |
| `REDIS_PASSWORD` | Redis auth (`--requirepass`); embedded in broker URL |
| `API_KEY` | Sent by clients in `X-API-Key` header; required on all endpoints except `/health` |

Generate secrets with: `python -c "import secrets; print(secrets.token_hex(32))"`

Other security measures in place:
- All containers run as non-root (`appuser`)
- CORS locked to `http://localhost:8501` and `http://ui:8501`
- `/items` rate-limited to 30 req/min; all other endpoints 60 req/min (`slowapi`)
- `category` query param validated against the 5 known values via `Literal` type
- External article URLs sanitized to `http`/`https` only before rendering in UI and Discord embeds
- Discord webhook errors log only the exception type (not the URL/token)
- Celery tasks hard-killed after 3 min (`task_time_limit=180`)
- Container resource limits: worker/db 512 MB, api/ui 256 MB

## Known Gotchas

- The RedBeat scheduler package is published on PyPI as `celery-redbeat`, not `redbeat`. [worker/requirements.txt](worker/requirements.txt) uses `celery-redbeat==2.2.0`; the import name inside the code remains `redbeat`.
- The `version:` top-level key in `docker-compose.yml` is obsolete in modern Docker Compose and has been removed.

## Key Files

- [worker/app/risk.py](worker/app/risk.py) — Category definitions and risk scoring formula
- [worker/app/tasks.py](worker/app/tasks.py) — Ingest, compute, and alert task implementations
- [worker/app/celery_app.py](worker/app/celery_app.py) — Celery/RedBeat configuration and beat schedule
- [worker/app/alerting/discord.py](worker/app/alerting/discord.py) — Discord embed builder and cooldown logic
- [api/app/main.py](api/app/main.py) — FastAPI app with all five endpoints
- [api/app/crud.py](api/app/crud.py) — All database read queries
- [ui/app/streamlit_app.py](ui/app/streamlit_app.py) — Entire dashboard in a single file

### UI Conventions

- **Layout:** `centered` (mobile-friendly); sidebar collapsed by default.
- **Timezone:** All timestamps displayed in **Bahrain Time (UTC+3)** via the `_to_bht()` helper.
- **News cards:** Show snippet as main body text (HTML-stripped via `_strip_html()`); published date shown in BHT; no raw URL link.
- **Snippet HTML:** Google News RSS returns HTML-encoded snippets — `_strip_html()` removes tags and decodes entities before display.
