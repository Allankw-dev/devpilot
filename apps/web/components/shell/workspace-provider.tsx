"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useMemo } from "react";

import { ApiError, authedApi, type Me, type OrgWithRole } from "@/lib/api";
import { accessToken } from "@/lib/supabase/token";
import { pickWorkspace, useWorkspaceStore } from "@/lib/workspace";

interface WorkspaceValue {
  me: Me;
  orgs: OrgWithRole[];
  org: OrgWithRole | null; // the selected workspace, null when you have none
  select: (orgId: string) => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function useWorkspace(): WorkspaceValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return value;
}

/** Loads who you are and which workspaces you have, and sends you to sign in if you aren't. */
export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const storedId = useWorkspaceStore((s) => s.orgId);
  const select = useWorkspaceStore((s) => s.select);

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => authedApi.me(await accessToken()),
    retry: (count, err) => !(err instanceof ApiError && err.status === 401) && count < 1,
  });

  const unauthenticated = me.error instanceof ApiError && me.error.status === 401;
  useEffect(() => {
    if (unauthenticated) router.push("/login");
  }, [unauthenticated, router]);

  const value = useMemo<WorkspaceValue | null>(() => {
    if (!me.data) return null;
    return {
      me: me.data,
      orgs: me.data.organizations,
      org: pickWorkspace(me.data.organizations, storedId),
      select,
    };
  }, [me.data, storedId, select]);

  if (unauthenticated) return null;
  if (me.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted-foreground" role="status">
        Loading your workspace…
      </div>
    );
  }
  if (me.isError || !value) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 px-6 text-center">
        <p role="alert" className="text-danger">
          {me.error instanceof Error ? me.error.message : "Couldn’t load your account."}
        </p>
        <button
          type="button"
          onClick={() => me.refetch()}
          className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
        >
          Try again
        </button>
      </div>
    );
  }
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}
