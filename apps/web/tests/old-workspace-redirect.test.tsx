import { describe, expect, it, vi } from "vitest";

const redirect = vi.fn();
vi.mock("next/navigation", () => ({ redirect: (...a: unknown[]) => redirect(...a) }));

describe("the old workspace page", () => {
  it("sends old links and bookmarks to the dashboard", async () => {
    const { default: OldWorkspacePage } = await import("@/app/(app)/orgs/[orgId]/page");
    OldWorkspacePage();
    expect(redirect).toHaveBeenCalledWith("/dashboard");
  });
});
