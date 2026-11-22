import { describe, expect, it } from "vitest";

import { NAV_ITEMS, titleFor } from "@/lib/nav";

const PAGES = [
  "/dashboard", "/repositories", "/repositories/r1", "/assistant", "/search", "/code-reviews", "/code-reviews/p1",
  "/ci-cd", "/ci-cd/r1", "/analytics", "/integrations", "/team", "/settings",
];

describe("navigation", () => {
  it("has unique ids, labels and links", () => {
    expect(new Set(NAV_ITEMS.map((i) => i.id)).size).toBe(NAV_ITEMS.length);
    expect(new Set(NAV_ITEMS.map((i) => i.label)).size).toBe(NAV_ITEMS.length);
    expect(new Set(NAV_ITEMS.map((i) => i.href)).size).toBe(NAV_ITEMS.length);
  });

  it("only links inside the app", () => {
    for (const item of NAV_ITEMS) expect(item.href.startsWith("/")).toBe(true);
  });

  it("marks exactly one item active for each page", () => {
    for (const path of PAGES) expect(NAV_ITEMS.filter((i) => i.match(path))).toHaveLength(1);
    expect(NAV_ITEMS.filter((i) => i.match("/somewhere-else"))).toHaveLength(0);
  });

  it("makes every item's own link active for itself", () => {
    for (const item of NAV_ITEMS) expect(item.match(item.href)).toBe(true);
  });

  it("no longer has the old Workspace page", () => {
    expect(NAV_ITEMS.some((i) => i.label === "Workspace")).toBe(false);
    expect(NAV_ITEMS.some((i) => i.match("/orgs/org-1"))).toBe(false);
  });

  it("names the current page for the breadcrumb", () => {
    expect(titleFor("/dashboard")).toBe("Dashboard");
    expect(titleFor("/repositories/r1")).toBe("Repositories");
    expect(titleFor("/assistant")).toBe("Assistant");
    expect(titleFor("/search")).toBe("Code Search");
    expect(titleFor("/code-reviews")).toBe("Code Reviews");
    expect(titleFor("/ci-cd/r1")).toBe("CI/CD");
    expect(titleFor("/analytics")).toBe("Analytics");
    expect(titleFor("/integrations")).toBe("Integrations");
    expect(titleFor("/team")).toBe("Team");
    expect(titleFor("/settings")).toBe("Settings");
    expect(titleFor("/nowhere")).toBe("");
  });
});
