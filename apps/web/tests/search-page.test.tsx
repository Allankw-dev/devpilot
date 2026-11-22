import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SearchPage } from "@/components/search/search-page";
import { ORG, renderWithQuery, repo } from "./helpers";

const repos = vi.fn();
let hasOrg = true;

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: hasOrg ? ORG : null, select: vi.fn() }),
}));
vi.mock("@/components/code-search", () => ({
  CodeSearch: ({ repos: r }: { repos: unknown[] }) => <div>search box for {r.length} repos</div>,
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => repos(...a) } };
});

const ready = { ...repo().index, status: "ready" as const, chunks: 40 };

beforeEach(() => {
  hasOrg = true;
  repos.mockReset();
});

describe("<SearchPage>", () => {
  it("asks you to create a workspace first when you have none", () => {
    hasOrg = false;
    renderWithQuery(<SearchPage />);
    expect(screen.getByText(/Create a workspace on the dashboard first/)).toBeInTheDocument();
    expect(repos).not.toHaveBeenCalled();
  });

  it("shows the search box once something is indexed", async () => {
    repos.mockResolvedValue([repo({ id: "a", index: ready }), repo({ id: "b" })]);
    renderWithQuery(<SearchPage />);
    expect(await screen.findByText("search box for 2 repos")).toBeInTheDocument();
  });

  it("sends you to index a repository when nothing is searchable", async () => {
    repos.mockResolvedValue([repo(), repo({ id: "b", index: { ...ready, chunks: 0 } })]);
    renderWithQuery(<SearchPage />);
    expect(await screen.findByText("Index a repository to search it")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to repositories" })).toHaveAttribute("href", "/repositories");
    expect(screen.queryByText(/search box for/)).not.toBeInTheDocument();
  });

  it("shows an error when repositories can't load", async () => {
    repos.mockRejectedValue(new Error("boom"));
    renderWithQuery(<SearchPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load your repositories.");
  });
});
