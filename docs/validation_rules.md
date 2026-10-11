# Validation and Reconciliation Rules

Severity decides the record status:

- any **ERROR** issue → `QUARANTINED` (kept, but not trusted)
- otherwise any **WARNING** issue → `FLAGGED` (usable, needs review)
- no issues → `ACCEPTED`
- identical re-import of a known record → `DUPLICATE` (no new event)

No record is ever deleted or auto-corrected. The raw row is always kept.

| Rule | Check | Severity | Status | Where |
|---|---|---|---|---|
| VAL-001 | Required field missing or blank (one issue per field). Row has more or fewer cells than the header, or an API item has fields outside the contract. | ERROR | implemented | `validation/rules.py` |
| VAL-002 | Quantity is not a finite decimal | ERROR | implemented | `validation/rules.py` |
| VAL-003 | Negative quantity on an event type other than `INVENTORY_ADJUSTMENT` | WARNING | implemented | `validation/rules.py` |
| VAL-004 | Unit not in the supported list | ERROR | implemented | `validation/rules.py` |
| VAL-005 | Timestamp not ISO 8601, impossible, or **missing a timezone** | ERROR | implemented | `validation/rules.py` |
| VAL-006 | Event type not in the configured list | ERROR | implemented | `validation/rules.py` |
| VAL-007 | Same `(source_name, source_record_id)` with identical payload already imported | WARNING | implemented | `pipeline.py` |
| VAL-008 | Material name has no known alias | WARNING | implemented | `validation/rules.py` |
| VAL-009 | Same stable key already imported with **different** values; both kept | WARNING | implemented (same-source only) | `pipeline.py` |
| VAL-010 | Source stale: no successful import within its freshness window (see below) | WARNING | implemented | `validation/freshness.py` |
| REC-001 | Material-flow balance per facility, material and period (formula below) | — | implemented | `reconciliation/engine.py` |
| REC-002 | Variance compared with tolerance: `WITHIN_TOLERANCE` or `NEEDS_REVIEW` | — | implemented | `reconciliation/engine.py` |
| REC-003 | Missing or conflicting counts, or unresolved exceptions → `NEEDS_DATA` | — | implemented | `reconciliation/engine.py` |
| REC-004 | Quantities are never changed, corrected or invented to make a balance work | — | implemented | `reconciliation/engine.py` |

## Constants and policies

- **Units:** 1 kg = 1 kg; 1 lb = **0.45359237 kg** (exact international definition). Quantities use Python `Decimal`.
- **Timezones:** timestamps are stored in UTC. The raw string is kept. A timestamp with no offset is rejected rather than guessed.
- **Materials:** see `MATERIAL_ALIASES` in `backend/app/config.py`. Unknown names are flagged, not rejected, so a reviewer can add the alias.
- **Duplicate key:** `(source_name, source_record_id)`. Rows without a `source_record_id` are quarantined (VAL-001) and cannot be de-duplicated.
- **Reconciliation tolerance:** `RECONCILIATION_TOLERANCE = {"absolute_kg": 5, "percent_of_throughput": 1.0}`. A request can override both.
- All thresholds and tables live in `backend/app/config.py`. They are illustrative until validated against domain evidence.

## Source freshness (VAL-010)

`GET /api/v1/sources/health` checks each source from the `ingestion_runs` table. Windows are set in
`SOURCE_FRESHNESS_HOURS` in `backend/app/config.py`: `{"csv": 168, "simulated_api": 24}` (illustrative, SRS §16).

| Status | When |
|---|---|
| `FRESH` | The last successful import finished at most `window` hours ago. Exactly at the window is still fresh. |
| `STALE` | The last successful import is older than the window (VAL-010). |
| `NEVER_SUCCEEDED` | The source has no successful run (no runs at all, or only failed ones). |
| `NO_WINDOW` | A source seen in runs that has no configured window; its age is shown but not judged. |

- Every configured source is listed, plus any other `source_name` found in runs.
- Age is measured from the last **successful** run's `finished_at`. A failed run does not reset it: a source whose latest
  run failed but whose last success is inside the window stays `FRESH`, and the message says when the latest run failed.
