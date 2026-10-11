# RecyTrack

**Recycling Data Quality & Material Traceability Platform**

RecyTrack imports recycling-operation records from CSV files and a simulated API, standardizes and validates them,
keeps invalid records in quarantine with a specific reason instead of deleting them, and reconciles material
quantities across receiving, processing, inventory and shipment events. A FastAPI backend with PostgreSQL does the
work; a React dashboard shows runs, exceptions, review decisions, reconciliations and source health. Every number in
this README comes from [`scripts/measure.py`](backend/scripts/measure.py) or a test run.

> **Synthetic data.** This is a portfolio project inspired by recycling and material-recovery operations. It uses no
> company data and no private systems, and it is not affiliated with or endorsed by any company. All facility event
> data in `data/fixtures/` and in the simulated source is synthetic.

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
| M8 Demo and evidence | Measurement script, measured results, architecture, demo script, acceptance checklist | ✔️ done |

## Screenshots

| Overview | Exceptions | Exception detail |
|---|---|---|
| ![Overview: quality tiles, issues by rule, latest runs](docs/screenshots/overview.png) | ![Exceptions list filtered by rule code](docs/screenshots/exceptions.png) | ![Exception detail: original row, issue, review history](docs/screenshots/exception-detail.png) |

| Reconciliation | Source health | API docs |
|---|---|---|
| ![Reconciliation detail: formula, tolerance, linked events](docs/screenshots/reconciliation.png) | ![Source health: freshness per source and simulated import](docs/screenshots/source-health.png) | ![Interactive API docs at /docs](docs/screenshots/api-docs.png) |

## Architecture

```mermaid
flowchart LR
    csv[CSV upload] --> api
    sim["Simulated API source<br/>(separate service)"] -- "HTTP, bounded retries" --> api
    api[FastAPI] --> ing[Ingestion]
    ing --> norm[Normalization]
    norm --> val[Validation]
    val --> db[(PostgreSQL)]
    db --> rec[Reconciliation]
    db --> met[Metrics and freshness]
    rec --> ui[React dashboard]
    met --> ui
    db --> ui
```

- **FastAPI** (`app/main.py`, `app/api/routes.py`): REST endpoints under `/api/v1`, request ids and one structured
  log line per request, upload type and size limits, and actionable errors that never leak SQL or connection strings.
- **Ingestion** (`app/ingestion/`, `app/pipeline.py`): reads a CSV or the simulated source into immutable raw records
  with a SHA-256 payload hash, stored before anything else happens. CSV and API share one processing loop and one
  run record. An unreadable source becomes a `FAILED` run, not a crash.
- **Normalization** (`app/normalization/`): trims text, maps material aliases to codes, converts `lb` to `kg` with an
  exact `Decimal` constant, and converts timestamps to UTC. The raw values are kept unchanged.
- **Validation** (`app/validation/`): rules VAL-001…VAL-009 give each record `ACCEPTED`, `FLAGGED` or `QUARANTINED`
  (or `DUPLICATE`); VAL-010 judges each source's freshness from its runs.
- **PostgreSQL** (`app/database/`): runs, raw records, events, issues, append-only audit events and reconciliation
  snapshots, through SQLAlchemy (SQLite for local use and tests).
- **Reconciliation** (`app/reconciliation/`): a pure `Decimal` material-flow balance with a tolerance, saved as a new
  snapshot linked to every event it used or left out.
- **React dashboard** (`frontend/`): Overview, Ingestion, Records, Exceptions, Reconciliation and Source health,
  using the API only.
- **Simulator** (`backend/simulator/`): a separate FastAPI service with 200 deterministic synthetic events (10%
  faulty) and fault injection, reached over real HTTP.

The longer version, one section per layer: [docs/architecture.md](docs/architecture.md).

## Key design decisions

- **Raw data is immutable.** Every input row is stored as received, with its hash and run, before normalization.
- **`Decimal` and UTC.** Quantities are never floats (in the database, the API's decimal strings, and the dashboard's
  formatting). Timestamps are stored in UTC; the source value is kept.
- **Quarantine instead of delete.** A bad record stays visible with a specific rule code and its original value.
- **Idempotency in two layers.** The pipeline skips exact duplicates by payload hash (VAL-007), and a database unique
  constraint on `(source_name, source_record_id, payload_hash)` catches two imports racing.
