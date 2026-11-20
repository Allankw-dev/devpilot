"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { analysisActionLabel, conclusionTone } from "@/components/ci-cd/ci-list";
import { CiPanel } from "@/components/ci-panel";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, ciApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { canWrite } from "@/lib/labels";
import { accessToken } from "@/lib/supabase/token";

export function CiPage({ runId }: { runId: string }) {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const queryClient = useQueryClient();
  const canAnalyze = canWrite(org?.role);

  const run = useQuery({
    queryKey: ["org", orgId, "ci-run", runId],
    queryFn: async () => ciApi.run(await accessToken(), orgId, runId),
    enabled: !!org,
    refetchInterval: (q) =>
      q.state.data?.analysis?.status === "queued" || q.state.data?.analysis?.status === "running" ? 3000 : false,
  });
  const start = useMutation({
    mutationFn: async (force: boolean) => ciApi.start(await accessToken(), orgId, runId, force),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-run", runId] });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-analysis", runId] });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "ci-runs"] });
    },
  });

  const back = (
    <Link href="/ci-cd" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" aria-hidden /> CI/CD
    </Link>
  );

  if (!org || run.isPending) return <p role="status" className="text-sm text-muted-foreground">Loading run…</p>;
  if (run.isError || !run.data) {
    const notFound = run.error instanceof ApiError && run.error.status === 404;
    return (
      <>
        {back}
        <p role="alert" className="text-sm text-danger">
          {notFound ? "Run not found in this workspace." : "Couldn’t load this run."}
        </p>
        {!notFound && (
          <Button size="sm" className="mt-2" onClick={() => run.refetch()}>
            Try again
          </Button>
        )}
      </>
    );
  }

  const row = run.data;
  const a = row.analysis;
  const active = a?.status === "queued" || a?.status === "running";
  const label = analysisActionLabel(row);
  return (
    <>
      {back}
      <PageHeader
        title={`${row.name ?? "Workflow"} #${row.run_number ?? "?"}`}
        description={`${row.repository} · ${row.branch ?? "unknown branch"} · ${row.event ?? "unknown event"} · updated ${ago(row.updated_at)}`}
        actions={
          <>
            <Badge tone={conclusionTone(row.conclusion)}>{row.conclusion ?? row.status ?? "unknown"}</Badge>
            {row.html_url && (
              <a
                href={row.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
              >
                Open on GitHub
              </a>
            )}
            {canAnalyze && row.analyzable && (
              <Button size="sm" variant="primary" disabled={active || start.isPending} onClick={() => start.mutate(label === "Re-run")}>
                {active ? "Analyzing…" : label}
              </Button>
            )}
          </>
        }
      />
      {start.isError && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the analysis."}
        </p>
      )}
      <Card>
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">AI analysis</h2>
        </div>
        {!row.analyzable ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            Only finished runs that failed or timed out can be analyzed. This run is {row.conclusion ?? row.status ?? "not finished"}.
          </p>
        ) : a ? (
          <CiPanel orgId={orgId} run={row} />
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            This run has not been analyzed.
            {canAnalyze ? " Click Analyze to start. It reads the job logs and uses AI tokens." : " Ask a member to start an analysis."}
          </p>
        )}
      </Card>
    </>
  );
}
