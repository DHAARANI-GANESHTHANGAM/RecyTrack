# RecyTrack

**Recycling Data Quality & Material Traceability Platform**

RecyTrack imports recycling-operation records, standardizes and validates them, keeps invalid records for review instead of deleting them, and reconciles material quantities across receiving, processing, inventory and shipment events.

> This is a portfolio project inspired by recycling and material-recovery operations. It is not an internal company specification. It uses no private company systems or data. **All facility event data in `data/fixtures/` is synthetic.**

## Status

| Milestone | Scope | State |
|---|---|---|
| M1 Data contract | Event schema, clean and corrupted CSV fixtures, labeled expected outcomes | ✔️ done |
| M2 Ingestion | CSV reader, run ID, immutable raw records, run summary | ✔️ done |
| M3 Validation | Normalization, VAL-001…009, quarantine/flag, idempotent re-import | ✔️ done |
| M4 Database + API | PostgreSQL tables, FastAPI endpoints, review audit trail, CSV export, Docker Compose | ✔️ done |
| M5 Reconciliation | Material-flow balance with tolerance and NEEDS_DATA, snapshots traceable to their events | ✔️ done |
| M6 Dashboard | React views for runs, records, exceptions and review, metrics, reconciliation | ✔️ done |
| M7 Reliability | Simulated API source, bounded retries, VAL-010 source freshness, structured logs and request ids, Docker and CI hardening | ✔️ done |
| M8 | Demo and evidence | planned |

## Architecture

```
Browser ──► React dashboard  (frontend/, Vite dev server or nginx in Docker)
                 │  same-origin /api/v1/... (proxied, no CORS)
                 ▼
CSV upload ──► FastAPI  (app/main.py: request ids + request log; app/api/routes.py)
                 │                     ▲
                 │                     │ HTTP GET /v1/events?since=…   (bounded retries, timeout)
                 │      Simulated source (simulator/, separate service, SIMULATED synthetic data, :8001)
                 ▼
           pipeline.py   run_csv_ingestion / run_api_ingestion → process_raw_records (shared)
             ├─ ingestion/csv_reader.py     header check, raw rows + SHA-256 hash (read-only)
             ├─ ingestion/api_client.py     httpx client: retries only timeouts, connection errors, 5xx
             ├─ ingestion/api_records.py    API fields → contract fields, original item kept as _source_json
             ├─ normalization/normalize.py  whitespace, material alias, unit → kg, timestamp → UTC
             ├─ validation/rules.py         VAL-001…008 → ACCEPTED / FLAGGED / QUARANTINED
             └─ duplicate / conflict checks VAL-007, VAL-009
                 │
                 ▼
           database/repository.py ──► PostgreSQL
             ingestion_runs · raw_records · material_events · validation_issues · audit_events
                 │
                 ▼
           reconciliation/service.py   load candidate events, save snapshot + linked events + audit row
             └─ reconciliation/engine.py   pure balance: REC-001…004 → WITHIN_TOLERANCE / NEEDS_REVIEW / NEEDS_DATA
             reconciliations · reconciliation_events
                 │
           validation/freshness.py   VAL-010 from ingestion_runs → FRESH / STALE / NEVER_SUCCEEDED
```

Duplicates are blocked twice: the pipeline checks known payload hashes, and the database has a unique
constraint on `(source_name, source_record_id, payload_hash)` in case two imports run at the same time.

## Quick start

### Option 1: Docker (PostgreSQL + simulated source + API + dashboard)

```bash
cp .env.example .env          # then change POSTGRES_PASSWORD
docker compose up --build
```

Open http://localhost:5173 for the dashboard and http://localhost:8000/docs for the interactive API documentation.
The simulated source runs at http://localhost:8001. See [docs/operations.md](docs/operations.md) for logs and fault injection.

### Option 2: Python only (no Docker)

Without `DATABASE_URL` the API uses a local SQLite file (`backend/recytrack.db`), so you can try it with nothing else installed.
Set `DATABASE_URL` to use PostgreSQL instead.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

uvicorn app.main:app --reload        # API on http://127.0.0.1:8000/docs
uvicorn simulator.main:app --port 8001   # optional, in another terminal: the simulated API source
pytest -q                            # run the tests
python -m app.pipeline ../data/fixtures/invalid_events.csv   # import without the API and print the run summary
```

### Try the demo flow (SRS Appendix B)

```bash
curl -F file=@data/fixtures/valid_events.csv   http://localhost:8000/api/v1/ingestion/csv
curl -F file=@data/fixtures/invalid_events.csv http://localhost:8000/api/v1/ingestion/csv
curl "http://localhost:8000/api/v1/quarantine?rule_code=VAL-004"
curl -F file=@data/fixtures/valid_events.csv   http://localhost:8000/api/v1/ingestion/csv   # re-import: duplicate_count = 10
curl http://localhost:8000/api/v1/metrics/quality
curl -o exceptions.csv http://localhost:8000/api/v1/reports/exceptions.csv

