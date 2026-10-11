import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Load data when `key` changes. Responses that arrive after a newer request
 * started are ignored, so fast filter changes never show stale results.
 */
export function useApi<T>(loader: () => Promise<T>, key: string): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const latest = useRef(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    const id = ++latest.current;
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((result) => {
        if (id === latest.current) setData(result);
      })
      .catch((err: unknown) => {
        if (id === latest.current) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (id === latest.current) setLoading(false);
      });
  }, [key, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { data, error, loading, reload };
}
