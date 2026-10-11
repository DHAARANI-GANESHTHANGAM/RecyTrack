import { Link } from "react-router-dom";

import { DataTable } from "../components/DataTable";
import { EmptyState } from "../components/EmptyState";
import { ErrorBanner } from "../components/ErrorBanner";
import { FilterBar } from "../components/FilterBar";
import { Loading } from "../components/Loading";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";
import { useApi } from "../hooks/useApi";
import { useUrlFilters } from "../hooks/useUrlFilters";
import { api, recordsCsvUrl, type MaterialEvent } from "../services/api";
import { formatKg, formatQuantity, formatUtc, MISSING } from "../utils/format";
import { apiFilters, EVENT_FILTER_NAMES, eventFilterFields } from "./eventFilters";

const PAGE_SIZE = 50;

export default function Records() {
  const { values, page, setFilters, setPage, key } = useUrlFilters(EVENT_FILTER_NAMES);
  const meta = useApi(api.meta, "meta");
  const filters = apiFilters(values);
  const records = useApi(() => api.listRecords({ ...filters, page, page_size: PAGE_SIZE }), key);
  const filtered = Object.keys(filters).length > 0;

  return (
    <>
      <div className="page-head">
        <h1>Records</h1>
        <a className="button" href={recordsCsvUrl(filters)} download>
          Export CSV
        </a>
      </div>
      <FilterBar fields={eventFilterFields(meta.data)} values={values} onApply={setFilters} />
      {records.loading && !records.data ? <Loading /> : null}
      {records.error ? <ErrorBanner error={records.error} onRetry={records.reload} /> : null}
      {records.data && records.data.total === 0 ? (
        <EmptyState>
          {filtered ? (
            "No records match these filters."
          ) : (
            <>
              No records yet. Import a CSV on the <Link to="/ingestion">Ingestion page</Link>.
            </>
          )}
        </EmptyState>
      ) : null}
      {records.data && records.data.total > 0 ? (
        <>
          <DataTable<MaterialEvent>
            rows={records.data.items}
            rowKey={(e) => e.event_id}
            columns={[
              { header: "Source ID", render: (e) => e.source_record_id ?? MISSING },
              { header: "Facility", render: (e) => e.facility_id ?? MISSING },
              { header: "Material", render: (e) => e.material_code ?? e.material_name_raw ?? MISSING },
              { header: "Type", render: (e) => e.event_type ?? MISSING },
              { header: "Quantity", render: (e) => formatQuantity(e.quantity, e.unit ?? e.unit_raw), className: "num" },
              { header: "Quantity (kg)", render: (e) => formatKg(e.quantity_kg), className: "num" },
              { header: "Timestamp", render: (e) => formatUtc(e.event_timestamp) },
              { header: "Batch", render: (e) => e.batch_id ?? MISSING },
              {
                header: "Status",
                render: (e) =>
                  e.validation_status === "ACCEPTED" ? (
                    <StatusBadge status={e.validation_status} />
                  ) : (
                    <Link to={`/exceptions/${e.event_id}`} aria-label={`${e.validation_status}: open exception detail`}>
                      <StatusBadge status={e.validation_status} />
                    </Link>
                  ),
              },
            ]}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={records.data.total} onPage={setPage} />
        </>
      ) : null}
    </>
  );
}
