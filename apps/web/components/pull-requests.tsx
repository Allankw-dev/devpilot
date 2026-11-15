"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ReviewPanel } from "@/components/review-panel";
import { ApiError, reviewApi, type PullRequestRow } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

function ReviewBadge({ row }: { row: PullRequestRow }) {
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

export function PullRequests({ orgId, canReview }: { orgId: string; canReview: boolean }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"open" | "all">("open");
  const [openId, setOpenId] = useState<string | null>(null);
  const key = ["org", orgId, "pull-requests", state];

  const list = useQuery({
    queryKey: key,
    queryFn: async () => reviewApi.list(await accessToken(), orgId, state),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.review?.status === "queued" || r.review?.status === "running") ? 3000 : false,
  });
  const start = useMutation({
    mutationFn: async (v: { row: PullRequestRow; force: boolean }) =>
      reviewApi.start(await accessToken(), orgId, v.row.id, v.force),
    onSuccess: (_data, v) => setOpenId(v.row.id),
    onSettled: (_data, _err, v) => {
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "pull-requests"] });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "review", v.row.id] });
    },
  });

  const rows = list.data ?? [];
  return (
    <section className="mt-10" aria-label="Pull requests">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium">Pull requests</h2>
        <div className="flex gap-1 text-xs">
          {(["open", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setState(s)}
              className={cn("rounded-md border border-border px-2 py-1", state === s ? "bg-muted font-medium" : "hover:bg-muted")}
            >
              {s === "open" ? "Open" : "All"}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        AI review of the changes: bugs, security risks and missing error handling, with file and line. Nothing is posted to GitHub.
      </p>

      {list.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Couldn’t load pull requests.
        </p>
      )}
      {list.isSuccess && rows.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          {state === "open" ? "No open pull requests." : "No pull requests."}
        </p>
      )}
      {start.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the review."}
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {rows.map((row) => {
          const r = row.review;
          const active = r?.status === "queued" || r?.status === "running";
          const label = !r ? "Review" : r.status === "failed" ? "Retry" : r.stale ? "Review again" : "Re-run";
          return (
            <li key={row.id} className="rounded-md border border-border">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <a href={row.html_url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                    {row.title}
                  </a>
                  <p className="text-xs text-muted-foreground">
                    {row.repository} #{row.number} · {row.author ?? "unknown"} · {ago(row.updated_at)}
                    {row.draft && " · draft"}
                    {row.merged ? " · merged" : row.state === "closed" ? " · closed" : ""}
                  </p>
                </div>
                <ReviewBadge row={row} />
                {r && !active && (
                  <button
                    type="button"
                    onClick={() => setOpenId(openId === row.id ? null : row.id)}
                    className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
                  >
                    {openId === row.id ? "Hide" : "View"}
                  </button>
                )}
                {canReview && (
                  <button
                    type="button"
                    onClick={() => start.mutate({ row, force: label === "Re-run" })}
                    disabled={active || (start.isPending && start.variables?.row.id === row.id)}
                    className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50"
                  >
                    {active ? "Reviewing…" : label}
                  </button>
                )}
              </div>
              {(openId === row.id || active) && (
                <div className="border-t border-border">
                  <ReviewPanel orgId={orgId} row={row} canEdit={canReview} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
