"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { issueApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const PAGE = 30;
const STATES = ["open", "closed", "all"] as const;

export function RepoIssues({ orgId, repoId }: { orgId: string; repoId: string }) {
  const [state, setState] = useState<(typeof STATES)[number]>("open");
  const [text, setText] = useState("");
  const q = useDebounced(text);
  const issues = useInfiniteQuery({
    queryKey: ["org", orgId, "repo", repoId, "issues", state, q],
    queryFn: async ({ pageParam }) =>
      issueApi.list(await accessToken(), orgId, state, { repoId, q, limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  });
  const rows = issues.data?.pages.flat() ?? [];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex gap-1" role="group" aria-label="Issue state">
          {STATES.map((s) => (
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
        <label className="sr-only" htmlFor="issue-search">
          Search issues
        </label>
        <input
          id="issue-search"
          type="search"
          placeholder="Search issue titles"
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="w-64 max-w-full rounded-md border border-border bg-background px-2.5 py-1.5 text-sm"
        />
      </div>

      {issues.isPending && <p role="status" className="text-sm text-muted-foreground">Loading issues…</p>}
      {issues.isError && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load issues.{" "}
          <Button size="sm" onClick={() => issues.refetch()}>
            Try again
          </Button>
        </p>
      )}
      {issues.isSuccess && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {q ? "No issues match your search." : state === "all" ? "No issues." : `No ${state} issues.`}
        </p>
      )}
      {rows.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {rows.map((i) => (
              <li key={i.id} className="px-4 py-2.5 text-sm">
                <a href={i.html_url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                  {i.title}
                </a>
                {i.state === "closed" && <Badge className="ml-2">closed</Badge>}
                <p className="text-xs text-muted-foreground">
                  #{i.number} · {i.author ?? "unknown"} · {i.comments} {i.comments === 1 ? "comment" : "comments"} ·{" "}
                  {ago(i.updated_at)}
                </p>
              </li>
            ))}
          </ul>
          {issues.hasNextPage && (
            <div className="border-t border-border p-3 text-center">
              <Button size="sm" onClick={() => issues.fetchNextPage()} disabled={issues.isFetchingNextPage}>
                {issues.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
