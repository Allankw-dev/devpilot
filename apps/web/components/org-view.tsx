"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { AiPanel } from "@/components/ai-panel";
import { ApiError, orgApi, type CiState, type GithubInstallation } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

const CI_LABEL: Record<CiState, { text: string; cls: string }> = {
  passing: { text: "Passing", cls: "text-success" },
  failing: { text: "Failing", cls: "text-danger" },
  running: { text: "Running", cls: "text-primary" },
  other: { text: "Other", cls: "text-muted-foreground" },
  none: { text: "No runs", cls: "text-muted-foreground" },
};

function ago(iso: string | null): string {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return new Date(iso).toLocaleDateString();
}

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
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["org", orgId] });

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
    refetchInterval: syncing ? 3000 : false,
  });

  const connect = useMutation({
    mutationFn: async () => orgApi.installUrl(await accessToken(), orgId),
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const sync = useMutation({
    mutationFn: async (installationId: string) =>
      orgApi.sync(await accessToken(), orgId, installationId),
    onSuccess: refresh,
  });
  const disconnect = useMutation({
    mutationFn: async (installationId: string) =>
      orgApi.disconnect(await accessToken(), orgId, installationId),
    onSuccess: refresh,
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
  const gh = github.data;
  const mutationError = [connect, sync, disconnect].find((m) => m.isError)?.error;

  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
        ← Organizations
      </Link>
      <header className="mt-4 flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{org.data?.name ?? "…"}</h1>
        {org.data && (
          <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs capitalize text-muted-foreground">
            {org.data.role}
          </span>
        )}
      </header>

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

      <section className="mt-10">
        <h2 className="text-lg font-medium">GitHub</h2>

        {gh && !gh.configured && (
          <div className="mt-3 space-y-1 text-sm">
            <p className="text-muted-foreground">GitHub isn’t set up on the server yet.</p>
            {gh.missing.length > 0 && (
              <p className="text-muted-foreground">
                Missing: <code className="font-mono">{gh.missing.join(", ")}</code>. See{" "}
                <code className="font-mono">docs/GITHUB.md</code>.
              </p>
            )}
          </div>
        )}

        {gh?.configured && gh.installations.length === 0 && (
          <div className="mt-3">
            <p className="text-sm text-muted-foreground">
              Connect a GitHub account or organization to see its repositories here. DevPilot only
              asks for read access.
            </p>
            {isAdmin ? (
              <button
                onClick={() => connect.mutate()}
                disabled={connect.isPending}
                className="mt-4 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
              >
                {connect.isPending ? "Opening GitHub…" : "Connect GitHub"}
              </button>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">
                An admin of this organization needs to connect GitHub.
              </p>
            )}
          </div>
        )}

        {gh && gh.installations.length > 0 && (
          <ul className="mt-3 divide-y divide-border border-y border-border">
            {gh.installations.map((i: GithubInstallation) => (
              <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="font-medium">{i.account_login}</p>
                  <p className="text-xs text-muted-foreground">
                    {i.suspended
                      ? "Suspended on GitHub"
                      : i.sync_status === "running"
                        ? "Syncing…"
                        : `Last synced ${ago(i.last_synced_at)}`}
                  </p>
                  {i.sync_error && (
                    <p role="status" className="mt-1 text-xs text-danger">
                      {i.sync_error}
                    </p>
                  )}
                </div>
                {isAdmin && (
                  <div className="flex gap-2 text-sm">
                    <button
                      onClick={() => sync.mutate(i.id)}
                      disabled={i.sync_status === "running" || i.suspended || sync.isPending}
                      className="rounded-md border border-border px-3 py-1.5 hover:bg-muted disabled:opacity-50"
                    >
                      Sync now
                    </button>
                    <button
                      onClick={() => {
                        if (
                          window.confirm(
                            `Disconnect ${i.account_login}? Its synced data is removed from DevPilot. The app stays installed on GitHub until you remove it there.`,
                          )
                        )
                          disconnect.mutate(i.id);
                      }}
                      className="rounded-md border border-border px-3 py-1.5 text-danger hover:bg-muted"
                    >
                      Disconnect
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {mutationError && (
          <p role="alert" className="mt-3 text-sm text-danger">
            {mutationError instanceof Error ? mutationError.message : "Something went wrong."}
          </p>
        )}
      </section>

      {org.data && <AiPanel orgId={orgId} isAdmin={isAdmin} />}

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
                  <th className="py-2 font-medium">Last commit</th>
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
                    <td className="py-2.5 text-muted-foreground">{ago(r.last_commit_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

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
    </main>
  );
}
