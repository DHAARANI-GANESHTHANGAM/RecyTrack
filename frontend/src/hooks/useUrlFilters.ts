import { useSearchParams } from "react-router-dom";

/**
 * Filters and the page number live in the URL query string, so a filtered view
 * can be shared, bookmarked, and survives a refresh.
 */
export function useUrlFilters(names: string[]) {
  const [params, setParams] = useSearchParams();
  const values = Object.fromEntries(names.map((n) => [n, params.get(n) ?? ""]));
  const page = Math.max(1, Number(params.get("page")) || 1);

  /** Replace all filters (empty ones are removed) and go back to page 1. */
  const setFilters = (next: Record<string, string>) => {
    const search = new URLSearchParams();
    for (const n of names) {
      const v = (next[n] ?? "").trim();
      if (v) search.set(n, v);
    }
    setParams(search);
  };

  const setPage = (p: number) => {
    const search = new URLSearchParams(params);
    if (p <= 1) search.delete("page");
    else search.set("page", String(p));
    setParams(search);
  };

  return { values, page, setFilters, setPage, key: params.toString() };
}
