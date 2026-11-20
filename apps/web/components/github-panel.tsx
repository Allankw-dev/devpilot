"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { orgApi, type GithubInstallation } from "@/lib/api";
import { ago } from "@/lib/format";
import { accessToken } from "@/lib/supabase/token";

/** Connecting GitHub, syncing and disconnecting. Admins only can change anything. */
export function GithubPanel({ orgId, isAdmin }: { orgId: string; isAdmin: boolean }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["org", orgId] });

  const github = useQuery({
    queryKey: ["org", orgId, "github"],
    queryFn: async () => orgApi.githubStatus(await accessToken(), orgId),
    // poll while a sync is running so the numbers fill in by themselves
    refetchInterval: (q) => (q.state.data?.installations.some((i) => i.sync_status === "running") ? 3000 : false),
  });
  const connect = useMutation({
    mutationFn: async () => orgApi.installUrl(await accessToken(), orgId),
    onSuccess: ({ url }) => window.location.assign(url),
  });
  const sync = useMutation({
    mutationFn: async (installationId: string) => orgApi.sync(await accessToken(), orgId, installationId),
    onSuccess: refresh,
  });
  const disconnect = useMutation({
    mutationFn: async (installationId: string) => orgApi.disconnect(await accessToken(), orgId, installationId),
    onSuccess: refresh,
  });

  const gh = github.data;
  const mutationError = [connect, sync, disconnect].find((m) => m.isError)?.error;

  return (
    <section className="mt-10" aria-label="GitHub">
      <h2 className="text-lg font-medium">GitHub</h2>

      {github.isPending && <p role="status" className="mt-3 text-sm text-muted-foreground">Loading…</p>}
      {github.isError && (
        <p role="alert" className="mt-3 text-sm text-danger">
          Couldn’t load GitHub status.
        </p>
      )}

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
            Connect a GitHub account or organization to see its repositories here. DevPilot only asks for read access.
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
            <p className="mt-3 text-sm text-muted-foreground">An admin of this organization needs to connect GitHub.</p>
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
  );
}
