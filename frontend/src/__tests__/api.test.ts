import { describe, expect, it, vi } from "vitest";

import { API_UNREACHABLE, ApiError, api, DATABASE_UNAVAILABLE, exceptionsCsvUrl, recordsCsvUrl } from "../services/api";
import { mockFetch } from "./helpers";

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError);
    return err as ApiError;
  }
  throw new Error("expected the request to fail");
}

describe("api error handling", () => {
  it("surfaces a string detail", async () => {
    mockFetch({ "GET /api/v1/quarantine/x": () => ({ status: 404, body: { detail: "No record with id x." } }) });
    const err = await failure(api.getException("x"));
    expect(err.status).toBe(404);
    expect(err.message).toBe("No record with id x.");
  });

  it("surfaces an object detail and keeps the body (failed import run)", async () => {
    const run = { run_id: "r1", status: "FAILED" };
    mockFetch({
      "POST /api/v1/ingestion/csv": () => ({ status: 422, body: { detail: { message: "CSV header does not match", run } } }),
    });
    const err = await failure(api.importCsv(new File(["a,b\n"], "bad.csv")));
    expect(err.status).toBe(422);
    expect(err.message).toBe("CSV header does not match");
    expect((err.body as { detail: { run: unknown } }).detail.run).toEqual(run);
  });

  it("joins FastAPI validation errors into one message", async () => {
    mockFetch({
      "POST /api/v1/reconciliations": () => ({
        status: 422,
        body: {
          detail: [
            { loc: ["body", "material_code"], msg: "Value error, unknown material_code", type: "value_error" },
            { loc: ["body"], msg: "Value error, period_end must be after period_start", type: "value_error" },
          ],
        },
      }),
    });
    const err = await failure(
      api.createReconciliation({ facility_id: "F", material_code: "X", period_start: "a", period_end: "b" }),
    );
    expect(err.message).toBe("material_code: unknown material_code; period_end must be after period_start");
  });

  it("shows the database message on 503", async () => {
    const dbDown = "Database unavailable. Check that PostgreSQL is running and DATABASE_URL is set, then retry.";
    mockFetch({ "GET /api/v1/ingestion/runs": () => ({ status: 503, body: { detail: dbDown } }) });
    expect((await failure(api.listRuns())).message).toBe(dbDown);

    mockFetch({ "GET /api/v1/ingestion/runs": () => ({ status: 503, body: undefined }) });
    expect((await failure(api.listRuns())).message).toBe(DATABASE_UNAVAILABLE);
  });

  it("explains when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await failure(api.meta());
    expect(err.status).toBe(0);
    expect(err.message).toBe(API_UNREACHABLE);
  });
});

describe("api requests", () => {
  it("uses relative URLs and drops empty filters", async () => {
    const { calls } = mockFetch({ "GET /api/v1/records": () => ({ items: [], total: 0, page: 1, page_size: 50, filters: {} }) });
    await api.listRecords({ facility_id: "FAC-01", status: "", page: 2 });
    expect(calls[0].url).toBe("/api/v1/records?facility_id=FAC-01&page=2");
  });

  it("sends review decisions as PATCH JSON", async () => {
    const { calls } = mockFetch({ "PATCH /api/v1/quarantine/e1/review": () => ({ event_id: "e1" }) });
    await api.reviewException("e1", { review_status: "APPROVED", actor_label: "analyst-1", note: null });
    expect(calls[0].method).toBe("PATCH");
    expect(calls[0].body).toEqual({ review_status: "APPROVED", actor_label: "analyst-1", note: null });
  });

  it("reads health even when the database is down", async () => {
    mockFetch({ "GET /health": () => ({ status: 503, body: { status: "degraded", database: "unavailable" } }) });
    expect(await api.health()).toEqual({ status: "degraded", database: "unavailable" });
  });

  it("builds export links with the same filters", () => {
    expect(recordsCsvUrl({ facility_id: "FAC-01", status: "" })).toBe("/api/v1/reports/records.csv?facility_id=FAC-01");
    expect(exceptionsCsvUrl({ rule_code: "VAL-004" })).toBe("/api/v1/reports/exceptions.csv?rule_code=VAL-004");
  });
});
