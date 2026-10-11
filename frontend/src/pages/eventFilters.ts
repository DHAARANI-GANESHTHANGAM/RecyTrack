import type { FilterField } from "../components/FilterBar";
import type { Meta } from "../services/api";

/** Filters shared by Records and Exceptions; they match the API's EventFilters. */
export const EVENT_FILTER_NAMES = [
  "facility_id",
  "material_code",
  "event_type",
  "status",
  "batch_id",
  "run_id",
  "date_from",
  "date_to",
];

/** Dropdowns use /meta; if it could not be loaded, they fall back to free text so filtering still works. */
function choice(name: string, label: string, options: string[] | undefined): FilterField {
  return options ? { name, label, type: "select", options } : { name, label, type: "text" };
}

export function eventFilterFields(meta: Meta | null, statuses?: string[]): FilterField[] {
  return [
    choice("facility_id", "Facility", meta?.facilities),
    choice("material_code", "Material", meta?.material_codes),
    choice("event_type", "Event type", meta?.event_types),
    choice("status", "Status", statuses ?? meta?.validation_statuses),
    { name: "batch_id", label: "Batch", placeholder: "e.g. BATCH-42" },
    { name: "run_id", label: "Run ID" },
    { name: "date_from", label: "From (UTC, inclusive)", type: "datetime" },
    { name: "date_to", label: "To (UTC, exclusive)", type: "datetime" },
  ];
}

/**
 * URL filter values as API query parameters. datetime-local values have no offset,
 * which the API reads as UTC, matching the "(UTC)" labels.
 */
export function apiFilters(values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v !== ""));
}
