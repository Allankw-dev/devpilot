"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { ReviewBadge } from "@/components/review-badge";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, orgApi, reviewApi, type PullRequestRow } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const PAGE = 30;
const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";

/** Starting a review costs AI tokens, so it is a deliberate click, never automatic. */
export function reviewActionLabel(row: PullRequestRow): "Review" | "Retry" | "Review again" | "Re-run" {
  const r = row.review;
  if (!r) return "Review";
  if (r.status === "failed") return "Retry";
  return r.stale ? "Review again" : "Re-run";
}

/**
 * Pull requests with their AI review status. With `repoId` it lists one repository's pull requests;
 * without, it adds a repository filter.
 */
export function ReviewList({ orgId, canReview, repoId }: { orgId: string; canReview: boolean; repoId?: string }) {
  const queryClient = useQueryClient();
  const [state, setState] = useState<"open" | "all">("open");
  const [repoFilter, setRepoFilter] = useState("");
  const [text, setText] = useState("");
  const q = useDebounced(text);
  const effectiveRepo = repoId ?? (repoFilter || undefined);

  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    enabled: !repoId,
  });
  const list = useInfiniteQuery({
    queryKey: ["org", orgId, "pull-requests", state, effectiveRepo ?? "", q],
    queryFn: async ({ pageParam }) =>
      reviewApi.list(await accessToken(), orgId, state, { repoId: effectiveRepo, q, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
    refetchInterval: (query) =>
      query.state.data?.pages.flat().some((r) => r.review?.status === "queued" || r.review?.status === "running")
        ? 3000
        : false,
  });
  const start = useMutation({
    mutationFn: async (v: { row: PullRequestRow; force: boolean }) =>
      reviewApi.start(await accessToken(), orgId, v.row.id, v.force),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "pull-requests"] }),
  });
  const rows = list.data?.pages.flat() ?? [];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Pull request state">
          {(["open", "all"] as const).map((s) => (
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
        {!repoId && (
          <>
            <label className="sr-only" htmlFor="review-repo">
              Repository
            </label>
            <select id="review-repo" value={repoFilter} onChange={(e) => setRepoFilter(e.target.value)} className={field}>
              <option value="">All repositories</option>
              {(repos.data ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.full_name}
                </option>
              ))}
            </select>
          </>
        )}
        <label className="sr-only" htmlFor="review-search">
          Search pull requests
        </label>
        <input
          id="review-search"
          type="search"
          placeholder="Search pull request titles"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className={cn(field, "w-64 max-w-full")}
        />
      </div>

      {list.isPending && <p role="status" className="text-sm text-muted-foreground">Loading pull requests…</p>}
      {list.isError && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load pull requests.{" "}
          <Button size="sm" onClick={() => list.refetch()}>
            Try again
          </Button>
        </p>
      )}
      {start.isError && (
        <p role="alert" className="mb-2 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the review."}
        </p>
      )}
      {list.isSuccess && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {q ? "No pull requests match your search." : state === "open" ? "No open pull requests." : "No pull requests."}
        </p>
      )}

      {rows.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {rows.map((row) => {
              const active = row.review?.status === "queued" || row.review?.status === "running";
              const label = reviewActionLabel(row);
              return (
                <li key={row.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <a href={row.html_url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                      {row.title}
                    </a>
                    {row.draft && <Badge className="ml-2">draft</Badge>}
                    {row.merged && <Badge tone="primary" className="ml-2">merged</Badge>}
                    {!row.merged && row.state === "closed" && <Badge className="ml-2">closed</Badge>}
                    <p className="text-xs text-muted-foreground">
                      {row.repository} #{row.number} · {row.author ?? "unknown"} · {ago(row.updated_at)}
                    </p>
                  </div>
                  <ReviewBadge row={row} />
                  {row.review && !active && (
                    <Link href={`/code-reviews/${row.id}`} className={buttonVariants({ size: "sm" })}>
                      View review
                    </Link>
                  )}
                  {canReview && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => start.mutate({ row, force: label === "Re-run" })}
                      disabled={active || (start.isPending && start.variables?.row.id === row.id)}
                    >
                      {active ? "Reviewing…" : label}
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
