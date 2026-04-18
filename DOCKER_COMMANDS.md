# Docker Commands Reference (GCC Dashboard)

Run all commands from the repository root:

```bash
cd /Users/pmartonz/development/GCC-Dashboard
```

## Start and Rebuild

Rebuild and start everything:

```bash
docker compose up --build
```

Rebuild and restart only worker + beat (after worker code changes):

```bash
docker compose up -d --build worker beat
```

Rebuild and restart only API:

```bash
docker compose up -d --build api
```

Rebuild and restart only UI:

```bash
docker compose up -d --build ui
```

## Restart Without Rebuild

Use this when only env/config changed:

```bash
docker compose up -d worker beat api ui
```

Restart just worker + beat:

```bash
docker compose up -d worker beat
```

## Stop Stack

Stop containers, keep volumes/data:

```bash
docker compose down
```

Stop containers and remove volumes/data:

```bash
docker compose down -v
```

## Service Status

```bash
docker compose ps
```

## Logs

Follow all logs:

```bash
docker compose logs -f
```

Follow worker logs:

```bash
docker compose logs -f --tail=100 worker
```

Follow worker + beat logs:

```bash
docker compose logs -f --tail=100 worker beat
```

Follow API logs:

```bash
docker compose logs -f --tail=100 api
```

Only warnings/errors from worker:

```bash
docker compose logs -f --tail=200 worker | grep -E "WARNING|ERROR|CRITICAL"
```

GDELT-focused worker logs:

```bash
docker compose logs -f --tail=200 worker | grep -E "GDELT|rate-limited|invalid_json|reasons=|retry pressure|yielded|saved"
```

## Verify GDELT Data Flow

Check GDELT items are reaching API:

```bash
curl -s "http://localhost:8000/items?source_type=gdelt&limit=5" | jq 'length'
```

## Print .env Variables Used by Docker

Show resolved environment variables per service from the rendered Docker Compose config:

```bash
docker compose config --format json | python3 -c "
import json, sys
cfg = json.load(sys.stdin)
for svc, val in cfg.get('services', {}).items():
	env = val.get('environment', {})
	if env:
		print(f'--- {svc} ---')
		for k, v in env.items():
			print(f'  {k}={v}')
"
```

Show a service's runtime environment (example: worker):

```bash
docker compose run --rm worker env
```

Show fully resolved compose file with all substitutions:

```bash
docker compose convert
```

## Trigger Risk Compute Manually

```bash
docker compose exec -T worker celery -A app.celery_app call app.tasks.compute_risk
```

## UI Smoke Test

Use after UI code changes:

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

## Quick Notes

- You usually do not need `docker compose down` before `docker compose up -d --build ...`.
- If source code changes in api/worker/ui, rebuild the affected service.
- If only `.env` changes, restart affected services without `--build`.
