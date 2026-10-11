# Data Dictionary

All operational data in this repository is **synthetic**. It was written by hand to exercise the pipeline and does not come from any real facility or company.

## CSV input contract

Files must be UTF-8 (a BOM is allowed). The header must use these exact column names, in any order:

| Column | Required | Example | Notes |
|---|---|---|---|
| `source_record_id` | yes | `SRC-1001` | Stable ID from the source system. Used for duplicate detection. |
| `facility_id` | yes | `FAC-01` | Trimmed and upper-cased. |
| `material_name` | yes | `Plastic film` | Mapped to a canonical `material_code` through the alias table. |
| `event_type` | yes | `RECEIPT` | One of `RECEIPT`, `PRODUCTION`, `SHIPMENT`, `LOSS`, `INVENTORY_ADJUSTMENT`. Case, spaces and hyphens are normalized. |
| `quantity` | yes | `1000`, `1,500`, `-12.5` | Parsed as a decimal (never a float). Thousands separators are allowed. |
| `unit` | yes | `kg`, `lb` | Aliases: `kgs`, `kilogram(s)`, `lbs`, `pound(s)`, any case. |
| `event_timestamp` | yes | `2026-10-01T09:00:00Z` | ISO 8601 **with** a timezone offset. |
| `batch_id` | no | `BATCH-42` | Optional. |

Whole-file problems (empty file, wrong or missing columns, non-UTF-8 data, over 10 MB) fail the run with a message saying what to fix. No rows are imported in that case.

## Normalized event

| Field | Type | Meaning |
|---|---|---|
| `event_id` | UUID | Internal ID. |
| `raw_id` | UUID | Link to the untouched raw record. |
| `run_id` | UUID | Ingestion run that produced it. |
| `source_name` | text | `csv` (later also `simulated_api`). |
| `source_record_id` | text | As in the source, trimmed. |
| `facility_id` | text | Upper-cased. |
| `material_name_raw` | text | Exactly as received. |
| `material_code` | text | `PLASTIC_FILM`, `RECYCLED_RESIN`, or empty if unknown. |
| `event_type` | text | Canonical event type. |
| `quantity` | decimal | Parsed quantity in the source unit. |
| `unit_raw` / `unit` | text | Raw unit and canonical unit (`kg` / `lb`). |
| `quantity_kg` | decimal | `quantity × kg-per-unit`. |
| `event_timestamp_raw` / `event_timestamp` | text / UTC datetime | Raw value and UTC-normalized value. |
| `batch_id` | text | Optional. |
| `validation_status` | enum | `ACCEPTED`, `FLAGGED`, `QUARANTINED`, or `DUPLICATE`. |
| `issues` | list | Rule code, field, message, severity and raw value for each problem. |

## Raw record

Every input row is stored as a read-only `RawRecord`, whatever happens to it later. It holds `raw_id`, `run_id`, `source_name`, `row_number` (as in the file, header = row 1), the original `payload` and a SHA-256 `payload_hash`.

## Ingestion run

`run_id`, `source_name`, `started_at`, `finished_at`, `status` (`RUNNING` / `SUCCEEDED` / `FAILED`), `received`, `accepted`, `quarantined`, `flagged` and `duplicates` counts, derived rates, and `error_summary`.

## Database tables (PostgreSQL)

Defined in `backend/app/database/tables.py`. Tables are created on startup.

| Table | Contents |
|---|---|
| `ingestion_runs` | One row per import: file name, start/finish time, status, counts, error summary |
| `raw_records` | Every input row as received (JSONB payload), its hash, row number and run. Insert-only. |
| `material_events` | One normalized event per non-duplicate row, with `validation_status`. Unique on `(source_name, source_record_id, payload_hash)`. |
| `validation_issues` | Rule code, field, message, severity, raw value and `review_status` for each problem |
| `audit_events` | Append-only log of review decisions: actor label, details, timestamp |

Duplicate rows have a `raw_records` entry, so the row stays traceable, but no new `material_events` entry.
