import { useState, type FormEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { api, REVIEW_STATUSES, type Audit, type ExceptionDetail as Detail, type ReviewStatus } from "../services/api";
import { formatDecimal, formatKg, formatUtc, humanize, MISSING } from "../utils/format";
import { loadReviewer, saveReviewer } from "../utils/reviewer";

export default function ExceptionDetail() {
  const { eventId = "" } = useParams();
  const detail = useApi(() => api.getException(eventId), eventId);

  return (
    <>
      <p className="breadcrumb">
        <Link to="/exceptions">← Exceptions</Link>
      </p>
      <h1>Exception {detail.data?.event.source_record_id ?? ""}</h1>
      {detail.loading && !detail.data ? <Loading /> : null}
      {detail.error ? <ErrorBanner error={detail.error} onRetry={detail.reload} /> : null}
      {detail.data ? <DetailBody detail={detail.data} onReviewed={detail.reload} /> : null}
    </>
  );
}

function KeyValueTable({ rows, caption }: { rows: [string, ReactNode][]; caption?: string }) {
  return (
    <div className="table-wrap">
      <table className="kv">
        {caption ? <caption>{caption}</caption> : null}
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th scope="row">{k}</th>
              <td>{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Shows a raw cell exactly, including surrounding spaces, and makes empty cells visible. */
function RawValue({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined || value === "") return <span className="muted">(empty)</span>;
  return <code className="raw">{value}</code>;
}

function DetailBody({ detail, onReviewed }: { detail: Detail; onReviewed: () => void }) {
  const { event: e, raw, run, issues, review_history } = detail;
  return (
    <>
      <p>
        <StatusBadge status={e.validation_status} /> Imported in run{" "}
        <Link to={`/records?run_id=${encodeURIComponent(run.run_id)}`}>{run.file_name ?? run.run_id}</Link> on{" "}
        {formatUtc(run.started_at)}.
      </p>

      <div className="panels">
        <section className="panel" aria-labelledby="raw-heading">
          <h2 id="raw-heading">Original row</h2>
          <KeyValueTable rows={Object.entries(raw.raw_payload).map(([k, v]) => [k, <RawValue value={v} />])} />
          <p className="muted small">
            Row {raw.row_number} of the file · payload hash <code className="hash">{raw.payload_hash}</code>
          </p>
        </section>

        <section className="panel" aria-labelledby="norm-heading">
          <h2 id="norm-heading">Normalized values</h2>
          <KeyValueTable
            rows={[
              ["source_record_id", e.source_record_id ?? MISSING],
              ["facility_id", e.facility_id ?? MISSING],
              ["material_code", e.material_code ?? MISSING],
              ["event_type", e.event_type ?? MISSING],
              ["quantity", e.quantity === null ? MISSING : `${formatDecimal(e.quantity)} ${e.unit ?? ""}`.trim()],
              ["quantity_kg", formatKg(e.quantity_kg)],
              ["event_timestamp", formatUtc(e.event_timestamp, true)],
              ["batch_id", e.batch_id ?? MISSING],
            ]}
          />
          <p className="muted small">"—" means the value could not be normalized; see the issues.</p>
        </section>
      </div>

      <section aria-labelledby="issues-heading">
        <h2 id="issues-heading">Issues</h2>
        <DataTable
          rows={issues}
          rowKey={(i) => String(i.issue_id)}
          columns={[
            { header: "Rule", render: (i) => <strong>{i.rule_code}</strong> },
            { header: "Field", render: (i) => i.field_name ?? "(row)" },
            { header: "Message", render: (i) => i.message },
            { header: "Severity", render: (i) => i.severity },
            { header: "Raw value", render: (i) => <RawValue value={i.raw_value} /> },
            { header: "Review status", render: (i) => <StatusBadge status={i.review_status} /> },
          ]}
        />
      </section>

      <div className="panels">
        <ReviewForm eventId={e.event_id} current={issues[0]?.review_status} onReviewed={onReviewed} />
        <section className="panel" aria-labelledby="history-heading">
          <h2 id="history-heading">Review history</h2>
          <ReviewHistory history={review_history} />
        </section>
      </div>
    </>
  );
}

function ReviewForm({ eventId, current, onReviewed }: { eventId: string; current?: string; onReviewed: () => void }) {
  const [status, setStatus] = useState<ReviewStatus>(
    current && current !== "OPEN" ? (current as ReviewStatus) : "APPROVED",
  );
  const [reviewer, setReviewer] = useState(loadReviewer);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const actor = reviewer.trim();
    if (!actor) {
      setError("Enter your reviewer name.");
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(null);
    try {
      await api.reviewException(eventId, { review_status: status, actor_label: actor, note: note.trim() || null });
      saveReviewer(actor);
      setNote("");
      setSaved(`Saved: ${humanize(status)}.`);
      onReviewed();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="review-heading">
      <h2 id="review-heading">Record a review decision</h2>
      <p className="muted small">
        A review decision is added to the audit trail. It never changes the original row or the normalized values.
      </p>
      <form className="stack" onSubmit={submit} noValidate>
        <div className="field">
          <label htmlFor="review-status">Decision</label>
          <select id="review-status" value={status} onChange={(e) => setStatus(e.target.value as ReviewStatus)}>
            {REVIEW_STATUSES.map((s) => (
              <option key={s} value={s}>
                {humanize(s)}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="reviewer">Reviewer name (required)</label>
          <input
            id="reviewer"
            value={reviewer}
            required
            maxLength={100}
            aria-invalid={error !== null && !reviewer.trim()}
            onChange={(e) => setReviewer(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="note">Note</label>
          <textarea id="note" value={note} maxLength={2000} rows={3} onChange={(e) => setNote(e.target.value)} />
        </div>
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Saving…" : "Save decision"}
        </button>
        {error ? <ErrorBanner error={error} /> : null}
        {saved ? (
          <p className="success" role="status">
            {saved}
          </p>
        ) : null}
      </form>
    </section>
  );
}

function ReviewHistory({ history }: { history: Audit[] }) {
  if (history.length === 0) return <EmptyState>No decisions yet.</EmptyState>;
  return (
    <ol className="history">
      {history.map((a) => (
        <li key={a.audit_id}>
          <div>
            <strong>{a.actor_label}</strong>: {(a.details.previous_review_status ?? []).map(humanize).join(", ") || "?"} →{" "}
            {humanize(a.details.review_status ?? "?")}
          </div>
          {a.details.note ? <div className="note">“{a.details.note}”</div> : null}
          <div className="muted small">{formatUtc(a.created_at, true)}</div>
        </li>
      ))}
    </ol>
  );
}
