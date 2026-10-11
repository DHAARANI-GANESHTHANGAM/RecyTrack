# Data Dictionary

All operational data in this repository is **synthetic**. It was written by hand to exercise the pipeline and does not come from any real facility or company.

## CSV input contract

Files must be UTF-8 (a BOM is allowed). The header must use these exact column names, in any order:

| Column | Required | Example | Notes |
|---|---|---|---|
| `source_record_id` | yes | `SRC-1001` | Stable ID from the source system. Used for duplicate detection. |
| `facility_id` | yes | `FAC-01` | Trimmed and upper-cased. |
| `material_name` | yes | `Plastic film` | Mapped to a canonical `material_code` through the alias table. |
| `event_type` | yes | `RECEIPT` | One of `RECEIPT`, `PRODUCTION`, `SHIPMENT`, `LOSS`, `INVENTORY_ADJUSTMENT`, `INVENTORY_COUNT`, `CONSUMPTION` (see [Event types](#event-types)). Case, spaces and hyphens are normalized. |
| `quantity` | yes | `1000`, `1,500`, `-12.5` | Parsed as a decimal (never a float). Thousands separators are allowed. |
| `unit` | yes | `kg`, `lb` | Aliases: `kgs`, `kilogram(s)`, `lbs`, `pound(s)`, any case. |
| `event_timestamp` | yes | `2026-10-01T09:00:00Z` | ISO 8601 **with** a timezone offset. |
| `batch_id` | no | `BATCH-42` | Optional. |

### Event types

| Event type | Meaning | Effect on the material's balance (REC-001) |
|---|---|---|
| `RECEIPT` | Material received at the facility | adds |
| `PRODUCTION` | Output material produced by processing | adds |
| `INVENTORY_ADJUSTMENT` | Booked stock correction; the only type that may be negative (VAL-003) | adds, keeping its sign |
| `SHIPMENT` | Material shipped out | subtracts |
| `LOSS` | Material lost (scrap, spill, write-off) | subtracts |
| `CONSUMPTION` | Feedstock used up by processing (M5) | subtracts |
| `INVENTORY_COUNT` | Physical stock count at a point in time, quantity >= 0 (M5) | not a flow; sets the opening or closing stock |

Each material is balanced on its own. A negative `INVENTORY_COUNT` or `CONSUMPTION` is flagged by VAL-003, as for
other unsigned types.

Whole-file problems (empty file, wrong or missing columns, non-UTF-8 data, over 10 MB) fail the run with a message saying what to fix. No rows are imported in that case.

## Simulated API source contract (M7)

The simulated source (`backend/simulator/`, a separate service) is **synthetic test data**, not a real system.
`GET /v1/events?since=<ISO 8601 with offset>&limit=<1..1000, default 500>` returns:

```json
{"source": "simulated_api", "simulated": true,
 "items": [{"id": "SIM-0001", "facility": "FAC-20", "material": "Plastic film", "type": "RECEIPT",
            "qty": "1200.5", "unit": "kg", "occurred_at": "2026-10-01T06:00:00Z", "batch": "SB-1"}],
 "next_since": "2026-10-01T06:00:00Z"}
```

- `since` is exclusive and filters on the event time; items are sorted by time, then `id`. A `since` without an
  offset is rejected with `422`. `next_since` is the time of the last item returned.
- 200 events, always the same (fixed seed): October 2026, facilities `FAC-20` and `FAC-21`, both materials, every
  event type. 20 (10%) are deliberately faulty; their expected outcomes are in
  [`data/fixtures/simulated_expected_outcomes.csv`](../data/fixtures/simulated_expected_outcomes.csv):

| Fault | Count | Expected |
|---|---|---|
| `qty` missing | 4 | `QUARANTINED`, VAL-001 |
| `unit` = `tonnes` | 4 | `QUARANTINED`, VAL-004 |
| bad `occurred_at` (impossible date, no offset, or `DD/MM/YYYY`) | 3 | `QUARANTINED`, VAL-005 |
| `type` = `TRANSFER` | 3 | `QUARANTINED`, VAL-006 |
| negative `qty` on a `SHIPMENT` | 3 | `FLAGGED`, VAL-003 |
| same `id` as an earlier event with a different `qty` | 3 | `FLAGGED`, VAL-009 |

A first full import gives 200 received, 180 accepted, 14 quarantined, 6 flagged.

### Field mapping

Each item becomes a raw record with the CSV contract's field names, so the same normalization and validation apply.

| API field | Raw record field |
|---|---|
| `id` | `source_record_id` |
| `facility` | `facility_id` |
| `material` | `material_name` |
| `type` | `event_type` |
| `qty` | `quantity` |
| `unit` | `unit` |
| `occurred_at` | `event_timestamp` |
| `batch` | `batch_id` |

- Values are converted to text **exactly as received** (no trimming or cleanup). A missing key or `null` becomes `""`,
  so a missing required field is reported by VAL-001.
- The whole original item is kept as `_source_json` (compact JSON, sorted keys) in the raw payload (FR-03).
- Keys outside the mapping are listed in `_extra_fields` and make the item structurally suspect: VAL-001, like extra
  cells in a CSV row.
- `row_number` is the item's 1-based position in the response. The run's `file_name` is the request, e.g.
  `GET /v1/events?since=2026-10-25T22:41:00+00:00`.
- Duplicate keys are `(simulated_api, id)`, separate from CSV records.

## Normalized event

| Field | Type | Meaning |
|---|---|---|
| `event_id` | UUID | Internal ID. |
| `raw_id` | UUID | Link to the untouched raw record. |
| `run_id` | UUID | Ingestion run that produced it. |
| `source_name` | text | `csv` or `simulated_api`. |
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

Every input row is stored as a read-only `RawRecord`, whatever happens to it later. It holds `raw_id`, `run_id`, `source_name`, `row_number` (as in the file, header = row 1; for the API source, the position in the response), the original `payload` and a SHA-256 `payload_hash`.

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
| `audit_events` | Append-only log of review decisions (`entity_type = material_event`) and reconciliation runs (`entity_type = reconciliation`, `action = reconciliation_run`): actor label, details, timestamp |
| `reconciliations` | One snapshot per reconciliation run (see below). Insert-only; running again creates a new row. |
| `reconciliation_events` | Which events a reconciliation used or left out, and in what role |

Duplicate rows have a `raw_records` entry, so the row stays traceable, but no new `material_events` entry.

### `reconciliations`

| Column | Type | Meaning |
|---|---|---|
| `reconciliation_id` | UUID | Snapshot ID. |
| `facility_id`, `material_code` | text | What was balanced. |
| `period_start`, `period_end` | UTC datetime | The requested period. |
| `opening_stock_kg`, `closing_stock_kg` | decimal, nullable | From the opening and closing `INVENTORY_COUNT`. NULL when missing or conflicting. |
| `receipts_kg`, `production_kg`, `adjustments_kg`, `shipments_kg`, `losses_kg`, `consumption_kg` | decimal | Sums of counted flow events in the window. Adjustments keep their sign. |
| `expected_closing_kg`, `variance_kg`, `throughput_kg`, `tolerance_kg` | decimal, nullable | Calculated values (formula in [validation_rules.md](validation_rules.md#reconciliation-rec-001rec-004)). NULL when an input is unknown. |
| `tolerance_absolute_kg`, `tolerance_percent` | decimal | Tolerance settings used for this run. |
| `status` | text | `WITHIN_TOLERANCE`, `NEEDS_REVIEW` or `NEEDS_DATA`. |
| `reasons` | JSON list | Plain-English explanation of the status. |
| `created_at` | UTC datetime | When the snapshot was taken. |

Decimal columns are `NUMERIC(24, 10)` on PostgreSQL and exact text on SQLite.

### `reconciliation_events`

| Column | Type | Meaning |
|---|---|---|
| `reconciliation_id` | UUID | The snapshot. |
| `event_id` | UUID | The `material_events` row. |
| `role` | text | `opening_count`, `closing_count`, `intermediate_count`, `receipt`, `production`, `adjustment`, `shipment`, `loss`, `consumption` or `excluded`. |
| `excluded_reason` | text, nullable | Why an `excluded` event was left out (e.g. quarantined, rejected, not approved yet). |
