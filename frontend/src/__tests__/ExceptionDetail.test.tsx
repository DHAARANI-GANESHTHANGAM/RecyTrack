import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import ExceptionDetail from "../pages/ExceptionDetail";
import type { Audit, ExceptionDetail as Detail } from "../services/api";
import { mockFetch, renderAt } from "./helpers";

const DETAIL: Detail = {
  event: {
    event_id: "e1",
    run_id: "run-1",
    raw_id: "raw-1",
    source_name: "csv",
    source_record_id: "SRC-2002",
    facility_id: "FAC-01",
    material_name_raw: "Plastic film",
    material_code: "PLASTIC_FILM",
    event_type: "RECEIPT",
    quantity: "750",
    unit_raw: "tons",
    unit: null,
    quantity_kg: null,
    event_timestamp_raw: "2026-10-01T10:00:00Z",
    event_timestamp: "2026-10-01T10:00:00+00:00",
    batch_id: "BATCH-50",
    validation_status: "QUARANTINED",
    created_at: "2026-10-01T12:00:00+00:00",
  },
  raw: {
    raw_id: "raw-1",
    row_number: 3,
    raw_payload: { source_record_id: "SRC-2002", unit: "tons", quantity: "750", batch_id: "" },
    payload_hash: "ab".repeat(32),
    received_at: "2026-10-01T12:00:00+00:00",
  },
  run: {
    run_id: "run-1",
    source_name: "csv",
    file_name: "invalid_events.csv",
    status: "SUCCEEDED",
    started_at: "2026-10-01T12:00:00+00:00",
    finished_at: "2026-10-01T12:00:01+00:00",
    received_count: 15,
    accepted_count: 2,
    quarantined_count: 9,
    flagged_count: 3,
    duplicate_count: 1,
    error_summary: null,
  },
  issues: [
    {
      issue_id: 7,
      rule_code: "VAL-004",
      field_name: "unit",
      message: "Unit 'tons' is not supported. Use kg or lb.",
      severity: "ERROR",
      raw_value: "tons",
      review_status: "OPEN",
      created_at: "2026-10-01T12:00:00+00:00",
    },
  ],
  review_history: [],
};

const AUDIT: Audit = {
  audit_id: 1,
  action: "review_decision",
  actor_label: "analyst-1",
  details: { previous_review_status: ["OPEN"], review_status: "REJECTED", note: "Unit cannot be converted", rule_codes: ["VAL-004"] },
  created_at: "2026-10-02T08:30:00+00:00",
};

function setup() {
  let reviewed = false;
  const mock = mockFetch({
    "GET /api/v1/quarantine/e1": () =>
      reviewed
        ? {
            ...DETAIL,
            issues: [{ ...DETAIL.issues[0], review_status: "REJECTED" }],
            review_history: [AUDIT],
          }
        : DETAIL,
    "PATCH /api/v1/quarantine/e1/review": () => {
      reviewed = true;
      return { event_id: "e1", review_status: "REJECTED", audit: AUDIT };
    },
  });
  renderAt("/exceptions/e1", "/exceptions/:eventId", <ExceptionDetail />);
  return mock;
}

describe("Exception detail", () => {
  it("renders the original row, normalized values and issues", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "Exception SRC-2002" })).toBeInTheDocument();

    const original = screen.getByRole("region", { name: "Original row" });
    expect(within(original).getByText("unit")).toBeInTheDocument();
    expect(within(original).getAllByText("tons").length).toBeGreaterThan(0);
    expect(within(original).getByText("(empty)")).toBeInTheDocument(); // blank batch_id is visible
    expect(within(original).getByText(/Row 3 of the file/)).toBeInTheDocument();

    const issues = screen.getByRole("region", { name: "Issues" });
    expect(within(issues).getByText("VAL-004")).toBeInTheDocument();
    expect(within(issues).getByText("Unit 'tons' is not supported. Use kg or lb.")).toBeInTheDocument();
    expect(within(issues).getByText("OPEN")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "invalid_events.csv" })).toHaveAttribute("href", "/records?run_id=run-1");
    expect(screen.getByText(/never changes the original row or the normalized values/)).toBeInTheDocument();
    expect(screen.getByText("No decisions yet.")).toBeInTheDocument();
  });

  it("requires a reviewer name before sending", async () => {
    const user = userEvent.setup();
    const { calls } = setup();
    await screen.findByRole("heading", { name: "Exception SRC-2002" });

    await user.click(screen.getByRole("button", { name: "Save decision" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter your reviewer name.");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("sends the PATCH body, remembers the reviewer and shows the new history entry", async () => {
    const user = userEvent.setup();
    const { calls } = setup();
    await screen.findByRole("heading", { name: "Exception SRC-2002" });

    await user.selectOptions(screen.getByLabelText("Decision"), "REJECTED");
    await user.type(screen.getByLabelText("Reviewer name (required)"), "analyst-1");
    await user.type(screen.getByLabelText("Note"), "Unit cannot be converted");
    await user.click(screen.getByRole("button", { name: "Save decision" }));

    const history = screen.getByRole("region", { name: "Review history" });
    expect(await within(history).findByText("analyst-1")).toBeInTheDocument();
    expect(within(history).getByText(/OPEN → REJECTED/)).toBeInTheDocument();
    expect(within(history).getByText("“Unit cannot be converted”")).toBeInTheDocument();
    expect(within(history).getByText("2026-10-02 08:30:00 UTC")).toBeInTheDocument();

    const patch = calls.find((c) => c.method === "PATCH")!;
    expect(patch.path).toBe("/api/v1/quarantine/e1/review");
    expect(patch.body).toEqual({ review_status: "REJECTED", actor_label: "analyst-1", note: "Unit cannot be converted" });
    expect(window.localStorage.getItem("recytrack.actor_label")).toBe("analyst-1");
  });

  it("pre-fills the remembered reviewer name", async () => {
    window.localStorage.setItem("recytrack.actor_label", "analyst-2");
    setup();
    expect(await screen.findByLabelText("Reviewer name (required)")).toHaveValue("analyst-2");
  });

  it("shows a 404 message with Retry", async () => {
    mockFetch({ "GET /api/v1/quarantine/nope": () => ({ status: 404, body: { detail: "No record with id nope." } }) });
    renderAt("/exceptions/nope", "/exceptions/:eventId", <ExceptionDetail />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No record with id nope.");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
