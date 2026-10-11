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
                 │
                 ▼
           reconciliation/service.py   load candidate events, save snapshot + linked events + audit row
             └─ reconciliation/engine.py   pure balance: REC-001…004 → WITHIN_TOLERANCE / NEEDS_REVIEW / NEEDS_DATA
             reconciliations · reconciliation_events
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

# reconciliation (M5)
curl -F file=@data/fixtures/reconciliation_scenarios.csv http://localhost:8000/api/v1/ingestion/csv
curl -X POST http://localhost:8000/api/v1/reconciliations -H "Content-Type: application/json" \
     -d '{"facility_id": "FAC-11", "material_code": "PLASTIC_FILM", "period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-31T23:59:59Z"}'
curl "http://localhost:8000/api/v1/reconciliations?status=NEEDS_REVIEW"
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
| `POST /api/v1/reconciliations` | Run a material-flow balance: `facility_id`, `material_code`, `period_start`, `period_end` (ISO 8601 with offset), optional `absolute_tolerance_kg`, `percent_tolerance`, `actor_label`. Saves a new snapshot and returns `201` with the full detail. `422` if `period_end <= period_start`, a datetime has no offset, the material code is unknown, or a tolerance is negative. |
| `GET /api/v1/reconciliations` | List snapshots, newest first (`facility_id`, `material_code`, `status`, paging) |
| `GET /api/v1/reconciliations/{id}` | Inputs, totals, `formula` with the numbers filled in, `tolerance_explanation`, status, reasons, and linked events grouped by role |
| `GET /health` | Service and database availability (`503` if the database is down) |

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

## Measured results

Measured on the development container. They are not a production guarantee.

| Check | Result |
|---|---|
| Test suite | 163 tests pass on SQLite. The 28 M4 API tests also pass on PostgreSQL 16; the 22 reconciliation API tests run on PostgreSQL in CI |
| Reconciliation fixtures (`expected_reconciliations.csv`) | All 7 scenarios get the expected status, variance and tolerance |
| Labeled fixtures (`expected_outcomes.csv`) | All 25 rows get the expected status and rule codes (15 faulty-file rows, 10 clean rows; 0 clean rows flagged) |
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
- The dashboard is not built yet.
