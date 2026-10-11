import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Overview from "../pages/Overview";
import { EMPTY_PAGE, mockFetch, renderAt } from "./helpers";

const METRICS = {
  run_id: null,
  runs: 2,
  failed_runs: 0,
  received: 25,
  accepted: 12,
  quarantined: 9,
  flagged: 3,
  duplicates: 1,
  acceptance_rate: 0.48,
  quarantine_rate: 0.36,
  flag_rate: 0.12,
  duplicate_rate: 0.04,
  open_exceptions: 12,
  issues_by_rule: { "VAL-001": 4, "VAL-005": 2 },
};

const RUN = {
  run_id: "run-1",
  source_name: "csv",
  file_name: "invalid_events.csv",
  status: "SUCCEEDED",
  started_at: "2026-10-01T09:00:00+00:00",
  finished_at: "2026-10-01T09:00:01+00:00",
  received_count: 15,
  accepted_count: 2,
  quarantined_count: 9,
  flagged_count: 3,
  duplicate_count: 1,
  error_summary: null,
};

const RECONCILIATION = {
  reconciliation_id: "rec-1",
  facility_id: "FAC-11",
  material_code: "PLASTIC_FILM",
  period_start: "2026-10-01T00:00:00+00:00",
  period_end: "2026-10-31T23:59:59+00:00",
  variance_kg: "-80",
  tolerance_kg: "15",
  status: "NEEDS_REVIEW",
};

function tile(label: string) {
  return screen.getByText(label, { selector: ".stat-label" }).closest(".stat-tile") as HTMLElement;
}

describe("Overview", () => {
  it("renders tiles, chart text, latest runs and reconciliations", async () => {
    mockFetch({
      "GET /api/v1/metrics/quality": () => METRICS,
      "GET /api/v1/ingestion/runs": () => ({ ...EMPTY_PAGE, items: [RUN], total: 1 }),
      "GET /api/v1/reconciliations": () => ({ ...EMPTY_PAGE, items: [RECONCILIATION], total: 1 }),
      "GET /health": () => ({ status: "ok", database: "ok" }),
    });
    renderAt("/", "/", <Overview />);

    expect(await screen.findByText("Data quality (all runs)")).toBeInTheDocument();
    expect(within(tile("Runs")).getByText("2")).toBeInTheDocument();
    expect(within(tile("Received")).getByText("25")).toBeInTheDocument();
    expect(within(tile("Accepted")).getByText("48.0%")).toBeInTheDocument();
    expect(within(tile("Quarantined")).getByText("9")).toBeInTheDocument();
    expect(within(tile("Flagged")).getByText("3")).toBeInTheDocument();
    expect(within(tile("Duplicates")).getByText("1")).toBeInTheDocument();
    expect(within(tile("Open exceptions")).getByText("12")).toBeInTheDocument();

    // Text alternative for the chart.
    expect(screen.getByText("6 issue(s): VAL-001 4, VAL-005 2.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "invalid_events.csv" })).toHaveAttribute("href", "/ingestion");
    expect(screen.getByRole("link", { name: "FAC-11 · PLASTIC_FILM" })).toHaveAttribute("href", "/reconciliations/rec-1");
    expect(screen.getByText("NEEDS REVIEW")).toBeInTheDocument();
    expect(screen.getByText("-80 kg")).toBeInTheDocument();
    expect(await screen.findByText("API and database OK")).toBeInTheDocument();
  });

  it("shows the empty state when there are no runs", async () => {
    mockFetch({
      "GET /api/v1/metrics/quality": () => ({ ...METRICS, runs: 0, received: 0, issues_by_rule: {} }),
      "GET /api/v1/ingestion/runs": () => EMPTY_PAGE,
      "GET /api/v1/reconciliations": () => EMPTY_PAGE,
      "GET /health": () => ({ status: "ok", database: "ok" }),
    });
    renderAt("/", "/", <Overview />);
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ingestion page" })).toHaveAttribute("href", "/ingestion");
    expect(screen.queryByText("Data quality (all runs)")).not.toBeInTheDocument();
  });

  it("shows the API error with a Retry button and the health problem", async () => {
    mockFetch({
      "GET /api/v1/metrics/quality": () => ({ status: 503, body: { detail: "Database unavailable." } }),
      "GET /api/v1/ingestion/runs": () => EMPTY_PAGE,
      "GET /api/v1/reconciliations": () => EMPTY_PAGE,
      "GET /health": () => ({ status: 503, body: { status: "degraded", database: "unavailable" } }),
    });
    renderAt("/", "/", <Overview />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Database unavailable.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(await screen.findByText("API degraded, database unavailable")).toBeInTheDocument();
  });

  it("shows the stale sources tile with a link to Source health", async () => {
    mockFetch({
      "GET /api/v1/metrics/quality": () => ({ ...METRICS, sources_stale: 1 }),
      "GET /api/v1/ingestion/runs": () => ({ ...EMPTY_PAGE, items: [RUN], total: 1 }),
      "GET /api/v1/reconciliations": () => EMPTY_PAGE,
      "GET /health": () => ({ status: "ok", database: "ok" }),
    });
    renderAt("/", "/", <Overview />);
    await screen.findByText("Data quality (all runs)");
    const stale = tile("Stale sources");
    expect(within(stale).getByText("1")).toBeInTheDocument();
    expect(within(stale).getByRole("link", { name: "Source health" })).toHaveAttribute("href", "/sources");
  });
});
