# M7 — Reliability: Implementation Spec

Implements the SRS items still open after M6:
- the simulated API source (§1.4, §5.3);
- VAL-010 source freshness and the **Source health** page (§6, §9);
- bounded, safe retries and logging (NFR-02, M7);
- failure tests for an unavailable source (§11);
- Docker and CI hardening (NFR-10).

Read README.md, `backend/app/pipeline.py`, `backend/app/ingestion/csv_reader.py`, `backend/app/api/routes.py`
and `frontend/src/` first. Keep the existing style: pure logic in small modules, `Decimal` for quantities,
UTC timestamps, actionable error messages, and no secrets in logs or responses.

## 1. Simulated API source (a separate small service)

The simulated source runs as **its own FastAPI app**, so the main API calls it over real HTTP, like a real
external system. Everything about it must be labelled **simulated**.

- New package `backend/simulator/` with `main.py` (`uvicorn simulator.main:app --port 8001`).
- `GET /v1/events?since=<ISO 8601 with offset>&limit=<1..1000, default 500>` returns:
  ```json
  {"source": "simulated_api", "simulated": true,
   "items": [{"id": "SIM-0001", "facility": "FAC-20", "material": "Plastic film", "type": "RECEIPT",
              "qty": "1200.5", "unit": "kg", "occurred_at": "2026-10-01T06:00:00Z", "batch": "SB-1"}],
   "next_since": "2026-10-01T06:00:00Z"}
  ```
  Field names deliberately differ from the CSV contract, so mapping them is a real step.
- **Deterministic data.** A fixed seed generates the same 200 events every time (October 2026, facilities
  FAC-20 and FAC-21, both materials, all event types). About 10% are deliberately faulty: a missing qty, an
  unknown unit, a bad timestamp, an unknown type, a negative shipment, or the same id with a different qty.
  Store the expected outcome per id in `data/fixtures/simulated_expected_outcomes.csv`, using the same columns as
  `expected_outcomes.csv`, so the labeled-set test covers this source too.
  `since` filters on `occurred_at` (exclusive); results are sorted by `occurred_at`, then `id`.
- **Fault injection** for testing reliability, through the env var `SIM_FAILURE_MODE`:
  `none` (default), `always_500`, `flaky` (the first 2 requests per process return 503, then OK),
  or `slow` (sleeps longer than the client timeout).
- `GET /health` returns `{"status":"ok","simulated":true}`.

## 2. Client with bounded retries (NFR-02)

New module `backend/app/ingestion/api_client.py`, using `httpx`. Move `httpx` from `requirements-dev.txt` to
`requirements.txt`; keep the pinned version.

- `fetch_simulated_events(base_url, since, *, attempts=3, backoff_s=0.5, timeout_s=5.0, transport=None) -> list[dict]`
- Retry **only** on connection errors, timeouts and 5xx responses. **Never** retry 4xx: raise immediately with
  the status and the response's error message.
- At most `attempts` tries in total, with exponential backoff (`backoff_s * 2**n`). Log a WARNING for each retry with
  the attempt number, the reason and the delay.
- After the last failure, raise `SourceUnavailableError` with an actionable message, e.g.
  `"Simulated source at http://simulator:8001 unreachable after 3 attempts (last error: timeout). Check that the simulator is running."`
- Retries are safe because reads are idempotent and imports are idempotent (VAL-007).
- The `transport` parameter lets tests use `httpx.MockTransport` or the simulator app directly, with no network.
- Settings via environment (`app/settings.py`): `SIMULATED_SOURCE_URL` (default `http://127.0.0.1:8001`),
  `SOURCE_RETRY_ATTEMPTS` (3), `SOURCE_RETRY_BACKOFF_S` (0.5), `SOURCE_TIMEOUT_S` (5).

## 3. Pipeline refactor (no behaviour change for CSV)

- Split `run_csv_ingestion` so the processing loop (normalize → duplicate check → validate → store → counts) is
  a shared function, e.g. `process_raw_records(raw_records, run, repo)`. The CSV path behaves exactly as now;
  all existing tests must pass unchanged.
- New `records_from_api_items(items, run_id, source_name="simulated_api") -> list[RawRecord]`:
  - map `id→source_record_id`, `facility→facility_id`, `material→material_name`, `type→event_type`,
    `qty→quantity`, `unit→unit`, `occurred_at→event_timestamp`, `batch→batch_id`;
  - convert values to strings **exactly as received** (no cleanup), and use `""` for missing keys;
  - keep the original item as `payload["_source_json"]` (compact JSON, sorted keys) to preserve the raw input (FR-03);
  - `row_number` = 1-based position in the response;
  - unexpected extra keys in an item make it structurally suspect: VAL-001, like the CSV `_extra_cells` case.
- New `run_api_ingestion(items, repo, source_name="simulated_api") -> IngestionResult`, using the same counts and run
  record as CSV. `file_name` = `"GET /v1/events?since=..."` so the run shows where the data came from.
- `since` for the next import = the latest `event_timestamp` already stored for `source_name="simulated_api"`
  (none means fetch everything). Re-running is therefore cheap and still safe, because duplicates are detected anyway.

## 4. Endpoint: `POST /api/v1/ingestion/simulated-api`

- Body (optional): `{"since": "<ISO 8601 with offset>"}` overrides the automatic `since`.
- Success: 201 with the run (same `RunOut` as the CSV import).
- Source unavailable after retries: the run is **saved as FAILED** with `error_summary` = the actionable message,
  and the endpoint returns **502** with `{"detail": {"message": ..., "run": ...}}`. A 4xx from the source also
  gives 502, with no retries.

