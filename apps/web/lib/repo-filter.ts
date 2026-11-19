import type { CiState, Repo } from "@/lib/api";

export interface RepoFilters {
  q: string;
  language: string; // "" = any
  ci: CiState | ""; // "" = any
  showArchived: boolean;
}

export const NO_FILTERS: RepoFilters = { q: "", language: "", ci: "", showArchived: false };

export function hasFilters(f: RepoFilters): boolean {
  return f.q.trim() !== "" || f.language !== "" || f.ci !== "" || f.showArchived;
}

/** Repositories matching the search text (name or description), language, CI state and archive switch. */
export function filterRepos(repos: Repo[], f: RepoFilters): Repo[] {
  const needle = f.q.trim().toLowerCase();
  return repos.filter((r) => {
    if (r.archived && !f.showArchived) return false;
    if (f.language && r.language !== f.language) return false;
    if (f.ci && r.ci !== f.ci) return false;
    if (!needle) return true;
    return r.full_name.toLowerCase().includes(needle) || (r.description ?? "").toLowerCase().includes(needle);
  });
}

/** The languages that appear, sorted, for the filter menu. */
export function languagesOf(repos: Repo[]): string[] {
  return [...new Set(repos.map((r) => r.language).filter((l): l is string => !!l))].sort((a, b) =>
    a.localeCompare(b),
  );
}

export function pageCount(total: number, size: number): number {
  return Math.max(1, Math.ceil(total / size));
}

/** One page of a list. `page` is 1-based and is clamped into range. */
export function paginate<T>(items: T[], page: number, size: number): { rows: T[]; page: number; pages: number } {
  const pages = pageCount(items.length, size);
  const current = Math.min(Math.max(1, page), pages);
  return { rows: items.slice((current - 1) * size, current * size), page: current, pages };
}

/** `?tab=` value, limited to the tabs that exist. */
export function parseTab<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.find((t) => t === value) ?? fallback;
}
