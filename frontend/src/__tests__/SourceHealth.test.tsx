import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import SourceHealth from "../pages/SourceHealth";
import { mockFetch, renderAt } from "./helpers";

const FRESH = {
  source_name: "simulated_api",
  last_run_at: "2026-10-10T11:00:00+00:00",
  last_run_status: "FAILED",
  last_success_at: "2026-10-10T09:00:00+00:00",
  age_hours: 3.0,
  freshness_window_hours: 24,
  status: "FRESH",
  message: "Last successful import 3.0 h ago; window is 24 h. The latest run failed at 2026-10-10T11:00:00+00:00.",
};

const STALE = {
  source_name: "csv",
  last_run_at: "2026-10-01T09:00:00+00:00",
  last_run_status: "SUCCEEDED",
  last_success_at: "2026-10-01T09:00:00+00:00",
  age_hours: 219.0,
  freshness_window_hours: 168,
  status: "STALE",
  message: "No successful import in 219.0 h; window is 168 h.",
};

const NEVER = {
  source_name: "partner_feed",
  last_run_at: null,
  last_run_status: null,
  last_success_at: null,
  age_hours: null,
  freshness_window_hours: 24,
  status: "NEVER_SUCCEEDED",
  message: "No successful import yet; window is 24 h.",
};

const RUN = {
  run_id: "run-sim",
  source_name: "simulated_api",
  file_name: "GET /v1/events",
  status: "SUCCEEDED",
  started_at: "2026-10-10T12:00:00+00:00",
  finished_at: "2026-10-10T12:00:01+00:00",
  received_count: 200,
  accepted_count: 180,
  quarantined_count: 14,
  flagged_count: 6,
  duplicate_count: 0,
  error_summary: null,
};

const UNAVAILABLE =
  "Simulated source at http://simulator:8001 unreachable after 3 attempts (last error: timeout). Check that the simulator is running.";

function row(source: string) {
  return screen.getByRole("cell", { name: source }).closest("tr") as HTMLElement;
}

describe("Source health", () => {
  it("shows each source with its freshness badge, message and last run", async () => {
    mockFetch({ "GET /api/v1/sources/health": () => [STALE, FRESH, NEVER] });
    renderAt("/sources", "/sources", <SourceHealth />);

    await screen.findByRole("cell", { name: "simulated_api" });
    const fresh = within(row("simulated_api"));
    expect(fresh.getByText("FRESH", { selector: ".badge" })).toHaveClass("badge-green");
    expect(fresh.getByText(/The latest run failed/)).toBeInTheDocument();
    expect(fresh.getByText("FAILED", { selector: ".badge" })).toBeInTheDocument();
    expect(fresh.getByText("2026-10-10 11:00 UTC")).toBeInTheDocument();
    expect(fresh.getByText("24 h")).toBeInTheDocument();

    const stale = within(row("csv"));
    expect(stale.getByText("STALE", { selector: ".badge" })).toHaveClass("badge-amber");
    expect(stale.getByText("No successful import in 219.0 h; window is 168 h.")).toBeInTheDocument();

    const never = within(row("partner_feed"));
    expect(never.getByText("NEVER SUCCEEDED", { selector: ".badge" })).toHaveClass("badge-grey");

    expect(screen.getByText(/This source is/)).toHaveTextContent("simulated");
  });

  it("imports from the simulated API, shows the run and reloads the table", async () => {
    const user = userEvent.setup();
    let healthCalls = 0;
    const { calls } = mockFetch({
      "GET /api/v1/sources/health": () => {
        healthCalls += 1;
        return [FRESH];
      },
      "POST /api/v1/ingestion/simulated-api": () => ({ status: 201, body: RUN }),
    });
    renderAt("/sources", "/sources", <SourceHealth />);
    await screen.findByRole("cell", { name: "simulated_api" });

    await user.click(screen.getByRole("button", { name: "Import from simulated API" }));

    expect(await screen.findByText(/Import finished: GET \/v1\/events/)).toBeInTheDocument();
    const summary = screen.getByText(/Import finished/).closest(".run-summary") as HTMLElement;
    expect(within(summary).getByText("200")).toBeInTheDocument();
    expect(within(summary).getByText("180")).toBeInTheDocument();
    expect(within(summary).getByRole("link", { name: "See this run's records" })).toHaveAttribute(
      "href",
      "/records?run_id=run-sim",
    );
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({});
    expect(healthCalls).toBe(2);
  });

  it("shows the source error and the FAILED run for a 502", async () => {
    const user = userEvent.setup();
    const failed = { ...RUN, status: "FAILED", received_count: 0, accepted_count: 0, quarantined_count: 0, flagged_count: 0, error_summary: UNAVAILABLE };
    mockFetch({
      "GET /api/v1/sources/health": () => [FRESH],
      "POST /api/v1/ingestion/simulated-api": () => ({ status: 502, body: { detail: { message: UNAVAILABLE, run: failed } } }),
    });
    renderAt("/sources", "/sources", <SourceHealth />);
    await user.click(await screen.findByRole("button", { name: "Import from simulated API" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("unreachable after 3 attempts (last error: timeout)");
    expect(screen.getByText(/Failed run: GET \/v1\/events/)).toBeInTheDocument();
    const summary = screen.getByText(/Failed run/).closest(".run-summary") as HTMLElement;
    expect(within(summary).getByText("FAILED", { selector: ".badge" })).toBeInTheDocument();
    expect(within(summary).getByText(UNAVAILABLE)).toBeInTheDocument();
  });

  it("shows an error with Retry when the health check cannot be loaded", async () => {
    mockFetch({ "GET /api/v1/sources/health": () => ({ status: 503, body: { detail: "Database unavailable." } }) });
    renderAt("/sources", "/sources", <SourceHealth />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Database unavailable.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
