import { describe, expect, it } from "vitest";

import { assignableRoles, canManageMember, isAdmin, ROLE_HELP, ROLE_LABEL } from "@/lib/roles";

describe("assignableRoles", () => {
  it("lets owners grant anything, admins only member or viewer, and others nothing", () => {
    expect(assignableRoles("owner")).toEqual(["viewer", "member", "admin", "owner"]);
    expect(assignableRoles("admin")).toEqual(["viewer", "member"]);
    expect(assignableRoles("member")).toEqual([]);
    expect(assignableRoles("viewer")).toEqual([]);
    expect(assignableRoles(undefined)).toEqual([]);
  });
});

describe("canManageMember", () => {
  it("lets owners manage everyone", () => {
    for (const role of ["viewer", "member", "admin", "owner"] as const) expect(canManageMember("owner", role)).toBe(true);
  });

  it("keeps admins away from admins and owners", () => {
    expect(canManageMember("admin", "viewer")).toBe(true);
    expect(canManageMember("admin", "member")).toBe(true);
    expect(canManageMember("admin", "admin")).toBe(false);
    expect(canManageMember("admin", "owner")).toBe(false);
  });

  it("gives members, viewers and strangers no power over anyone", () => {
    for (const actor of ["member", "viewer", undefined] as const) {
      for (const role of ["viewer", "member", "admin", "owner"] as const) expect(canManageMember(actor, role)).toBe(false);
    }
  });
});

describe("labels", () => {
  it("has a label and a description for every role", () => {
    for (const role of ["viewer", "member", "admin", "owner"] as const) {
      expect(ROLE_LABEL[role]).toBeTruthy();
      expect(ROLE_HELP[role]).toBeTruthy();
    }
  });

  it("knows who is an admin", () => {
    expect(isAdmin("owner")).toBe(true);
    expect(isAdmin("admin")).toBe(true);
    expect(isAdmin("member")).toBe(false);
    expect(isAdmin(undefined)).toBe(false);
  });
});
