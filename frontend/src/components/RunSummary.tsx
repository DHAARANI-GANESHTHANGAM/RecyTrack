import { Link } from "react-router-dom";

import type { Run } from "../services/api";
import { StatusBadge } from "./StatusBadge";

/** Counts of one run, its error if it failed, and links to its records and exceptions. */
export function RunSummary({ run, title }: { run: Run; title: string }) {
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
