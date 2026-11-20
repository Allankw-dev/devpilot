/** "45 s", "2 min 5 s", "1 h 3 min": how long something took, for people. */
export function formatSeconds(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return "n/a";
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 === 0 ? `${m} min` : `${m} min ${s % 60} s`;
  const h = Math.floor(m / 60);
  return m % 60 === 0 ? `${h} h` : `${h} h ${m % 60} min`;
}

/** 0.6667 -> "67%". Null means there was nothing to measure. */
export function formatPercent(rate: number | null): string {
  return rate === null ? "n/a" : `${Math.round(rate * 100)}%`;
}
