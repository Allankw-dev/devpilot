import { describe, expect, it } from "vitest";

import { NAV_ITEMS, titleFor } from "@/lib/nav";

describe("navigation", () => {
  it("has unique ids and labels", () => {
    expect(new Set(NAV_ITEMS.map((i) => i.id)).size).toBe(NAV_ITEMS.length);
    expect(new Set(NAV_ITEMS.map((i) => i.label)).size).toBe(NAV_ITEMS.length);
  });

  it("only links inside the app", () => {
    for (const item of NAV_ITEMS) {
      const href = item.href("org-1");
      expect(href === null || href.startsWith("/")).toBe(true);
    }
  });

  it("can't open the workspace page before you have a workspace", () => {
    const workspace = NAV_ITEMS.find((i) => i.id === "workspace");
    expect(workspace?.href(null)).toBeNull();
    expect(workspace?.href("org-1")).toBe("/orgs/org-1");
  });

  it("marks exactly one item active for each page", () => {
    for (const path of ["/dashboard", "/orgs/org-1", "/repositories", "/repositories/r1", "/code-reviews", "/code-reviews/p1", "/ci-cd", "/ci-cd/r1", "/analytics", "/integrations"]) {
      expect(NAV_ITEMS.filter((i) => i.match(path))).toHaveLength(1);
    }
    expect(NAV_ITEMS.filter((i) => i.match("/somewhere-else"))).toHaveLength(0);
  });

  it("names the current page for the breadcrumb", () => {
    expect(titleFor("/dashboard")).toBe("Dashboard");
    expect(titleFor("/orgs/org-1")).toBe("Workspace");
    expect(titleFor("/repositories/r1")).toBe("Repositories");
    expect(titleFor("/code-reviews")).toBe("Code Reviews");
    expect(titleFor("/ci-cd/r1")).toBe("CI/CD");
    expect(titleFor("/analytics")).toBe("Analytics");
    expect(titleFor("/integrations")).toBe("Integrations");
    expect(titleFor("/nowhere")).toBe("");
  });
});
