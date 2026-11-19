"use client";

import { ReviewList } from "@/components/code-reviews/review-list";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";
import { canWrite } from "@/lib/labels";

export function ReviewIndex() {
  const { org } = useWorkspace();
  if (!org) {
    return (
      <>
        <PageHeader title="Code reviews" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }
  return (
    <>
      <PageHeader
        title="Code reviews"
        description="AI review of pull requests: bugs, security risks and missing error handling, with file and line. Nothing is posted to GitHub."
      />
      <ReviewList orgId={org.id} canReview={canWrite(org.role)} />
    </>
  );
}
