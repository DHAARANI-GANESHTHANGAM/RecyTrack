# Operations

How to run RecyTrack, read its logs, inject faults into the simulated source, and what each error means.
Everything here is a local demo with synthetic data.

## Run everything

### Docker Compose

```bash
cp .env.example .env              # then change POSTGRES_PASSWORD
docker compose up --build         # db, simulator, api, web
```

| Service | URL | Health check |
|---|---|---|
| `web` (dashboard, nginx) | http://localhost:5173 | starts once `api` is healthy |
| `api` (FastAPI) | http://localhost:8000/docs | `GET /health` (503 if the database is down) |
| `simulator` (simulated source) | http://localhost:8001/docs | `GET /health` |
| `db` (PostgreSQL 16) | `localhost:5432` | `pg_isready` |

`docker compose ps` shows each service's health. The API waits for the database to be healthy; it does not need the
simulator to start, and reports a clear error on import if the simulator is down.

### Without Docker

```bash
cd backend
uvicorn simulator.main:app --port 8001          # terminal 1: simulated source
uvicorn app.main:app --reload                   # terminal 2: API on :8000 (SQLite unless DATABASE_URL is set)
cd ../frontend && npm run dev                   # terminal 3: dashboard on :5173
```

### Import from the simulated source

From the dashboard: **Source health → Import from simulated API**. Or:

```bash
curl -X POST http://localhost:8000/api/v1/ingestion/simulated-api
curl -X POST http://localhost:8000/api/v1/ingestion/simulated-api \
     -H "Content-Type: application/json" -d '{"since": "2026-10-01T00:00:00Z"}'   # override the cursor
curl http://localhost:8000/api/v1/sources/health
```

Without `since`, only events newer than the latest one already stored for `simulated_api` are fetched, so a second
import normally receives 0 events. Imports are triggered manually; there is no scheduler yet.

## Environment variables

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `DATABASE_URL` | SQLite file `backend/recytrack.db` | api | PostgreSQL connection string. Never logged. |
| `SIMULATED_SOURCE_URL` | `http://127.0.0.1:8001` | api | Base URL of the simulated source (`http://simulator:8001` in Compose). |
| `SOURCE_RETRY_ATTEMPTS` | `3` | api | Total tries per request to the source (at least 1). |
| `SOURCE_RETRY_BACKOFF_S` | `0.5` | api | First wait between tries; doubles each time (0.5 s, 1 s, …). |
| `SOURCE_TIMEOUT_S` | `5` | api | Timeout per request to the source, in seconds. |
| `LOG_FORMAT` | `text` (`json` in Compose) | api | `json` or `text`. |
| `LOG_LEVEL` | `INFO` | api | `DEBUG`, `INFO`, `WARNING` or `ERROR`. |
| `SIM_FAILURE_MODE` | `none` | simulator | Fault injection, see below. |
| `SIM_SLOW_SECONDS` | `10` | simulator | How long `slow` mode sleeps. |

An invalid value (e.g. `SOURCE_RETRY_ATTEMPTS=abc` or `LOG_FORMAT=xml`) stops the API at startup with a message
naming the variable.

## Logs

The API writes one line per event to stdout. With `LOG_FORMAT=json` each line is a JSON object with `ts` (UTC),
`level`, `logger` and `message`, plus fields for the event. Every line written while handling a request carries that
request's `request_id`.

```bash
docker compose logs -f api
docker compose logs api | grep '"request_id": "abc-123"'      # everything for one request
```

| `message` (logger) | Fields | When |
|---|---|---|
| `request` (`recytrack.request`) | `method`, `path`, `status`, `duration_ms`, `request_id` | every HTTP request |
| `ingestion run started` (`app.pipeline`) | `run_id`, `source_name` | start of a CSV or API import |
| `ingestion run finished` (`app.pipeline`) | `run_id`, `source_name`, `status`, `received`, `accepted`, `quarantined`, `flagged`, `duplicates`, `duration_ms` | end of an import, including FAILED runs |
| `source request failed; retrying` (`app.ingestion.api_client`), WARNING | `attempt`, `max_attempts`, `reason`, `retry_delay_s`, `source_url` | each retry against the simulated source |
| `simulated source import failed` (`app.api.routes`), ERROR | `error_type` | the source could not be read; a FAILED run was saved |
| `reconciliation run` (`app.reconciliation.service`) | `reconciliation_id`, `facility_id`, `material_code`, `status`, `event_count`, `duration_ms` | every reconciliation |
| `Database error on <method> <path>: <class>` | | a database call failed |

**Request ids.** Send `X-Request-ID: <id>` (letters, digits, `.`, `_`, `-`, up to 64 characters) and the API uses it;
otherwise it creates one. It is returned in the `X-Request-ID` response header, so a user can quote it when reporting
a problem.

**What is never logged:** row payloads and raw values, the `error_summary` of a run (it can quote input), query
strings, connection strings and passwords. Database errors are logged by class name only, because their text can
contain SQL parameters. `tests/test_logging.py` checks this.

## Fault injection (simulated source)

```bash
SIM_FAILURE_MODE=flaky docker compose up simulator          # or: up -d --force-recreate simulator
SIM_FAILURE_MODE=always_500 uvicorn simulator.main:app --port 8001   # without Docker
```

| Mode | Behaviour of `/v1/events` | What the import does |
|---|---|---|
| `none` | normal | 201 |
| `flaky` | the first 2 requests after the simulator starts return 503 | retried; succeeds on the 3rd attempt (2 retry warnings) |
| `always_500` | every request returns 500 | 3 attempts, then 502 and a FAILED run |
| `slow` | sleeps `SIM_SLOW_SECONDS` (10 s) | each attempt times out after `SOURCE_TIMEOUT_S` (5 s); 502 after 3 attempts |

`/health` is never affected, so the container stays healthy. To test an unreachable source, stop it:
`docker compose stop simulator`.

## What each error means

| Where | Message (start) | Meaning and what to do |
|---|---|---|
| Import from simulated API, **502** | `Simulated source at … unreachable after 3 attempts (last error: …)` | Connection errors, timeouts or 5xx on every attempt. Check that the simulator is running (`docker compose ps`) and `SIMULATED_SOURCE_URL`. The run is saved as FAILED; nothing was imported. Retry when the source is back. |
| Import from simulated API, **502** | `Simulated source at … rejected the request with HTTP 4xx: …` | The request itself is wrong (e.g. a bad `since`). Not retried. Fix the request. |
| Import from simulated API, **502** | `… returned an unexpected response` | The URL answers, but not with the simulator's JSON. Check `SIMULATED_SOURCE_URL`. |
| Import, **409** | `These records were imported by another run at the same time` | Two imports raced. Re-run; already-imported rows are counted as duplicates. |
| CSV import, **422** | `CSV header does not match the contract …`, `File is empty …` | Whole-file problem. The run is FAILED; fix the file as the message says. |
| Any endpoint, **503** | `Database unavailable. Check that PostgreSQL is running …` | The database is down or `DATABASE_URL` is wrong. |
| Source health | `STALE: No successful import in 30.5 h; window is 24 h.` | VAL-010. Import from that source again, or investigate why its imports fail. |
| Source health | `… The latest run failed; see its error on the Ingestion page.` | The source is still inside its window, but the most recent import failed (its time is in **Last run**). See that run's `error_summary` on the Ingestion page. |
| Startup | `SOURCE_RETRY_ATTEMPTS='abc' is not valid …`, `LOG_FORMAT 'xml' is not supported …` | Fix the environment variable. |

Retries are safe: reading events is idempotent, and importing the same events twice creates no new events (VAL-007).
