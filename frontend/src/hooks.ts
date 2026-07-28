import { useCallback, useEffect, useState } from "react";

/** Load once on mount, with loading and error states.
 *
 * Deliberately not a cache or a poller: every fetch here is a plain read, and
 * anything that costs money or a rate-limited request is a button instead.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const run = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    load()
      .then((value) => !cancelled && setData(value))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);
  return { data, error, loading, reload: run };
}

/** An action the user triggers — never run on mount. */
export function useAction<T, A extends unknown[]>(
  action: (...args: A) => Promise<T>,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const trigger = useCallback(
    async (...args: A) => {
      setRunning(true);
      setError(null);
      try {
        const value = await action(...args);
        setData(value);
        return value;
      } catch (e) {
        setError((e as Error).message);
        return null;
      } finally {
        setRunning(false);
      }
    },
    [action],
  );

  return { data, error, running, trigger, setData };
}
