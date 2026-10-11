# Demo script (SRS Appendix B)

A 5–7 minute walkthrough for an interview. Every number below comes from the fixtures in `data/fixtures/` and was
checked against the API on a fresh database; `python -m scripts.measure` and the test suite check the same values.
All data is synthetic.

**Before you start:** `docker compose up --build` on an **empty** database (`docker compose down -v` first if you
have run it before), so the counts match. Keep a terminal open in `backend/` for step 8.

---

### 1. Start the stack and open Overview (≈ 30 s)

- **Click:** open http://localhost:5173.
- **Appears:** the synthetic-data banner and "No runs yet. Import a CSV on the Ingestion page."
- **Say:** "RecyTrack is a data-quality pipeline for recycling records: import, validate, quarantine with a reason,
  and reconcile material flows. Everything you'll see is synthetic data."

### 2. Import `valid_events.csv` (≈ 45 s)

- **Click:** **Ingestion** → *CSV file* → `data/fixtures/valid_events.csv` → **Import**.
- **Appears:** "Import finished: valid_events.csv", status SUCCEEDED, a run ID in the runs table, and
  Received **10**, Accepted **10**, Quarantined **0**, Flagged **0**, Duplicates **0**.
- **Say:** "Every row is stored exactly as received before anything else happens, with a hash and its run ID.
  Normalization works on a copy, so `2204.62 lb` or `  recycled   resin ` is kept as the source sent it."

### 3. Import `invalid_events.csv` (≈ 45 s)

- **Click:** **Ingestion** → `invalid_events.csv` → **Import**.
- **Appears:** Received **15**: Accepted **2**, Quarantined **9**, Flagged **3**, Duplicates **1**.
  On **Overview**: Runs 2, Received 25, Accepted 12 (48.0%), Quarantined 9 (36.0%), Flagged 3 (12.0%),
  Duplicates 1 (4.0%), Open exceptions 12, and the issues-by-rule chart.
- **Say:** "This file has a missing quantity, an unsupported unit, a duplicate row, a negative shipment and more.
  Errors are quarantined, suspicious-but-usable rows are flagged, and the exact duplicate creates no new event."

### 4. Exceptions → SRC-2002, then record a decision (≈ 75 s)

- **Click:** **Exceptions** → *Rule code* `VAL-004` → open **SRC-2002**.
- **Appears:** Issue **VAL-004** on `unit`: "Unit 'tons' is not supported. Use kg or lb." Original row: quantity
  `750`, unit **`tons`**, row 3 of the run. Normalized quantity in kg is empty.
- **Say:** "It isn't deleted, because deleting hides the problem and breaks traceability. The original value, the
  row number and the run stay visible, so someone can fix it at the source."
- **Click:** *Decision* `NEEDS_INFO`, *Reviewer name* (e.g. `demo`), *Note* "Ask the facility which unit" →
  **Save decision**.
- **Appears:** the review status changes and **Review history** shows the decision with the reviewer and time.
- **Say:** "A decision is a separate audit row. The source value is never overwritten."

### 5. Re-import `valid_events.csv` (≈ 30 s)

- **Click:** **Ingestion** → `valid_events.csv` → **Import**.
- **Appears:** Received **10**, Accepted **0**, Duplicates **10**. The **Records** count does not grow.
- **Say:** "Re-importing is safe. Duplicates are caught by a hash check in the pipeline, and a unique constraint in
  the database backs it up if two imports race."

### 6. Reconciliation: FAC-11, then FAC-12 (≈ 75 s)

- **Click:** **Ingestion** → `reconciliation_scenarios.csv` → **Import** (Received 33, Accepted 32, Flagged 1).
  Then **Reconciliation** → facility `FAC-11`, material `PLASTIC_FILM`, period 2026-10-01 00:00 to
  2026-10-31 23:59:59 UTC → **Run reconciliation**.
- **Appears:** **NEEDS_REVIEW**. Formula: `expected_closing_kg = 1000 opening + 500 receipts + 0 production
  + 0 adjustments - 0 shipments - 20 losses - 1200 consumption = 280`; `variance_kg = 200 closing - 280 expected
  = -80`; tolerance **15 kg** (max of 5 kg absolute, 1.0% of throughput 1500 kg). Linked events by role.
- **Say:** "Eighty kilos are unaccounted for, beyond the 15 kg tolerance. That's a flag for a person to look at,
  not proof of fraud or an error: it could be moisture, a missed weighing or a late record."
