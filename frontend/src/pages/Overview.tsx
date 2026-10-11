import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { Loading } from "../components/Loading";
import { StatTile } from "../components/StatTile";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { api, type Health, type Page, type QualityMetrics, type Reconciliation, type Run } from "../services/api";
import { formatKg, formatRate, formatUtc } from "../utils/format";

interface OverviewData {
  metrics: QualityMetrics;
  runs: Page<Run>;
  reconciliations: Page<Reconciliation>;
}

function loadOverview(): Promise<OverviewData> {
  return Promise.all([
    api.qualityMetrics(),
    api.listRuns({ page_size: 5 }),
    api.listReconciliations({ page_size: 5 }),
  ]).then(([metrics, runs, reconciliations]) => ({ metrics, runs, reconciliations }));
}

export default function Overview() {
  const { data, error, loading, reload } = useApi(loadOverview, "overview");
  const health = useApi<Health>(api.health, "health");

  return (
    <>
      <div className="page-head">
        <h1>Overview</h1>
        <HealthIndicator health={health.data} loading={health.loading} />
      </div>
      {loading && !data ? <Loading /> : null}
      {error ? <ErrorBanner error={error} onRetry={reload} /> : null}
      {data && data.metrics.runs === 0 ? (
        <EmptyState>
          No runs yet. Import a CSV on the <Link to="/ingestion">Ingestion page</Link>.
        </EmptyState>
      ) : null}
      {data && data.metrics.runs > 0 ? <OverviewBody data={data} /> : null}
    </>
  );
}

function HealthIndicator({ health, loading }: { health: Health | null; loading: boolean }) {
  if (loading && !health) return <span className="health">Checking API…</span>;
  const ok = health?.status === "ok" && health.database === "ok";
  return (
    <span className={`health ${ok ? "health-ok" : "health-bad"}`} role="status">
      <span className="dot" aria-hidden="true" />
      {ok ? "API and database OK" : `API ${health?.status ?? "unknown"}, database ${health?.database ?? "unknown"}`}
    </span>
  );
}

function OverviewBody({ data }: { data: OverviewData }) {
  const { metrics: m, runs, reconciliations } = data;
  const issues = Object.entries(m.issues_by_rule).map(([rule, count]) => ({ rule, count }));
  const issueTotal = issues.reduce((sum, i) => sum + i.count, 0);

  return (
    <>
      <section aria-labelledby="quality-heading">
        <h2 id="quality-heading">Data quality (all runs)</h2>
        <div className="stat-grid">
          <StatTile label="Runs" value={m.runs} hint={m.failed_runs ? `${m.failed_runs} failed` : undefined} />
          <StatTile label="Received" value={m.received} />
          <StatTile label="Accepted" value={m.accepted} hint={formatRate(m.acceptance_rate)} />
          <StatTile label="Quarantined" value={m.quarantined} hint={formatRate(m.quarantine_rate)} />
          <StatTile label="Flagged" value={m.flagged} hint={formatRate(m.flag_rate)} />
          <StatTile label="Duplicates" value={m.duplicates} hint={formatRate(m.duplicate_rate)} />
          <StatTile
            label="Open exceptions"
            value={m.open_exceptions}
            hint={<Link to="/exceptions?review_status=OPEN">Review them</Link>}
          />
        </div>
      </section>

      <section aria-labelledby="issues-heading">
        <h2 id="issues-heading">Issues by rule</h2>
        {issues.length === 0 ? (
          <EmptyState>No validation issues recorded.</EmptyState>
        ) : (
          <figure className="chart">
            <div className="chart-box" aria-hidden="true">
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={issues} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="rule" />
                  <YAxis allowDecimals={false} width={32} />
                  <Tooltip />
                  <Bar dataKey="count" name="Issues" fill="var(--chart-bar)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <figcaption>
              {issueTotal} issue(s): {issues.map((i) => `${i.rule} ${i.count}`).join(", ")}.
            </figcaption>
          </figure>
        )}
      </section>

      <section aria-labelledby="runs-heading">
        <div className="section-head">
          <h2 id="runs-heading">Latest runs</h2>
          <Link to="/ingestion">All runs →</Link>
        </div>
        <DataTable
          rows={runs.items}
          rowKey={(r) => r.run_id}
          columns={[
            { header: "File", render: (r) => <Link to="/ingestion">{r.file_name ?? r.run_id}</Link> },
            { header: "Started", render: (r) => formatUtc(r.started_at) },
            { header: "Status", render: (r) => <StatusBadge status={r.status} /> },
            { header: "Received", render: (r) => r.received_count, className: "num" },
            { header: "Accepted", render: (r) => r.accepted_count, className: "num" },
            { header: "Quarantined", render: (r) => r.quarantined_count, className: "num" },
            { header: "Flagged", render: (r) => r.flagged_count, className: "num" },
            { header: "Duplicates", render: (r) => r.duplicate_count, className: "num" },
          ]}
        />
      </section>

      <section aria-labelledby="rec-heading">
        <div className="section-head">
          <h2 id="rec-heading">Latest reconciliations</h2>
          <Link to="/reconciliations">All reconciliations →</Link>
        </div>
        {reconciliations.items.length === 0 ? (
          <EmptyState>
            No reconciliations yet. Run one on the <Link to="/reconciliations">Reconciliation page</Link>.
          </EmptyState>
        ) : (
          <DataTable
            rows={reconciliations.items}
            rowKey={(r) => r.reconciliation_id}
            columns={[
              {
                header: "Facility / material",
                render: (r) => (
                  <Link to={`/reconciliations/${r.reconciliation_id}`}>
                    {r.facility_id} · {r.material_code}
                  </Link>
                ),
              },
              { header: "Period", render: (r) => `${formatUtc(r.period_start)} → ${formatUtc(r.period_end)}` },
              { header: "Status", render: (r) => <StatusBadge status={r.status} /> },
              { header: "Variance", render: (r) => formatKg(r.variance_kg), className: "num" },
              { header: "Tolerance", render: (r) => formatKg(r.tolerance_kg), className: "num" },
            ]}
          />
        )}
      </section>
    </>
  );
}
