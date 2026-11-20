import type { Role } from "@/lib/api";

const RANK: Record<Role, number> = { viewer: 1, member: 2, admin: 3, owner: 4 };

export const ROLE_LABEL: Record<Role, string> = {
  viewer: "Viewer",
  member: "Member",
  admin: "Admin",
  owner: "Owner",
};

export const ROLE_HELP: Record<Role, string> = {
  viewer: "Can read everything. Cannot start AI work.",
  member: "Can start reviews, analyses and indexing.",
  admin: "Can also manage GitHub, members below admin, and teams.",
  owner: "Full control, including deleting the workspace.",
};

export const isAdmin = (role: Role | undefined): boolean => role === "admin" || role === "owner";

/**
 * The roles you may hand out. Owners can grant any; admins only member or viewer; others none.
 * The server enforces this too: this only hides choices that would be refused.
 */
export function assignableRoles(actor: Role | undefined): Role[] {
  if (actor === "owner") return ["viewer", "member", "admin", "owner"];
  if (actor === "admin") return ["viewer", "member"];
  return [];
}

/** Owners manage everyone. Admins manage only people below admin. Nobody else manages anyone. */
export function canManageMember(actor: Role | undefined, target: Role): boolean {
  if (actor === "owner") return true;
  if (actor === "admin") return RANK[target] < RANK.admin;
  return false;
}
