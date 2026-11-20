"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { AiPanel } from "@/components/ai-panel";
import { AskPanel } from "@/components/ask-panel";
import { CiRuns } from "@/components/ci-runs";
import { CodeSearch } from "@/components/code-search";
import { GithubPanel } from "@/components/github-panel";
import { IndexCell } from "@/components/index-cell";
import { PageHeader } from "@/components/page-header";
import { PullRequests } from "@/components/pull-requests";
import { UsageDashboard } from "@/components/usage-dashboard";
import { ApiError, codeApi, orgApi, type CiState } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const CI_LABEL: Record<CiState, { text: string; cls: string }> = {
  passing: { text: "Passing", cls: "text-success" },
  failing: { text: "Failing", cls: "text-danger" },
  running: { text: "Running", cls: "text-primary" },
  other: { text: "Other", cls: "text-muted-foreground" },
  none: { text: "No runs", cls: "text-muted-foreground" },
};

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-md border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold", tone)}>{value}</p>
    </div>
  );
}

export function OrgView() {
  const { orgId } = useParams<{ orgId: string }>();
  const queryClient = useQueryClient();

  const org = useQuery({
    queryKey: ["org", orgId, "info"],
    queryFn: async () => orgApi.org(await accessToken(), orgId),
  });
  const github = useQuery({
    queryKey: ["org", orgId, "github"],
    queryFn: async () => orgApi.githubStatus(await accessToken(), orgId),
    // poll while a sync is running so the numbers fill in by themselves
    refetchInterval: (q) =>
      q.state.data?.installations.some((i) => i.sync_status === "running") ? 3000 : false,
  });
  const syncing = github.data?.installations.some((i) => i.sync_status === "running") ?? false;
  const overview = useQuery({
    queryKey: ["org", orgId, "overview"],
    queryFn: async () => orgApi.overview(await accessToken(), orgId),
    refetchInterval: syncing ? 3000 : false,
  });
  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    // poll while a sync or an index run is in progress so the status updates by itself
    refetchInterval: (q) =>
      syncing || q.state.data?.some((r) => r.index.status === "queued" || r.index.status === "running")
        ? 3000
        : false,
  });
  const startIndex = useMutation({
    mutationFn: async (repoId: string) => codeApi.startIndex(await accessToken(), orgId, repoId),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "repos"] }),
  });

  if (org.isError) {
    const notFound = org.error instanceof ApiError && org.error.status === 404;
    return (
      <main className="mx-auto max-w-3xl px-6 py-12">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
          ← Organizations
        </Link>
        <p role="alert" className="mt-6 text-danger">
          {notFound ? "Organization not found." : "Couldn’t load this organization."}
        </p>
      </main>
    );
  }

  const isAdmin = org.data?.role === "admin" || org.data?.role === "owner";
  const canIndex = isAdmin || org.data?.role === "member";

  return (
    <div>
      <PageHeader
        title={org.data?.name ?? "Workspace"}
        description="GitHub, pull requests, CI and AI for this organization."
        actions={
          org.data && (
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs capitalize text-muted-foreground">
              {org.data.role}
            </span>
          )
        }
      />

      {overview.data && (
        <section className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4" aria-label="Summary">
          <Stat label="Repositories" value={overview.data.repositories} />
          <Stat label="Open pull requests" value={overview.data.open_pull_requests} />
          <Stat label="Open issues" value={overview.data.open_issues} />
          <Stat
            label="CI failing"
            value={overview.data.ci.failing}
            tone={overview.data.ci.failing > 0 ? "text-danger" : undefined}
          />
        </section>
      )}

      <GithubPanel orgId={orgId} isAdmin={isAdmin} />

      {org.data && <AiPanel orgId={orgId} isAdmin={isAdmin} />}

      {org.data && <UsageDashboard orgId={orgId} />}

      {repos.data && repos.data.length > 0 && (
        <section className="mt-10">
          <h2 className="text-lg font-medium">Repositories</h2>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-4 font-medium">Repository</th>
                  <th className="py-2 pr-4 font-medium">CI</th>
                  <th className="py-2 pr-4 text-right font-medium">PRs</th>
                  <th className="py-2 pr-4 text-right font-medium">Issues</th>
                  <th className="py-2 pr-4 font-medium">Last commit</th>
                  <th className="py-2 font-medium">Code index</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {repos.data.map((r) => (
                  <tr key={r.id}>
                    <td className="py-2.5 pr-4">
                      <a
                        href={r.html_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-medium hover:underline"
                      >
                        {r.full_name}
                      </a>
                      {r.private && (
                        <span className="ml-2 text-xs text-muted-foreground">private</span>
                      )}
                      {r.language && (
                        <span className="ml-2 text-xs text-muted-foreground">{r.language}</span>
                      )}
                    </td>
                    <td className={cn("py-2.5 pr-4", CI_LABEL[r.ci].cls)}>{CI_LABEL[r.ci].text}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">{r.open_pull_requests}</td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">{r.open_issues}</td>
                    <td className="py-2.5 pr-4 text-muted-foreground">{ago(r.last_commit_at)}</td>
                    <td className="py-2.5">
                      <IndexCell
                        repo={r}
                        canIndex={canIndex}
                        busy={startIndex.isPending && startIndex.variables === r.id}
                        onStart={() => startIndex.mutate(r.id)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {startIndex.isError && (
            <p role="alert" className="mt-3 text-sm text-danger">
              {startIndex.error instanceof Error ? startIndex.error.message : "Could not start indexing."}
            </p>
          )}
        </section>
      )}

      {repos.data && repos.data.length > 0 && <PullRequests orgId={orgId} canReview={canIndex} />}

      {repos.data && repos.data.length > 0 && <CiRuns orgId={orgId} canAnalyze={canIndex} />}

      {canIndex && repos.data && <AskPanel orgId={orgId} repos={repos.data} />}

      {canIndex && repos.data && <CodeSearch orgId={orgId} repos={repos.data} />}

      {overview.data && overview.data.recent_commits.length > 0 && (
        <section className="mt-10">
          <h2 className="text-lg font-medium">Recent commits</h2>
          <ul className="mt-3 divide-y divide-border border-y border-border">
            {overview.data.recent_commits.map((c) => (
              <li key={`${c.repository}-${c.sha}`} className="py-2.5 text-sm">
                <p className="font-medium">{c.message || "(no message)"}</p>
                <p className="text-xs text-muted-foreground">
                  {c.repository} · {c.author ?? "unknown"} · {ago(c.committed_at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