# reconciliation (M5)
curl -F file=@data/fixtures/reconciliation_scenarios.csv http://localhost:8000/api/v1/ingestion/csv
curl -X POST http://localhost:8000/api/v1/reconciliations -H "Content-Type: application/json" \
     -d '{"facility_id": "FAC-11", "material_code": "PLASTIC_FILM", "period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-31T23:59:59Z"}'
curl "http://localhost:8000/api/v1/reconciliations?status=NEEDS_REVIEW"

# simulated API source and source health (M7)
curl -X POST http://localhost:8000/api/v1/ingestion/simulated-api     # 200 received, 180 accepted, 14 quarantined, 6 flagged
curl http://localhost:8000/api/v1/sources/health
```

## API

| Method and path | Purpose |
|---|---|
| `POST /api/v1/ingestion/csv` | Upload a CSV (multipart field `file`). Returns the run with its counts. `415` for a non-CSV file, `413` if over 10 MB, `422` with the failed run for a malformed file. |
| `POST /api/v1/ingestion/simulated-api` | Import from the simulated API source. Optional body `{"since": "<ISO 8601 with offset>"}`; by default only events after the latest one already stored for `simulated_api`. `201` with the run. If the source is unreachable after the retries, or answers 4xx, the run is saved as FAILED and the answer is `502` with `{"detail": {"message", "run"}}`. |
| `GET /api/v1/ingestion/runs` | List runs, newest first (`status`, `page`, `page_size`) |
| `GET /api/v1/ingestion/runs/{run_id}` | One run |
| `GET /api/v1/records` | Search normalized events: `facility_id`, `material_code`, `event_type`, `source_name`, `status`, `batch_id`, `run_id`, `date_from`, `date_to`, paging |
| `GET /api/v1/quarantine` | Quarantined and flagged records with their issues. The same filters, plus `rule_code` and `review_status` |
| `GET /api/v1/quarantine/{event_id}` | Raw row, normalized values, issues, run and review history |
| `PATCH /api/v1/quarantine/{event_id}/review` | Record a decision: `{"review_status": "APPROVED" \| "REJECTED" \| "NEEDS_INFO" \| "OPEN", "actor_label": "...", "note": "..."}` |
| `GET /api/v1/metrics/quality` | Counts, rates, open exceptions and issues per rule (`run_id`, `started_from`, `started_to`), and `sources_stale` |
| `GET /api/v1/sources/health` | Freshness per source (VAL-010): last run and its status, last success, age, window, `FRESH` / `STALE` / `NEVER_SUCCEEDED`, and a message |
| `GET /api/v1/reports/exceptions.csv` | One row per validation issue, with the same filters as `/quarantine` |
| `GET /api/v1/reports/records.csv` | Filtered normalized events |
| `POST /api/v1/reconciliations` | Run a material-flow balance: `facility_id`, `material_code`, `period_start`, `period_end` (ISO 8601 with offset), optional `absolute_tolerance_kg`, `percent_tolerance`, `actor_label`. Saves a new snapshot and returns `201` with the full detail. `422` if `period_end <= period_start`, a datetime has no offset, the material code is unknown, or a tolerance is negative. |
| `GET /api/v1/reconciliations` | List snapshots, newest first (`facility_id`, `material_code`, `status`, paging) |
| `GET /api/v1/reconciliations/{id}` | Inputs, totals, `formula` with the numbers filled in, `tolerance_explanation`, status, reasons, and linked events grouped by role |
| `GET /api/v1/meta` | Valid values for dashboard dropdowns: event types, material codes, imported facilities, statuses, default tolerance |
| `GET /health` | Service and database availability (`503` if the database is down) |

Every response carries an `X-Request-ID` header (the caller's, if it sent a valid one).

Quantities are returned as decimal strings (e.g. `"453.59237"`) so no precision is lost. Timestamps are UTC.

## Reconciliation

A reconciliation balances one facility and one material over a period, using physical stock counts
(`INVENTORY_COUNT` events) at both ends. All quantities are in kg (`quantity_kg`) and use `Decimal`:

```
expected_closing_kg = opening_stock_kg
                    + receipts_kg + production_kg + adjustments_kg   (adjustments keep their sign)
                    - shipments_kg - losses_kg - consumption_kg
