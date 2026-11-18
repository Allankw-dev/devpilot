import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardHome } from "@/components/dashboard-home";
import { ApiError, type DashboardData } from "@/lib/api";
import { ME, ORG, renderWithQuery } from "./helpers";

let currentOrg: typeof ORG | null = ORG;
const dashboardGet = vi.fn();
const usageGet = vi.fn();
const createOrg = vi.fn();

vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div data-testid="chart">{children}</div>;
  return {
    ResponsiveContainer: Box, BarChart: Box, Bar: Box, CartesianGrid: Box,
    XAxis: Box, YAxis: Box, Tooltip: Box, Legend: Box,
  };
});
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: { ...ME }, orgs: currentOrg ? [currentOrg] : [], org: currentOrg, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    dashboardApi: { get: (...a: unknown[]) => dashboardGet(...a) },
    aiApi: { ...actual.aiApi, usage: (...a: unknown[]) => usageGet(...a) },
    authedApi: { ...actual.authedApi, createOrg: (...a: unknown[]) => createOrg(...a) },
  };
});

const EMPTY_USAGE = { by_day: [], calls_last_24h: 0, daily_limit: null };

function data(over: Partial<DashboardData> = {}): DashboardData {
  return {
    days: 14,
    since: "2026-11-05",
    github_connected: true,
    last_synced_at: new Date().toISOString(),
    stats: {
      repositories: 4, open_pull_requests: 2, open_issues: 3,
      reviews_completed: 5, ci_analyses_completed: 1, failed_runs: 2,
    },
    activity: [{ day: "2026-11-17", commits: 3, pull_requests_opened: 1 }],
    recent_pull_requests: [
      { id: "p1", repository: "acme/web", number: 7, title: "Fix login redirect", author: "ada",
        draft: false, html_url: "https://github.com/acme/web/pull/7", updated_at: new Date().toISOString() },
    ],
    recent_reviews: [
      { id: "r1", pull_request_id: "p1", repository: "acme/web", number: 7, title: "Fix login redirect",
        status: "ready", open_findings: 3, serious_findings: 1, finished_at: new Date().toISOString() },
    ],
    recent_failed_runs: [],
    open_issues: [],
    ...over,
  };
}

beforeEach(() => {
  currentOrg = ORG;
  dashboardGet.mockReset();
  usageGet.mockReset().mockResolvedValue(EMPTY_USAGE);
  createOrg.mockReset();
});

describe("<DashboardHome>", () => {
  it("asks you to create a workspace when you have none, and creates it", async () => {
    currentOrg = null;
    createOrg.mockResolvedValue({ id: "new" });
    const user = userEvent.setup();
    renderWithQuery(<DashboardHome />);
    expect(screen.getByText("Create your first workspace")).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled(); // a name is required
    await user.type(screen.getByLabelText("Workspace name"), "Acme");
    await user.click(create);
    await waitFor(() => expect(createOrg).toHaveBeenCalledWith("token", "Acme"));
    expect(dashboardGet).not.toHaveBeenCalled();
  });

  it("greets you by first name and shows the workspace", async () => {
    dashboardGet.mockResolvedValue(data());
    renderWithQuery(<DashboardHome />);
    expect(screen.getByRole("heading", { name: "Welcome back, Ada" })).toBeInTheDocument();
    expect(screen.getByText(/Acme · last 14 days/)).toBeInTheDocument();
  });

  it("shows a Connect GitHub call to action when nothing is connected", async () => {
    dashboardGet.mockResolvedValue(data({ github_connected: false }));
    renderWithQuery(<DashboardHome />);
    const cta = await screen.findByRole("link", { name: "Connect GitHub" });
    expect(cta).toHaveAttribute("href", "/orgs/org-1");
    expect(screen.queryByText("Repositories")).not.toBeInTheDocument(); // no fake numbers
  });

  it("shows the real numbers and lists", async () => {
    dashboardGet.mockResolvedValue(data());
    renderWithQuery(<DashboardHome />);
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("Repositories");
    expect(summary).toHaveTextContent("4");
    expect(summary).toHaveTextContent("AI reviews");
    expect(summary).toHaveTextContent("5");
    const pr = screen.getByRole("link", { name: "Fix login redirect" });
    expect(pr).toHaveAttribute("href", "https://github.com/acme/web/pull/7");
    expect(pr).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/3 open findings/)).toBeInTheDocument();
    expect(screen.getByText(/1 serious/)).toBeInTheDocument();
  });

  it("explains empty lists instead of leaving blanks", async () => {
    dashboardGet.mockResolvedValue(
      data({ recent_pull_requests: [], recent_reviews: [], activity: [{ day: "2026-11-17", commits: 0, pull_requests_opened: 0 }] }),
    );
    renderWithQuery(<DashboardHome />);
    expect(await screen.findByText("No open pull requests.")).toBeInTheDocument();
    expect(screen.getByText(/No AI reviews yet/)).toBeInTheDocument();
    expect(screen.getByText("No failed runs. Nice.")).toBeInTheDocument();
    expect(screen.getByText("No open issues.")).toBeInTheDocument();
    expect(screen.getByText(/No commits or pull requests in the last 14 days/)).toBeInTheDocument();
    expect(await screen.findByText(/No AI requests in the last 14 days/)).toBeInTheDocument();
  });

  it("shows a safe message for unexpected errors, with a retry button", async () => {
    dashboardGet.mockRejectedValueOnce(new Error("internal detail that should not be shown"));
    dashboardGet.mockResolvedValue(data());
    const user = userEvent.setup();
    renderWithQuery(<DashboardHome />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load the dashboard.");
    expect(alert).not.toHaveTextContent("internal detail");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("region", { name: "Summary" })).toBeInTheDocument();
  });

  it("shows the server's own message when the API explains the problem", async () => {
    dashboardGet.mockRejectedValue(new ApiError("Organization not found", 404));
    renderWithQuery(<DashboardHome />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Organization not found");
  });

  it("reloads for the period you pick", async () => {
    dashboardGet.mockResolvedValue(data());
    const user = userEvent.setup();
    renderWithQuery(<DashboardHome />);
    await screen.findByRole("region", { name: "Summary" });
    await user.click(screen.getByRole("button", { name: "30 days" }));
    await waitFor(() => expect(dashboardGet).toHaveBeenCalledWith("token", "org-1", 30));
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
  });
});
