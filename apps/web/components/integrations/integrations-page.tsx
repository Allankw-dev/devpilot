"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { AiPanel } from "@/components/ai-panel";
import { GithubPanel } from "@/components/github-panel";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { orgApi } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";

export function IntegrationsPage() {
  const { org } = useWorkspace();
  const orgId = org?.id ?? "";
  const isAdmin = org?.role === "owner" || org?.role === "admin";

  const github = useQuery({
    queryKey: ["org", orgId, "github"],
    queryFn: async () => orgApi.githubStatus(await accessToken(), orgId),
    enabled: !!org,
  });

  if (!org) {
    return (
      <>
        <PageHeader title="Integrations" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }

  const connected = (github.data?.installations.length ?? 0) > 0;
  return (
    <>
      <PageHeader
        title="Integrations"
        description="What DevPilot is connected to. Secret values are never shown here."
      />

      <Card className="px-4 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Permissions DevPilot asks GitHub for</h2>
          <Badge tone="success">read-only</Badge>
        </div>
        <p className="mt-2 text-sm text-muted-foreground">
          Repository metadata, contents, pull requests, issues, and Actions (workflow runs and logs). DevPilot never
          writes to GitHub. Details are in <code className="font-mono">docs/GITHUB.md</code>.
        </p>
      </Card>

      <GithubPanel orgId={orgId} isAdmin={isAdmin} />

      <section className="mt-10" aria-label="GitHub Actions">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-medium">GitHub Actions</h2>
          {github.isSuccess && <Badge tone={connected ? "success" : "neutral"}>{connected ? "available" : "needs GitHub"}</Badge>}
        </div>
        <p className="mt-3 text-sm text-muted-foreground">
          Workflow runs and their logs come through the GitHub connection above, so there is nothing separate to set up.
          The AI explains failed runs on the{" "}
          <Link href="/ci-cd" className="text-primary hover:underline">
            CI/CD page
          </Link>
          . If a log can’t be read, check that the GitHub app has the <em>Actions: read</em> permission.
        </p>
      </section>

      <AiPanel orgId={orgId} isAdmin={isAdmin} />
    </>
  );
}
