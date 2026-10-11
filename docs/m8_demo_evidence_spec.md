# M8 — Demo and Evidence: Implementation Spec

The last milestone (SRS §12 M8, §15 Success Metrics, §17 Definition of Done, Appendices B and C). Most of it is
**measuring and presenting** what M1–M7 built, honestly. Read README.md, every file in `docs/`, `data/fixtures/`,
`backend/` and `frontend/` first. Make no behavior changes except the two UI fixes in section 6.

**Golden rule (SRS §15, App. C):** every number in the README, docs or portfolio text must come from a script
output or a test run in this repo. No invented or rounded-up claims. When a number depends on the machine
(timings), say which machine.

## 1. Measurement script: `backend/scripts/measure.py`

Run as `python -m scripts.measure [--database-url URL] [--out ../docs/results.md]` from `backend/`.
It must be deterministic and need no network. It reports:

1. **Labeled-set quality** for each labeled set and in total:
   - `valid_events.csv` and `invalid_events.csv`, using `data/fixtures/expected_outcomes.csv` and `run_csv_ingestion`
     with `InMemoryRepository`;
   - the simulated source, using `simulator.data.generate_events()` items, `run_api_ingestion` and
     `data/fixtures/simulated_expected_outcomes.csv`.

   Match rows by `row_number`. A row is *faulty* if its expected status is not `ACCEPTED`. Report: rows, faulty,
   detected (actual status ≠ ACCEPTED), **detection rate** = detected/faulty, clean, false positives
   (clean but actual ≠ ACCEPTED), **false-positive rate** = FP/clean, and **exact matches** (status AND the set of
   rule codes both equal the label). Also give a per-rule breakdown: expected vs found per rule code.
2. **Idempotency**: import each labeled set twice into the same repository and report the new events on the second run
   (expected 0) and the duplicate count.
3. **Reconciliation scenarios**: import `reconciliation_scenarios.csv` through the API (`TestClient`, SQLite in
   memory), run each row of `expected_reconciliations.csv`, and report status, variance and tolerance against the
   expected values (match count).
4. **Performance (NFR-08)**, only when `--database-url` is given: generate a seeded 10,000-row CSV in memory (same mix
   as the existing perf test idea: some faulty units, types, materials and negatives), import it through the API, import
   it again, and report seconds plus counts. Also record Python version, OS, CPU count and database version.
   Never commit the generated 10k file.
5. **Test counts**: not computed by the script. The README states them from the latest CI run (see section 5).

Write the results to `docs/results.md` as Markdown tables, with a header line giving the date, git commit (short hash)
and environment. Also print them to the console. The script exits with code 1 if any exact-match, idempotency or
reconciliation check is below 100%, so it can guard against regressions.

Add `tests/test_measure.py`, which runs the script's functions (not the timing part) and asserts the results structure,
plus 100% exact matches on the current fixtures.

**CI:** add a step to `backend-tests`: `python -m scripts.measure` (no DB URL, so no timing). It fails the build if
quality regresses.

### Expected results (measured on the reviewer's machine for this spec; your timing will differ)

| Measure | Expected |
|---|---|
| Labeled rows (CSV 25 + simulated 200) | 225 |
| Faulty / detected | 33 / 33 → **100.0%** detection |
| Clean / false positives | 192 / 0 → **0.0%** false-positive rate |
| Exact status and rule-code matches | 225 / 225 |
| Reconciliation scenarios | 7 / 7 |
| 10,000-row import, PostgreSQL 16 (Linux container) | ~5.0 s first import (4,212 accepted, 4,699 quarantined, 1,089 flagged); ~1.2 s re-import (10,000 duplicates, 0 new) |

**Honesty note to put in `docs/results.md` and the README:** the labeled sets were written by the developer
together with the rules, so 100% shows the rules behave **as designed** on known cases. It is **not** a real-world
accuracy claim. Real data would contain error types that aren't in the fixtures.

## 2. README rewrite (`README.md`)

Structure:
1. **Title and one-paragraph summary**, plus a "Synthetic data" notice (no company data, not affiliated with any company).
2. **Screenshots**: 4–6 images from `docs/screenshots/` (the developer adds the PNGs; reference these file names:
   `overview.png`, `exceptions.png`, `exception-detail.png`, `reconciliation.png`, `source-health.png`, `api-docs.png`).