- The message is actionable, e.g. `No successful import in 30.5 h; window is 24 h.`
- `GET /api/v1/metrics/quality` returns `sources_stale`, the number of `STALE` sources. `NEVER_SUCCEEDED` is not
  counted, so an empty install does not show stale sources.

## Review decisions

Quarantined and flagged records start with `review_status = OPEN`. A reviewer records a decision with
`PATCH /api/v1/quarantine/{event_id}/review`:

| Review status | Meaning |
|---|---|
| `OPEN` | Not reviewed yet |
| `APPROVED` | The data is usable despite the issue (e.g. a new material that needs an alias) |
| `REJECTED` | The record is wrong and should stay out of totals |
| `NEEDS_INFO` | Waiting on the source for more information |

A decision never changes the raw row or the normalized values. It updates `review_status` on the record's
issues and appends an `audit_events` row with the actor label, the previous and new status, the note and a timestamp.

## Reconciliation (REC-001..REC-004)

Run with `POST /api/v1/reconciliations` for one `facility_id` + `material_code` + period `[period_start, period_end]`.
Each material is reconciled on its own; there is no film → resin yield calculation in v1.

### Which events count (REC-001)

| Event | In the totals? |
|---|---|
| `ACCEPTED` | yes |
| `FLAGGED`, every issue `APPROVED` | yes |
| `FLAGGED`, any issue `OPEN`, `NEEDS_INFO` or `REJECTED` | no, listed as `excluded` with the reason |
| `QUARANTINED` (any review status) | no, listed as `excluded` with the reason |

### Opening stock, closing stock and the flow window

- **Opening count**: the latest counted `INVENTORY_COUNT` with `event_timestamp <= period_start`.
- **Closing count**: the latest counted `INVENTORY_COUNT` with `period_start < event_timestamp <= period_end`.
- Two counts at that latest timestamp with **different** quantities are a conflict ("conflicting stock counts").
  Identical counts are not.
- **Flow window**: `opening_count.ts < event_timestamp <= closing_count.ts`. A count reflects stock *after* every
  event with the same timestamp. When a count is missing, the period bound takes its place for listing events.
- `INVENTORY_COUNT` events between the opening and closing counts are listed as `intermediate_count` and are not flows.

### Formula (all in kg, `Decimal`)

```
expected_closing_kg = opening_stock_kg
                    + receipts_kg + production_kg + adjustments_kg   (adjustments keep their sign)
                    - shipments_kg - losses_kg - consumption_kg
variance_kg         = closing_stock_kg - expected_closing_kg
throughput_kg       = opening_stock_kg + receipts_kg + production_kg
tolerance_kg        = max(absolute_kg, throughput_kg * percent_of_throughput / 100)
```

### Status (REC-002, REC-003), checked in this order

1. **`NEEDS_DATA`**: no opening count, no closing count, conflicting counts, **or** an unresolved exception
   (`FLAGGED` / `QUARANTINED` with review status `OPEN` or `NEEDS_INFO`) for this facility and material inside the
   window. Values that can still be calculated are stored, but the status says the evidence is incomplete.
2. **`WITHIN_TOLERANCE`** if `abs(variance_kg) <= tolerance_kg`. The boundary is inclusive.
3. **`NEEDS_REVIEW`** otherwise. This is a flag for a person to review, **not proof of an error**.

Every result stores a `reasons` list in plain English, e.g. `No INVENTORY_COUNT at or before 2026-10-01T00:00:00Z`
or `|variance| 80 kg exceeds tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg)`.

### No silent correction (REC-004)

Quantities are summed exactly as recorded. A balance never changes, rounds or invents a quantity, and a review
decision never changes source values. Results are snapshots: running the check again creates a new
`reconciliations` row and leaves earlier ones unchanged. Each run links every event it used or left out
(`reconciliation_events`) and writes an `audit_events` row (`entity_type = reconciliation`, `action = reconciliation_run`).
