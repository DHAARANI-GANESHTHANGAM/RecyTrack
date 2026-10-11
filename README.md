# RecyTrack

**Recycling Data Quality & Material Traceability Platform**

RecyTrack imports recycling-operation records, standardizes and validates them, keeps invalid records for review instead of deleting them, and (later) reconciles material quantities across receiving, processing, inventory and shipment events.

> This is a portfolio project inspired by recycling and material-recovery operations. It is not an internal company specification. It uses no private company systems or data. **All facility event data in `data/fixtures/` is synthetic.**

## Status

| Milestone | Scope | State |
|---|---|---|
| M1 Data contract | Event schema, clean and corrupted CSV fixtures, labeled expected outcomes | ✔️ done |
| M2 Ingestion | CSV reader, run ID, immutable raw records, run summary | ✔️ done |
| M3 Validation | Normalization, VAL-001…009, quarantine/flag, idempotent re-import | ✔️ done |
| M4 Database + API | PostgreSQL tables, FastAPI endpoints, review audit trail, CSV export, Docker Compose | ✔️ done |
| M5 Reconciliation | Material-flow balance with tolerance and NEEDS_DATA | next |
| M6 Dashboard | React views for runs, exceptions, metrics, reconciliation | planned |
| M7–M8 | Reliability, CI hardening, demo and evidence | planned |

## Architecture

```
CSV upload ──► FastAPI  (app/main.py, app/api/routes.py)
                 │
                 ▼
           pipeline.py
             ├─ ingestion/csv_reader.py     header check, raw rows + SHA-256 hash (read-only)
             ├─ normalization/normalize.py  whitespace, material alias, unit → kg, timestamp → UTC
             ├─ validation/rules.py         VAL-001…008 → ACCEPTED / FLAGGED / QUARANTINED
             └─ duplicate / conflict checks VAL-007, VAL-009
                 │
                 ▼
           database/repository.py ──► PostgreSQL
             ingestion_runs · raw_records · material_events · validation_issues · audit_events
```

Duplicates are blocked twice: the pipeline checks known payload hashes, and the database has a unique
constraint on `(source_name, source_record_id, payload_hash)` in case two imports run at the same time.

## Quick start

### Option 1: Docker (PostgreSQL + API)

```bash
cp .env.example .env          # then change POSTGRES_PASSWORD
docker compose up --build
```

Open http://localhost:8000/docs for the interactive API documentation.

### Option 2: Python only (no Docker)

Without `DATABASE_URL` the API uses a local SQLite file (`backend/recytrack.db`), so you can try it with nothing else installed.
Set `DATABASE_URL` to use PostgreSQL instead.

```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

uvicorn app.main:app --reload        # API on http://127.0.0.1:8000/docs
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
```

## API

| Method and path | Purpose |
|---|---|
| `POST /api/v1/ingestion/csv` | Upload a CSV (multipart field `file`). Returns the run with its counts. `415` for a non-CSV file, `413` if over 10 MB, `422` with the failed run for a malformed file. |
| `GET /api/v1/ingestion/runs` | List runs, newest first (`status`, `page`, `page_size`) |
| `GET /api/v1/ingestion/runs/{run_id}` | One run |
| `GET /api/v1/records` | Search normalized events: `facility_id`, `material_code`, `event_type`, `source_name`, `status`, `batch_id`, `run_id`, `date_from`, `date_to`, paging |
| `GET /api/v1/quarantine` | Quarantined and flagged records with their issues. The same filters, plus `rule_code` and `review_status` |
| `GET /api/v1/quarantine/{event_id}` | Raw row, normalized values, issues, run and review history |
| `PATCH /api/v1/quarantine/{event_id}/review` | Record a decision: `{"review_status": "APPROVED" \| "REJECTED" \| "NEEDS_INFO" \| "OPEN", "actor_label": "...", "note": "..."}` |
| `GET /api/v1/metrics/quality` | Counts, rates, open exceptions and issues per rule (`run_id`, `started_from`, `started_to`) |
| `GET /api/v1/reports/exceptions.csv` | One row per validation issue, with the same filters as `/quarantine` |
| `GET /api/v1/reports/records.csv` | Filtered normalized events |
| `GET /health` | Service and database availability (`503` if the database is down) |

Quantities are returned as decimal strings (e.g. `"453.59237"`) so no precision is lost. Timestamps are UTC.

## Measured results

Measured on the development container. They are not a production guarantee.

| Check | Result |
|---|---|
| Test suite | 102 tests pass on SQLite; the 28 API tests also pass on PostgreSQL 16 |
| Labeled fixtures (`expected_outcomes.csv`) | All 25 rows get the expected status and rule codes (15 faulty-file rows, 10 clean rows; 0 clean rows flagged) |
| 10,000-row synthetic CSV via the API on PostgreSQL 16 (target < 30 s, NFR-08) | First import 3.9 s; re-import 1.0 s with 10,000 duplicates and 0 new events |

## Documentation

- [Data dictionary](docs/data_dictionary.md): CSV contract and normalized fields
- [Validation rules](docs/validation_rules.md): rule codes, severities, review statuses, constants and policies
- [`data/fixtures/expected_outcomes.csv`](data/fixtures/expected_outcomes.csv): labeled expected status and rule codes for every fixture row, checked by the test suite

## Known limitations

- The schema is created on startup with `create_all`; there are no migrations yet (Alembic can be added when the schema starts changing).
- Imports run synchronously in the request; very large files would need a background job.
- There is no authentication. This is a single-user local demo (SRS §16).
- Only `kg` and `lb`, and two materials (plastic film, recycled resin), are supported.
- Reconciliation, the API and the dashboard are not built yet.
