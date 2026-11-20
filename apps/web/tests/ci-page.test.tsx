import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CiPage } from "@/components/ci-cd/ci-page";
import { ApiError } from "@/lib/api";
import { ORG, renderWithQuery, run } from "./helpers";

const getRun = vi.fn();
const start = vi.fn();
let role: "owner" | "viewer" = "owner";

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/components/ci-panel", () => ({ CiPanel: () => <div>analysis panel</div> }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, ciApi: { ...actual.ciApi, run: (...a: unknown[]) => getRun(...a), start: (...a: unknown[]) => start(...a) } };
});

const analysis = { id: "a1", status: "ready" as const, category: "test_failure" as const, confidence: "high" as const,
  finished_at: new Date().toISOString(), stale: false, error: null };

beforeEach(() => {
  role = "owner";
  getRun.mockReset();
  start.mockReset().mockResolvedValue({});
});

describe("<CiPage>", () => {
  it("shows the run, its outcome, a GitHub link and the analysis", async () => {
    getRun.mockResolvedValue(run({ analysis }));
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByRole("heading", { name: "CI #7" })).toBeInTheDocument();
    expect(screen.getByText("failure")).toBeInTheDocument();
    expect(screen.getByText(/acme\/web · main · push/)).toBeInTheDocument();
    expect(screen.getByText("analysis panel")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByRole("link", { name: /CI\/CD/ })).toHaveAttribute("href", "/ci-cd");
    expect(getRun).toHaveBeenCalledWith("token", "org-1", "run-1");
  });

  it("says a run that has not been analyzed has no analysis, and lets a member start one", async () => {
    getRun.mockResolvedValue(run());
    const user = userEvent.setup();
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByText(/has not been analyzed/)).toBeInTheDocument();
    expect(screen.getByText(/uses AI tokens/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "run-1", false));
  });

  it("explains why a run that did not fail can't be analyzed", async () => {
    getRun.mockResolvedValue(run({ conclusion: "success", analyzable: false }));
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByText(/Only finished runs that failed or timed out can be analyzed/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Analyze|Re-run|Retry/ })).not.toBeInTheDocument();
  });

  it("is read-only for viewers", async () => {
    role = "viewer";
    getRun.mockResolvedValue(run());
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByText(/Ask a member to start an analysis/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Analyze" })).not.toBeInTheDocument();
  });

  it("disables the button while it runs", async () => {
    getRun.mockResolvedValue(run({ analysis: { ...analysis, status: "running" } }));
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByRole("button", { name: "Analyzing…" })).toBeDisabled();
  });

  it("handles a run from another workspace and other errors", async () => {
    getRun.mockRejectedValueOnce(new ApiError("Workflow run not found", 404));
    const { unmount } = renderWithQuery(<CiPage runId="nope" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Run not found in this workspace.");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    unmount();

    getRun.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(run());
    const user = userEvent.setup();
    renderWithQuery(<CiPage runId="run-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load this run.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "CI #7" })).toBeInTheDocument();
  });

  it("shows why an analysis couldn't start", async () => {
    getRun.mockResolvedValue(run());
    start.mockRejectedValue(new ApiError("An analysis of this run is already in progress", 409));
    const user = userEvent.setup();
    renderWithQuery(<CiPage runId="run-1" />);
    await user.click(await screen.findByRole("button", { name: "Analyze" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already in progress");
  });
});
