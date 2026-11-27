"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { aiApi, ApiError, authedApi, dashboardApi, type DashboardData } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const RANGES = [7, 14, 30] as const;
const fmt = new Intl.NumberFormat();
const CHART_COLORS = { commits: "hsl(var(--primary))", prs: "hsl(var(--muted-foreground))", calls: "hsl(var(--primary))" };

function StatCard({ label, value, hint, tone }: { label: string; value: number; hint?: string; tone?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold", tone)}>{fmt.format(value)}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </Card>
  );
}

function ListCard({
  title,
  description,
  empty,
  viewAllHref,
  children,
  isEmpty,
}: {
  title: string;
  description: string;
  empty: string;
  viewAllHref: string | null;
  isEmpty: boolean;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader
        title={title}
        description={description}
        action={
          viewAllHref ? (
            <Link href={viewAllHref} className="shrink-0 text-xs text-primary hover:underline">
              View all
            </Link>
          ) : undefined
        }
      />
      {isEmpty ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="divide-y divide-border">{children}</ul>
      )}
    </Card>
  );
}

function ExternalLink({ href, children }: { href: string | null; children: React.ReactNode }) {
  if (!href) return <span className="font-medium">{children}</span>;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="font-medium hover:underline">
      {children}
    </a>
  );
}

function CreateWorkspace() {
  const queryClient = useQueryClient();
  const { select } = useWorkspace();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: async (orgName: string) => authedApi.createOrg(await accessToken(), orgName),
    onSuccess: async (org) => {
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      select(org.id);
    },
  });
  return (
    <Card className="mx-auto max-w-lg p-6">
      <h2 className="text-lg font-semibold">Create your first workspace</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        A workspace holds your team, your connected GitHub repositories and everything the AI does
        with them.
      </p>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim().length >= 2) create.mutate(name.trim());
        }}
      >
        <label htmlFor="first-workspace" className="sr-only">
          Workspace name
        </label>
        <input
          id="first-workspace"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={80}
          placeholder="Workspace name"
          className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={create.isPending || name.trim().length < 2}
          className={buttonVariants({ variant: "primary" })}
        >
          {create.isPending ? "Creating…" : "Create"}
        </button>
      </form>
      {create.isError && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {create.error instanceof Error ? create.error.message : "Could not create it."}
        </p>
      )}
    </Card>
  );
}