- **`NEEDS_DATA` instead of guessing.** A reconciliation with a missing or conflicting stock count, or an unresolved
  exception, says what is missing rather than reporting a variance.
- **Review decisions are audited and never overwrite data.** A decision is a separate audit row; source values do
  not change.
- **Bounded retries.** Only timeouts, connection errors and 5xx are retried, at most 3 tries with backoff; 4xx fails
  at once.
- **No secrets in logs.** Logs carry ids, counts and statuses, never payloads, raw values, connection strings or
  passwords (checked by `tests/test_logging.py`).

## Measured results

From [docs/results.md](docs/results.md), generated by `python -m scripts.measure --database-url … --out ../docs/results.md`
on 2026-10-11 (Python 3.13.5, Windows 11, 14 logical CPUs). CI re-runs the script on every push and fails if an
exact-match, idempotency or reconciliation check drops below 100%.

> The labeled sets were written by the developer together with the rules, so 100% shows that the rules behave
> **as designed** on known cases. It is **not** a real-world accuracy claim: real data would contain error types
> that are not in the fixtures.

**Labeled-set quality** (`expected_outcomes.csv` for the two CSV fixtures, `simulated_expected_outcomes.csv` for the
simulated source). Faulty = labeled status is not `ACCEPTED`; exact match = status and rule codes both equal the label.

| Set | Rows | Faulty | Detected | Detection rate | Clean | False positives | False-positive rate | Exact matches |
|---|---|---|---|---|---|---|---|---|
| `valid_events.csv` | 10 | 0 | 0 | n/a | 10 | 0 | 0.0% | 10 / 10 |
| `invalid_events.csv` | 15 | 13 | 13 | 100.0% | 2 | 0 | 0.0% | 15 / 15 |
| `simulated_api` | 200 | 20 | 20 | 100.0% | 180 | 0 | 0.0% | 200 / 200 |
| **Total** | 225 | 33 | 33 | 100.0% | 192 | 0 | 0.0% | 225 / 225 |

