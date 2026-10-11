import { describe, expect, it } from "vitest";

import {
  buildQuery,
  formatDecimal,
  formatKg,
  formatQuantity,
  formatRate,
  formatUtc,
  localInputToUtcIso,
} from "../utils/format";

describe("formatDecimal", () => {
  it.each([
    ["1000", "1,000"],
    ["-12.5", "-12.5"],
    ["453.59237", "453.592"],
    ["1000.17117585", "1,000.171"],
    ["0", "0"],
    ["1234567.5", "1,234,567.5"],
    ["15.000", "15"],
    ["-80", "-80"],
    ["-0.17117585", "-0.171"],
    ["10.0017117585", "10.002"],
  ])("%s -> %s", (input, expected) => {
    expect(formatDecimal(input)).toBe(expected);
  });

  it("rounds half up on the digits, carrying into the integer part", () => {
    expect(formatDecimal("0.9995")).toBe("1");
    expect(formatDecimal("999.9996")).toBe("1,000");
    expect(formatDecimal("-2.0005")).toBe("-2.001");
    expect(formatDecimal("2.0004")).toBe("2");
  });

  it("never loses the sign, even when rounding would show zero", () => {
    expect(formatDecimal("-0.0001")).toBe("-0.0001");
    expect(formatDecimal("0.00002")).toBe("0.00002");
    expect(formatDecimal("-0.0005")).toBe("-0.001");
  });

  it("keeps digits a float would lose", () => {
    expect(formatDecimal("12345678901234567890.5")).toBe("12,345,678,901,234,567,890.5");
    expect(formatDecimal("0.1000000000000000055", 19)).toBe("0.1000000000000000055");
  });

  it("handles missing and unexpected values", () => {
    expect(formatDecimal(null)).toBe("—");
    expect(formatDecimal(undefined)).toBe("—");
    expect(formatDecimal("")).toBe("—");
    expect(formatDecimal("1E+3")).toBe("1E+3"); // not a plain decimal: shown as received
  });

  it("formats kg and quantities with units", () => {
    expect(formatKg("280")).toBe("280 kg");
    expect(formatKg(null)).toBe("—");
    expect(formatQuantity("2204.62", "lb")).toBe("2,204.62 lb");
    expect(formatQuantity("1", null)).toBe("1");
  });
});

describe("formatUtc", () => {
  it.each([
    ["2026-10-01T09:00:00Z", "2026-10-01 09:00 UTC"],
    ["2026-10-01T09:00:00+00:00", "2026-10-01 09:00 UTC"],
    ["2026-10-02T06:15:00.123456+00:00", "2026-10-02 06:15 UTC"],
    ["2026-10-02T08:15:00+02:00", "2026-10-02 06:15 UTC"],
  ])("%s -> %s", (input, expected) => {
    expect(formatUtc(input)).toBe(expected);
  });

  it("can show seconds and handles missing or invalid values", () => {
    expect(formatUtc("2026-10-31T23:59:59Z", true)).toBe("2026-10-31 23:59:59 UTC");
    expect(formatUtc(null)).toBe("—");
    expect(formatUtc("not a date")).toBe("not a date");
  });
});

describe("buildQuery", () => {
  it("drops empty filters", () => {
    expect(buildQuery({ facility_id: "FAC-01", status: "", batch_id: undefined, run_id: null, page: 2 })).toBe(
      "?facility_id=FAC-01&page=2",
    );
    expect(buildQuery({ a: "  " })).toBe("");
    expect(buildQuery({})).toBe("");
  });

  it("encodes values", () => {
    expect(buildQuery({ date_from: "2026-10-01T00:00", q: "a&b" })).toBe("?date_from=2026-10-01T00%3A00&q=a%26b");
  });
});

describe("other helpers", () => {
  it("formats rates", () => {
    expect(formatRate(0.48)).toBe("48.0%");
    expect(formatRate(null)).toBe("—");
  });

  it("reads datetime-local values as UTC", () => {
    expect(localInputToUtcIso("2026-10-01T00:00")).toBe("2026-10-01T00:00:00Z");
    expect(localInputToUtcIso("2026-10-31T23:59:59")).toBe("2026-10-31T23:59:59Z");
    expect(localInputToUtcIso("")).toBe("");
  });
});
