# RecyTrack dashboard

React + TypeScript + Vite single-page app for the RecyTrack API. All demo data is synthetic.

## Development

Start the API first (from `backend/`): `uvicorn app.main:app --reload` (port 8000). Then:

```bash
npm ci              # install exactly what package-lock.json lists
npm run dev         # http://localhost:5173 (proxies /api, /health, /docs to http://127.0.0.1:8000)
```

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload and the API proxy |
| `npm run typecheck` | `tsc --noEmit` |
| `npm test` | Vitest in watch mode; `npm test -- --run` runs once (CI) |
| `npm run build` | Type-check, then build to `dist/` |
| `npm run preview` | Serve the built `dist/` locally |

Node 20.19+ or 22.12+ is required (CI uses Node 20).

> If `npm install <package>` fails with `Cannot read properties of null (reading 'edgesOut')`, that is a bug in
> npm 10's peer-dependency resolution. `npm ci` is not affected. Use `npx npm@11 install <package>` to change
> dependencies.

## Layout

```
src/
  main.tsx, App.tsx       entry point; layout with sidebar navigation and routes (pages load lazily)
  styles.css              all styles, plain CSS with variables
  services/api.ts         typed fetch client; types mirror backend/app/schemas.py
  hooks/                  useApi (loading/error/data + reload), useUrlFilters (filters in the query string)
  components/             StatusBadge, StatTile, DataTable, Pagination, FilterBar, ErrorBanner, EmptyState, Loading, RunSummary
  pages/                  Overview, Ingestion, Records, Exceptions, ExceptionDetail, Reconciliations, ReconciliationDetail, SourceHealth
  utils/format.ts         decimal-string and UTC formatting, query strings
  utils/reviewer.ts       remembers the reviewer name in localStorage
  __tests__/              Vitest + React Testing Library (fetch is mocked)
```

## Conventions

- **Quantities stay decimal strings.** `formatDecimal` adds thousands separators and rounds to 3 decimals for
  display by working on the digits, so no value passes through a float. A non-zero value that would round to zero
  is shown in full. `Number()` is only used to feed chart values (counts).
- **Times are UTC**, shown as `2026-10-01 09:00 UTC`. Date-time inputs are labelled "(UTC)" and sent with `Z`.
- **Errors show the API's `detail`** (string, `{message}`, or FastAPI validation errors), with a Retry button.
- **Filters live in the URL**, so a filtered view can be shared and survives a refresh. Export links carry the
  same filters.
- Status badges always show the status as text; colour is never the only signal.

## Docker

`Dockerfile` builds with Node and serves `dist/` from nginx. `nginx.conf` falls back to `index.html` for app routes
and proxies `/api`, `/health`, `/docs` and `/openapi.json` to the `api` service. From the repository root:
`docker compose up --build`, then open http://localhost:5173.
