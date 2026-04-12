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
                      └──────────────┘    └────────────────────┘
                        ▲
                        │
                      ┌──────────────┐
                      │ Celery beat  │
                      └──────────────┘
```

| Service  | Port  | Description                                  |
|----------|-------|----------------------------------------------|
| `db`     | 5432  | PostgreSQL 16 – persistent storage           |
| `redis`  | 6379  | Redis 7 – Celery broker + result backend     |
| `api`    | 8000  | FastAPI – data endpoints for the UI          |
| `worker` | —     | Celery worker (ingest + risk tasks)          |
| `beat`   | —     | Celery beat scheduler                         |
| `ui`     | 8501  | Streamlit dashboard                          |

---

## Quick Start

For day-to-day Docker operations (build/restart/logs/debug), see [DOCKER_COMMANDS.md](DOCKER_COMMANDS.md).

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

### Time zones

- **UI display timezone:** Bahrain (`Asia/Bahrain`, UTC+3)
- **Backend storage and scheduling:** UTC
- **UI item filter time basis:** affects item list filtering only, not the already-computed risk snapshot

This keeps database writes, filtering windows, and Celery scheduling consistent while showing operator-facing timestamps in Bahrain local time.

### Mobile layout

The Streamlit UI supports a mobile-friendly mode:

- Auto-detected from browser user-agent
- Manual override from sidebar: `Mobile layout`
- Visible banner under title when active: `Mobile layout: ON`
- In mobile mode, key sections stack vertically (risk overview, item cards, and stream cards)

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
| `GDELT_RETRY_WARN_THRESHOLD` | `3` | Warn when retries for one GDELT query reach this count |
| `RSS_INGEST_INTERVAL_MINUTES` | `2` | RSS ingestion cadence |
| `GDELT_INGEST_INTERVAL_MINUTES` | `5` | GDELT ingestion cadence |
| `RISK_COMPUTE_INTERVAL_MINUTES` | `5` | Risk recompute cadence |
| `YOUTUBE_STREAMS` | *(5 channels)* | JSON array of {name, url} objects |
| `API_BASE_URL` | `http://localhost:8000` | UI target for FastAPI |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery result backend |
| `DATABASE_URL` | `postgresql+psycopg://postgres:postgres@localhost:5432/wardb` | API/worker DB connection string |

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

**Cool-down / deduplication:** the same alert fingerprint (type + risk bucket) will not re-fire within `ALERT_COOLDOWN_MINUTES` (default 30 min). Alerts that pass trigger + cooldown checks are written to the `alerts` table; `sent` indicates whether webhook delivery succeeded.

---

## Adding RSS Queries

Edit `RSS_QUERIES` in `.env`:

```
RSS_QUERIES=["Iran US strike missile", "Strait Hormuz tanker ship", "Iran nuclear IAEA ceasefire"]
```

Each query becomes `https://news.google.com/rss/search?q=<QUERY>&hl=en-US&gl=US&ceid=US:en`.  
Keep queries short (under ~150 chars URL-encoded) to avoid HTTP 414 errors.

RSS snippet handling:

- Snippets are normalized to plain text (HTML tags removed)
- Embedded source tails are stripped from snippet text
- UI displays a larger snippet preview for better context

---

## Adding GDELT Queries

Edit `GDELT_QUERIES` in `.env`:

```
GDELT_QUERIES=["Iran United States war strike missile Hormuz", "Iran nuclear ceasefire diplomacy"]
```

These are passed to the GDELT 2.1 Doc API — no API key required.

### GDELT rate limits (429)

The worker now includes automatic retry/backoff for transient GDELT throttling:

- Retries up to 4 attempts per request
- Honors `Retry-After` when provided by GDELT
- Uses exponential backoff when `Retry-After` is absent

If 429 responses are still frequent, tune:

- `GDELT_INGEST_INTERVAL_MINUTES` upward (for example `5` -> `10`)
- `GDELT_MAX_RECORDS` downward (for example `100` -> `50`)
- Optionally set `GDELT_RETRY_WARN_THRESHOLD=2` for earlier warning visibility while tuning

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

Risk is computed every 5 minutes over the last `RISK_WINDOW_MINUTES` (default 60 min) using item `published_at` timestamps.
Items with missing `published_at` are excluded from risk computation.

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
| GET | /risk/series?hours=6&since_days=7 | Risk time series (supports `hours` or `since_days`) |
| GET | /items | Paginated items (filters: `source_type`, `category`, `since_days`, `since_minutes`, `time_basis`) |
| GET | /alerts | Recent alerts (supports `since_days`, `limit`) |

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
Record of alert attempts that passed trigger and cooldown checks, with delivery status in `sent`.

---

## Development

Run services individually (requires a running Postgres and Redis):

```bash
# API
cd api && pip install -r requirements.txt
uvicorn app.main:app --reload

# Worker
cd worker && pip install -r requirements.txt

# Terminal 1: worker
celery -A app.celery_app worker --loglevel=debug

# Terminal 2: beat scheduler
celery -A app.celery_app beat --loglevel=debug

# UI
cd ui && pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

### UI smoke test

After UI changes, a quick verification flow:

```bash
docker compose up -d --build ui
docker compose ps ui
curl -s -o /dev/null -w "ui_http_status=%{http_code}\n" http://localhost:8501
docker compose logs --tail=60 ui
```

Expected:

- `ui_http_status=200`
- UI service is `Up` in `docker compose ps`
- No startup tracebacks in recent UI logs

---

## Troubleshooting

### GDELT 429 Too Many Requests

Typical worker log:

```text
GDELT fetch failed for query='...': 429 Client Error: Too Many Requests
```

The worker already retries with backoff. If this keeps happening, reduce request pressure in `.env`:

```env
GDELT_INGEST_INTERVAL_MINUTES=10
GDELT_MAX_RECORDS=50
```

Then restart services:

```bash
docker compose up -d --build worker beat
```

Verify recovery:

```bash
# 1) Confirm worker/beat are running
docker compose ps worker beat

# 2) Watch recent logs for retries/successes
docker compose logs --tail=100 worker | grep -E "GDELT|rate-limited|invalid_json|reasons=|yielded|saved"

# 3) Confirm data is flowing to API
curl -s "http://localhost:8000/items?source_type=gdelt&limit=5" | jq 'length'
```

Expected outcome:

- Fewer or no repeated 429 failures
- Periodic successful GDELT ingestion messages in worker logs
- `/items?source_type=gdelt` returns non-zero results once ingestion cycles complete

### GDELT invalid JSON / empty body

Typical worker log:

```text
GDELT request error: Expecting value: line 1 column 1 (char 0). Retrying in 2s (attempt 1/4)
```

This usually means GDELT returned an empty or non-JSON body (often temporary upstream throttling/proxy behavior).
The worker now treats this as retryable and logs response diagnostics (status/content-type/body preview).
It also emits retry reason summaries, for example:

```text
GDELT fetch recovered for query='...' after retries=2 reasons={'invalid_json': 2}
```

If retries for a single query cross `GDELT_RETRY_WARN_THRESHOLD`, the worker also emits a pressure warning, for example:

```text
GDELT retry pressure high for query='test query' retries=2 threshold=2 reasons={'invalid_json': 2}
```

If this repeats frequently, apply the same pressure reduction as 429 handling:

```env
GDELT_INGEST_INTERVAL_MINUTES=10
GDELT_MAX_RECORDS=50
GDELT_RETRY_WARN_THRESHOLD=2
```

---

## License

MIT
