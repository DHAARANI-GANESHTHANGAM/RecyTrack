# M6 — Dashboard: Implementation Spec

Implements SRS §9 (User Interface Requirements) and FR-16 (dashboard) on top of the existing API (M4, M5).
Read README.md and `backend/app/api/routes.py` + `backend/app/schemas.py` first; the UI must use the API
exactly as it is. The only backend change allowed is the small `meta` endpoint in section 3.

## 1. Stack and decisions

- **React + TypeScript + Vite** in a new top-level `frontend/` folder. Use current stable versions and commit
  `package-lock.json`.
- **react-router-dom** for pages and **recharts** for charts. No other UI framework: plain CSS
  (one `src/styles.css` with CSS variables), so the code stays easy to read and explain in an interview.
- No global state library. A small typed API client in `src/services/api.ts` plus simple hooks.
- **No CORS needed.** In development, Vite proxies `/api` and `/health` to `http://127.0.0.1:8000`.
  In Docker, nginx serves the built app and proxies `/api` and `/health` to the `api` service. All API calls
  use relative URLs (`/api/v1/...`).
- **Quantities are decimal strings** in the API. Display them as received, with formatting (thousand
  separators, max 3 decimals for display) done on the string. Never do arithmetic with `parseFloat`.
  `Number()` is allowed only to feed chart values.
- Timestamps are UTC from the API. Show them in UTC with a "UTC" label (e.g. `2026-10-01 09:00 UTC`).
- Single-user local demo, no login (SRS §16). Remember the reviewer name (`actor_label`) in `localStorage`
  (wrapped in try/catch).
- A thin banner on every page: "Demo data is synthetic. Not connected to any real facility."

## 2. Folder layout (SRS §13)

```
frontend/
  index.html
  package.json
  vite.config.ts            # dev proxy for /api and /health
  tsconfig.json
  Dockerfile                # multi-stage: node build -> nginx:alpine
  nginx.conf                # serves dist/, SPA fallback to index.html, proxies /api and /health to http://api:8000
  src/
    main.tsx
    App.tsx                 # layout: sidebar nav + routes
    styles.css
    services/api.ts         # typed fetch wrapper + all endpoint functions + TypeScript types matching schemas.py
    components/             # StatusBadge, StatTile, DataTable, Pagination, FilterBar, ErrorBanner, EmptyState, Loading
    pages/                  # Overview, Ingestion, Records, Exceptions, ExceptionDetail, Reconciliations, ReconciliationDetail
    utils/format.ts         # decimal-string formatting, UTC date formatting, build query strings
  src/__tests__/            # Vitest + React Testing Library
```

## 3. Small backend addition: `GET /api/v1/meta`

Dropdowns need valid values. Add to `routes.py` (and a schema in `schemas.py`):

```json
{
  "event_types": ["CONSUMPTION", "INVENTORY_ADJUSTMENT", ...],   // from config.EVENT_TYPES, sorted
  "material_codes": ["PLASTIC_FILM", "RECYCLED_RESIN"],          // sorted unique values of config.MATERIAL_ALIASES
  "facilities": ["FAC-01", "FAC-02", ...],                       // distinct non-null facility_id in material_events
  "validation_statuses": ["ACCEPTED", "FLAGGED", "QUARANTINED"],
  "review_statuses": ["OPEN", "APPROVED", "REJECTED", "NEEDS_INFO"],
  "reconciliation_statuses": ["WITHIN_TOLERANCE", "NEEDS_REVIEW", "NEEDS_DATA"],
  "default_tolerance": {"absolute_kg": "5", "percent_of_throughput": "1.0"}
}
```
Add tests for it in `backend/tests/test_api.py` (empty database, and after importing a fixture).

## 4. Pages

