/**
 * Display helpers.
 *
 * Quantities arrive from the API as decimal strings (e.g. "1000.17117585") so no
 * precision is lost. All formatting here works on the string's digits; nothing is
 * converted to a float, so a value is never silently changed on its way to the screen.
 */

const DECIMAL = /^([+-]?)(\d+)(?:\.(\d+))?$/;
export const MISSING = "—";

/** Add thousands separators to a string of digits: "1234567" -> "1,234,567". */
function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Add one to a string of digits: "0999" -> "1000". */
function incrementDigits(digits: string): string {
  const out = digits.split("");
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i] !== "9") {
      out[i] = String(Number(out[i]) + 1);
      return out.join("");
    }
    out[i] = "0";
  }
  return "1" + out.join("");
}

/**
 * Format a decimal string for display: thousands separators and at most
 * `maxDecimals` decimals (rounded half up, on the digits). Trailing zeros are dropped.
 *
 * "1000" -> "1,000", "-12.5" -> "-12.5", "453.59237" -> "453.592",
 * "1000.17117585" -> "1,000.171". A non-zero value that would round to zero is
 * shown in full instead, so its sign and size are never hidden.
 * Anything that is not a plain decimal string is returned unchanged.
 */
export function formatDecimal(value: string | null | undefined, maxDecimals = 3): string {
  if (value === null || value === undefined || value === "") return MISSING;
  const match = DECIMAL.exec(value.trim());
  if (!match) return value;
  const [, sign, intPart, fracPart = ""] = match;

  let integer = intPart;
  let fraction = fracPart;
  if (fraction.length > maxDecimals) {
    const roundUp = Number(fraction[maxDecimals]) >= 5;
    let kept = integer + fraction.slice(0, maxDecimals);
    if (roundUp) kept = incrementDigits(kept);
    integer = kept.slice(0, kept.length - maxDecimals) || "0";
    fraction = kept.slice(kept.length - maxDecimals);
  }
  fraction = fraction.replace(/0+$/, "");
  integer = integer.replace(/^0+(?=\d)/, "");

  const isZero = /^0*$/.test(integer + fraction);
  const wasZero = /^0*$/.test(intPart + fracPart);
  if (isZero && !wasZero) {
    // Rounding would show "0" for a real value: show every digit instead.
    return formatDecimal(value, fracPart.length);
  }
  const shownSign = sign === "-" && !isZero ? "-" : "";
  return shownSign + groupThousands(integer) + (fraction ? "." + fraction : "");
}

/** "280" -> "280 kg"; null -> "—". */
export function formatKg(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? MISSING : `${formatDecimal(value)} kg`;
}

/** A quantity with its unit as received: ("2204.62", "lb") -> "2,204.62 lb". */
export function formatQuantity(value: string | null | undefined, unit: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return MISSING;
  return unit ? `${formatDecimal(value)} ${unit}` : formatDecimal(value);
}

const pad = (n: number) => String(n).padStart(2, "0");

/**
 * "2026-10-01T09:00:00+00:00" -> "2026-10-01 09:00 UTC".
 * The API sends UTC; any offset is converted so the label is always true.
 */
export function formatUtc(value: string | null | undefined, withSeconds = false): string {
  if (!value) return MISSING;
  // Python can send microseconds; Date understands milliseconds.
  const date = new Date(value.replace(/(\.\d{3})\d+/, "$1"));
  if (Number.isNaN(date.getTime())) return value;
  const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
  const time = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}` + (withSeconds ? `:${pad(date.getUTCSeconds())}` : "");
  return `${day} ${time} UTC`;
}

/** A rate from the API (0.48) as a percentage ("48.0%"). Rates are ratios, not quantities. */
export function formatRate(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? MISSING : `${(rate * 100).toFixed(1)}%`;
}

/** "NEEDS_REVIEW" -> "NEEDS REVIEW". */
export function humanize(value: string): string {
  return value.replace(/_/g, " ");
}

export type QueryValue = string | number | null | undefined;

/** {a: "1", b: "", c: undefined} -> "?a=1". Empty filters are dropped. */
export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    const text = String(value).trim();
    if (text !== "") search.set(key, text);
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

/**
 * Value of an <input type="datetime-local"> read as UTC: "2026-10-01T00:00" -> "2026-10-01T00:00:00Z".
 * Returns "" for an empty or malformed value.
 */
export function localInputToUtcIso(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(:\d{2})?/.exec(value);
  if (!match) return "";
  return `${match[1]}T${match[2]}${match[3] ?? ":00"}Z`;
}
