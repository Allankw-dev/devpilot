import { describe, expect, it } from "vitest";

import { pickWorkspace } from "@/lib/workspace";
import { ORG } from "./helpers";

const other = { ...ORG, id: "org-2", name: "Beta" };

describe("pickWorkspace", () => {
  it("uses the remembered workspace when you are still a member", () => {
    expect(pickWorkspace([ORG, other], "org-2")).toBe(other);
  });

  it("falls back to the first one when the remembered one is gone", () => {
    expect(pickWorkspace([ORG, other], "left-this-org")).toBe(ORG);
    expect(pickWorkspace([ORG, other], null)).toBe(ORG);
  });

  it("returns null when you have no workspace", () => {
    expect(pickWorkspace([], "org-1")).toBeNull();
  });
});
