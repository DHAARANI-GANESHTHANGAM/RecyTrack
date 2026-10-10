# Validation and Reconciliation Rules

Severity decides the record status:

- any **ERROR** issue → `QUARANTINED` (kept, but not trusted)
- otherwise any **WARNING** issue → `FLAGGED` (usable, needs review)
- no issues → `ACCEPTED`
- identical re-import of a known record → `DUPLICATE` (no new event)

No record is ever deleted or auto-corrected. The raw row is always kept.

| Rule | Check | Severity | Status | Where |
|---|---|---|---|---|
| VAL-001 | Required field missing or blank (one issue per field). Row has more or fewer cells than the header. | ERROR | implemented | `validation/rules.py` |
| VAL-002 | Quantity is not a finite decimal | ERROR | implemented | `validation/rules.py` |
| VAL-003 | Negative quantity on an event type other than `INVENTORY_ADJUSTMENT` | WARNING | implemented | `validation/rules.py` |
| VAL-004 | Unit not in the supported list | ERROR | implemented | `validation/rules.py` |
| VAL-005 | Timestamp not ISO 8601, impossible, or **missing a timezone** | ERROR | implemented | `validation/rules.py` |
| VAL-006 | Event type not in the configured list | ERROR | implemented | `validation/rules.py` |
| VAL-007 | Same `(source_name, source_record_id)` with identical payload already imported | WARNING | implemented | `pipeline.py` |
| VAL-008 | Material name has no known alias | WARNING | implemented | `validation/rules.py` |
| VAL-009 | Same stable key already imported with **different** values; both kept | WARNING | implemented (same-source only) | `pipeline.py` |
| VAL-010 | Source stale beyond its freshness window | WARNING | planned (with the simulated API source) | |
| REC-001..004 | Mass balance, tolerance, NEEDS_DATA, no silent correction | — | planned (M5) | |

## Constants and policies

- **Units:** 1 kg = 1 kg; 1 lb = **0.45359237 kg** (exact international definition). Quantities use Python `Decimal`.
- **Timezones:** timestamps are stored in UTC. The raw string is kept. A timestamp with no offset is rejected rather than guessed.
- **Materials:** see `MATERIAL_ALIASES` in `backend/app/config.py`. Unknown names are flagged, not rejected, so a reviewer can add the alias.
- **Duplicate key:** `(source_name, source_record_id)`. Rows without a `source_record_id` are quarantined (VAL-001) and cannot be de-duplicated.
- All thresholds and tables live in `backend/app/config.py`. They are illustrative until validated against domain evidence.

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