variance_kg         = closing_stock_kg - expected_closing_kg
throughput_kg       = opening_stock_kg + receipts_kg + production_kg
tolerance_kg        = max(absolute_kg, throughput_kg × percent_of_throughput / 100)    default max(5 kg, 1.0%)
```

- **Opening count**: the latest counted `INVENTORY_COUNT` at or before `period_start`. **Closing count**: the latest
  one after `period_start` and at or before `period_end`. Flows are the events after the opening count up to and
  including the closing count. A count reflects stock after every event with the same timestamp.
- **Which events count**: `ACCEPTED` events, and `FLAGGED` events whose issues are all `APPROVED`. Quarantined,
  rejected and unreviewed events are left out of the totals but listed in the result with the reason.
- **Status**: `NEEDS_DATA` if a count is missing or conflicting, or an exception for that facility and material in
  the window is still `OPEN` or `NEEDS_INFO`. Otherwise `WITHIN_TOLERANCE` if `|variance_kg| <= tolerance_kg`
  (inclusive), else `NEEDS_REVIEW`. **`NEEDS_REVIEW` is a flag for a person to look at, not proof of an error.**
- Quantities are never corrected or invented to make a balance work (REC-004). Each run is saved as a new snapshot
  (`reconciliations`) with links to every event it used or left out (`reconciliation_events`) and an audit row.
  Running the check again, for example after a review decision, creates a new snapshot; old ones are never updated.

The scenarios in `data/fixtures/reconciliation_scenarios.csv` and their expected results in
`data/fixtures/expected_reconciliations.csv` are checked by the test suite.

## Reliability

- **Simulated source.** `backend/simulator/` is a separate FastAPI service (`uvicorn simulator.main:app --port 8001`)
  that serves 200 deterministic synthetic events, 10% deliberately faulty, with field names that differ from the CSV
  contract. It is labelled simulated everywhere. The expected outcome of every item is in
  `data/fixtures/simulated_expected_outcomes.csv` and checked by the tests. Contract and mapping:
  [docs/data_dictionary.md](docs/data_dictionary.md#simulated-api-source-contract-m7).
- **Bounded retries (NFR-02).** The client retries only connection errors, timeouts and 5xx responses, at most
  `SOURCE_RETRY_ATTEMPTS` (3) tries with exponential backoff (0.5 s, then 1 s), each try limited to `SOURCE_TIMEOUT_S`
  (5 s). A 4xx is reported at once. Each retry is logged as a WARNING. Retries are safe because reads are idempotent and
  re-imports create no new events (VAL-007).
- **Failures are recorded, not crashes.** If the source stays unavailable, the run is saved as `FAILED` with an
  actionable `error_summary` and the API answers `502`.
- **Source freshness (VAL-010).** `GET /api/v1/sources/health` compares each source's last successful import with its
  window (`SOURCE_FRESHNESS_HOURS`: csv 168 h, simulated_api 24 h). See
  [docs/validation_rules.md](docs/validation_rules.md#source-freshness-val-010).
- **Structured logs.** `LOG_FORMAT=json` (the default in Docker) writes one JSON object per line with `ts`, `level`,
  `logger`, `message` and fields: one line per request (`method`, `path`, `status`, `duration_ms`, `request_id`), and
  lines for import start and end, every retry and every reconciliation. Payloads, raw values, connection strings and
  passwords are never logged; a test checks this.
- **Request ids.** `X-Request-ID` is read (or created), returned on the response, and added to every log line of that
  request.
- **Docker and CI.** Compose health checks for `api` and `simulator`; `web` waits for a healthy `api`. CI has a
  `docker` job (`docker compose config -q` and `docker compose build`), and also runs the simulated-import and
  freshness tests on PostgreSQL.

How to run, read the logs, inject faults and interpret each error: [docs/operations.md](docs/operations.md).

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `recytrack`, *(required)*, `recytrack` | Docker Compose database (set in `.env`) |
| `DATABASE_URL` | local SQLite file | API database |
| `SIMULATED_SOURCE_URL` | `http://127.0.0.1:8001` | Simulated source base URL (`http://simulator:8001` in Compose) |
| `SOURCE_RETRY_ATTEMPTS` | `3` | Total tries per request to the source |
| `SOURCE_RETRY_BACKOFF_S` | `0.5` | First wait between tries; doubles each time |
| `SOURCE_TIMEOUT_S` | `5` | Timeout per request to the source, in seconds |
| `LOG_FORMAT` | `text` (`json` in Compose) | `json` or `text` |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `SIM_FAILURE_MODE` | `none` | Simulator fault injection: `none`, `always_500`, `flaky`, `slow` |
| `SIM_SLOW_SECONDS` | `10` | How long the simulator's `slow` mode sleeps |

## Dashboard

A React + TypeScript single-page app in [`frontend/`](frontend/README.md) that uses the API above, unchanged.
It shows a banner on every page: demo data is synthetic and not connected to any real facility.

**Run it in development** (two terminals):

```bash
cd backend && uvicorn app.main:app --reload     # API on :8000
cd frontend && npm ci && npm run dev            # dashboard on http://localhost:5173
```

