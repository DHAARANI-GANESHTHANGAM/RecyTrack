# M5 — Material-Flow Reconciliation: Implementation Spec

Implements SRS FR-10, FR-11, FR-15 and rules REC-001 to REC-004. Builds on M1–M4 (see README.md, docs/).
Follow the existing code style: pure logic in small modules, database access in `app/database/`,
routes in `app/api/routes.py`, `Decimal` for every quantity (never float), UTC timestamps.

## 1. Decisions already made

1. **Stock counts come from a new event type `INVENTORY_COUNT`**: a physical stock count at a point in time,
   quantity >= 0. It is imported through the same CSV like any other event.
2. **Processing uses a new event type `CONSUMPTION`**: feedstock used up by processing. It reduces the input
   material's balance. `PRODUCTION` increases the output material's balance. Each material is reconciled
   on its own. There is no film→resin yield calculation in v1 (document this as a known limitation).
3. Results are **snapshots**. Running a check again creates a new row and never updates an old one.
4. Never change, correct or invent quantities to make a balance work (REC-004).

## 2. Changes to existing code

- `app/config.py`: add `INVENTORY_COUNT` and `CONSUMPTION` to `EVENT_TYPES`. Keep `SIGNED_EVENT_TYPES = {"INVENTORY_ADJUSTMENT"}`
  (so a negative count or consumption is flagged by VAL-003, as for other types).
  Add:
  ```python
  RECONCILIATION_TOLERANCE = {"absolute_kg": Decimal("5"), "percent_of_throughput": Decimal("1.0")}
  ```
  with a comment that the values are illustrative until validated (SRS §16).
- `docs/data_dictionary.md` and `docs/validation_rules.md`: list the new event types, mark REC-001..004 as implemented,
  and add the accounting model in section 3 below.
- Existing tests must keep passing. Update any test that asserts the exact list of event types.

## 3. Accounting model (REC-001)

For one `facility_id` + `material_code` + period `[period_start, period_end]`:

**Which events count**
- `ACCEPTED` events.
- `FLAGGED` events whose issues are all `review_status = APPROVED`.
- Everything else is excluded: `QUARANTINED`, `REJECTED`, and unreviewed `FLAGGED`. Excluded events matching the
  facility, material and window are still listed in the result with the reason they were excluded.

**Opening and closing stock**
- Opening count = the latest counting `INVENTORY_COUNT` with `event_timestamp <= period_start`.
- Closing count = the latest counting `INVENTORY_COUNT` with `period_start < event_timestamp <= period_end`.
- If two counts share that latest timestamp with different quantities, the result is `NEEDS_DATA` ("conflicting stock counts").

**Flow window**: events with `opening_count.ts < event_timestamp <= closing_count.ts`. A count reflects stock *after*
all events that share its timestamp.

**Formula** (all in kg, using `quantity_kg`):
```
expected_closing_kg = opening_stock_kg
                    + receipts_kg + production_kg + adjustments_kg   (adjustments keep their sign)
                    - shipments_kg - losses_kg - consumption_kg
variance_kg         = closing_stock_kg - expected_closing_kg
throughput_kg       = opening_stock_kg + receipts_kg + production_kg
tolerance_kg        = max(absolute_kg, throughput_kg * percent_of_throughput / 100)
```
`INVENTORY_COUNT` events between the opening and closing counts are not flows. List them as `intermediate_count`.

**Status (REC-002, REC-003)**, checked in this order:
1. `NEEDS_DATA`: no opening count, no closing count, conflicting counts, **or** any unresolved exception
   (`FLAGGED`/`QUARANTINED` with review status `OPEN` or `NEEDS_INFO`) for this facility and material inside the window.
   Calculated values are still stored where they are possible, but the status says the evidence is incomplete.
2. `WITHIN_TOLERANCE` if `abs(variance_kg) <= tolerance_kg`. The boundary is inclusive.
3. `NEEDS_REVIEW` otherwise. The wording everywhere must say this is a review flag, not proof of an error.

Store a `reasons` list of plain-English strings explaining the status, e.g.
`"No INVENTORY_COUNT at or before 2026-10-01T00:00:00Z"` or
`"|variance| 80 kg exceeds tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg)"`.

## 4. Code layout

- `app/reconciliation/engine.py`: **pure function, no database**:
  `reconcile(events, facility_id, material_code, period_start, period_end, tolerance) -> ReconciliationResult`.
  `events` are plain objects with event_id, event_type, quantity_kg, event_timestamp, validation_status and
  review statuses. Most unit tests target this function.
- `app/reconciliation/service.py`: loads the candidate events from the database, calls `reconcile`, and saves the result.
- `app/database/tables.py`: add
  - `reconciliations`: reconciliation_id (uuid str), facility_id, material_code, period_start, period_end,
    opening_stock_kg, receipts_kg, production_kg, adjustments_kg, shipments_kg, losses_kg, consumption_kg,
    closing_stock_kg, expected_closing_kg, variance_kg, throughput_kg, tolerance_kg, tolerance_absolute_kg,
    tolerance_percent, status, reasons (JSON), created_at. Kg columns use `ExactDecimal`, nullable when unknown.
  - `reconciliation_events`: reconciliation_id, event_id, role (`opening_count`, `closing_count`, `intermediate_count`,
    `receipt`, `production`, `adjustment`, `shipment`, `loss`, `consumption`, `excluded`), excluded_reason (nullable).
