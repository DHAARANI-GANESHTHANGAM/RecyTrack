interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPage }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(page * pageSize, total);
  return (
    <nav className="pagination" aria-label="Pagination">
      <button type="button" onClick={() => onPage(page - 1)} disabled={page <= 1}>
        ← Previous
      </button>
      <span>
        {first}–{last} of {total} · page {page} of {pages}
      </span>
      <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages}>
        Next →
      </button>
    </nav>
  );
}
