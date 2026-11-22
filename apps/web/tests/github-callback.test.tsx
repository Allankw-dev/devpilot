import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GithubCallback } from "@/components/github-callback";
import { useWorkspaceStore } from "@/lib/workspace";

const claim = vi.fn();
const replace = vi.fn();
let query = "";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(query),
}));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, orgApi: { ...actual.orgApi, claim: (...a: unknown[]) => claim(...a) } };
});

beforeEach(() => {
  query = "";
  claim.mockReset();
  replace.mockReset();
  useWorkspaceStore.setState({ orgId: null });
});

describe("<GithubCallback>", () => {
  it("finishes connecting, selects that workspace and opens Integrations", async () => {
    query = "code=abc&installation_id=777&state=xyz";
    claim.mockResolvedValue({ org_id: "org-7" });
    render(<GithubCallback />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/integrations"));
    expect(claim).toHaveBeenCalledWith("token", { code: "abc", installation_id: 777, state: "xyz" });
    expect(useWorkspaceStore.getState().orgId).toBe("org-7");
  });

  it("explains a request that is waiting for GitHub organization owners", () => {
    query = "setup_action=request";
    render(<GithubCallback />);
    expect(screen.getByRole("status")).toHaveTextContent("Once they approve it, connect again from the Integrations page.");
    expect(claim).not.toHaveBeenCalled();
  });

  it("refuses a link with missing information without calling the server", () => {
    query = "installation_id=oops";
    render(<GithubCallback />);
    expect(screen.getByRole("alert")).toHaveTextContent("missing information from GitHub");
    expect(claim).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("shows the server's reason when claiming fails, and stays put", async () => {
    query = "code=abc&installation_id=777";
    claim.mockRejectedValue(new Error("The installation does not belong to you"));
    render(<GithubCallback />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not belong to you");
    expect(replace).not.toHaveBeenCalled();
    expect(useWorkspaceStore.getState().orgId).toBeNull();
  });

  it("only uses the one-time code once", async () => {
    query = "code=abc&installation_id=777";
    claim.mockResolvedValue({ org_id: "org-7" });
    const { rerender } = render(<GithubCallback />);
    rerender(<GithubCallback />);
    await waitFor(() => expect(replace).toHaveBeenCalled());
    expect(claim).toHaveBeenCalledTimes(1);
  });
});
