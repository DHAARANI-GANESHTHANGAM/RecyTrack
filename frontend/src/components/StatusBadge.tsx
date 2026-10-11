import { humanize } from "../utils/format";

/** Colour per status. The status text is always shown too, so colour is never the only signal. */
const TONES: Record<string, string> = {
  ACCEPTED: "green",
  WITHIN_TOLERANCE: "green",
  SUCCEEDED: "green",
  APPROVED: "green",
  FLAGGED: "amber",
  NEEDS_REVIEW: "amber",
  NEEDS_INFO: "amber",
  QUARANTINED: "red",
  FAILED: "red",
  REJECTED: "red",
  NEEDS_DATA: "grey",
  RUNNING: "grey",
  DUPLICATE: "bluegrey",
  OPEN: "outline",
};

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const tone = TONES[status] ?? "grey";
  return <span className={`badge badge-${tone}`}>{humanize(status)}</span>;
}
