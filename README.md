# RecyTrack

**Recycling Data Quality & Material Traceability Platform**

RecyTrack imports recycling-operation records, standardizes and validates them, keeps invalid records for review instead of deleting them, and (later) reconciles material quantities across receiving, processing, inventory and shipment events.

> This is a portfolio project inspired by recycling and material-recovery operations. It is not an internal company specification. It uses no private company systems or data. **All facility event data in `data/fixtures/` is synthetic.**

## Status

| Milestone | Scope | State |
|---|---|---|
| M1 Data contract | Event schema, clean and corrupted CSV fixtures, labeled expected outcomes | ✅ done |
| M2 Ingestion | CSV reader, run ID, immutable raw records, run summary | ✅ done |
| M3 Validation | Normalization, VAL-001…009, quarantine/flag, idempotent re-import | ✅ done (in-memory store) |
| M4 Database + API | PostgreSQL tables, FastAPI endpoints, Docker Compose | next |
| M5 Reconciliation | Material-flow balance with tolerance and NEEDS_DATA | planned |
| M6 Dashboard | React views for runs, exceptions, metrics, reconciliation | planned |
| M7–M8 | Reliability, CI hardening, demo and evidence | planned |

## Architecture (current)

```
CSV file
  → ingestion/csv_reader.py     header check, raw rows + SHA-256 hash (read-only)
  → normalization/normalize.py  whitespace, material alias, unit → kg, timestamp → UTC
  → validation/rules.py         VAL-001…008 → ACCEPTED / FLAGGED / QUARANTINED
  → pipeline.py                 duplicate / conflict checks (VAL-007, VAL-009), run counts
  → store.py                    Repository interface (in-memory now, PostgreSQL in M4)
```

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                                                   # run the tests
python -m app.pipeline ../data/fixtures/invalid_events.csv  # import a file and print the run summary
```

## Documentation

- [Data dictionary](docs/data_dictionary.md): CSV contract and normalized fields
- [Validation rules](docs/validation_rules.md): rule codes, severities, constants and policies
- [`data/fixtures/expected_outcomes.csv`](data/fixtures/expected_outcomes.csv): labeled expected status and rule codes for every fixture row, checked by the test suite

## Known limitations

- Storage is in-memory until M4, so nothing persists between runs.
- Only `kg` and `lb`, and two materials (plastic film, recycled resin), are supported.
- Reconciliation, the API and the dashboard are not built yet.
