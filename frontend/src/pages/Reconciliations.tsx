import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { FilterBar, type FilterField } from "../components/FilterBar";
import { Loading } from "../components/Loading";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api, type Meta, type Reconciliation, type ReconciliationIn } from "../services/api";
import { formatKg, formatUtc, localInputToUtcIso } from "../utils/format";
import { loadReviewer, saveReviewer } from "../utils/reviewer";

const PAGE_SIZE = 20;
const DECIMAL_INPUT = /^\d+(\.\d+)?$/;

/** The current UTC month as datetime-local values: first second to last second. */
function currentMonth(): { start: string; end: string } {
  const now = new Date();
  const y = now.getUTCFullYear();
  const m = now.getUTCMonth();
  const lastDay = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
  const mm = String(m + 1).padStart(2, "0");
  return { start: `${y}-${mm}-01T00:00:00`, end: `${y}-${mm}-${String(lastDay).padStart(2, "0")}T23:59:59` };
}

export default function Reconciliations() {
  const meta = useApi(api.meta, "meta");
  const { values, page, setFilters, setPage, key } = useUrlFilters(["facility_id", "material_code", "status"]);
  const list = useApi(() => api.listReconciliations({ ...values, page, page_size: PAGE_SIZE }), key);

  const choice = (name: string, label: string, options?: string[]): FilterField =>
    options ? { name, label, type: "select", options } : { name, label };
  const filterFields = [
    choice("facility_id", "Facility", meta.data?.facilities),
    choice("material_code", "Material", meta.data?.material_codes),
    choice("status", "Status", meta.data?.reconciliation_statuses),
  ];

  return (
    <>
      <h1>Reconciliation</h1>
      <p className="muted">
        Balances one facility and one material over a period, from the opening stock count to the closing stock
        count. Quantities are never corrected to make a balance work.
      </p>
      {meta.loading && !meta.data ? <Loading label="Loading form…" /> : null}
      {meta.error ? <ErrorBanner error={meta.error} onRetry={meta.reload} /> : null}
      {meta.data ? <ReconciliationForm meta={meta.data} /> : null}

      <section aria-labelledby="list-heading">
        <h2 id="list-heading">Snapshots</h2>
        <FilterBar fields={filterFields} values={values} onApply={setFilters} />
        {list.loading && !list.data ? <Loading /> : null}
        {list.error ? <ErrorBanner error={list.error} onRetry={list.reload} /> : null}
        {list.data && list.data.total === 0 ? (
          <EmptyState>
            {Object.values(values).some(Boolean)
              ? "No reconciliations match these filters."
              : "No reconciliations yet. Run one with the form above."}
          </EmptyState>
        ) : null}
        {list.data && list.data.total > 0 ? (
          <>
            <DataTable<Reconciliation>
              rows={list.data.items}
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
                { header: "Run at", render: (r) => formatUtc(r.created_at) },
              ]}
            />
            <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.total} onPage={setPage} />
          </>
        ) : null}
      </section>
    </>
  );
}

function ReconciliationForm({ meta }: { meta: Meta }) {
  const navigate = useNavigate();
  const month = currentMonth();
  const [facility, setFacility] = useState(meta.facilities[0] ?? "");
  const [material, setMaterial] = useState(meta.material_codes[0] ?? "");
  const [start, setStart] = useState(month.start);
  const [end, setEnd] = useState(month.end);
  const [absolute, setAbsolute] = useState("");
  const [percent, setPercent] = useState("");
  const [reviewer, setReviewer] = useState(loadReviewer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (meta.facilities.length === 0) {
    return (
      <EmptyState>
        No facilities yet. Import events on the <Link to="/ingestion">Ingestion page</Link> first (for example{" "}
        <code>data/fixtures/reconciliation_scenarios.csv</code>).
      </EmptyState>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const periodStart = localInputToUtcIso(start);
    const periodEnd = localInputToUtcIso(end);
    if (!periodStart || !periodEnd) {
      setError("Enter both the period start and the period end.");
      return;
    }
    for (const [label, value] of [
      ["Absolute tolerance", absolute],
      ["Percent tolerance", percent],
    ]) {
      if (value.trim() && !DECIMAL_INPUT.test(value.trim())) {
        setError(`${label} must be a number of 0 or more, e.g. 5 or 1.5.`);
        return;
      }
    }
    // Tolerances are sent as decimal strings; the API parses them as Decimal.
    const body: ReconciliationIn = { facility_id: facility, material_code: material, period_start: periodStart, period_end: periodEnd };
    if (absolute.trim()) body.absolute_tolerance_kg = absolute.trim();
    if (percent.trim()) body.percent_tolerance = percent.trim();
    if (reviewer.trim()) body.actor_label = reviewer.trim();

    setBusy(true);
    setError(null);
    try {
      const created = await api.createReconciliation(body);
      if (reviewer.trim()) saveReviewer(reviewer);
      navigate(`/reconciliations/${created.reconciliation_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const tol = meta.default_tolerance;
  return (
    <section className="panel" aria-labelledby="form-heading">
      <h2 id="form-heading">Run a reconciliation</h2>
      <form className="grid-form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="rec-facility">Facility</label>
          <select id="rec-facility" value={facility} onChange={(e) => setFacility(e.target.value)}>
            {meta.facilities.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rec-material">Material</label>
          <select id="rec-material" value={material} onChange={(e) => setMaterial(e.target.value)}>
            {meta.material_codes.map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="rec-start">Period start (UTC)</label>
          <input id="rec-start" type="datetime-local" step="1" value={start} onChange={(e) => setStart(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="rec-end">Period end (UTC)</label>
          <input id="rec-end" type="datetime-local" step="1" value={end} onChange={(e) => setEnd(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="rec-abs">Absolute tolerance (kg, optional)</label>
          <input id="rec-abs" inputMode="decimal" placeholder={`default ${tol.absolute_kg}`} value={absolute} onChange={(e) => setAbsolute(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rec-pct">Percent of throughput (optional)</label>
          <input id="rec-pct" inputMode="decimal" placeholder={`default ${tol.percent_of_throughput}`} value={percent} onChange={(e) => setPercent(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="rec-reviewer">Reviewer name (optional)</label>
          <input id="rec-reviewer" maxLength={100} value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        </div>
        <div className="form-actions">
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Running…" : "Run reconciliation"}
          </button>
        </div>
      </form>
      <p className="muted small">
        Default tolerance: max({tol.absolute_kg} kg, {tol.percent_of_throughput}% of throughput). Each run is saved as a
        new snapshot; earlier snapshots are never changed.
      </p>
      {error ? <ErrorBanner error={error} /> : null}
    </section>
  );
}
