import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ReconciliationDetail, { STATUS_MEANING } from "../pages/ReconciliationDetail";
import type { ReconciliationDetail as Detail } from "../services/api";
import { mockFetch, renderAt } from "./helpers";

const FORMULA = [
  "expected_closing_kg = 1000 opening + 500 receipts + 0 production + 0 adjustments - 0 shipments - 20 losses - 1200 consumption = 280",
  "variance_kg = 200 closing - 280 expected = -80",
  "throughput_kg = 1000 opening + 500 receipts + 0 production = 1500",
].join("\n");

const BASE: Detail = {
  reconciliation_id: "rec-1",
  facility_id: "FAC-11",
  material_code: "PLASTIC_FILM",
  period_start: "2026-10-01T00:00:00+00:00",
  period_end: "2026-10-31T23:59:59+00:00",
  opening_stock_kg: "1000",
  receipts_kg: "500",
  production_kg: "0",
  adjustments_kg: "0",
  shipments_kg: "0",
  losses_kg: "20",
  consumption_kg: "1200",
  closing_stock_kg: "200",
  expected_closing_kg: "280",
  variance_kg: "-80",
  throughput_kg: "1500",
  tolerance_kg: "15",
  tolerance_absolute_kg: "5",
  tolerance_percent: "1",
  status: "NEEDS_REVIEW",
  reasons: [
    "|variance| 80 kg exceeds tolerance 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg). This is a flag for review, not proof of an error",
  ],
  created_at: "2026-11-01T08:00:00+00:00",
  formula: FORMULA,
  tolerance_explanation:
    "tolerance_kg = 15 kg (max of 5 kg absolute, 1.0% of throughput 1500 kg); within tolerance when |variance_kg| <= tolerance_kg",
  events: {
    opening_count: [
      {
        event_id: "e1",
        source_record_id: "REC-1101",
        event_type: "INVENTORY_COUNT",
        quantity_kg: "1000",
        event_timestamp: "2026-10-01T00:00:00+00:00",
        validation_status: "ACCEPTED",
        excluded_reason: null,
      },
    ],
    receipt: [],
    excluded: [
      {
        event_id: "e9",
        source_record_id: "REC-1506",
        event_type: "SHIPMENT",
        quantity_kg: "-10",
        event_timestamp: "2026-10-25T14:00:00+00:00",
        validation_status: "FLAGGED",
        excluded_reason: "FLAGGED and not approved by a reviewer (review status OPEN)",
      },
    ],
  },
};

function show(detail: Detail) {
  mockFetch({ [`GET /api/v1/reconciliations/${detail.reconciliation_id}`]: () => detail });
  renderAt(`/reconciliations/${detail.reconciliation_id}`, "/reconciliations/:id", <ReconciliationDetail />);
}

describe("Reconciliation detail", () => {
  it("shows the formula, reasons, tolerance and balance", async () => {
    show(BASE);
    expect(await screen.findByRole("heading", { name: "FAC-11 · PLASTIC_FILM" })).toBeInTheDocument();

    const formula = screen.getByLabelText("Formula with this reconciliation's numbers");
    expect(formula.tagName).toBe("PRE");
    expect(formula.textContent).toBe(FORMULA);

    const reasons = screen.getByRole("region", { name: "Reasons" });
    expect(within(reasons).getByText(/exceeds tolerance 15 kg/)).toBeInTheDocument();
    expect(screen.getByText(BASE.tolerance_explanation)).toBeInTheDocument();

    const balance = screen.getByRole("region", { name: "Balance (kg)" });
    expect(within(balance).getByRole("row", { name: /Variance/ })).toHaveTextContent("-80 kg");
    expect(within(balance).getByRole("row", { name: /Expected closing/ })).toHaveTextContent("280 kg");
  });

  it("explains NEEDS_REVIEW as a review flag, not proof of an error", async () => {
    show(BASE);
    expect(await screen.findByText("NEEDS REVIEW")).toBeInTheDocument();
    expect(screen.getByText(STATUS_MEANING.NEEDS_REVIEW)).toBeInTheDocument();
    expect(STATUS_MEANING.NEEDS_REVIEW).toMatch(/needs a person to look; not proof of an error/i);
  });

  it("explains NEEDS_DATA as incomplete evidence and shows unknown values", async () => {
    show({
      ...BASE,
      reconciliation_id: "rec-2",
      status: "NEEDS_DATA",
      closing_stock_kg: null,
      variance_kg: null,
      reasons: ["No INVENTORY_COUNT after 2026-10-01T00:00:00Z and at or before 2026-10-31T23:59:59Z"],
    });
    expect(await screen.findByText("NEEDS DATA")).toBeInTheDocument();
    expect(screen.getByText(STATUS_MEANING.NEEDS_DATA)).toBeInTheDocument();
    expect(STATUS_MEANING.NEEDS_DATA).toMatch(/evidence incomplete/i);
    expect(screen.getByText(/No INVENTORY_COUNT after/)).toBeInTheDocument();
    const balance = screen.getByRole("region", { name: "Balance (kg)" });
    expect(within(balance).getByRole("row", { name: /Variance/ })).toHaveTextContent("unknown");
  });

  it("explains WITHIN_TOLERANCE", async () => {
    show({ ...BASE, reconciliation_id: "rec-3", status: "WITHIN_TOLERANCE" });
    expect(await screen.findByText("WITHIN TOLERANCE")).toBeInTheDocument();
    expect(screen.getByText(STATUS_MEANING.WITHIN_TOLERANCE)).toBeInTheDocument();
  });

  it("lists linked events by role, with the excluded reason", async () => {
    show(BASE);
    expect(await screen.findByRole("heading", { name: "Opening count (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Receipts/ })).not.toBeInTheDocument(); // empty roles hidden
    expect(screen.getByRole("heading", { name: "Excluded events (1)" })).toBeInTheDocument();
    expect(screen.getByText("FLAGGED and not approved by a reviewer (review status OPEN)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "REC-1506" })).toHaveAttribute("href", "/exceptions/e9");
    expect(screen.getByText("-10 kg")).toBeInTheDocument();
  });
});
