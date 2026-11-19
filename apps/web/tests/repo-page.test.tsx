import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepoPage } from "@/components/repositories/repo-page";
import { ORG, pull, renderWithQuery, repo } from "./helpers";

const reposGet = vi.fn();
const commits = vi.fn();
const issues = vi.fn();
const startIndex = vi.fn();
const pulls = vi.fn();
let search = "";
let role: "owner" | "viewer" = "owner";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(search) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => reposGet(...a) },
    codeApi: { ...actual.codeApi, startIndex: (...a: unknown[]) => startIndex(...a) },
    repoApi: { commits: (...a: unknown[]) => commits(...a) },
    issueApi: { list: (...a: unknown[]) => issues(...a) },
    reviewApi: { ...actual.reviewApi, list: (...a: unknown[]) => pulls(...a) },
  };
});

beforeEach(() => {
  search = "";
  role = "owner";
  reposGet.mockReset().mockResolvedValue([repo({ id: "repo-1" }), repo({ id: "repo-2", full_name: "acme/api" })]);
  commits.mockReset().mockResolvedValue([]);
  issues.mockReset().mockResolvedValue([]);
  pulls.mockReset().mockResolvedValue([]);
  startIndex.mockReset().mockResolvedValue({});
});

describe("<RepoPage>", () => {
  it("shows the repository's name, description and facts from real data", async () => {
    reposGet.mockResolvedValue([repo({ id: "repo-1", private: true, language: "Go", default_branch: "trunk", open_issues: 9 })]);
    renderWithQuery(<RepoPage repoId="repo-1" />);
    expect(await screen.findByRole("heading", { name: "acme/web" })).toBeInTheDocument();
    expect(screen.getByText("The web app")).toBeInTheDocument();
    expect(screen.getByText("private")).toBeInTheDocument();
    expect(screen.getByText("Go")).toBeInTheDocument();
    expect(screen.getByText("trunk")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("href", "https://github.com/acme/web");
    expect(screen.getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("has bookmarkable tabs with counts and marks the current one", async () => {
    renderWithQuery(<RepoPage repoId="repo-1" />);
    await screen.findByRole("heading", { name: "acme/web" });
    const nav = screen.getByRole("navigation", { name: "Repository sections" });
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/repositories/repo-1");
    expect(screen.getByRole("link", { name: /Commits/ })).toHaveAttribute("href", "/repositories/repo-1?tab=commits");
    expect(nav).toHaveTextContent("Pull requests2");
    expect(nav).toHaveTextContent("Issues3");
  });

  it("falls back to the overview for an unknown tab", async () => {
    search = "tab=nonsense";
    renderWithQuery(<RepoPage repoId="repo-1" />);
    await screen.findByRole("heading", { name: "acme/web" });
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");
  });

  it("says when the repository isn't in this workspace", async () => {
    renderWithQuery(<RepoPage repoId="someone-elses" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Repository not found in this workspace.");
    expect(screen.getByRole("link", { name: /Repositories/ })).toHaveAttribute("href", "/repositories");
  });

  it("lets members start indexing from the overview", async () => {
    const user = userEvent.setup();
    renderWithQuery(<RepoPage repoId="repo-1" />);
    await user.click(await screen.findByRole("button", { name: /Index/ }));
    await waitFor(() => expect(startIndex).toHaveBeenCalledWith("token", "org-1", "repo-1"));
  });

  it("doesn't offer indexing to viewers", async () => {
    role = "viewer";
    renderWithQuery(<RepoPage repoId="repo-1" />);
    await screen.findByRole("heading", { name: "acme/web" });
    expect(screen.queryByRole("button", { name: /Index/ })).not.toBeInTheDocument();
  });

  it("lists commits and loads more pages", async () => {
    search = "tab=commits";
    const page = Array.from({ length: 30 }, (_, i) => ({
      sha: `${i}`.padStart(40, "a"), message: `Commit ${i}`, author: "ada", repository: "acme/web",
      committed_at: new Date().toISOString(), url: `https://github.com/acme/web/commit/${i}`,
    }));
    commits.mockResolvedValueOnce(page).mockResolvedValueOnce([{ ...page[0], sha: "b".repeat(40), message: "Older commit" }]);
    const user = userEvent.setup();
    renderWithQuery(<RepoPage repoId="repo-1" />);
    expect(await screen.findByRole("link", { name: "Commit 0" })).toHaveAttribute("href", "https://github.com/acme/web/commit/0");
    expect(screen.getAllByText("aaaaaaa").length).toBeGreaterThan(0); // 7-character short hash
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Older commit")).toBeInTheDocument();
    expect(commits).toHaveBeenLastCalledWith("token", "org-1", "repo-1", { limit: 30, offset: 30 });
  });

  it("explains an empty commit list", async () => {
    search = "tab=commits";
    renderWithQuery(<RepoPage repoId="repo-1" />);
    expect(await screen.findByText(/No commits stored yet/)).toBeInTheDocument();
  });

  it("lists this repository's issues, filtered by state and search", async () => {
    search = "tab=issues";
    issues.mockResolvedValue([
      { id: "i1", repository_id: "repo-1", repository: "acme/web", number: 4, title: "Crash on login", state: "closed",
        author: "ada", comments: 1, html_url: "https://github.com/acme/web/issues/4",
        created_at: null, updated_at: new Date().toISOString() },
    ]);
    const user = userEvent.setup();
    renderWithQuery(<RepoPage repoId="repo-1" />);
    const item = (await screen.findByRole("link", { name: "Crash on login" })).closest("li")!;
    expect(within(item).getByText("closed")).toBeInTheDocument(); // the badge, not the filter button
    expect(within(item).getByText(/1 comment\b/)).toBeInTheDocument();
    expect(issues).toHaveBeenCalledWith("token", "org-1", "open", { repoId: "repo-1", q: "", limit: 30, offset: 0 });
    await user.click(screen.getByRole("button", { name: "closed" }));
    await waitFor(() => expect(issues).toHaveBeenLastCalledWith("token", "org-1", "closed", expect.anything()));
    await user.type(screen.getByLabelText("Search issues"), "crash");
    await waitFor(() => expect(issues).toHaveBeenLastCalledWith("token", "org-1", "closed", expect.objectContaining({ q: "crash" })));
  });

  it("shows this repository's pull requests with review actions", async () => {
    search = "tab=pulls";
    pulls.mockResolvedValue([pull({ repository_id: "repo-1" })]);
    renderWithQuery(<RepoPage repoId="repo-1" />);
    expect(await screen.findByRole("link", { name: "Fix login redirect" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review" })).toBeInTheDocument();
    expect(pulls).toHaveBeenCalledWith("token", "org-1", "open", expect.objectContaining({ repoId: "repo-1" }));
  });
});
