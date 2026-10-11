import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import Records from "../pages/Records";
import { EMPTY_PAGE, META, mockFetch, renderAt } from "./helpers";

const EVENT = {
  event_id: "e1",
  run_id: "run-1",
  raw_id: "raw-1",
  source_name: "csv",
  source_record_id: "SRC-1002",
  facility_id: "FAC-01",
  material_name_raw: "Plastic film - mixed",
  material_code: "PLASTIC_FILM",
  event_type: "RECEIPT",
  quantity: "2204.62",
  unit_raw: "lb",
  unit: "lb",
  quantity_kg: "999.998815",
  event_timestamp_raw: "2026-10-01T11:30:00Z",
  event_timestamp: "2026-10-01T11:30:00+00:00",
  batch_id: "BATCH-43",
  validation_status: "ACCEPTED",
  created_at: "2026-10-01T12:00:00+00:00",
};

function setup(path: string) {
  const mock = mockFetch({
    "GET /api/v1/meta": () => META,
    "GET /api/v1/records": () => ({ ...EMPTY_PAGE, items: [EVENT], total: 1 }),
  });
  renderAt(path, "/records", <Records />);
  return mock;
}

describe("Records", () => {
  it("reads filters from the URL and sends them to the API", async () => {
    const { calls } = setup("/records?facility_id=FAC-01&status=ACCEPTED&page=2");
    expect(await screen.findByText("SRC-1002")).toBeInTheDocument();

    const request = calls.find((c) => c.path === "/api/v1/records")!;
    expect(request.params.get("facility_id")).toBe("FAC-01");
    expect(request.params.get("status")).toBe("ACCEPTED");
    expect(request.params.get("page")).toBe("2");
    expect(await screen.findByLabelText("Facility")).toHaveValue("FAC-01");
  });

  it("shows decimal strings as received, with units", async () => {
    setup("/records");
    expect(await screen.findByText("2,204.62 lb")).toBeInTheDocument();
    expect(screen.getByText("999.999 kg")).toBeInTheDocument();
    expect(screen.getByText("2026-10-01 11:30 UTC")).toBeInTheDocument();
  });

  it("writes applied filters to the URL and the export link carries them", async () => {
    const user = userEvent.setup();
    const { calls } = setup("/records");
    await screen.findByText("SRC-1002");
    await waitFor(() => expect(screen.getByLabelText("Material").querySelectorAll("option").length).toBeGreaterThan(1));

    await user.selectOptions(screen.getByLabelText("Material"), "RECYCLED_RESIN");
    await user.type(screen.getByLabelText("Batch"), "BATCH-42");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/records?material_code=RECYCLED_RESIN&batch_id=BATCH-42"),
    );
    await waitFor(() => {
      const last = calls.filter((c) => c.path === "/api/v1/records").at(-1)!;
      expect(last.params.get("material_code")).toBe("RECYCLED_RESIN");
      expect(last.params.get("batch_id")).toBe("BATCH-42");
    });
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/v1/reports/records.csv?material_code=RECYCLED_RESIN&batch_id=BATCH-42",
    );
  });

  it("clearing filters empties the URL", async () => {
    const user = userEvent.setup();
    setup("/records?facility_id=FAC-01");
    await screen.findByText("SRC-1002");
    await user.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent(/^\/records$/));
    expect(screen.getByRole("link", { name: "Export CSV" })).toHaveAttribute("href", "/api/v1/reports/records.csv");
  });

  it("shows an empty state", async () => {
    mockFetch({ "GET /api/v1/meta": () => META, "GET /api/v1/records": () => EMPTY_PAGE });
    renderAt("/records", "/records", <Records />);
    expect(await screen.findByText(/No records yet/)).toBeInTheDocument();
  });
});
