import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RepoList } from "@/components/repositories/repo-list";
import { ORG, renderWithQuery, repo } from "./helpers";

const reposGet = vi.fn();
let currentOrg: typeof ORG | null = ORG;

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: currentOrg, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => reposGet(...a) } };
});

beforeEach(() => {
  currentOrg = ORG;
  reposGet.mockReset();
});

const many = Array.from({ length: 12 }, (_, i) => repo({ id: `r${i}`, full_name: `acme/repo-${String(i).padStart(2, "0")}` }));

describe("<RepoList>", () => {
  it("asks you to create a workspace first when you have none", () => {
    currentOrg = null;
    renderWithQuery(<RepoList />);
    expect(screen.getByText(/Create a workspace on the dashboard first/)).toBeInTheDocument();
    expect(reposGet).not.toHaveBeenCalled();
  });

  it("shows a Connect GitHub call to action when there are no repositories", async () => {
    reposGet.mockResolvedValue([]);
    renderWithQuery(<RepoList />);
    expect(await screen.findByText("No repositories yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect GitHub" })).toHaveAttribute("href", "/orgs/org-1");
  });

  it("lists repositories with links to their pages and real details", async () => {
    reposGet.mockResolvedValue([
      repo({ id: "a", full_name: "acme/web", private: true, ci: "failing", open_pull_requests: 5, index: { ...repo().index, status: "ready" } }),
    ]);
    renderWithQuery(<RepoList />);
    const link = await screen.findByRole("link", { name: "acme/web" });
    expect(link).toHaveAttribute("href", "/repositories/a");
    const row = link.closest("tr")!;
    expect(within(row).getByText("private")).toBeInTheDocument();
    expect(within(row).getByText("Failing")).toBeInTheDocument();
    expect(within(row).getByText("Indexed")).toBeInTheDocument();
    expect(within(row).getByText("TypeScript")).toBeInTheDocument();
    expect(within(row).getByText("5")).toBeInTheDocument();
  });

  it("searches by name or description", async () => {
    reposGet.mockResolvedValue([
      repo({ id: "a", full_name: "acme/web", description: "Customer portal" }),
      repo({ id: "b", full_name: "acme/api", description: "Billing service" }),
    ]);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/web" });
    await user.type(screen.getByLabelText("Search repositories"), "billing");
    expect(screen.queryByRole("link", { name: "acme/web" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "acme/api" })).toBeInTheDocument();
  });

  it("filters by language and CI status, and clears the filters", async () => {
    reposGet.mockResolvedValue([
      repo({ id: "a", full_name: "acme/web", language: "TypeScript", ci: "passing" }),
      repo({ id: "b", full_name: "acme/api", language: "Python", ci: "failing" }),
    ]);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/web" });
    await user.selectOptions(screen.getByLabelText("Language"), "Python");
    expect(screen.queryByRole("link", { name: "acme/web" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await user.selectOptions(screen.getByLabelText("CI status"), "passing");
    expect(screen.queryByRole("link", { name: "acme/api" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "acme/web" })).toBeInTheDocument();
  });

  it("hides archived repositories until you ask, and says how many are hidden", async () => {
    reposGet.mockResolvedValue([repo({ id: "a", full_name: "acme/web" }), repo({ id: "b", full_name: "acme/old", archived: true })]);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/web" });
    expect(screen.queryByRole("link", { name: "acme/old" })).not.toBeInTheDocument();
    await user.click(screen.getByLabelText(/Show archived \(1 hidden\)/));
    expect(screen.getByRole("link", { name: "acme/old" })).toBeInTheDocument();
    expect(screen.getByText("archived")).toBeInTheDocument();
  });

  it("explains when nothing matches", async () => {
    reposGet.mockResolvedValue([repo()]);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/web" });
    await user.type(screen.getByLabelText("Search repositories"), "nothing like this");
    expect(screen.getByText("No repositories match these filters.")).toBeInTheDocument();
  });

  it("pages through long lists ten at a time", async () => {
    reposGet.mockResolvedValue(many);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/repo-00" });
    expect(screen.getAllByRole("link", { name: /acme\/repo-/ })).toHaveLength(10);
    expect(screen.getByText("Page 1 of 2 · 12 total")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getAllByRole("link", { name: /acme\/repo-/ })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("goes back to the first page when a filter changes", async () => {
    reposGet.mockResolvedValue(many);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    await screen.findByRole("link", { name: "acme/repo-00" });
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.type(screen.getByLabelText("Search repositories"), "repo-0");
    expect(screen.getByText(/Page 1 of 1|10 total/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "acme/repo-00" })).toBeInTheDocument();
  });

  it("shows an error with a retry", async () => {
    reposGet.mockRejectedValueOnce(new Error("boom"));
    reposGet.mockResolvedValue([repo()]);
    const user = userEvent.setup();
    renderWithQuery(<RepoList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load repositories.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "acme/web" })).toBeInTheDocument();
  });
});
