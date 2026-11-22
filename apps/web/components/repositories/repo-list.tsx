"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Pager } from "@/components/ui/pager";
import { orgApi, type CiState } from "@/lib/api";
import { ago } from "@/lib/format";
import { CI_LABEL, INDEX_LABEL } from "@/lib/labels";
import { filterRepos, hasFilters, languagesOf, NO_FILTERS, paginate, type RepoFilters } from "@/lib/repo-filter";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 10;
const CI_OPTIONS: CiState[] = ["passing", "failing", "running", "other", "none"];
const field = "rounded-md border border-border bg-background px-2.5 py-1.5 text-sm";

export function RepoList() {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const [filters, setFilters] = useState<RepoFilters>(NO_FILTERS);
  const [page, setPage] = useState(1);

  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    enabled: !!org,
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.index.status === "queued" || r.index.status === "running") ? 3000 : false,
  });

  useEffect(() => setPage(1), [filters]); // a new search starts at the first page

  const all = useMemo(() => repos.data ?? [], [repos.data]);
  const languages = useMemo(() => languagesOf(all), [all]);
  const matching = useMemo(() => filterRepos(all, filters), [all, filters]);
  const { rows, page: current, pages } = paginate(matching, page, PAGE_SIZE);
  const archivedHidden = !filters.showArchived ? all.filter((r) => r.archived).length : 0;

  if (!org) {
    return (
      <>
        <PageHeader title="Repositories" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Repositories"
        description="Repositories GitHub has shared with this workspace."
        actions={
          <Link href="/integrations" className={buttonVariants({ variant: "outline", size: "sm" })}>
            GitHub settings
          </Link>
        }
      />

      {repos.isPending && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading repositories…
        </p>
      )}
      {repos.isError && (
        <div role="alert" className="flex items-center gap-3 text-sm text-danger">
          Couldn’t load repositories.
          <Button size="sm" onClick={() => repos.refetch()}>
            Try again
          </Button>
        </div>
      )}

      {repos.isSuccess && all.length === 0 && (
        <Card className="mx-auto max-w-xl p-8 text-center">
          <h2 className="text-lg font-semibold">No repositories yet</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Connect GitHub and choose which repositories to share, then sync.
          </p>
          <Link href="/integrations" className={cn(buttonVariants({ variant: "primary" }), "mt-5")}>
            Connect GitHub
          </Link>
        </Card>
      )}

      {repos.isSuccess && all.length > 0 && (
        <>
          <form role="search" aria-label="Filter repositories" className="mb-4 flex flex-wrap items-center gap-2" onSubmit={(e) => e.preventDefault()}>
            <label className="sr-only" htmlFor="repo-search">
              Search repositories
            </label>
            <input
              id="repo-search"
              type="search"
              placeholder="Search name or description"
              value={filters.q}
              onChange={(e) => setFilters({ ...filters, q: e.target.value })}
              className={cn(field, "w-64 max-w-full")}
            />
            <label className="sr-only" htmlFor="repo-language">
              Language
            </label>
            <select
              id="repo-language"
              value={filters.language}
              onChange={(e) => setFilters({ ...filters, language: e.target.value })}
              className={field}
            >
              <option value="">All languages</option>
              {languages.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="repo-ci">
              CI status
            </label>
            <select
              id="repo-ci"
              value={filters.ci}
              onChange={(e) => setFilters({ ...filters, ci: e.target.value as CiState | "" })}
              className={field}
            >
              <option value="">Any CI status</option>
              {CI_OPTIONS.map((c) => (
                <option key={c} value={c}>
                  {CI_LABEL[c].text}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={filters.showArchived}
                onChange={(e) => setFilters({ ...filters, showArchived: e.target.checked })}
              />
              Show archived{archivedHidden > 0 ? ` (${archivedHidden} hidden)` : ""}
            </label>
            {hasFilters(filters) && (
              <Button size="sm" variant="ghost" onClick={() => setFilters(NO_FILTERS)}>
                Clear filters
              </Button>
            )}
          </form>

          {matching.length === 0 ? (
            <p className="text-sm text-muted-foreground">No repositories match these filters.</p>
          ) : (
            <Card className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-border text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2 font-normal">Repository</th>
                    <th className="px-3 py-2 font-normal">Language</th>
                    <th className="px-3 py-2 font-normal">Branch</th>
                    <th className="px-3 py-2 text-right font-normal">PRs</th>
                    <th className="px-3 py-2 text-right font-normal">Issues</th>
                    <th className="px-3 py-2 font-normal">CI</th>
                    <th className="px-3 py-2 font-normal">Code index</th>
                    <th className="px-3 py-2 font-normal">Last push</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="border-b border-border last:border-0">
                      <td className="max-w-xs px-4 py-3">
                        <Link href={`/repositories/${r.id}`} className="font-medium hover:underline">
                          {r.full_name}
                        </Link>
                        <span className="ml-2 inline-flex gap-1 align-middle">
                          {r.private && <Badge>private</Badge>}
                          {r.archived && <Badge tone="warning">archived</Badge>}
                        </span>
                        {r.description && <p className="mt-0.5 truncate text-xs text-muted-foreground">{r.description}</p>}
                      </td>
                      <td className="px-3 py-3">{r.language ?? <span className="text-muted-foreground">n/a</span>}</td>
                      <td className="px-3 py-3 font-mono text-xs">{r.default_branch ?? "n/a"}</td>
                      <td className="px-3 py-3 text-right">{r.open_pull_requests}</td>
                      <td className="px-3 py-3 text-right">{r.open_issues}</td>
                      <td className={cn("px-3 py-3", CI_LABEL[r.ci].cls)}>{CI_LABEL[r.ci].text}</td>
                      <td className="px-3 py-3">{INDEX_LABEL[r.index.status] ?? r.index.status}</td>
                      <td className="whitespace-nowrap px-3 py-3 text-muted-foreground">{ago(r.pushed_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
          <Pager page={current} pages={pages} total={matching.length} onPage={setPage} />
        </>
      )}
    </>
  );
}
