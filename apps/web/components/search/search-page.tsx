"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { CodeSearch } from "@/components/code-search";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { orgApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

export function SearchPage() {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const repos = useQuery({
    queryKey: ["org", orgId, "repos"],
    queryFn: async () => orgApi.repos(await accessToken(), orgId),
    enabled: !!org,
  });

  if (!org) {
    return (
      <>
        <PageHeader title="Code search" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }

  const indexed = (repos.data ?? []).filter((r) => r.index.status === "ready" && r.index.chunks > 0);
  return (
    <>
      <PageHeader
        title="Code search"
        description="Find code by meaning, not just by words. Searches the repositories you have indexed."
      />
      {repos.isPending && <p role="status" className="text-sm text-muted-foreground">Loading…</p>}
      {repos.isError && (
        <p role="alert" className="text-sm text-danger">
          Couldn’t load your repositories.
        </p>
      )}
      {repos.isSuccess && indexed.length === 0 && (
        <Card className="mx-auto max-w-xl p-8 text-center">
          <h2 className="text-lg font-semibold">Index a repository to search it</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Search works on indexed code. Secrets and build output are skipped.
          </p>
          <Link href="/repositories" className={`${buttonVariants({ variant: "primary" })} mt-5`}>
            Go to repositories
          </Link>
        </Card>
      )}
      {repos.isSuccess && indexed.length > 0 && <CodeSearch orgId={orgId} repos={repos.data} />}
    </>
  );
}
