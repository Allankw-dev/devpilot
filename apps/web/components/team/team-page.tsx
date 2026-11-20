"use client";

import { MembersCard } from "@/components/team/members-card";
import { TeamsCard } from "@/components/team/teams-card";
import { PageHeader } from "@/components/page-header";
import { useWorkspace } from "@/components/shell/workspace-provider";

export function TeamPage() {
  const { org } = useWorkspace();
  if (!org) {
    return (
      <>
        <PageHeader title="Team" />
        <p className="text-sm text-muted-foreground">Create a workspace on the dashboard first.</p>
      </>
    );
  }
  return (
    <>
      <PageHeader title="Team" description={`Members and teams in ${org.name}.`} />
      <div className="space-y-6">
        <MembersCard orgId={org.id} />
        <TeamsCard orgId={org.id} />
      </div>
    </>
  );
}