function ActivityChart({ data }: { data: DashboardData }) {
  const rows = data.activity.map((d) => ({ ...d, label: d.day.slice(5) }));
  const empty = rows.every((r) => r.commits === 0 && r.pull_requests_opened === 0);
  return (
    <Card>
      <CardHeader title="Repository activity" description="Commits and pull requests opened per day (UTC)" />
      {empty ? (
        <p className="px-4 py-10 text-sm text-muted-foreground">
          No commits or pull requests in the last {data.days} days. Sync GitHub if you expected some.
        </p>
      ) : (
        <div className="h-64 px-2 py-3" role="img" aria-label="Bar chart of commits and pull requests per day">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis allowDecimals={false} stroke="hsl(var(--muted-foreground))" fontSize={11} width={28} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--elevated))", border: "1px solid hsl(var(--border))", borderRadius: 6 }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="commits" name="Commits" fill={CHART_COLORS.commits} radius={[3, 3, 0, 0]} />
              <Bar dataKey="pull_requests_opened" name="PRs opened" fill={CHART_COLORS.prs} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

function AiCallsChart({ orgId, days }: { orgId: string; days: number }) {
  const usage = useQuery({
    queryKey: ["org", orgId, "ai-usage", days],
    queryFn: async () => aiApi.usage(await accessToken(), orgId, days),
  });
  const rows = (usage.data?.by_day ?? []).map((d) => ({ ...d, label: d.day.slice(5) }));
  const empty = rows.every((r) => r.provider_calls === 0);
  return (
    <Card>
      <CardHeader title="AI provider calls" description="Requests sent to the AI provider per day, retries included" />
      {usage.isPending ? (
        <p className="px-4 py-10 text-sm text-muted-foreground">Loading…</p>
      ) : usage.isError ? (
        <p role="alert" className="px-4 py-10 text-sm text-danger">
          Couldn’t load AI usage.
        </p>
      ) : empty ? (
        <p className="px-4 py-10 text-sm text-muted-foreground">No AI requests in the last {days} days.</p>
      ) : (
        <div className="h-64 px-2 py-3" role="img" aria-label="Bar chart of AI provider calls per day">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis allowDecimals={false} stroke="hsl(var(--muted-foreground))" fontSize={11} width={28} />
              <Tooltip
                contentStyle={{ background: "hsl(var(--elevated))", border: "1px solid hsl(var(--border))", borderRadius: 6 }}
                labelStyle={{ color: "hsl(var(--foreground))" }}
              />
              <Bar dataKey="provider_calls" name="Calls" fill={CHART_COLORS.calls} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}

export function DashboardHome() {
  const { me, org } = useWorkspace();
  const [days, setDays] = useState<(typeof RANGES)[number]>(14);

  const dash = useQuery({
    queryKey: ["org", org?.id, "dashboard", days],
    queryFn: async () => dashboardApi.get(await accessToken(), org!.id, days),
    enabled: !!org,
  });

  const first = (me.user.display_name || me.user.email.split("@")[0]).split(" ")[0];
  if (!org) {
    return (
      <>
        <PageHeader title={`Welcome, ${first}`} description="Let’s set up your first workspace." />
        <CreateWorkspace />
      </>
    );
  }

  const data = dash.data;
  return (
    <>
      <PageHeader
        title={`Welcome back, ${first}`}
        description={`${org.name} · last ${days} days`}
        actions={
          <>
            <div className="flex gap-1" role="group" aria-label="Time period">
              {RANGES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setDays(r)}
                  aria-pressed={days === r}
                  className={cn(
                    "rounded-md border border-border px-2.5 py-1.5 text-xs",
                    days === r ? "bg-muted font-medium" : "hover:bg-muted",
                  )}
                >
                  {r} days
                </button>
              ))}
            </div>
            <Link href="/repositories" className={buttonVariants({ variant: "outline", size: "sm" })}>
              Repositories
            </Link>
          </>
        }
      />

      {dash.isPending && (
        <p role="status" className="text-sm text-muted-foreground">
          Loading your dashboard…
        </p>
      )}
      {dash.isError && (
        <div role="alert" className="flex items-center gap-3 text-sm text-danger">
          {dash.error instanceof ApiError ? dash.error.message : "Couldn’t load the dashboard."}
          <button
            type="button"
            onClick={() => dash.refetch()}
            className="rounded-md border border-border px-2.5 py-1 text-xs text-foreground hover:bg-muted"
          >
            Try again
          </button>
        </div>
      )}

      {data && !data.github_connected && (
        <Card className="mx-auto max-w-xl p-8 text-center">
          <h2 className="text-lg font-semibold">Connect GitHub to get started</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            DevPilot reads your repositories, pull requests, issues and CI runs (read-only), then
            the AI can review pull requests, explain failed builds and answer questions about your
            code.
          </p>
          <Link href="/integrations" className={cn(buttonVariants({ variant: "primary" }), "mt-5")}>
            Connect GitHub
          </Link>
        </Card>
      )}

      {data && data.github_connected && (
        <div className="space-y-6">
          <section aria-label="Summary" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <StatCard label="Repositories" value={data.stats.repositories} />
            <StatCard label="Open pull requests" value={data.stats.open_pull_requests} />
            <StatCard label="Open issues" value={data.stats.open_issues} />
            <StatCard label="AI reviews" value={data.stats.reviews_completed} hint={`last ${days} days`} />
            <StatCard label="CI analyses" value={data.stats.ci_analyses_completed} hint={`last ${days} days`} />
            <StatCard
              label="Failed CI runs"
              value={data.stats.failed_runs}
              hint={`last ${days} days`}
              tone={data.stats.failed_runs > 0 ? "text-danger" : undefined}
            />
          </section>
          <p className="-mt-3 text-xs text-muted-foreground">
            GitHub data last synced {ago(data.last_synced_at)}.
          </p>

          <div className="grid gap-4 lg:grid-cols-2">
            <ActivityChart data={data} />
            <AiCallsChart orgId={org.id} days={days} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <ListCard
              title="Open pull requests"
              description="Most recently updated"
              empty="No open pull requests."
              viewAllHref={"/code-reviews"}
              isEmpty={data.recent_pull_requests.length === 0}
            >
              {data.recent_pull_requests.map((pr) => (
                <li key={pr.id} className="px-4 py-2.5 text-sm">
                  <ExternalLink href={pr.html_url}>{pr.title}</ExternalLink>
                  <p className="text-xs text-muted-foreground">
                    {pr.repository} #{pr.number} · {pr.author ?? "unknown"}
                    {pr.draft ? " · draft" : ""} · {ago(pr.updated_at)}
                  </p>
                </li>
              ))}
            </ListCard>

            <ListCard
              title="Recent AI reviews"
              description="Latest pull request reviews"
              empty="No AI reviews yet. Open Code Reviews and review a pull request."
              viewAllHref={"/code-reviews"}
              isEmpty={data.recent_reviews.length === 0}
            >
              {data.recent_reviews.map((r) => (
                <li key={r.id} className="px-4 py-2.5 text-sm">
                  <span className="font-medium">{r.title}</span>
                  <p className="text-xs text-muted-foreground">
                    {r.repository} #{r.number} ·{" "}
                    {r.status === "ready" ? (
                      <>
                        {r.open_findings} open {r.open_findings === 1 ? "finding" : "findings"}
                        {r.serious_findings > 0 && (
                          <span className="text-danger"> ({r.serious_findings} serious)</span>
                        )}
                      </>
                    ) : r.status === "failed" ? (
                      "failed"
                    ) : (
                      "in progress"
                    )}
                    {r.finished_at ? ` · ${ago(r.finished_at)}` : ""}
                  </p>
                </li>
              ))}
            </ListCard>

            <ListCard
              title="Failed CI runs"
              description="Latest failed or timed-out workflow runs"
              empty="No failed runs. Nice."
              viewAllHref={"/ci-cd"}
              isEmpty={data.recent_failed_runs.length === 0}
            >
              {data.recent_failed_runs.map((run) => (
                <li key={run.id} className="px-4 py-2.5 text-sm">
                  <ExternalLink href={run.html_url}>{run.name ?? "Workflow"}</ExternalLink>
                  <p className="text-xs text-muted-foreground">
                    {run.repository} · {run.branch ?? "unknown branch"} ·{" "}
                    <span className="text-danger">{run.conclusion}</span> · {ago(run.updated_at)}
                    {run.analysis_status === "ready" && " · analyzed"}
                  </p>
                </li>
              ))}
            </ListCard>

            <ListCard
              title="Open issues"
              description="Most recently updated"
              empty="No open issues."
              viewAllHref={null}
              isEmpty={data.open_issues.length === 0}
            >
              {data.open_issues.map((issue) => (
                <li key={issue.id} className="px-4 py-2.5 text-sm">
                  <ExternalLink href={issue.html_url}>{issue.title}</ExternalLink>
                  <p className="text-xs text-muted-foreground">
                    {issue.repository} #{issue.number} · {issue.author ?? "unknown"} · {issue.comments}{" "}
                    {issue.comments === 1 ? "comment" : "comments"} · {ago(issue.updated_at)}
                  </p>
                </li>
              ))}
            </ListCard>
          </div>
        </div>
      )}
    </>
  );
}
