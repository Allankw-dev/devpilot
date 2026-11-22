import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsPage } from "@/components/analytics/analytics-page";
import { ApiError, type Analytics } from "@/lib/api";
import { ORG, renderWithQuery } from "./helpers";

const analyticsGet = vi.fn();
const usageGet = vi.fn();
let currentOrg: typeof ORG | null = ORG;

vi.mock("recharts", () => {
  const Box = ({ children }: { children?: React.ReactNode }) => <div data-testid="chart">{children}</div>;
  return { ResponsiveContainer: Box, BarChart: Box, Bar: Box, Cell: Box, CartesianGrid: Box, XAxis: Box, YAxis: Box, Tooltip: Box, Legend: Box };
});
vi.mock("@/components/usage-dashboard", () => ({
  UsageDashboard: ({ orgId }: { orgId: string }) => <div>ai usage details for {orgId}</div>,
}));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: currentOrg, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    analyticsApi: { get: (...a: unknown[]) => analyticsGet(...a) },
    aiApi: { ...actual.aiApi, usage: (...a: unknown[]) => usageGet(...a) },
  };
});

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

function analytics(over: Partial<Analytics> = {}): Analytics {
  return {
    days: 30, since: "2026-10-21",
    reviews_finished: 4, ci_analyses_finished: 2, runs_succeeded: 8, runs_failed: 2, ci_success_rate: 0.8,
    avg_review_seconds: 95, avg_ci_analysis_seconds: 12,
    findings_by_severity: SEVERITIES.map((severity, i) => ({ severity, count: i })),
    by_day: [{ day: "2026-11-18", reviews_finished: 1, ci_analyses_finished: 1, runs_succeeded: 3, runs_failed: 1 }],
    ...over,
  };
}
const USAGE = { input_tokens: 1000, output_tokens: 500, provider_calls: 12, by_day: [{ day: "2026-11-18", input_tokens: 1000, output_tokens: 500 }] };

beforeEach(() => {
  currentOrg = ORG;
  analyticsGet.mockReset();
  usageGet.mockReset().mockResolvedValue(USAGE);
});

describe("<AnalyticsPage>", () => {
  it("asks you to create a workspace first when you have none", () => {
    currentOrg = null;
    renderWithQuery(<AnalyticsPage />);
    expect(screen.getByText(/Create a workspace on the dashboard first/)).toBeInTheDocument();
    expect(analyticsGet).not.toHaveBeenCalled();
  });

  it("shows the real numbers: success rate, counts, average times and tokens", async () => {
    analyticsGet.mockResolvedValue(analytics());
    renderWithQuery(<AnalyticsPage />);
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(within(summary).getByText("80%")).toBeInTheDocument();
    expect(summary).toHaveTextContent("8 passed, 2 failed");
    expect(summary).toHaveTextContent("AI reviews finished");
    expect(summary).toHaveTextContent("avg 1 min 35 s");
    expect(summary).toHaveTextContent("avg 12 s");
    await waitFor(() => expect(summary).toHaveTextContent("1,500")); // 1000 + 500 tokens
    expect(summary).toHaveTextContent("12 provider calls");
    expect(analyticsGet).toHaveBeenCalledWith("token", "org-1", 30);
  });

  it("says n/a rather than inventing a rate or time when there is nothing to measure", async () => {
    analyticsGet.mockResolvedValue(
      analytics({ ci_success_rate: null, avg_review_seconds: null, avg_ci_analysis_seconds: null, runs_succeeded: 0, runs_failed: 0 }),
    );
    renderWithQuery(<AnalyticsPage />);
    const summary = await screen.findByRole("region", { name: "Summary" });
    expect(summary).toHaveTextContent("n/a");
    expect(summary).not.toHaveTextContent("0%");
    expect(summary).toHaveTextContent("avg n/a");
  });

  it("explains charts that have no data", async () => {
    analyticsGet.mockResolvedValue(
      analytics({
        reviews_finished: 0, ci_analyses_finished: 0, runs_succeeded: 0, runs_failed: 0,
        findings_by_severity: SEVERITIES.map((severity) => ({ severity, count: 0 })),
        by_day: [{ day: "2026-11-18", reviews_finished: 0, ci_analyses_finished: 0, runs_succeeded: 0, runs_failed: 0 }],
      }),
    );
    usageGet.mockResolvedValue({ ...USAGE, input_tokens: 0, output_tokens: 0, by_day: [{ day: "2026-11-18", input_tokens: 0, output_tokens: 0 }] });
    renderWithQuery(<AnalyticsPage />);
    expect(await screen.findByText(/No finished reviews or analyses in the last 30 days/)).toBeInTheDocument();
    expect(screen.getByText(/No finished CI runs in the last 30 days/)).toBeInTheDocument();
    expect(screen.getByText(/No review findings in the last 30 days/)).toBeInTheDocument();
    expect(await screen.findByText(/No AI requests in the last 30 days/)).toBeInTheDocument();
    expect(screen.queryByTestId("chart")).not.toBeInTheDocument();
  });

  it("describes the severity chart in words for screen readers", async () => {
    analyticsGet.mockResolvedValue(analytics());
    renderWithQuery(<AnalyticsPage />);
    expect(
      await screen.findByRole("img", { name: "Bar chart of review findings by severity: critical 0, high 1, medium 2, low 3, info 4" }),
    ).toBeInTheDocument();
  });

  it("reloads for the period you pick", async () => {
    analyticsGet.mockResolvedValue(analytics());
    const user = userEvent.setup();
    renderWithQuery(<AnalyticsPage />);
    await screen.findByRole("region", { name: "Summary" });
    await user.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() => expect(analyticsGet).toHaveBeenCalledWith("token", "org-1", 7));
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
    expect(usageGet).toHaveBeenCalledWith("token", "org-1", 7);
  });

  it("includes the detailed AI usage: calls, quota status, features and models", async () => {
    analyticsGet.mockResolvedValue(analytics());
    renderWithQuery(<AnalyticsPage />);
    expect(await screen.findByText("ai usage details for org-1")).toBeInTheDocument();
  });

  it("says these are activity counts, not productivity", async () => {
    analyticsGet.mockResolvedValue(analytics());
    renderWithQuery(<AnalyticsPage />);
    expect(await screen.findByText(/not a measure of developer productivity/)).toBeInTheDocument();
  });

  it("shows the server's message, or a generic one, when it can't load", async () => {
    analyticsGet.mockRejectedValueOnce(new ApiError("Organization not found", 404));
    const { unmount } = renderWithQuery(<AnalyticsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Organization not found");
    unmount();
    analyticsGet.mockRejectedValueOnce(new Error("internal detail"));
    renderWithQuery(<AnalyticsPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t load analytics.");
    expect(alert).not.toHaveTextContent("internal detail");
  });
});
