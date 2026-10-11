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
import { api, exceptionsCsvUrl, type ExceptionSummary } from "../services/api";
import { formatUtc, MISSING } from "../utils/format";
import { apiFilters, EVENT_FILTER_NAMES, eventFilterFields } from "./eventFilters";

const PAGE_SIZE = 50;
const NAMES = [...EVENT_FILTER_NAMES, "rule_code", "review_status"];

function reviewStatuses(e: ExceptionSummary): string[] {
  return [...new Set(e.issues.map((i) => i.review_status))];
}

export default function Exceptions() {
  const navigate = useNavigate();
  const { values, page, setFilters, setPage, key } = useUrlFilters(NAMES);
  const meta = useApi(api.meta, "meta");
  const filters = apiFilters(values);
  const exceptions = useApi(() => api.listExceptions({ ...filters, page, page_size: PAGE_SIZE }), key);
  const filtered = Object.keys(filters).length > 0;

  const fields = [
    ...eventFilterFields(meta.data, ["FLAGGED", "QUARANTINED"]),
    { name: "rule_code", label: "Rule code", placeholder: "e.g. VAL-004" },
    meta.data
      ? { name: "review_status", label: "Review status", type: "select" as const, options: meta.data.review_statuses }
      : { name: "review_status", label: "Review status" },
  ];

  return (
    <>
      <div className="page-head">
        <h1>Exceptions</h1>
        <a className="button" href={exceptionsCsvUrl(filters)} download>
          Export CSV
        </a>
      </div>
      <p className="muted">Quarantined and flagged records. They are kept for review and never deleted.</p>
      <FilterBar fields={fields} values={values} onApply={setFilters} />
      {exceptions.loading && !exceptions.data ? <Loading /> : null}
      {exceptions.error ? <ErrorBanner error={exceptions.error} onRetry={exceptions.reload} /> : null}
      {exceptions.data && exceptions.data.total === 0 ? (
        <EmptyState>{filtered ? "No exceptions match these filters." : "No exceptions. Every imported record passed validation."}</EmptyState>
      ) : null}
      {exceptions.data && exceptions.data.total > 0 ? (
        <>
          <DataTable<ExceptionSummary>
            caption="Select a row to see the original values and record a review decision."
            rows={exceptions.data.items}
            rowKey={(e) => e.event_id}
            onRowClick={(e) => navigate(`/exceptions/${e.event_id}`)}
            columns={[
              {
                header: "Source ID",
                render: (e) => <Link to={`/exceptions/${e.event_id}`}>{e.source_record_id ?? "(no source id)"}</Link>,
              },
              { header: "Facility", render: (e) => e.facility_id ?? MISSING },
              { header: "Status", render: (e) => <StatusBadge status={e.validation_status} /> },
              { header: "Rule codes", render: (e) => [...new Set(e.issues.map((i) => i.rule_code))].join(", ") },
              {
                header: "Review status",
                render: (e) => (
                  <span className="badge-list">
                    {reviewStatuses(e).map((s) => (
                      <StatusBadge key={s} status={s} />
                    ))}
                  </span>
                ),
              },
              { header: "Created", render: (e) => formatUtc(e.created_at) },
            ]}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={exceptions.data.total} onPage={setPage} />
        </>
      ) : null}
    </>
  );
}
