/**
 * Typed client for the RecyTrack REST API (backend/app/api/routes.py).
 *
 * Types mirror backend/app/schemas.py. Decimal quantities are strings and
 * timestamps are UTC ISO strings, exactly as the API sends them.
 * All URLs are relative: Vite (dev) and nginx (Docker) proxy /api to the backend.
 */
import { buildQuery, type QueryValue } from "../utils/format";

const BASE = "/api/v1";

/** Python Decimal serialized as a JSON string, e.g. "453.59237". Never parse for arithmetic. */
export type DecimalString = string;
/** UTC ISO 8601 timestamp, e.g. "2026-10-01T09:00:00Z". */
export type UtcIso = string;

export type ValidationStatus = "ACCEPTED" | "FLAGGED" | "QUARANTINED" | "DUPLICATE";
export type ReviewStatus = "OPEN" | "APPROVED" | "REJECTED" | "NEEDS_INFO";
export type ReconciliationStatus = "WITHIN_TOLERANCE" | "NEEDS_REVIEW" | "NEEDS_DATA";
export type RunStatus = "RUNNING" | "SUCCEEDED" | "FAILED";

export const REVIEW_STATUSES: ReviewStatus[] = ["OPEN", "APPROVED", "REJECTED", "NEEDS_INFO"];
export const RUN_STATUSES: RunStatus[] = ["SUCCEEDED", "FAILED", "RUNNING"];

export interface Run {
  run_id: string;
  source_name: string;
  file_name: string | null;
  status: RunStatus | string;
  started_at: UtcIso;
  finished_at: UtcIso | null;
  received_count: number;
  accepted_count: number;
  quarantined_count: number;
  flagged_count: number;
  duplicate_count: number;
  error_summary: string | null;
}

export interface Issue {
  issue_id: number;
  rule_code: string;
  field_name: string | null;
  message: string;
  severity: string;
  raw_value: string | null;
  review_status: ReviewStatus | string;
  created_at: UtcIso;
}

export interface MaterialEvent {
  event_id: string;
  run_id: string;
  raw_id: string;
  source_name: string;
  source_record_id: string | null;
  facility_id: string | null;
  material_name_raw: string | null;
  material_code: string | null;
  event_type: string | null;
  quantity: DecimalString | null;
  unit_raw: string | null;
  unit: string | null;
  quantity_kg: DecimalString | null;
  event_timestamp_raw: string | null;
  event_timestamp: UtcIso | null;
  batch_id: string | null;
  validation_status: ValidationStatus | string;
  created_at: UtcIso;
}

export interface ExceptionSummary extends MaterialEvent {
  issues: Issue[];
}

export interface RawRecord {
  raw_id: string;
  row_number: number;
  raw_payload: Record<string, string>;
  payload_hash: string;
  received_at: UtcIso;
}

export interface Audit {
  audit_id: number;
  action: string;
  actor_label: string;
  details: {
    previous_review_status?: string[];
    review_status?: string;
    note?: string | null;
    rule_codes?: string[];
    [key: string]: unknown;
  };
  created_at: UtcIso;
}

