import { Link, useParams } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { api, type LinkedEvent, type ReconciliationDetail as Detail } from "../services/api";
import { formatKg, formatUtc, humanize, MISSING } from "../utils/format";

/** Plain-English meaning of each status, shown next to the badge. */
export const STATUS_MEANING: Record<string, string> = {
  WITHIN_TOLERANCE: "The closing count matches the expected stock within tolerance.",
  NEEDS_REVIEW: "Needs a person to look; not proof of an error. The variance is larger than the tolerance.",
  NEEDS_DATA:
    "Evidence incomplete: a stock count is missing or conflicting, or an exception is still unresolved. " +
    "The balance cannot be trusted either way.",
};

const ROLE_LABELS: Record<string, string> = {
  opening_count: "Opening count",
  closing_count: "Closing count",
  intermediate_count: "Intermediate counts (not flows)",
  receipt: "Receipts",
  production: "Production",
  adjustment: "Adjustments",
  shipment: "Shipments",
  loss: "Losses",
  consumption: "Consumption",
  excluded: "Excluded events",
};

export default function ReconciliationDetail() {
  const { id = "" } = useParams();
  const detail = useApi(() => api.getReconciliation(id), id);
  return (
    <>
      <p className="breadcrumb">
        <Link to="/reconciliations">← Reconciliation</Link>
      </p>
      {detail.loading && !detail.data ? <Loading /> : null}
      {detail.error ? <ErrorBanner error={detail.error} onRetry={detail.reload} /> : null}
      {detail.data ? <DetailBody r={detail.data} /> : null}
    </>
  );
}

function DetailBody({ r }: { r: Detail }) {
  const inputs: [string, string | null][] = [
    ["Opening stock", r.opening_stock_kg],
    ["+ Receipts", r.receipts_kg],
    ["+ Production", r.production_kg],
    ["+ Adjustments (signed)", r.adjustments_kg],
    ["− Shipments", r.shipments_kg],
    ["− Losses", r.losses_kg],
    ["− Consumption", r.consumption_kg],
    ["= Expected closing", r.expected_closing_kg],
    ["Closing stock (counted)", r.closing_stock_kg],
    ["Variance (closing − expected)", r.variance_kg],
  ];
  const roles = Object.keys(ROLE_LABELS).filter((role) => (r.events[role] ?? []).length > 0);

  return (
    <>
      <h1>
        {r.facility_id} · {r.material_code}
      </h1>
      <p className="muted">
        {formatUtc(r.period_start, true)} → {formatUtc(r.period_end, true)} · run {formatUtc(r.created_at)}
      </p>

      <div className={`status-callout status-${r.status.toLowerCase()}`}>
        <StatusBadge status={r.status} />
        <p>{STATUS_MEANING[r.status] ?? humanize(r.status)}</p>
      </div>

      <section aria-labelledby="reasons-heading">
        <h2 id="reasons-heading">Reasons</h2>
        <ul className="reasons">
          {r.reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      </section>

      <div className="panels">
        <section className="panel" aria-labelledby="inputs-heading">
          <h2 id="inputs-heading">Balance (kg)</h2>
          <div className="table-wrap">
            <table className="kv">
              <tbody>
                {inputs.map(([label, value]) => (
                  <tr key={label}>
                    <th scope="row">{label}</th>
                    <td className="num">{value === null ? "unknown" : formatKg(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel" aria-labelledby="tolerance-heading">
          <h2 id="tolerance-heading">Tolerance</h2>
          <p>{r.tolerance_explanation}</p>
          <p className="muted small">
            Throughput: {formatKg(r.throughput_kg)} · settings: {formatKg(r.tolerance_absolute_kg)} absolute,{" "}
            {r.tolerance_percent}% of throughput
          </p>
        </section>
      </div>

      <section aria-labelledby="formula-heading">
        <h2 id="formula-heading">Formula</h2>
        <pre className="formula" aria-label="Formula with this reconciliation's numbers">
          {r.formula}
        </pre>
      </section>

      <section aria-labelledby="events-heading">
        <h2 id="events-heading">Linked events</h2>
        <p className="muted small">Every event this snapshot used or left out, so each number can be traced.</p>
        {roles.length === 0 ? <p>No events were found for this facility, material and period.</p> : null}
        {roles.map((role) => (
          <div key={role} className="role-group">
            <h3>
              {ROLE_LABELS[role]} ({r.events[role].length})
            </h3>
            <DataTable<LinkedEvent>
              rows={r.events[role]}
              rowKey={(e) => e.event_id}
              columns={[
                {
                  header: "Source ID",
                  render: (e) =>
                    e.validation_status === "ACCEPTED" ? (
                      e.source_record_id ?? e.event_id
                    ) : (
                      <Link to={`/exceptions/${e.event_id}`}>{e.source_record_id ?? e.event_id}</Link>
                    ),
                },
                { header: "Type", render: (e) => e.event_type ?? MISSING },
                { header: "Quantity (kg)", render: (e) => formatKg(e.quantity_kg), className: "num" },
                { header: "Timestamp", render: (e) => formatUtc(e.event_timestamp) },
                { header: "Status", render: (e) => <StatusBadge status={e.validation_status} /> },
                ...(role === "excluded"
                  ? [{ header: "Why excluded", render: (e: LinkedEvent) => e.excluded_reason ?? MISSING }]
                  : []),
              ]}
            />
          </div>
        ))}
      </section>
    </>
  );
}
