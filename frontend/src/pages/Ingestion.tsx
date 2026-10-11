import { useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { FilterBar } from "../components/FilterBar";
import { Loading } from "../components/Loading";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { ApiError, api, RUN_STATUSES, type Run } from "../services/api";
import { formatUtc } from "../utils/format";

const PAGE_SIZE = 20;

export default function Ingestion() {
  const navigate = useNavigate();
  const { values, page, setFilters, setPage, key } = useUrlFilters(["status"]);
  const runs = useApi(() => api.listRuns({ ...values, page, page_size: PAGE_SIZE }), key);

  return (
    <>
      <h1>Ingestion</h1>
      <UploadForm onImported={runs.reload} />

      <section aria-labelledby="runs-heading">
        <h2 id="runs-heading">Runs</h2>
        <FilterBar
          fields={[{ name: "status", label: "Status", type: "select", options: RUN_STATUSES }]}
          values={values}
          onApply={setFilters}
        />
        {runs.loading && !runs.data ? <Loading /> : null}
        {runs.error ? <ErrorBanner error={runs.error} onRetry={runs.reload} /> : null}
        {runs.data && runs.data.total === 0 ? (
          <EmptyState>{values.status ? "No runs match this filter." : "No runs yet. Import a CSV above."}</EmptyState>
        ) : null}
        {runs.data && runs.data.total > 0 ? (
          <>
            <DataTable
              caption="Select a run to see its records."
              rows={runs.data.items}
              rowKey={(r) => r.run_id}
              onRowClick={(r) => navigate(`/records?run_id=${encodeURIComponent(r.run_id)}`)}
              columns={[
                {
                  header: "File",
                  render: (r) => (
                    <Link to={`/records?run_id=${encodeURIComponent(r.run_id)}`}>{r.file_name ?? r.run_id}</Link>
                  ),
                },
                { header: "Started", render: (r) => formatUtc(r.started_at) },
                { header: "Status", render: (r) => <StatusBadge status={r.status} /> },
                { header: "Received", render: (r) => r.received_count, className: "num" },
                { header: "Accepted", render: (r) => r.accepted_count, className: "num" },
                { header: "Quarantined", render: (r) => r.quarantined_count, className: "num" },
                { header: "Flagged", render: (r) => r.flagged_count, className: "num" },
                { header: "Duplicates", render: (r) => r.duplicate_count, className: "num" },
              ]}
            />
            <Pagination page={page} pageSize={PAGE_SIZE} total={runs.data.total} onPage={setPage} />
          </>
        ) : null}
      </section>
    </>
  );
}

function UploadForm({ onImported }: { onImported: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedRun, setFailedRun] = useState<Run | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    setError(null);
    setFailedRun(null);
    try {
      setResult(await api.importCsv(file));
      setFile(null);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      // A malformed file (422) is still recorded as a FAILED run; show it.
      const run = err instanceof ApiError ? (err.body as { detail?: { run?: Run } } | null)?.detail?.run : undefined;
      if (run) setFailedRun(run);
    } finally {
      setBusy(false);
      onImported();
    }
  };

  return (
    <section aria-labelledby="upload-heading" className="panel">
      <h2 id="upload-heading">Import a CSV file</h2>
      <p className="muted">
        The file must follow the CSV contract in <code>docs/data_dictionary.md</code>. Invalid rows are kept for
        review, never deleted.
      </p>
      <form className="upload-form" onSubmit={submit}>
        <label htmlFor="csv-file">CSV file</label>
        <input
          id="csv-file"
          ref={input}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" className="primary" disabled={!file || busy}>
          {busy ? "Importing…" : "Import"}
        </button>
      </form>
      {error ? <ErrorBanner error={error} /> : null}
      {result ? <RunSummary run={result} title="Import finished" /> : null}
      {failedRun ? <RunSummary run={failedRun} title="Failed run" /> : null}
    </section>
  );
}

function RunSummary({ run, title }: { run: Run; title: string }) {
  return (
    <div className="run-summary" role="status">
      <h3>
        {title}: {run.file_name} <StatusBadge status={run.status} />
      </h3>
      <dl className="counts">
        <div>
          <dt>Received</dt>
          <dd>{run.received_count}</dd>
        </div>
        <div>
          <dt>Accepted</dt>
          <dd>{run.accepted_count}</dd>
        </div>
        <div>
          <dt>Quarantined</dt>
          <dd>{run.quarantined_count}</dd>
        </div>
        <div>
          <dt>Flagged</dt>
          <dd>{run.flagged_count}</dd>
        </div>
        <div>
          <dt>Duplicates</dt>
          <dd>{run.duplicate_count}</dd>
        </div>
      </dl>
      {run.error_summary ? <p className="error-text">{run.error_summary}</p> : null}
      {run.status === "SUCCEEDED" ? (
        <p>
          <Link to={`/records?run_id=${encodeURIComponent(run.run_id)}`}>See this run's records</Link>
          {run.quarantined_count + run.flagged_count > 0 ? (
            <>
              {" · "}
              <Link to={`/exceptions?run_id=${encodeURIComponent(run.run_id)}`}>See its exceptions</Link>
            </>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
