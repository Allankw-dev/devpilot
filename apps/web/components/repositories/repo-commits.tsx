"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { repoApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";

const PAGE = 30;

export function RepoCommits({ orgId, repoId }: { orgId: string; repoId: string }) {
  const commits = useInfiniteQuery({
    queryKey: ["org", orgId, "repo", repoId, "commits"],
    queryFn: async ({ pageParam }) =>
      repoApi.commits(await accessToken(), orgId, repoId, { limit: PAGE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, all) => (last.length === PAGE ? all.length * PAGE : undefined),
  });
  const rows = commits.data?.pages.flat() ?? [];

  if (commits.isPending) return <p role="status" className="text-sm text-muted-foreground">Loading commits…</p>;
  if (commits.isError)
    return (
      <p role="alert" className="text-sm text-danger">
        Couldn’t load commits.{" "}
        <Button size="sm" onClick={() => commits.refetch()}>
          Try again
        </Button>
      </p>
    );
  if (rows.length === 0)
    return <p className="text-sm text-muted-foreground">No commits stored yet. Sync GitHub from the Integrations page.</p>;

  return (
    <Card>
      <ul className="divide-y divide-border">
        {rows.map((c) => (
          <li key={c.sha} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2.5 text-sm">
            <div className="min-w-0 flex-1">
              {c.url ? (
                <a href={c.url} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
                  {c.message}
                </a>
              ) : (
                <span className="font-medium">{c.message}</span>
              )}
              <p className="text-xs text-muted-foreground">
                {c.author ?? "unknown"} · {ago(c.committed_at)}
              </p>
            </div>
            <code className="font-mono text-xs text-muted-foreground">{c.sha.slice(0, 7)}</code>
          </li>
        ))}
      </ul>
      {commits.hasNextPage && (
        <div className="border-t border-border p-3 text-center">
          <Button size="sm" onClick={() => commits.fetchNextPage()} disabled={commits.isFetchingNextPage}>
            {commits.isFetchingNextPage ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </Card>
  );
}
