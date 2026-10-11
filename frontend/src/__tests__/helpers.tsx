import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { vi } from "vitest";

export interface FetchCall {
  method: string;
  url: string;
  path: string;
  params: URLSearchParams;
  body: unknown;
}

type Handler = (call: FetchCall) => { status?: number; body: unknown } | unknown;

/**
 * Replace global fetch. Handlers are keyed by "METHOD /path" (query string ignored).
 * A handler returns either a plain body (200) or {status, body}.
 */
export function mockFetch(handlers: Record<string, Handler>) {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const parsed = new URL(url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    let body: unknown = init?.body;
    if (typeof body === "string") body = JSON.parse(body);
    const call: FetchCall = { method, url, path: parsed.pathname, params: parsed.searchParams, body };
    calls.push(call);
    const handler = handlers[`${method} ${parsed.pathname}`];
    if (!handler) return jsonResponse({ detail: `No mock for ${method} ${parsed.pathname}` }, 404);
    const result = handler(call);
    if (result && typeof result === "object" && "status" in result && "body" in result) {
      const r = result as { status: number; body: unknown };
      return jsonResponse(r.body, r.status);
    }
    return jsonResponse(result, 200);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Shows the router's current URL so tests can assert on query strings. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

export function renderAt(path: string, routePattern: string, element: ReactElement, extraRoutes: Record<string, ReactElement> = {}) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={routePattern} element={element} />
        {Object.entries(extraRoutes).map(([p, el]) => (
          <Route key={p} path={p} element={el} />
        ))}
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

export const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 50, filters: {} };

export const META = {
  event_types: ["CONSUMPTION", "INVENTORY_ADJUSTMENT", "INVENTORY_COUNT", "LOSS", "PRODUCTION", "RECEIPT", "SHIPMENT"],
  material_codes: ["PLASTIC_FILM", "RECYCLED_RESIN"],
  facilities: ["FAC-01", "FAC-02"],
  validation_statuses: ["ACCEPTED", "FLAGGED", "QUARANTINED"],
  review_statuses: ["OPEN", "APPROVED", "REJECTED", "NEEDS_INFO"],
  reconciliation_statuses: ["WITHIN_TOLERANCE", "NEEDS_REVIEW", "NEEDS_DATA"],
  default_tolerance: { absolute_kg: "5", percent_of_throughput: "1.0" },
};