## 5. VAL-010 source freshness and `GET /api/v1/sources/health`

- `app/config.py`: `SOURCE_FRESHNESS_HOURS = {"csv": 168, "simulated_api": 24}`, illustrative values (SRS §16).
- Pure function `app/validation/freshness.py`:
  `source_health(runs, freshness, now) -> list[SourceHealth]`, computed from `ingestion_runs`. One entry per
  configured source **plus** any other source_name seen in runs:
  `source_name, last_run_at, last_run_status, last_success_at, age_hours (since last success),
  freshness_window_hours, status` where status is `FRESH` / `STALE` (VAL-010) / `NEVER_SUCCEEDED`, plus `message`
  (e.g. `"No successful import in 30.5 h; window is 24 h"`).
  A source whose latest run FAILED but whose last success is inside the window stays `FRESH`, with the failure shown.
- `GET /api/v1/sources/health` returns the list. `now` must be injectable for tests.
- Add `sources_stale` (count) to `GET /api/v1/metrics/quality`.

## 6. Logging (NFR-02, NFR-05)

- `app/logging_config.py`: configure stdlib logging once at startup. `LOG_FORMAT=json|text` (default `text`
  locally, `json` in Docker) and `LOG_LEVEL` (default `INFO`). The JSON lines have `ts, level, logger, message`
  plus extra fields.
- Middleware: read or create `X-Request-ID`, return it in the response header, and log one line per request:
  `method, path, status, duration_ms, request_id`.
- Log ingestion runs at start and end (`run_id, source_name, status, counts, duration_ms`), every retry, and
  every reconciliation run.
- **Never log** row payloads, raw values, connection strings or passwords. Add a test that captures the logs during
  a failed DB call and a CSV import, and asserts that neither the password nor a payload value appears.

## 7. Dashboard changes (`frontend/`)

- Enable **Source health** in the nav (remove "planned"). Page `/sources`:
  - table from `/api/v1/sources/health` with status badges (FRESH green, STALE amber, NEVER_SUCCEEDED grey), the
    `message`, the last run status and time;
  - a button **"Import from simulated API"** that calls `POST /api/v1/ingestion/simulated-api` and shows the run
    result, or the error message with the failed run (502);
  - text saying the source is simulated.
- Overview: add a tile "Stale sources" from `sources_stale`.
- Ingestion page: the runs table shows `source_name`.
- Add a favicon (simple SVG in `frontend/public/favicon.svg`, linked from `index.html`) to fix the 404.
- Tests for the new page (FRESH/STALE rendering, button success, 502 error display) and the new tile.

## 8. Docker and CI

- `backend/Dockerfile` copies `simulator/` too.
- `docker-compose.yml`:
  - add a `simulator` service (same image, command `uvicorn simulator.main:app --host 0.0.0.0 --port 8001`,
    port `127.0.0.1:8001:8001`);
  - the `api` service gets `SIMULATED_SOURCE_URL=http://simulator:8001` and `LOG_FORMAT=json`;
  - add healthchecks for `api` and `simulator` using
    `python -c "import urllib.request; urllib.request.urlopen('http://localhost:PORT/health')"`;
  - `web` depends on `api` being healthy.
- CI: add a job `docker` that runs `docker compose config -q` and `docker compose build`, with
  `POSTGRES_PASSWORD=ci` in the env, so a broken Dockerfile fails CI.

## 9. Tests (all must pass; report actual counts)

- `tests/test_api_client.py`:
  - success;
  - flaky (two 503s, then success) → 3 attempts, with retry logs;
  - always 500 → `SourceUnavailableError` after exactly 3 attempts;
  - timeout → retried;
  - 404 → **not** retried (1 attempt);
  - backoff delays computed correctly (inject a fake `sleep`).
- `tests/test_simulator.py`: deterministic output (two calls are identical), `since` filtering, `limit`, each
  failure mode.
- `tests/test_api_ingestion.py`:
  - import from the simulator (via transport) → expected counts;
  - the labeled outcomes in `simulated_expected_outcomes.csv` match;
  - a re-import adds 0 events;
  - `_source_json` preserved;
  - source down → 502 and a FAILED run saved.
- `tests/test_freshness.py`: FRESH, STALE, NEVER_SUCCEEDED, failure inside the window, the boundary exactly at the
  window, and an unknown source.
- Logging tests from section 6, plus `X-Request-ID` echoed.
- All existing backend (165) and frontend (56) tests still pass; the API tests also pass on PostgreSQL via
  `TEST_DATABASE_URL`.

## 10. Docs

- `README.md`:
  - M7 ✔️ done;
  - architecture diagram updated (simulator → API);
  - new endpoints;
  - a "Reliability" section covering retries, freshness, logging and request ids;
  - environment variables table;
  - known limitations (simulated source only; no scheduler yet, imports are triggered manually).
- `docs/validation_rules.md`: VAL-010 implemented, with the rules above.
- `docs/data_dictionary.md`: the simulated JSON contract and the field mapping.
- New `docs/operations.md`: how to run everything, read the logs, trigger failure modes
  (`SIM_FAILURE_MODE=flaky docker compose up simulator`), and what each error means.

## 11. Definition of done (SRS §17)

- The simulated source can be imported from the dashboard.
- Stopping the simulator gives a clear error and a FAILED run, not a crash.
- Source health shows FRESH and STALE correctly.
- Logs are structured and contain no secrets.
- `docker compose up --build` starts db, simulator, api and web.
- All tests pass.

Do not commit; the developer reviews and commits.
