import { useState } from "react";

import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { RunSummary } from "../components/RunSummary";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { ApiError, api, type Run } from "../services/api";
import { formatUtc, MISSING } from "../utils/format";

/** Freshness of each source (VAL-010) and a manual import from the simulated API source. */
export default function SourceHealth() {
  const health = useApi(api.sourcesHealth, "sources-health");

  return (
    <>
      <h1>Source health</h1>
      <p className="muted">
        A source is <strong>STALE</strong> when its last successful import is older than its freshness window (VAL-010).
        A failed run inside the window keeps the source fresh, but the failure is shown.
      </p>

      <section aria-labelledby="sources-heading">
        <h2 id="sources-heading">Sources</h2>
        {health.loading && !health.data ? <Loading /> : null}
        {health.error ? <ErrorBanner error={health.error} onRetry={health.reload} /> : null}
        {health.data ? (
          <DataTable
            rows={health.data}
            rowKey={(s) => s.source_name}
            columns={[
              { header: "Source", render: (s) => s.source_name },
              { header: "Freshness", render: (s) => <StatusBadge status={s.status} /> },
              { header: "Details", render: (s) => s.message },
              {
                header: "Window",
                render: (s) => (s.freshness_window_hours === null ? MISSING : `${s.freshness_window_hours} h`),
                className: "num",
              },
              { header: "Last success", render: (s) => formatUtc(s.last_success_at) },
              {
                header: "Last run",
                render: (s) =>
                  s.last_run_status ? (
                    <>
                      <StatusBadge status={s.last_run_status} /> {formatUtc(s.last_run_at)}
                    </>
                  ) : (
                    MISSING
                  ),
              },
            ]}
          />
        ) : null}
      </section>

      <SimulatedImport onImported={health.reload} />
    </>
  );
}

function SimulatedImport({ onImported }: { onImported: () => void }) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [failedRun, setFailedRun] = useState<Run | null>(null);

  const runImport = async () => {
    setBusy(true);
    setResult(null);
    setError(null);
    setFailedRun(null);
    try {
      setResult(await api.importSimulatedApi());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      // An unavailable source (502) is still recorded as a FAILED run; show it.
      const run = err instanceof ApiError ? (err.body as { detail?: { run?: Run } } | null)?.detail?.run : undefined;
      if (run) setFailedRun(run);
    } finally {
      setBusy(false);
      onImported();
    }
  };

  return (
    <section aria-labelledby="simulated-heading" className="panel">
      <h2 id="simulated-heading">Simulated API source</h2>
      <p className="muted">
        This source is <strong>simulated</strong>: a separate test service that serves synthetic events, about 10% of
        them deliberately faulty. It is not connected to any real system. Only events newer than the latest one already
        imported are fetched; re-importing is safe because duplicates are detected.
      </p>
      <button type="button" className="primary" onClick={runImport} disabled={busy}>
        {busy ? "Importing…" : "Import from simulated API"}
      </button>
      {error ? <ErrorBanner error={error} /> : null}
      {result ? <RunSummary run={result} title="Import finished" /> : null}
      {failedRun ? <RunSummary run={failedRun} title="Failed run" /> : null}
    </section>
  );
}
