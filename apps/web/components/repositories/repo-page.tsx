"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ReviewList } from "@/components/code-reviews/review-list";
import { PageHeader } from "@/components/page-header";
import { RepoCommits } from "@/components/repositories/repo-commits";
import { RepoIssues } from "@/components/repositories/repo-issues";
import { RepoOverview } from "@/components/repositories/repo-overview";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SectionTabs } from "@/components/ui/section-tabs";
import { orgApi } from "@/lib/api";
import { canWrite } from "@/lib/labels";
import { parseTab } from "@/lib/repo-filter";
import { accessToken } from "@/lib/supabase/token";

const TABS = ["overview", "commits", "pulls", "issues"] as const;

export function RepoPage({ repoId }: { repoId: string }) {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const tab = parseTab(useSearchParams().get("tab"), TABS, "overview");
  const writer = canWrite(org?.role);

  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    enabled: !!org,
    refetchInterval: (q) =>
      q.state.data?.some((r) => r.index.status === "queued" || r.index.status === "running") ? 3000 : false,
  });

  const back = (
    <Link href="/repositories" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" aria-hidden /> Repositories
    </Link>
  );

  if (!org || repos.isPending) return <p role="status" className="text-sm text-muted-foreground">Loading repository…</p>;
  if (repos.isError)
    return (
      <>
        {back}
        <p role="alert" className="text-sm text-danger">
          Couldn’t load this repository.{" "}
          <Button size="sm" onClick={() => repos.refetch()}>
            Try again
          </Button>
        </p>
      </>
    );
  const repo = repos.data.find((r) => r.id === repoId);
  if (!repo)
    return (
      <>
        {back}
        <p role="alert" className="text-sm text-danger">
          Repository not found in this workspace.
        </p>
      </>
    );

  const base = `/repositories/${repo.id}`;
  return (
    <>
      {back}
      <PageHeader
        title={repo.full_name}
        description={repo.description ?? undefined}
        actions={
          <>
            {repo.private && <Badge>private</Badge>}
            {repo.archived && <Badge tone="warning">archived</Badge>}
            <a
              href={`https://github.com/${repo.full_name}`}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
            >
              Open on GitHub
            </a>
          </>
        }
      />
      <SectionTabs
        label="Repository sections"
        active={tab}
        hrefFor={(id) => (id === "overview" ? base : `${base}?tab=${id}`)}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "commits", label: "Commits" },
          { id: "pulls", label: "Pull requests", count: repo.open_pull_requests },
          { id: "issues", label: "Issues", count: repo.open_issues },
        ]}
      />
      {tab === "overview" && <RepoOverview orgId={org.id} repo={repo} canIndex={writer} />}
      {tab === "commits" && <RepoCommits orgId={org.id} repoId={repo.id} />}
      {tab === "pulls" && <ReviewList orgId={org.id} canReview={writer} repoId={repo.id} />}
      {tab === "issues" && <RepoIssues orgId={org.id} repoId={repo.id} />}
    </>
  );
}