Per rule, the expected and found counts are equal for all nine rule codes (VAL-001…VAL-009); see
[results.md](docs/results.md#per-rule-all-sets).

**Idempotency** (each set imported twice; second import):

| Set | Received | Duplicates | New events |
|---|---|---|---|
| `valid_events.csv` | 10 | 10 | 0 |
| `invalid_events.csv` | 15 | 14 | 1 (the row without a `source_record_id`, which has no stable key and is re-evaluated by design) |
| `simulated_api` | 200 | 200 | 0 |

**Reconciliation scenarios:** 7 / 7 match the expected status, variance and tolerance in
`expected_reconciliations.csv` (balanced, imbalanced −80 kg vs 15 kg → `NEEDS_REVIEW`, inclusive boundary −15 kg,
missing closing count → `NEEDS_DATA`, pound conversion, a second material, and an open exception → `NEEDS_DATA`).

**Performance (NFR-08, target < 30 s for 10,000 rows).** A seeded 10,000-row synthetic CSV imported through
`POST /api/v1/ingestion/csv`, measured once on **SQLite 3.49.1** on the Windows 11 development machine above:

| Run | Seconds | Received | Accepted | Quarantined | Flagged | Duplicates | New events |
|---|---|---|---|---|---|---|---|
| First import | 6.58 | 10,000 | 5,006 | 3,156 | 1,838 | 0 | 10,000 |
| Re-import | 2.50 | 10,000 | 0 | 0 | 0 | 10,000 | 0 |

These timings depend on the machine and are not a production guarantee. A PostgreSQL measurement was not taken for
this README; run `python -m scripts.measure --database-url postgresql+psycopg://… --out ../docs/results.md` against an
empty database to get one.

**Tests** (latest local run, 2026-10-11, Windows 11, Python 3.13.5, Node 22.17.1):

| Suite | Result |
|---|---|
| Backend, SQLite (`pytest -q`) | 227 passed |
| Backend, PostgreSQL 16 (CI step: `test_api`, `test_reconciliation_api`, `test_api_ingestion`, `test_freshness`, 74 tests) | runs in CI; not run locally for this change |
| Frontend (`npm test -- --run`) | 61 passed in 8 files; `npm run typecheck` and `npm run build` pass |

## Quick start

### Option 1: Docker (PostgreSQL + simulator + API + dashboard)

```bash
cp .env.example .env          # then change POSTGRES_PASSWORD
docker compose up --build
```

Open http://localhost:5173 for the dashboard and http://localhost:8000/docs for the API docs.

### Option 2: without Docker (three terminals)

Without `DATABASE_URL` the API uses a local SQLite file (`backend/recytrack.db`). Set it to use PostgreSQL.

**Windows PowerShell**

```powershell
# terminal 1: simulated source
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn simulator.main:app --port 8001

# terminal 2: API on http://127.0.0.1:8000/docs
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload

# terminal 3: dashboard on http://localhost:5173
cd frontend
npm ci
npm run dev
```

**macOS / Linux**

```bash
# terminal 1: simulated source
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn simulator.main:app --port 8001

# terminal 2: API on http://127.0.0.1:8000/docs
cd backend && source .venv/bin/activate && uvicorn app.main:app --reload

# terminal 3: dashboard on http://localhost:5173
cd frontend && npm ci && npm run dev
```

### Tests and measurements

```bash
cd backend
pytest -q                           # backend tests (SQLite; set TEST_DATABASE_URL for PostgreSQL)
python -m scripts.measure           # quality, idempotency, reconciliation; exit code 1 on a regression
python -m scripts.measure --database-url postgresql+psycopg://user:pass@localhost:5432/empty_db --out ../docs/results.md
cd ../frontend
npm run typecheck && npm test -- --run && npm run build
```

The timing run needs an empty database (or `--reset`, which drops and recreates RecyTrack's tables in it). The
10,000-row file is generated in memory and never written to disk.

## Demo

A 5–7 minute walkthrough with exact expected numbers, talking points and likely interview questions:
[docs/demo_script.md](docs/demo_script.md).

## SRS acceptance checklist (§10)

| # | Acceptance criterion | ✔️ | Where it is shown |
|---|---|---|---|
| 1 | A valid fixture file imports and its raw rows are preserved | ✔️ | `tests/test_pipeline.py::test_valid_fixture_is_fully_accepted_and_raw_rows_preserved`, `tests/test_api.py::test_raw_rows_are_stored_exactly`; Exception detail → *Original row*; demo step 2 |
| 2 | Missing fields, invalid quantities, unsupported units, invalid event types and duplicate rows are handled by the documented rules | ✔️ | `tests/test_validation.py`, `tests/test_pipeline.py::test_labeled_expected_outcomes`; [results.md](docs/results.md) (225 / 225 exact matches); [validation_rules.md](docs/validation_rules.md); demo step 3 |
| 3 | Every quarantined record has a specific reason and can be traced to the original row and run | ✔️ | `tests/test_pipeline.py::test_quarantined_record_is_traceable_to_row_and_run`; Exceptions and Exception detail pages; demo step 4 |
| 4 | Re-importing the same fixture does not duplicate accepted events | ✔️ | `tests/test_pipeline.py::test_reimport_is_idempotent`, `tests/test_api.py::test_reimport_does_not_duplicate_events`, `tests/test_api.py::test_database_rejects_duplicate_event`; results.md *Idempotency*; demo step 5 |
| 5 | The database stores ingestion-run counts and a run status | ✔️ | `ingestion_runs` in [data_dictionary.md](docs/data_dictionary.md#database-tables-postgresql); `tests/test_api.py::test_import_valid_fixture`; Ingestion page runs table |
| 6 | A reconciliation example shows its formula, inputs, variance, tolerance and status | ✔️ | `tests/test_reconciliation_api.py::test_detail_links_events_and_shows_formula`, `ReconciliationDetail.test.tsx`; Reconciliation detail page; demo step 6 (FAC-11) |
| 7 | Missing events produce `NEEDS_DATA`, not a false claim that the balance is wrong | ✔️ | `tests/test_reconciliation_engine.py::test_missing_closing_count_needs_data_with_expected_value`; `missing_closing` scenario in results.md; demo step 6 (FAC-12) |
| 8 | Automated tests cover normal, invalid, boundary and repeat-import cases | ✔️ | 227 backend + 61 frontend tests (above); boundaries: `test_reconciliation_engine.py::test_boundary_is_inclusive`, `test_validation.py::test_val003_zero_is_not_negative`, `test_freshness.py::test_boundary_exactly_at_the_window_is_fresh`; repeat imports: item 4 |
| 9 | The dashboard displays run metrics, exceptions and reconciliation results | ✔️ | Overview, Exceptions and Reconciliation pages (screenshots above); `Overview.test.tsx`, `ExceptionDetail.test.tsx`, `ReconciliationDetail.test.tsx` |
| 10 | A README explains architecture, setup, data provenance, validation rules, test execution, known limitations and which data is synthetic | ✔️ | This README: *Synthetic data*, *Architecture*, *Quick start*, *Tests and measurements*, *Validation rules*, *Known limitations* |
| 11 | A reviewer can reproduce the demo locally using documented commands | ✔️ | *Quick start* above, [demo_script.md](docs/demo_script.md), [operations.md](docs/operations.md); CI `docker` job builds the images |

## API overview

Interactive documentation with every parameter and schema: http://localhost:8000/docs.

| Method and path | Purpose |
|---|---|
| `POST /api/v1/ingestion/csv` | Upload a CSV (field `file`); returns the run with its counts |
| `POST /api/v1/ingestion/simulated-api` | Import from the simulated source; `502` with the FAILED run if it is unreachable |
| `GET /api/v1/ingestion/runs`, `/runs/{run_id}` | Runs, newest first |
| `GET /api/v1/records` | Search normalized events |
| `GET /api/v1/quarantine`, `/quarantine/{event_id}` | Exceptions with their issues; one exception with raw row, run and review history |
| `PATCH /api/v1/quarantine/{event_id}/review` | Record an audited review decision |
| `GET /api/v1/metrics/quality` | Counts, rates, open exceptions, issues per rule, stale sources |
| `GET /api/v1/sources/health` | Freshness per source (VAL-010) |
| `POST /api/v1/reconciliations`, `GET /api/v1/reconciliations`, `/reconciliations/{id}` | Run, list and inspect material-flow balances |
| `GET /api/v1/reports/exceptions.csv`, `/reports/records.csv` | CSV exports with the same filters |
| `GET /api/v1/meta`, `GET /health` | Dropdown values; service and database health |

Quantities are decimal strings (e.g. `"453.59237"`); timestamps are UTC; every response has an `X-Request-ID` header.

- **Validation and reconciliation rules:** [docs/validation_rules.md](docs/validation_rules.md)
- **Data dictionary** (CSV contract, simulated source contract, tables): [docs/data_dictionary.md](docs/data_dictionary.md)
- **Operations** (environment variables, logs, fault injection, what each error means): [docs/operations.md](docs/operations.md)
- **Dashboard development:** [frontend/README.md](frontend/README.md)

## Known limitations

- **Synthetic data only.** No real facility data; the only API source is a local simulator.
- **Simplified accounting.** No yield or moisture modeling; each material is balanced on its own, and film
  consumption is not linked to resin production. Stock counts are point-in-time, and tolerances are illustrative.
- **Single user, no authentication.** A local demo (SRS §16); the reviewer name is free text.
- **No scheduler.** Imports (CSV or simulated API) are manual, so a source becomes STALE if nobody imports; there are
  no alerts. Imports run synchronously in the request.
- **No migrations.** The schema is created with `create_all`.
- **Two materials and two units.** Plastic film and recycled resin; `kg` and `lb`.
- Events with an unknown material or an unparseable timestamp cannot be placed in a balance; they stay visible in
  `/quarantine`. The simulated source's `since` cursor is exclusive on event time (see
  [operations.md](docs/operations.md#import-from-the-simulated-source)).

## Project history

| Milestone | One line |
|---|---|
| M1 | Event contract, clean and corrupted CSV fixtures, and labeled expected outcomes for every row |
| M2 | CSV reader with run IDs and immutable raw records with payload hashes |
| M3 | Normalization (aliases, units, UTC), rules VAL-001…009, quarantine and flags, idempotent re-import |
| M4 | PostgreSQL tables, FastAPI endpoints, audited review decisions, CSV exports, Docker Compose |
| M5 | `Decimal` material-flow reconciliation with tolerance, NEEDS_DATA and traceable snapshots |
| M6 | React + TypeScript dashboard for the whole workflow |
| M7 | Simulated API source, bounded retries, VAL-010 freshness, structured logs, request ids, Docker and CI hardening |
| M8 | Measurement script and measured results, architecture and demo docs, acceptance checklist, two Source health fixes |
