"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, ciApi, orgApi, type CiRunRow } from "@/lib/api";
import { CATEGORY_LABEL } from "@/lib/ci-markdown";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const PAGE = 30;
const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";

/** Starting an analysis costs AI tokens, so it is a deliberate click, never automatic. */
export function analysisActionLabel(row: CiRunRow): "Analyze" | "Retry" | "Analyze again" | "Re-run" {
  const a = row.analysis;
  if (!a) return "Analyze";
  if (a.status === "failed") return "Retry";
  return a.stale ? "Analyze again" : "Re-run";
}

export function conclusionTone(conclusion: string | null): "danger" | "success" | "neutral" {
  if (conclusion === "failure" || conclusion === "timed_out") return "danger";
  if (conclusion === "success") return "success";
  return "neutral";
}

function AnalysisSummary({ row }: { row: CiRunRow }) {
  const a = row.analysis;
  if (!row.analyzable) return null;
  if (!a) return <span className="text-xs text-muted-foreground">Not analyzed</span>;
  if (a.status === "queued" || a.status === "running")
    return <span className="text-xs text-muted-foreground">{a.status === "queued" ? "Queued…" : "Reading logs…"}</span>;
  if (a.status === "failed") return <span className="text-xs text-danger">Analysis failed</span>;
  return (
    <span className="text-xs">
      <span className="font-semibold">{a.category ? CATEGORY_LABEL[a.category] : "Unclear"}</span>
      <span className="text-muted-foreground">
        {" "}
        · {a.confidence ?? "?"} confidence{a.stale && " · run changed since"}
      </span>
    </span>
  );
}

export function CiList({ orgId, canAnalyze }: { orgId: string; canAnalyze: boolean }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"failed" | "all">("failed");
  const [repoId, setRepoId] = useState("");
  const [text, setText] = useState("");
  const q = useDebounced(text);

  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
  });
  const list = useInfiniteQuery({
    queryKey: ["org", orgId, "ci-runs", state, repoId, q],
    queryFn: async ({ pageParam }) =>
      ciApi.list(await accessToken(), orgId, state, { repoId: repoId || undefined, q, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.flat().some((r) => r.analysis?.status === "queued" || r.analysis?.status === "running")
        ? 3000
        : false,
  });
  const start = useMutation({
    mutationFn: async (v: { row: CiRunRow; force: boolean }) =>
      ciApi.start(await accessToken(), orgId, v.row.id, v.force),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-runs"] }),
  });
  const rows = list.data?.pages.flat() ?? [];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Run state">
          {(["failed", "all"] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={state === s}
              onClick={() => setState(s)}
              className={cn(
                "rounded-md border border-border px-2.5 py-1.5 text-xs capitalize",
                state === s ? "bg-muted font-medium" : "hover:bg-muted",
              )}
            >
              {s}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="ci-repo">
          Repository
        </label>
        <select id="ci-repo" value={repoId} onChange={(e) => setRepoId(e.target.value)} className={field}>
          <option value="">All repositories</option>
          {(repos.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.full_name}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="ci-search">
          Search runs
        </label>
        <input
          id="ci-search"
          type="search"
          placeholder="Search workflow or branch"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={cn(field, "w-64 max-w-full")}
        />
      </div>

      {list.isPending && <p role="status" className="text-sm text-muted-foreground">Loading runs…</p>}
      {list.isError && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load CI runs.{" "}
          <Button size="sm" onClick={() => list.refetch()}>
            Try again
          </Button>
        </p>
      )}
      {start.isError && (
        <p role="alert" className="mb-2 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the analysis."}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {q
            ? "No runs match your search."
            : state === "failed"
              ? "No failed runs."
              : "No CI runs yet. Sync GitHub from the Integrations page."}
        </p>
      )}

      {rows.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {rows.map((row) => {
              const a = row.analysis;
              const active = a?.status === "queued" || a?.status === "running";
              const label = analysisActionLabel(row);
              return (
                <li key={row.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
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
                    <Badge tone={conclusionTone(row.conclusion)} className="ml-2">
                      {row.conclusion ?? row.status ?? "unknown"}
                    </Badge>
                    <p className="text-xs text-muted-foreground">
                      {row.repository} · {row.branch ?? "unknown branch"} · {row.event ?? "unknown event"} · {ago(row.updated_at)}
                    </p>
                  </div>
                  <AnalysisSummary row={row} />
                  {a && !active && (
                    <Link href={`/ci-cd/${row.id}`} className={buttonVariants({ size: "sm" })}>
                      View analysis
                    </Link>
                  )}
                  {canAnalyze && row.analyzable && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => start.mutate({ row, force: label === "Re-run" })}
                      disabled={active || (start.isPending && start.variables?.row.id === row.id)}
                    >
                      {active ? "Analyzing…" : label}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
          {list.hasNextPage && (
            <div className="border-t border-border p-3 text-center">
              <Button size="sm" onClick={() => list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                {list.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
