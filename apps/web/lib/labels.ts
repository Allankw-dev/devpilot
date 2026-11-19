import type { CiState } from "@/lib/api";

export const CI_LABEL: Record<CiState, { text: string; cls: string }> = {
  passing: { text: "Passing", cls: "text-success" },
  failing: { text: "Failing", cls: "text-danger" },
  running: { text: "Running", cls: "text-primary" },
  other: { text: "Other", cls: "text-muted-foreground" },
  none: { text: "No runs", cls: "text-muted-foreground" },
};

export const INDEX_LABEL: Record<string, string> = {
  none: "Not indexed",
  queued: "Queued",
  running: "Indexing",
  ready: "Indexed",
  failed: "Failed",
};

/** People other than viewers can start reviews, analyses and indexing. */
export function canWrite(role: string | undefined): boolean {
  return role === "owner" || role === "admin" || role === "member";
}
