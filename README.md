# GCC Dashboard — U.S.–Iran Conflict Escalation Monitor

A **production-ready MVP** for monitoring escalation risk related to the U.S.–Iran conflict.  
All services run as a single **Docker Compose** stack.

---

## Architecture

```
┌────────────┐    ┌──────────────┐    ┌────────────────────┐
│  Streamlit │───▶│   FastAPI    │───▶│   PostgreSQL (db)  │
│    (ui)    │    │    (api)     │    └────────────────────┘
└────────────┘    └──────────────┘             ▲
                                               │
                  ┌──────────────┐    ┌────────┴───────────┐
                  │ Celery worker│───▶│   Redis (broker)   │
                  │  + beat      │    └────────────────────┘
                  └──────────────┘
```

| Service  | Port  | Description                                  |
|----------|-------|----------------------------------------------|
| `db`     | 5432  | PostgreSQL 16 – persistent storage           |
| `redis`  | 6379  | Redis 7 – Celery broker + result backend     |
| `api`    | 8000  | FastAPI – data endpoints for the UI          |
| `worker` | —     | Celery worker + beat scheduler               |
| `ui`     | 8501  | Streamlit dashboard                          |

---

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/martonz/GCC-Dashboard.git
cd GCC-Dashboard
cp .env.example .env
```

Edit `.env` and set your **Discord webhook URL** (required for alerts):

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### 2. Run

```bash
docker compose up --build
```

- Dashboard: http://localhost:8501  
- API docs:   http://localhost:8000/docs

### 3. Stop

```bash
docker compose down          # keep data
docker compose down -v       # remove data volumes too
```

---

## Environment Variables

Copy `.env.example` to `.env`. All variables have sane defaults except `DISCORD_WEBHOOK_URL`.

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | `postgres` | DB user |
| `POSTGRES_PASSWORD` | `postgres` | DB password |
| `POSTGRES_DB` | `wardb` | DB name |
| `DISCORD_WEBHOOK_URL` | *(empty)* | Discord incoming webhook for alerts |
| `RISK_WINDOW_MINUTES` | `60` | Rolling window for risk computation |
| `ALERT_RISK_THRESHOLD` | `70` | RiskIndex >= this triggers alert |
| `ALERT_DELTA_THRESHOLD` | `20` | Risk rise >= this in 30 min triggers alert |
| `ALERT_KINETIC_HITS` | `3` | Kinetic hits from distinct domains triggers alert |
| `ALERT_COOLDOWN_MINUTES` | `30` | Minutes before same alert can re-fire |
| `RSS_QUERIES` | *(see example)* | JSON array of Google News RSS queries |
| `GDELT_QUERIES` | *(see example)* | JSON array of GDELT search queries |
| `GDELT_MAX_RECORDS` | `100` | Max articles per GDELT request (max 250) |
| `RSS_INGEST_INTERVAL_MINUTES` | `2` | RSS ingestion cadence |
| `GDELT_INGEST_INTERVAL_MINUTES` | `5` | GDELT ingestion cadence |
| `RISK_COMPUTE_INTERVAL_MINUTES` | `5` | Risk recompute cadence |
| `YOUTUBE_STREAMS` | *(5 channels)* | JSON array of {name, url} objects |

---

## How Alerts Work

Alerts are evaluated every `RISK_COMPUTE_INTERVAL_MINUTES` minutes. Three trigger conditions:

| Condition | Default | Alert type |
|---|---|---|
| `RiskIndex >= ALERT_RISK_THRESHOLD` | 70 | `risk_threshold` |
| Risk rose >= `ALERT_DELTA_THRESHOLD` in last 30 min | 20 | `delta_spike` |
| >= `ALERT_KINETIC_HITS` kinetic items from distinct domains | 3 | `kinetic_cluster` |

Each Discord alert includes:
- Risk value + 30-minute delta
- Top 3 driving headlines (title, source, link, categories)

**Cool-down / deduplication:** the same alert fingerprint (type + risk bucket) will not re-fire within `ALERT_COOLDOWN_MINUTES` (default 30 min). All alerts are recorded in the `alerts` table for audit.

---

## Adding RSS Queries

Edit `RSS_QUERIES` in `.env`:

```
RSS_QUERIES=["Iran US strike missile", "Strait Hormuz tanker", "Iran nuclear IAEA"]
```

Each query becomes `https://news.google.com/rss/search?q=<QUERY>&hl=en-US&gl=US&ceid=US:en`.  
Keep queries short (under ~150 chars URL-encoded) to avoid HTTP 414 errors.

---

## Adding GDELT Queries

Edit `GDELT_QUERIES` in `.env`:

```
GDELT_QUERIES=["Iran US war strike missile Hormuz", "Iran nuclear ceasefire diplomacy"]
```

These are passed to the GDELT 2.1 Doc API — no API key required.

---

## Adding YouTube Channels

Edit `YOUTUBE_STREAMS` in `.env` (JSON array of objects with `name` and `url`):

```json
[
  {"name": "Al Jazeera English", "url": "https://www.youtube.com/@AlJazeeraEnglish/live"},
  {"name": "BBC News",           "url": "https://www.youtube.com/@BBCNews/live"},
  {"name": "CNN",                "url": "https://www.youtube.com/@CNN/live"},
  {"name": "Sky News",           "url": "https://www.youtube.com/@SkyNews/live"},
  {"name": "France 24",          "url": "https://www.youtube.com/@FRANCE24/live"}
]
```

The UI attempts to embed each channel's live feed and always provides a clickable link as fallback.

---

## Risk Scoring

Risk is computed every 5 minutes over the last `RISK_WINDOW_MINUTES` (default 60 min) of ingested items.

### Category keywords

| Category | Weight | Sample keywords |
|---|---|---|
| `kinetic` | +5 | strike, missile, drone, rocket, bombing |
| `shipping` | +4 | Hormuz, tanker, mine, blockade, naval |
| `casualties` | +4 | killed, dead, wounded, casualties |
| `nuclear` | +6 | nuclear, enrichment, IAEA, IRGC, mobilization |
| `deescalation` | -3 | ceasefire, talks, truce, diplomacy |

### Formula

```
RiskIndex = clamp(0, 100,
  10
  + 8 x kinetic_hits
  + 6 x shipping_hits
  + 7 x nuclear_hits
  + 5 x casualty_hits
  - 4 x deescalation_hits
)
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /health | Health check |
| GET | /risk/latest | Latest risk snapshot |
| GET | /risk/series?hours=6 | Risk time series (up to 168 h) |
| GET | /items | Paginated items (filters: source_type, category, since_minutes) |
| GET | /alerts | Recent alerts |

Interactive docs: http://localhost:8000/docs

---

## Data Model

### `items`
Ingested article metadata. Deduped by `url_hash`:
- If URL available: sha256(url)
- Otherwise: sha256(title + source_name + 30-min time bucket)

### `risk_timeseries`
Snapshot of RiskIndex every compute cycle with per-category hit counts and top-3 drivers.

### `alerts`
Record of every evaluated alert (sent or skipped), used for cooldown deduplication.

---

## Development

Run services individually (requires a running Postgres and Redis):

```bash
# API
cd api && pip install -r requirements.txt
uvicorn app.main:app --reload

# Worker
cd worker && pip install -r requirements.txt
celery -A app.celery_app worker --beat --loglevel=debug

# UI
cd ui && pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

---

## License

MIT