Vite proxies `/api`, `/health` and `/docs` to the API, so the backend needs no CORS settings.
**With Docker**, `docker compose up --build` serves the built dashboard from nginx at http://localhost:5173.

| Page | What it does |
|---|---|
| Overview | Quality tiles and rates (including stale sources), issues-by-rule chart, latest runs and reconciliations, API health |
| Ingestion | Upload a CSV and see the run summary (including a failed run's error); paged runs list with each run's source |
| Records | Normalized events with filters kept in the URL; CSV export with the same filters |
| Exceptions | Quarantined and flagged records, filterable by rule code and review status; CSV export |
| Exception detail | Original row, normalized values, issues, run; record a review decision; review history |
| Reconciliation | Run a balance for a facility, material and UTC period (optional tolerance overrides); snapshot list |
| Reconciliation detail | Status and its meaning, reasons, balance inputs, tolerance, formula, linked events by role |
| Source health | Freshness per source (FRESH / STALE / NEVER SUCCEEDED), message, last run; an **Import from simulated API** button that shows the run, or the source error with the failed run |

Quantities are shown from the API's decimal strings, formatted on the string (never through floats). Times are shown in UTC.

The whole demo flow (SRS Appendix B) works in the browser: import `valid_events.csv`, import `invalid_events.csv`,
open a quarantined record to see its rule code and original value, re-import `valid_events.csv` to see 10 duplicates,
then import `reconciliation_scenarios.csv` and run a reconciliation for `FAC-11` / `PLASTIC_FILM` in October 2026.

<!-- Screenshots: add real captures here, e.g. docs/screenshots/overview.png, exception-detail.png, reconciliation-detail.png -->
| Overview | Exception detail | Reconciliation detail |
|---|---|---|
| *(screenshot to be added)* | *(screenshot to be added)* | *(screenshot to be added)* |

## Measured results

Measured on the development container. They are not a production guarantee.

| Check | Result |
|---|---|
| Frontend tests | 61 Vitest + React Testing Library tests; `npm run typecheck` and `npm run build` pass |
| Test suite | 219 backend tests pass on SQLite. The 28 M4 API tests also pass on PostgreSQL 16; the reconciliation, simulated-import and freshness API tests run on PostgreSQL in CI |
| Reconciliation fixtures (`expected_reconciliations.csv`) | All 7 scenarios get the expected status, variance and tolerance |
| Labeled fixtures (`expected_outcomes.csv`) | All 25 rows get the expected status and rule codes (15 faulty-file rows, 10 clean rows; 0 clean rows flagged) |
| Simulated source (`simulated_expected_outcomes.csv`) | All 200 items get the expected status and rule codes (20 faulty, 180 clean; 0 clean items flagged); a re-import adds 0 events |
| 10,000-row synthetic CSV via the API on PostgreSQL 16 (target < 30 s, NFR-08) | First import 3.9 s; re-import 1.0 s with 10,000 duplicates and 0 new events |

## Documentation

- [Data dictionary](docs/data_dictionary.md): CSV contract and normalized fields
- [Validation rules](docs/validation_rules.md): rule codes, severities, review statuses, constants and policies
- [`data/fixtures/expected_outcomes.csv`](data/fixtures/expected_outcomes.csv): labeled expected status and rule codes for every fixture row, checked by the test suite
- [`data/fixtures/expected_reconciliations.csv`](data/fixtures/expected_reconciliations.csv): expected status, variance and tolerance for every reconciliation scenario

## Known limitations

- The schema is created on startup with `create_all`; there are no migrations yet (Alembic can be added when the schema starts changing).
- Imports run synchronously in the request; very large files would need a background job.
- There is no authentication. This is a single-user local demo (SRS §16).
- Only `kg` and `lb`, and two materials (plastic film, recycled resin), are supported.
- Reconciliation has no yield or moisture modeling: each material is balanced on its own, and there is no
  film → resin yield calculation. `CONSUMPTION` of film and `PRODUCTION` of resin are not linked.
- Stock counts are point-in-time. A balance is only as good as its opening and closing counts.
- Events with an unknown material or an unparseable timestamp cannot be placed in a balance, so they do not
  appear in a reconciliation; they remain visible in `/quarantine`.
- The dashboard has no login and no live updates; refresh or use Retry to reload data.
- The only API source is **simulated**: a local test service with synthetic data, not a real external system.
- There is no scheduler yet: imports (CSV or simulated API) are triggered manually, so a source becomes STALE if nobody
  imports. Freshness is computed when asked; there are no alerts.
- The simulated source pages on its event time with an exclusive `since`, so events sharing a timestamp across a page
  boundary could be skipped. With 200 events and the client's page size of 1000 this does not happen.
- Without `since`, the cursor is the latest *stored* event time; items with an unparseable timestamp do not move it,
  so they may be fetched again and counted as duplicates.
