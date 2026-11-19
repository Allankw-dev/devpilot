import { FolderGit2, GitBranch, GitPullRequest, LayoutDashboard, type LucideIcon } from "lucide-react";

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Where it goes. `null` means you have no workspace yet, so it can't be opened. */
  href: (orgId: string | null) => string | null;
  match: (pathname: string) => boolean;
}

/**
 * Only pages that work today are listed. New sections (tests, issues, documentation, ...) are
 * added here when their feature exists, never as empty placeholders.
 */
export const NAV_ITEMS: NavItem[] = [
  {
    id: "dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    href: () => "/dashboard",
    match: (p) => p === "/dashboard",
  },
  {
    id: "repositories",
    label: "Repositories",
    icon: GitBranch,
    href: () => "/repositories",
    match: (p) => p === "/repositories" || p.startsWith("/repositories/"),
  },
  {
    id: "code-reviews",
    label: "Code Reviews",
    icon: GitPullRequest,
    href: () => "/code-reviews",
    match: (p) => p === "/code-reviews" || p.startsWith("/code-reviews/"),
  },
  {
    id: "workspace",
    label: "Workspace",
    icon: FolderGit2,
    href: (orgId) => (orgId ? `/orgs/${orgId}` : null),
    match: (p) => p === "/orgs" || p.startsWith("/orgs/"),
  },
];

/** The title for the top bar's breadcrumb. */
export function titleFor(pathname: string): string {
  return NAV_ITEMS.find((item) => item.match(pathname))?.label ?? "";
}
