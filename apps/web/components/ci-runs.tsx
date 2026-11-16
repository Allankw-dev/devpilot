"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { CiPanel } from "@/components/ci-panel";
import { ApiError, ciApi, type CiRunRow } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/ci-markdown";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

function AnalysisBadge({ row }: { row: CiRunRow }) {
  const a = row.analysis;
  if (!a) return <span className="text-xs text-muted-foreground">Not analyzed</span>;
  if (a.status === "queued" || a.status === "running")
    return <span className="text-xs text-muted-foreground">{a.status === "queued" ? "Queued…" : "Reading logs…"}</span>;
  if (a.status === "failed") return <span className="text-xs text-danger">Analysis failed</span>;
  return (
    <span className="text-xs">
      <span className="font-semibold">{a.category ? CATEGORY_LABEL[a.category] : "Unclear"}</span>
      <span className="text-muted-foreground">
        {" "}
        · {a.confidence ?? "?"} confidence
        {a.stale && " · run changed since"}
      </span>
    </span>
  );
}

export function CiRuns({ orgId, canAnalyze }: { orgId: string; canAnalyze: boolean }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"failed" | "all">("failed");
  const [openId, setOpenId] = useState<string | null>(null);
  const key = ["org", orgId, "ci-runs", state];

  const list = useQuery({
    queryKey: key,
    queryFn: async () => ciApi.list(await accessToken(), orgId, state),
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.analysis?.status === "queued" || r.analysis?.status === "running") ? 3000 : false,
  });
  const start = useMutation({
    mutationFn: async (v: { row: CiRunRow; force: boolean }) =>
      ciApi.start(await accessToken(), orgId, v.row.id, v.force),
    onSuccess: (_data, v) => setOpenId(v.row.id),
    onSettled: (_data, _err, v) => {
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-runs"] });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-analysis", v.row.id] });
    },
  });

  const rows = list.data ?? [];
  return (
    <section className="mt-10" aria-label="CI runs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-medium">CI runs</h2>
        <div className="flex gap-1 text-xs">
          {(["failed", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setState(s)}
              className={cn("rounded-md border border-border px-2 py-1", state === s ? "bg-muted font-medium" : "hover:bg-muted")}
            >
              {s === "failed" ? "Failed" : "All"}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">
        AI explanation of why a run failed, from its logs. Nothing is posted to GitHub and nothing is re-run.
      </p>

      {list.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Couldn’t load CI runs.
        </p>
      )}
      {list.isSuccess && rows.length === 0 && (
        <p className="mt-3 text-sm text-muted-foreground">
          {state === "failed" ? "No failed runs." : "No CI runs yet. Click Sync now on the GitHub section."}
        </p>
      )}
      {start.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the analysis."}
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {rows.map((row) => {
          const a = row.analysis;
          const active = a?.status === "queued" || a?.status === "running";
          const label = !a ? "Analyze" : a.status === "failed" ? "Retry" : a.stale ? "Analyze again" : "Re-run";
          return (
            <li key={row.id} className="rounded-md border border-border">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                <div className="min-w-0 flex-1">
                  {row.html_url ? (
                    <a href={row.html_url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                      {row.name ?? "Workflow"} #{row.run_number ?? "?"}
                    </a>
                  ) : (
                    <span className="font-medium">
                      {row.name ?? "Workflow"} #{row.run_number ?? "?"}
                    </span>
                  )}
                  <p className="text-xs text-muted-foreground">
                    {row.repository} · {row.branch ?? "unknown branch"} · {row.event ?? "unknown event"} ·{" "}
                    <span className={cn(row.conclusion === "failure" || row.conclusion === "timed_out" ? "text-danger" : "")}>
                      {row.conclusion ?? row.status ?? "unknown"}
                    </span>{" "}
                    · {ago(row.updated_at)}
                  </p>
                </div>
                {row.analyzable && <AnalysisBadge row={row} />}
                {a && !active && (
                  <button
                    type="button"
                    onClick={() => setOpenId(openId === row.id ? null : row.id)}
                    className="rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
                  >
                    {openId === row.id ? "Hide" : "View"}
                  </button>
                )}
                {canAnalyze && row.analyzable && (
                  <button
                    type="button"
                    onClick={() => start.mutate({ row, force: label === "Re-run" })}
                    disabled={active || (start.isPending && start.variables?.row.id === row.id)}
                    className="rounded-md bg-primary px-3 py-1 text-xs text-primary-foreground disabled:opacity-50"
                  >
                    {active ? "Analyzing…" : label}
                  </button>
                )}
              </div>
              {(openId === row.id || active) && (
                <div className="border-t border-border">
                  <CiPanel orgId={orgId} run={row} />
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
