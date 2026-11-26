# Operations

How to tell whether DevPilot is healthy, and how to follow one request through the logs. Deployment,
backups and recovery are **not documented yet** (see [`ROADMAP.md`](../ROADMAP.md)).

## Health endpoints

All under `/api/v1`, with no sign-in needed.

| Endpoint | Checks | Status codes | Use it for |
|---|---|---|---|
| `/health/live` | nothing but that the process answers | 200 | a supervisor deciding whether to restart the API |
| `/health/ready` | PostgreSQL and Redis | 200 `ready`, 503 `not_ready` | a load balancer deciding whether to send traffic |
| `/health` | PostgreSQL and Redis, plus product and environment | 200 `ok`, 503 `degraded` | the status panel in the web app |

Liveness deliberately ignores the database and Redis: if it didn't, a database outage would make a
supervisor restart perfectly healthy API processes.

Readiness reports `database` and `redis` as `ok` or `down` and never the reason. The reason is in
the log. It does **not** check that a worker is running, that migrations are applied, or that the AI
provider answers.

```powershell
curl.exe -i http://localhost:8001/api/v1/health/ready
```

## Request ids

Every response has an `X-Request-ID` header, and every log line written while handling that request
carries the same `request_id`. When something fails with a 500, the message names the id:

```
Internal server error (request id: 8dc0ad9b5e7e4868b25e18d0ac25e668)
```

The web app shows that text, so a user can quote it and you can search for it. To follow a request,
save the API output to a file and search for the id:

```powershell
uvicorn app.main:app --reload --port 8001 --no-access-log 2>&1 | Tee-Object api.log
Select-String -Path api.log -Pattern "8dc0ad9b5e7e4868b25e18d0ac25e668"
```

`--no-access-log` switches off uvicorn's own non-JSON access lines, because the app writes its own.

## Log format

One JSON object per line:

```json
{"ts": "2026-11-24T09:03:26.911000+00:00", "level": "INFO", "logger": "app.request", "message": "request", "request_id": "ff679b8d5fee49fba438c2ca6c7936cb", "http": {"method": "GET", "path": "/api/v1/nope", "status": 404, "duration_ms": 72.0}}
```

- `request_id` is present only on lines written while handling a request (not in worker jobs).
- `http` is present only on the access line. It never holds the query string, headers or body.
- `audit` is present only on `app.audit` lines, one per audit-log event, with ids and the action but
  no names or emails (see [`AUDIT.md`](AUDIT.md)). Its `request_id` matches the audit entry's.
- Health probes are logged at `DEBUG`; set `LOG_LEVEL=DEBUG` to see them.
- A failed health check is one `WARNING` line naming the error class. The traceback is at `DEBUG`.

## Settings that affect operations

| Setting | Default | Effect |
|---|---|---|
| `ENVIRONMENT` | `development` | `production` turns on HSTS and switches off the API docs |
| `LOG_LEVEL` | `INFO` | `DEBUG` also shows probes and health-check tracebacks |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | how long a database connection attempt may take |
| `AI_ORG_DAILY_REQUEST_LIMIT` | `0` | cap on Ask, review and CI requests per workspace per UTC day; 0 is no cap |

## Tables that grow

- `audit_logs` grows with activity and is kept until the workspace is deleted. There is no retention
  setting yet.
- `rate_counters` cleans itself: each new window deletes that counter's finished windows, so it holds
  roughly one row per active person and feature.

## Not available yet

Metrics, tracing, queue-depth and worker health, error monitoring (Sentry), database pool
monitoring, backups and restore tests. They are on the roadmap, and none of them is claimed here.
