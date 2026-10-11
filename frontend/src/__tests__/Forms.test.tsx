import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Ingestion from "../pages/Ingestion";
import Reconciliations from "../pages/Reconciliations";
import { EMPTY_PAGE, META, mockFetch, renderAt } from "./helpers";

describe("Reconciliation form", () => {
  it("sends the period as UTC ISO with Z and tolerances as decimal strings, then opens the detail", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({
      "GET /api/v1/meta": () => META,
      "GET /api/v1/reconciliations": () => EMPTY_PAGE,
      "POST /api/v1/reconciliations": () => ({ status: 201, body: { reconciliation_id: "new-1" } }),
    });
    renderAt("/reconciliations", "/reconciliations", <Reconciliations />, {
      "/reconciliations/:id": <p>detail page</p>,
    });

    // The list's filter bar also has a "Facility" field, so work inside the form.
    const form = within(await screen.findByRole("region", { name: "Run a reconciliation" }));
    await user.selectOptions(form.getByLabelText("Facility"), "FAC-02");
    // datetime-local inputs are set directly; typing them key by key is not reliable in jsdom.
    fireEvent.change(form.getByLabelText("Period start (UTC)"), { target: { value: "2026-10-01T00:00:00" } });
    fireEvent.change(form.getByLabelText("Period end (UTC)"), { target: { value: "2026-10-31T23:59:59" } });
    await user.type(form.getByLabelText("Absolute tolerance (kg, optional)"), "7.5");
    await user.click(form.getByRole("button", { name: "Run reconciliation" }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/reconciliations/new-1"));
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toEqual({
      facility_id: "FAC-02",
      material_code: "PLASTIC_FILM",
      period_start: "2026-10-01T00:00:00Z",
      period_end: "2026-10-31T23:59:59Z",
      absolute_tolerance_kg: "7.5",
    });
  });

  it("shows the API's validation message", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/v1/meta": () => META,
      "GET /api/v1/reconciliations": () => EMPTY_PAGE,
      "POST /api/v1/reconciliations": () => ({
        status: 422,
        body: { detail: [{ loc: ["body"], msg: "Value error, period_end must be after period_start" }] },
      }),
    });
    renderAt("/reconciliations", "/reconciliations", <Reconciliations />);
    await user.click(await screen.findByRole("button", { name: "Run reconciliation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("period_end must be after period_start");
  });

  it("asks for data when no facility has been imported", async () => {
    mockFetch({ "GET /api/v1/meta": () => ({ ...META, facilities: [] }), "GET /api/v1/reconciliations": () => EMPTY_PAGE });
    renderAt("/reconciliations", "/reconciliations", <Reconciliations />);
    expect(await screen.findByText(/No facilities yet/)).toBeInTheDocument();
  });
});

describe("Ingestion", () => {
  const FAILED_RUN = {
    run_id: "run-9",
    source_name: "csv",
    file_name: "bad.csv",
    status: "FAILED",
    started_at: "2026-10-01T09:00:00+00:00",
    finished_at: "2026-10-01T09:00:00+00:00",
    received_count: 0,
    accepted_count: 0,
    quarantined_count: 0,
    flagged_count: 0,
    duplicate_count: 0,
    error_summary: "CSV header does not match the contract (missing columns: unit).",
  };

  it("uploads a CSV and shows the run summary", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch({
      "GET /api/v1/ingestion/runs": () => EMPTY_PAGE,
      "POST /api/v1/ingestion/csv": () => ({
        status: 201,
        body: { ...FAILED_RUN, file_name: "valid_events.csv", status: "SUCCEEDED", received_count: 10, accepted_count: 10, error_summary: null },
      }),
    });
    renderAt("/ingestion", "/ingestion", <Ingestion />);
    const button = await screen.findByRole("button", { name: "Import" });
    expect(button).toBeDisabled();

    await user.upload(screen.getByLabelText("CSV file"), new File(["x"], "valid_events.csv", { type: "text/csv" }));
    await user.click(button);

    expect(await screen.findByText(/Import finished: valid_events.csv/)).toBeInTheDocument();
    expect(screen.getByText("SUCCEEDED", { selector: ".badge" })).toBeInTheDocument();
    const upload = calls.find((c) => c.method === "POST")!;
    expect(upload.body).toBeInstanceOf(FormData);
    expect((upload.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("shows the error and the failed run for a 422", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /api/v1/ingestion/runs": () => EMPTY_PAGE,
      "POST /api/v1/ingestion/csv": () => ({
        status: 422,
        body: { detail: { message: FAILED_RUN.error_summary, run: FAILED_RUN } },
      }),
    });
    renderAt("/ingestion", "/ingestion", <Ingestion />);
    await user.upload(await screen.findByLabelText("CSV file"), new File(["a,b"], "bad.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("missing columns: unit");
    expect(screen.getByText(/Failed run: bad.csv/)).toBeInTheDocument();
    expect(screen.getByText("FAILED", { selector: ".badge" })).toBeInTheDocument();
  });
});