- **Click:** run it again for `FAC-12`.
- **Appears:** **NEEDS_DATA**: "No INVENTORY_COUNT after 2026-10-01T00:00:00Z and at or before
  2026-10-31T23:59:59Z". No variance is shown.
- **Say:** "Without a closing count the system doesn't guess a variance. It says what is missing."

### 7. Source health and a source failure (≈ 60 s)

- **Click:** **Source health** → **Import from simulated API**.
- **Appears:** "Import finished: GET /v1/events": Received **200**, Accepted **180**, Quarantined **14**,
  Flagged **6**. `simulated_api` is **FRESH**.
- **Do:** in a terminal, `docker compose stop simulator`. **Click:** **Import from simulated API** again.
- **Appears:** after the retries (a few seconds), one red message: "Simulated source at http://simulator:8001
  unreachable after 3 attempts (last error: connection error …). Check that the simulator is running." and a
  **Failed run** with status FAILED. The table shows `simulated_api` still **FRESH**, with "The latest run failed;
  see its error on the Ingestion page." and the failed run's time under *Last run*.
- **Say:** "Only timeouts, connection errors and 5xx are retried, three tries with backoff. The failure is saved as
  a run, the app doesn't crash, and freshness stays honest: the last good import is still inside its 24 h window."
- **Do:** `docker compose start simulator` to restore it.

### 8. Tests and measured results (≈ 45 s)

- **Do:** in `backend/`: `pytest -q`, then `python -m scripts.measure`.
- **Appears:** `pytest` ends with the pass count (227 passed in the latest local run). The measure script prints the
  tables from [results.md](results.md): 225 labeled rows, 33 / 33 faulty rows detected, 0 false positives on 192
  clean rows, 225 / 225 exact matches, 7 / 7 reconciliation scenarios.
- **Say:** "These numbers come from the script, not from me. And to be clear: I wrote the labeled sets together with
  the rules, so 100% means the rules do what they were designed to do on known cases. It's not a real-world accuracy
  claim."

### 9. Limitations (≈ 30 s)

- **Say:** "It's synthetic data only, with simplified accounting: no yield or moisture model, two materials, kg and
  lb. It's single-user with no login, imports are manual, and it's not connected to any private company system."

---

## Likely interview questions

**Why `Decimal` and not floats?**
Quantities are summed and compared against a tolerance. Binary floats can't represent values like `0.1` exactly, so
a balance that should be exactly zero could come out as `-0.0000000001` and land on the wrong side of the boundary.
`Decimal` keeps every digit; the API sends quantities as strings and the dashboard formats the string, so no float
touches them anywhere.

**How do you stop duplicates if two imports run at the same time?**
Two layers. The pipeline looks up the payload hashes already stored for each `(source_name, source_record_id)` and
marks exact matches as VAL-007 duplicates. If two imports race past that check, the database unique constraint on
`(source_name, source_record_id, payload_hash)` rejects the second insert, and the API answers `409` with
"These records were imported by another run at the same time". Re-running then counts them as duplicates.

**Why NEEDS_DATA instead of computing a variance anyway?**
Without an opening or closing count, a "variance" would just be the size of the missing data, and it would look like
lost material. Saying `NEEDS_DATA` with the reason is more useful than a confident wrong number. The same applies
when an exception in the window is still open: the balance waits for the review.

**Why quarantine instead of deleting or fixing bad rows?**
Deleting hides the problem and breaks traceability; auto-fixing invents data. Quarantine keeps the original row with
a specific rule code, so a person can decide, and the decision is audited separately.

**What is the difference between QUARANTINED and FLAGGED?**
An `ERROR` issue means the record can't be trusted (no quantity, unknown unit), so it is quarantined and left out of
balances. A `WARNING` means it is usable but suspicious (a negative shipment, an unknown material alias, a conflicting
version), so it is flagged and counts in a balance only once a reviewer approves it.

**How do you know the rules work?**
A labeled set of 225 rows, every one with its expected status and rule codes, checked by the tests and by
`scripts.measure` in CI. It proves the rules behave as designed on known cases; real data would have error types I
haven't thought of.

**What would you change for production?**
Authentication and roles for reviewers; Alembic migrations instead of `create_all`; imports as background jobs with a
scheduler and alerts on STALE sources; a real source integration with agreed contracts; and yield and moisture
modeling validated with people who run the process. Tolerances would be set from evidence, not illustrative values.

**Why a separate simulator service instead of mocking the API?**
So the client is tested over real HTTP with real failure modes: timeouts, refused connections, 5xx, slow responses.
Unit tests still use `httpx.MockTransport` so they need no network.