export interface ExceptionDetail {
  event: MaterialEvent;
  raw: RawRecord;
  run: Run;
  issues: Issue[];
  review_history: Audit[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  filters: Record<string, string>;
}

export interface ReviewIn {
  review_status: ReviewStatus;
  actor_label: string;
  note?: string | null;
}

export interface ReviewOut {
  event_id: string;
  review_status: ReviewStatus;
  audit: Audit;
}

export interface QualityMetrics {
  run_id: string | null;
  runs: number;
  failed_runs: number;
  received: number;
  accepted: number;
  quarantined: number;
  flagged: number;
  duplicates: number;
  acceptance_rate: number | null;
  quarantine_rate: number | null;
  flag_rate: number | null;
  duplicate_rate: number | null;
  open_exceptions: number;
  issues_by_rule: Record<string, number>;
}

export interface ReconciliationIn {
  facility_id: string;
  material_code: string;
  period_start: UtcIso;
  period_end: UtcIso;
  absolute_tolerance_kg?: DecimalString;
  percent_tolerance?: DecimalString;
  actor_label?: string;
}

export interface Reconciliation {
  reconciliation_id: string;
  facility_id: string;
  material_code: string;
  period_start: UtcIso;
  period_end: UtcIso;
  opening_stock_kg: DecimalString | null;
  receipts_kg: DecimalString | null;
  production_kg: DecimalString | null;
  adjustments_kg: DecimalString | null;
  shipments_kg: DecimalString | null;
  losses_kg: DecimalString | null;
  consumption_kg: DecimalString | null;
  closing_stock_kg: DecimalString | null;
  expected_closing_kg: DecimalString | null;
  variance_kg: DecimalString | null;
  throughput_kg: DecimalString | null;
  tolerance_kg: DecimalString | null;
  tolerance_absolute_kg: DecimalString;
  tolerance_percent: DecimalString;
  status: ReconciliationStatus | string;
  reasons: string[];
  created_at: UtcIso;
}

export interface LinkedEvent {
  event_id: string;
  source_record_id: string | null;
  event_type: string | null;
  quantity_kg: DecimalString | null;
  event_timestamp: UtcIso | null;
  validation_status: string;
  excluded_reason: string | null;
}

export interface ReconciliationDetail extends Reconciliation {
  formula: string;
  tolerance_explanation: string;
  events: Record<string, LinkedEvent[]>;
}

export interface Meta {
  event_types: string[];
  material_codes: string[];
  facilities: string[];
  validation_statuses: string[];
  review_statuses: string[];
  reconciliation_statuses: string[];
  default_tolerance: { absolute_kg: DecimalString; percent_of_throughput: DecimalString };
}

export interface Health {
  status: string;
  database: string;
}

// ---------------------------------------------------------------- errors

export const DATABASE_UNAVAILABLE =
  "The database is unavailable. Check that PostgreSQL is running, then retry.";
export const API_UNREACHABLE =
  "Cannot reach the API. Check that the backend is running (uvicorn on port 8000), then retry.";

/** An HTTP error with the API's own explanation in `message` and the parsed body in `body`. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

interface ValidationErrorItem {
  loc?: (string | number)[];
  msg?: string;
}

/** Turn FastAPI's `detail` (string, {message}, or a list of validation errors) into one sentence. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item: ValidationErrorItem) => {
        const field = (item.loc ?? []).filter((part) => part !== "body").join(".");
        const msg = (item.msg ?? "invalid value").replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string") {
    return (detail as { message: string }).message;
  }
  if (status === 503) return DATABASE_UNAVAILABLE;
  return `Request failed (HTTP ${status}).`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, API_UNREACHABLE);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body), body);
  return body as T;
}

function postJson<T>(path: string, data: unknown, method = "POST"): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------- endpoints

export type Filters = Record<string, QueryValue>;

export const api = {
  /** Health is read even on 503: the body says which part is down. */
  async health(): Promise<Health> {
    try {
      const response = await fetch("/health");
      const body = (await response.json().catch(() => null)) as Health | null;
      return body ?? { status: response.ok ? "ok" : "degraded", database: response.ok ? "ok" : "unavailable" };
    } catch {
      return { status: "unreachable", database: "unknown" };
    }
  },
  meta: () => request<Meta>(`${BASE}/meta`),
  qualityMetrics: (filters: Filters = {}) => request<QualityMetrics>(`${BASE}/metrics/quality${buildQuery(filters)}`),

  listRuns: (filters: Filters = {}) => request<Page<Run>>(`${BASE}/ingestion/runs${buildQuery(filters)}`),
  getRun: (runId: string) => request<Run>(`${BASE}/ingestion/runs/${encodeURIComponent(runId)}`),
  importCsv(file: File): Promise<Run> {
    const form = new FormData();
    form.append("file", file);
    return request<Run>(`${BASE}/ingestion/csv`, { method: "POST", body: form });
  },

  listRecords: (filters: Filters = {}) => request<Page<MaterialEvent>>(`${BASE}/records${buildQuery(filters)}`),
  listExceptions: (filters: Filters = {}) =>
    request<Page<ExceptionSummary>>(`${BASE}/quarantine${buildQuery(filters)}`),
  getException: (eventId: string) => request<ExceptionDetail>(`${BASE}/quarantine/${encodeURIComponent(eventId)}`),
  reviewException: (eventId: string, body: ReviewIn) =>
    postJson<ReviewOut>(`${BASE}/quarantine/${encodeURIComponent(eventId)}/review`, body, "PATCH"),

  createReconciliation: (body: ReconciliationIn) => postJson<ReconciliationDetail>(`${BASE}/reconciliations`, body),
  listReconciliations: (filters: Filters = {}) =>
    request<Page<Reconciliation>>(`${BASE}/reconciliations${buildQuery(filters)}`),
  getReconciliation: (id: string) => request<ReconciliationDetail>(`${BASE}/reconciliations/${encodeURIComponent(id)}`),
};

/** CSV export links carry the same filters as the table (paging is not part of an export). */
export function recordsCsvUrl(filters: Filters): string {
  return `${BASE}/reports/records.csv${buildQuery(filters)}`;
}

export function exceptionsCsvUrl(filters: Filters): string {
  return `${BASE}/reports/exceptions.csv${buildQuery(filters)}`;
}
