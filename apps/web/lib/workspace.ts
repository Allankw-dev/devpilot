import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { OrgWithRole } from "@/lib/api";

/** Which of your organizations is selected. Stored in this browser only. */
interface WorkspaceState {
  orgId: string | null;
  select: (orgId: string) => void;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set) => ({
      orgId: null,
      select: (orgId) => set({ orgId }),
    }),
    { name: "devpilot-workspace" },
  ),
);

/**
 * The organization to show: the remembered one if you are still a member of it, otherwise the
 * first one. Null when you are in none (a stored id for an organization you left is ignored).
 */
export function pickWorkspace(orgs: OrgWithRole[], storedId: string | null): OrgWithRole | null {
  return orgs.find((o) => o.id === storedId) ?? orgs[0] ?? null;
}