3. **Architecture**: a Mermaid diagram (GitHub renders Mermaid). Flow:
   CSV upload / simulated API → FastAPI → ingestion → normalization → validation → PostgreSQL, then
   reconciliation and metrics → React dashboard, with the simulator as a separate service. One paragraph per layer.
   Put the longer version in `docs/architecture.md`.
4. **Key design decisions** (short bullets): raw data is immutable; Decimal and UTC; quarantine instead of delete;
   idempotency (pipeline check plus a DB unique constraint); NEEDS_DATA instead of guessing; review decisions are
   audited and never overwrite data; bounded retries; no secrets in logs.
5. **Measured results**: copy the tables from `docs/results.md` with the honesty note, plus test counts from CI.
6. **Quick start**: Docker (`docker compose up --build` → http://localhost:5173), and without Docker (three terminals:
   simulator, API, dashboard), for Windows PowerShell and macOS/Linux.
7. **Demo**: link to `docs/demo_script.md`.
8. **SRS acceptance checklist**: a table with every item of SRS §10, ✔️, and *where it is shown* (test file, page,
   or doc section).
9. **API overview** (keep it short; link to `/docs`), **validation rules** (link), **data dictionary** (link),
   **operations** (link).
10. **Known limitations**: synthetic data only; simplified accounting (no yield or moisture); single-user, no auth;
    no scheduler (imports are manual); schema via `create_all`, no migrations; 2 materials and 2 units.
11. **Project history**: the milestones M1–M8, one line each.

## 3. `docs/demo_script.md` (SRS Appendix B)

A 5–7 minute walkthrough for an interview, with numbered steps. For each step: **what to click**, **what appears**
(the exact expected numbers from the fixtures), and **what to say** (one or two sentences). Cover:
1. Start the stack and open Overview (empty).
2. Import `valid_events.csv`: run ID and counts; mention the raw rows are stored unchanged.
3. Import `invalid_events.csv`: 2 accepted / 9 quarantined / 3 flagged / 1 duplicate.
4. Exceptions → SRC-2002: rule VAL-004, original value `tons`. Explain why it is kept, not deleted. Record a decision and show the review history.
5. Re-import `valid_events.csv`: 10 duplicates, 0 new.
6. Import `reconciliation_scenarios.csv`, run FAC-11: NEEDS_REVIEW, −80 kg vs 15 kg tolerance. Explain that this is
   a review flag, not proof of fraud or error. Then FAC-12: NEEDS_DATA.
7. Source health: import from the simulated API, stop the simulator, try again → clear error, FAILED run, no crash.
8. Show `pytest -q` and `python -m scripts.measure` output.
9. Limitations (synthetic data, simplified accounting, no private systems).

Add a short "likely interview questions and answers" section (5–8 Q&As, e.g. *Why Decimal?*, *How do you stop
duplicates if two imports run at once?*, *Why NEEDS_DATA instead of a variance?*, *What would you change for
production?*).

## 4. `docs/portfolio.md` (SRS Appendix C)

- A project description (about 80 words) built from the Appendix C template, with the **measured** numbers filled in.
- 3–4 resume bullets in action-result form, using only numbers from `docs/results.md`. Where a number is
  fixture-based, say so (e.g. "on a 225-row labeled test set").
- One line on how AI assistance was used, written neutrally, which the developer can edit.

## 5. Test counts and version

- Run the full suites and put the actual counts in the README (backend: SQLite and PostgreSQL in CI; frontend).
- Set the API version in `app/main.py` and `frontend/package.json` to `1.0.0`.
- Mark M8 ✔️ done in the README status table.

## 6. Two UI fixes (found in the M7 review)

1. **Source health "Details"** text overflows the table and shows a raw ISO timestamp with microseconds
   (e.g. `2026-10-11T03:11:24.821430+0…`). Format timestamps like the rest of the dashboard
   (`2026-10-11 03:11 UTC`): either return a clean timestamp field from the API and format it in the UI, or format the
   time inside the message (preferred: keep the message free of raw timestamps, and add `last_failed_at` if needed).
   Long text must wrap within the cell.
2. On a failed simulated import the error message appears **twice** (red banner and again under "Failed run").
   Show it once.

Add or adjust tests for both.

## 7. Definition of done

- `docs/results.md` is generated by the script, not typed by hand.
- The README is complete per section 2, and every SRS §10 acceptance item maps to evidence.
- `demo_script.md` and `portfolio.md` exist.
- The UI fixes are in, and all tests pass (report the actual counts).
- CI runs the measure script.

Do not commit; the developer reviews, adds the screenshots and commits.