Every page handles four states: **loading**, **error** (show the API's `detail` message and a Retry button),
**empty** (a helpful message, e.g. "No runs yet. Import a CSV on the Ingestion page."), and **data**.

| Route | Content | API |
|---|---|---|
| `/` **Overview** | Stat tiles: runs, received, accepted, quarantined, flagged, duplicates, open exceptions; rates as %. Bar chart of `issues_by_rule`. Latest 5 runs (table, link to Ingestion). Latest 5 reconciliations with status badges. API health indicator from `/health`. | `GET /metrics/quality`, `GET /ingestion/runs?page_size=5`, `GET /reconciliations?page_size=5`, `GET /health` |
| `/ingestion` **Ingestion** | File picker (only `.csv`) + Import button. After upload, show the run summary (status, counts). On 4xx show the error message; for 422 also show the failed run. Below: paged runs table (file name, started, status, received/accepted/quarantined/flagged/duplicates) with a status filter. Clicking a run goes to `/records?run_id=...`. | `POST /ingestion/csv`, `GET /ingestion/runs` |
| `/records` **Records** | FilterBar: facility, material, event type, status, batch, run_id, date from/to. Filters live in the URL query string (shareable, survive refresh). Paged table: source id, facility, material, type, quantity + unit, quantity_kg, timestamp (UTC), batch, status badge. "Export CSV" button links to `/api/v1/reports/records.csv` with the same filters. | `GET /records`, `GET /meta` |
| `/exceptions` **Exceptions** | Same filters + rule code + review status. Table: source id, facility, status badge, rule codes, review status, created. Row click opens detail. "Export CSV" links to `/api/v1/reports/exceptions.csv` with the same filters. | `GET /quarantine`, `GET /meta` |
| `/exceptions/:eventId` **Exception detail** | Three panels: **Original row** (raw_payload as a key/value table, row number, payload hash), **Normalized values**, **Issues** (rule code, field, message, severity, raw value, review status). Run info with link. **Review form**: review status select, reviewer name (required, remembered), note; submit with PATCH and refresh. **Review history** (actor, status change, note, time). A sentence explaining that reviewing never changes the original values. | `GET /quarantine/{id}`, `PATCH /quarantine/{id}/review` |
| `/reconciliations` **Reconciliation** | Form: facility (select from meta), material, period start/end (date-time inputs, sent as UTC ISO with `Z`), optional tolerance overrides, reviewer name. Submit → navigate to the new detail. Below: paged list with facility/material/status filters. | `POST /reconciliations`, `GET /reconciliations`, `GET /meta` |
| `/reconciliations/:id` **Reconciliation detail** | Status badge with plain-English meaning (NEEDS_REVIEW = "needs a person to look; not proof of an error"; NEEDS_DATA = "evidence incomplete"). The `formula` string in a monospace block. Inputs table (opening, receipts, production, adjustments, shipments, losses, consumption, expected closing, closing, variance). `tolerance_explanation`. `reasons` list. Linked events grouped by role, with excluded events and their `excluded_reason`. A small bar chart of inflows vs outflows is optional. | `GET /reconciliations/{id}` |

Navigation: sidebar (or top bar on narrow screens) with Overview, Ingestion, Records, Exceptions, Reconciliation,
and a link to the API docs (`/docs`; proxy it too). The SRS **Source health** page is **out of scope for M6**
(it needs VAL-010 and the simulated API source, planned for M7). Show it in the nav as disabled with the label "planned".

**Status badge colors** (meaning must also be in the text, not color alone): ACCEPTED / WITHIN_TOLERANCE = green,
FLAGGED / NEEDS_REVIEW = amber, QUARANTINED = red, NEEDS_DATA = grey, DUPLICATE = blue-grey, review OPEN = outlined.

Layout must work at 375 px width (tables scroll horizontally inside their container, the page itself does not).
Use semantic HTML (`<table>`, `<label for>`, `<button>`), visible focus styles, and text alternatives for charts
(e.g. a caption with the totals).

## 5. Docker and CI

- `docker-compose.yml`: add a `web` service built from `./frontend`, `depends_on: api`, port `127.0.0.1:5173:80`.
  Keep `db` and `api` unchanged. Then `docker compose up --build` gives the dashboard at http://localhost:5173.
- `.github/workflows/ci.yml`: add a `frontend` job: `actions/setup-node` (Node 20), `npm ci`,
  `npm run typecheck`, `npm test -- --run`, `npm run build` (working-directory `frontend`).
- `package.json` scripts: `dev`, `build`, `preview`, `typecheck` (`tsc --noEmit`), `test` (`vitest`).

## 6. Tests

Frontend (Vitest + React Testing Library + jsdom; mock `fetch`):
- `format.ts`: decimal-string formatting (`"1000"`, `"-12.5"`, `"453.59237"`, `"1000.17117585"`), never loses
  the sign, UTC date formatting, query-string building drops empty filters.
- `api.ts`: error responses surface the API `detail` (string and object forms); 503 shows the database message.
- Overview renders tiles from a mocked metrics response and the empty state when `runs = 0`.
- Records: filters are read from and written to the URL; the export link carries the same filters.
- Exception detail: renders raw payload and issues; the review form requires a reviewer name, sends the PATCH
  body, and shows the new history entry.
- Reconciliation detail: shows formula, reasons, and the right explanation per status.

Backend: the new `meta` tests. **The full existing backend suite (163 tests) must still pass.**

## 7. Docs

- `README.md`: M6 ✔️ done; "Dashboard" section with how to run it (dev: `uvicorn` + `npm run dev`;
  Docker: `docker compose up --build`), a list of pages, and room for screenshots (the developer adds real ones).
  Update the architecture diagram to show React → FastAPI.
- Add `frontend/README.md` with dev commands.

## 8. Definition of done (SRS §17)

The main workflow from SRS Appendix B can be done entirely in the browser: import the clean fixture → import the
corrupted fixture → open a quarantined record and see its rule code and original value → re-import and see
duplicates counted → run a reconciliation and read its formula, tolerance and status.
`npm run typecheck`, `npm test -- --run`, `npm run build` and backend `pytest -q` all pass.
Report the actual test counts. Do not commit; the developer reviews and commits.
