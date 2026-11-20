"use client";

import { CiList } from "@/components/ci-cd/ci-list";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { canWrite } from "@/lib/labels";

export function CiIndex() {
  const { org } = useWorkspace();
  if (!org) {
    return (
      <>
        <PageHeader title="CI/CD" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="CI/CD"
        description="GitHub Actions runs, and AI explanations of why they failed, from their logs. Nothing is posted to GitHub and nothing is re-run."
      />
      <CiList orgId={org.id} canAnalyze={canWrite(org.role)} />
    </>
  );
}
