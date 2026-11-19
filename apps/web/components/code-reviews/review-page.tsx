"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { reviewActionLabel } from "@/components/code-reviews/review-list";
import { PageHeader } from "@/components/page-header";
import { ReviewBadge } from "@/components/review-badge";
import { ReviewPanel } from "@/components/review-panel";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ApiError, reviewApi } from "@/lib/api";
import { ago } from "@/lib/format";
import { canWrite } from "@/lib/labels";
import { accessToken } from "@/lib/supabase/token";

export function ReviewPage({ prId }: { prId: string }) {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const queryClient = useQueryClient();
  const canReview = canWrite(org?.role);

  const pr = useQuery({
    queryKey: ["org", orgId, "pull-request", prId],
    queryFn: async () => reviewApi.pull(await accessToken(), orgId, prId),
    enabled: !!org,
    refetchInterval: (q) =>
      q.state.data?.review?.status === "queued" || q.state.data?.review?.status === "running" ? 3000 : false,
  });
  const start = useMutation({
    mutationFn: async (force: boolean) => reviewApi.start(await accessToken(), orgId, prId, force),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "pull-request", prId] });
      void queryClient.invalidateQueries({ queryKey: ["org", orgId, "pull-requests"] });
    },
  });

  const back = (
    <Link href="/code-reviews" className="mb-4 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" aria-hidden /> Code reviews
    </Link>
  );

  if (pr.isPending) return <p role="status" className="text-sm text-muted-foreground">Loading pull request…</p>;
  if (pr.isError || !pr.data) {
    const notFound = pr.error instanceof ApiError && pr.error.status === 404;
    return (
      <>
        {back}
        <p role="alert" className="text-sm text-danger">
          {notFound ? "Pull request not found in this workspace." : "Couldn’t load this pull request."}
        </p>
        {!notFound && (
          <Button size="sm" className="mt-2" onClick={() => pr.refetch()}>
            Try again
          </Button>
        )}
      </>
    );
  }

  const row = pr.data;
  const active = row.review?.status === "queued" || row.review?.status === "running";
  const label = reviewActionLabel(row);
  return (
    <>
      {back}
      <PageHeader
        title={row.title}
        description={`${row.repository} #${row.number} · ${row.author ?? "unknown"} · updated ${ago(row.updated_at)}`}
        actions={
          <>
            {row.draft && <Badge>draft</Badge>}
            {row.merged && <Badge tone="primary">merged</Badge>}
            {!row.merged && row.state === "closed" && <Badge>closed</Badge>}
            <a
              href={row.html_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-muted"
            >
              Open on GitHub
            </a>
            {canReview && (
              <Button size="sm" variant="primary" disabled={active || start.isPending} onClick={() => start.mutate(label === "Re-run")}>
                {active ? "Reviewing…" : label}
              </Button>
            )}
          </>
        }
      />
      {start.isError && (
        <p role="alert" className="mb-3 text-sm text-danger">
          {start.error instanceof ApiError ? start.error.message : "Could not start the review."}
        </p>
      )}
      <Card>
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">AI review</h2>
          <ReviewBadge row={row} />
        </div>
        {row.review ? (
          <ReviewPanel orgId={orgId} row={row} canEdit={canReview} />
        ) : (
          <p className="px-4 py-6 text-sm text-muted-foreground">
            This pull request has not been reviewed.
            {canReview ? " Click Review to start. It uses AI tokens." : " Ask a member to start a review."}
          </p>
        )}
      </Card>
    </>
  );
}