- Write an `audit_events` row (`entity_type="reconciliation"`, `action="reconciliation_run"`) for each run.

## 5. API (add to `app/api/routes.py`, schemas in `app/schemas.py`)

| Method and path | Behavior |
|---|---|
| `POST /api/v1/reconciliations` | Body: `facility_id`, `material_code`, `period_start`, `period_end` (ISO 8601 with offset), optional `absolute_tolerance_kg`, `percent_tolerance`, `actor_label`. Returns 201 with the full detail. 422 if period_end <= period_start, naive datetimes, unknown material_code, or negative tolerances. |
| `GET /api/v1/reconciliations` | Paged list, filters `facility_id`, `material_code`, `status`. Newest first. |
| `GET /api/v1/reconciliations/{id}` | Detail: all inputs, `formula` (the formula as a readable string with the numbers filled in), tolerance explanation, status, reasons, and linked events grouped by role (event_id, source_record_id, type, quantity_kg, timestamp). 404 if unknown. |

Quantities are serialized as decimal strings, as in the other endpoints.

## 6. Fixtures

Create `data/fixtures/reconciliation_scenarios.csv` (same CSV contract as the other fixtures, all synthetic,
all `2026-10` dates, ids `REC-xxxx`) and `data/fixtures/expected_reconciliations.csv` with columns
`scenario,facility_id,material_code,period_start,period_end,expected_status,expected_variance_kg,expected_tolerance_kg`.
Use period `2026-10-01T00:00:00Z` → `2026-10-31T23:59:59Z` and default tolerance unless stated.

| Scenario | Facility / material | Events | Expected |
|---|---|---|---|
| balanced | FAC-10 PLASTIC_FILM | count 10-01T00:00 = 1000 kg; receipt 500 kg; consumption 1200 kg; loss 20 kg; count 10-31T23:00 = 280 kg | variance 0, tolerance 15 (1% of 1500), WITHIN_TOLERANCE |
| imbalanced | FAC-11 PLASTIC_FILM | same as balanced but closing count 200 kg | variance −80, NEEDS_REVIEW |
| boundary | FAC-13 PLASTIC_FILM | same as balanced but closing count 265 kg | variance −15, WITHIN_TOLERANCE (inclusive) |
| missing closing | FAC-12 PLASTIC_FILM | same as balanced without the closing count | NEEDS_DATA |
| two materials, film | FAC-14 PLASTIC_FILM | count 10-01T00:00 = 0 kg; receipt **2205 lb** (= 1000.17117585 kg); consumption 1000 kg; count 10-31T23:00 = 0 kg | variance −0.17117585, tolerance 10.0017117585, WITHIN_TOLERANCE (tests pound conversion) |
| two materials, resin | FAC-14 RECYCLED_RESIN | count 10-01T00:00 = 0 kg; production 900 kg; shipment 850 kg; count 10-31T23:00 = 50 kg | variance 0, tolerance 9 (1% of 900), WITHIN_TOLERANCE |
| open exception | FAC-15 PLASTIC_FILM | the balanced events plus one SHIPMENT of **−10 kg** (flagged by VAL-003, review status left OPEN) | NEEDS_DATA (unresolved exception) |

Add one more engine-level unit test: closing 264.99 kg gives variance −15.01 → NEEDS_REVIEW (just past the boundary).

## 7. Tests (must all pass on SQLite; API tests also with TEST_DATABASE_URL on PostgreSQL)

- `tests/test_reconciliation_engine.py`: each status, inclusive boundary and just past it, sign handling of
  adjustments, intermediate counts not treated as flows, events at exactly the count timestamp, conflicting counts,
  APPROVED flagged event included, REJECTED excluded, OPEN exception → NEEDS_DATA, Decimal-only arithmetic,
  custom tolerance.
- `tests/test_reconciliation_api.py`: import `reconciliation_scenarios.csv`, run every row in
  `expected_reconciliations.csv` through `POST /api/v1/reconciliations` and assert status, variance and tolerance.
  Also test the list filters, detail with linked events and formula, 404, 422 validations, the audit row, and that
  approving the FAC-15 exception and running again gives a new reconciliation with a different status while the old one is unchanged.
- The full existing suite (102 tests) still passes.

## 8. Docs to update

- `README.md`: M5 ✔️ done in the status table, new endpoints in the API table, a short "Reconciliation" section with
  the formula, and the known limitation (no yield or moisture modeling; counts are point-in-time).
- `docs/validation_rules.md`: REC-001..004 implemented, plus the status rules from section 3.
- `docs/data_dictionary.md`: new event types and the two new tables.

## 9. Definition of done (SRS §17)

Code plus tests for expected and failure behavior; results traceable to the events used; README and docs updated;
`pytest -q` passes. Report the actual test count and any test that was changed and why. Do not commit;
the developer reviews and commits.
