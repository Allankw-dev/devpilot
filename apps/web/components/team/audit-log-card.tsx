"use client";

import { useInfiniteQuery } from "@tanstack/react-query";

import { useWorkspace } from "@/components/shell/workspace-provider";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { auditApi } from "@/lib/api";
import { actorLabel, describeAudit } from "@/lib/audit";
import { ago } from "@/lib/format";
import { isAdmin } from "@/lib/roles";
import { accessToken } from "@/lib/supabase/token";

/** Admins and owners only: the API refuses everyone else, so we don't even ask. */
export function AuditLogCard({ orgId }: { orgId: string }) {
  const { org } = useWorkspace();
  const allowed = isAdmin(org?.role);

  const log = useInfiniteQuery({
    queryKey: ["org", orgId, "audit-log"],
    queryFn: async ({ pageParam }) => auditApi.list(await accessToken(), orgId, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_before ?? undefined,
    enabled: allowed,
  });

  if (!allowed) return null;
  const entries = log.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <Card>
      <CardHeader title="Audit log" description="Who did what in this workspace, newest first. Entries can’t be edited or deleted." />
      <div className="px-4 py-3">
        {log.isPending && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading…
          </p>
        )}
        {log.isError && (
          <p role="alert" className="text-sm text-danger">
            Couldn’t load the audit log.
          </p>
        )}
        {log.isSuccess && entries.length === 0 && (
          <p className="text-sm text-muted-foreground">Nothing recorded yet.</p>
        )}
        <ul className="divide-y divide-border">
          {entries.map((entry) => (
            <li key={entry.id} className="flex items-baseline justify-between gap-3 py-2 text-sm">
              <span className="min-w-0">
                <span className="font-medium">{actorLabel(entry)}</span> {describeAudit(entry)}
              </span>
              <time
                dateTime={entry.created_at}
                title={entry.request_id ? `${new Date(entry.created_at).toLocaleString()} · request ${entry.request_id}` : new Date(entry.created_at).toLocaleString()}
                className="shrink-0 text-xs text-muted-foreground"
              >
                {ago(entry.created_at)}
              </time>
            </li>
          ))}
        </ul>
        {log.hasNextPage && (
          <div className="mt-3">
            <Button size="sm" disabled={log.isFetchingNextPage} onClick={() => void log.fetchNextPage()}>
              {log.isFetchingNextPage ? "Loading…" : "Load older entries"}
            </Button>
          </div>
        )}
        {log.isFetchNextPageError && (
          <p role="alert" className="mt-2 text-sm text-danger">
            Couldn’t load older entries.
          </p>
        )}
      </div>
    </Card>
  );
}
