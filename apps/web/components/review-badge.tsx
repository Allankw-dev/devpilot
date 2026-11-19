import type { PullRequestRow } from "@/lib/api";
import { cn } from "@/lib/utils";

export function ReviewBadge({ row }: { row: PullRequestRow }) {
  const r = row.review;
  if (!r) return <span className="text-xs text-muted-foreground">Not reviewed</span>;
  if (r.status === "queued" || r.status === "running")
    return <span className="text-xs text-muted-foreground">{r.status === "queued" ? "Queued…" : "Reviewing…"}</span>;
  if (r.status === "failed") return <span className="text-xs text-danger">Review failed</span>;
  return (
    <span className="text-xs">
      <span className={cn("font-semibold", r.risk === "high" && "text-danger", r.risk === "low" && "text-success")}>
        {r.risk ?? "?"} risk
      </span>
      <span className="text-muted-foreground">
        {" "}
        · {r.open_findings} {r.open_findings === 1 ? "finding" : "findings"}
        {r.serious_findings > 0 && <span className="text-danger"> ({r.serious_findings} serious)</span>}
        {r.stale && " · changed since"}
      </span>
    </span>
  );
}
