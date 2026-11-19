"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { IndexCell } from "@/components/index-cell";
import { Card, CardHeader } from "@/components/ui/card";
import { ApiError, codeApi, type Repo } from "@/lib/api";
import { ago } from "@/lib/format";
import { CI_LABEL } from "@/lib/labels";
import { accessToken } from "@/lib/supabase/token";
import { cn } from "@/lib/utils";

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{children}</p>
    </div>
  );
}

export function RepoOverview({ orgId, repo, canIndex }: { orgId: string; repo: Repo; canIndex: boolean }) {
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: async () => codeApi.startIndex(await accessToken(), orgId, repo.id),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["org", orgId, "repos"] }),
  });
  const ci = CI_LABEL[repo.ci];
  return (
    <div className="space-y-6">
      <section aria-label="Repository facts" className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Fact label="Open pull requests">{repo.open_pull_requests}</Fact>
        <Fact label="Open issues">{repo.open_issues}</Fact>
        <Fact label="CI on the default branch">
          <span className={cn(ci.cls)}>{ci.text}</span>
        </Fact>
        <Fact label="Default branch">
          <span className="font-mono text-base">{repo.default_branch ?? "n/a"}</span>
        </Fact>
        <Fact label="Main language">{repo.language ?? "n/a"}</Fact>
        <Fact label="Last commit">
          <span className="text-base">{ago(repo.last_commit_at)}</span>
        </Fact>
        <Fact label="Last push">
          <span className="text-base">{ago(repo.pushed_at)}</span>
        </Fact>
        <Fact label="Visibility">
          <span className="text-base">{repo.private ? "Private" : "Public"}</span>
        </Fact>
      </section>

      <Card>
        <CardHeader
          title="Code index"
          description="Lets the AI search and answer questions about this repository. Secrets and build output are skipped."
        />
        <div className="px-4 py-4 text-sm">
          <IndexCell repo={repo} canIndex={canIndex} busy={start.isPending} onStart={() => start.mutate()} />
          {start.isError && (
            <p role="alert" className="mt-2 text-sm text-danger">
              {start.error instanceof ApiError ? start.error.message : "Could not start indexing."}
            </p>
          )}
        </div>
      </Card>
    </div>
  );
}
