import { useEffect, useState } from "react";

/** The current time, refreshed every `intervalMs`, so components can compare against "now" without
 * calling `Date.now()` while rendering. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
