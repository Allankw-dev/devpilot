import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { analysisActionLabel, CiList, conclusionTone } from "@/components/ci-cd/ci-list";
import { ApiError, type CiRunRow } from "@/lib/api";
import { renderWithQuery, repo, run } from "./helpers";

const list = vi.fn();
const start = vi.fn();
const repos = vi.fn();

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => repos(...a) },
    ciApi: { ...actual.ciApi, list: (...a: unknown[]) => list(...a), start: (...a: unknown[]) => start(...a) },
  };
});

const analysis = (over: Partial<NonNullable<CiRunRow["analysis"]>> = {}): NonNullable<CiRunRow["analysis"]> => ({
  id: "a1", status: "ready", category: "test_failure", confidence: "high",
  finished_at: new Date().toISOString(), stale: false, error: null, ...over,
});

beforeEach(() => {
  list.mockReset().mockResolvedValue([]);
  start.mockReset().mockResolvedValue({});
  repos.mockReset().mockResolvedValue([repo({ id: "r1", full_name: "acme/web" }), repo({ id: "r2", full_name: "acme/api" })]);
});

describe("helpers", () => {
  it("names what the button will do", () => {
    expect(analysisActionLabel(run())).toBe("Analyze");
    expect(analysisActionLabel(run({ analysis: analysis({ status: "failed" }) }))).toBe("Retry");
    expect(analysisActionLabel(run({ analysis: analysis({ stale: true }) }))).toBe("Analyze again");
    expect(analysisActionLabel(run({ analysis: analysis() }))).toBe("Re-run");
  });

  it("colors outcomes", () => {
    expect(conclusionTone("failure")).toBe("danger");
    expect(conclusionTone("timed_out")).toBe("danger");
    expect(conclusionTone("success")).toBe("success");
    expect(conclusionTone("cancelled")).toBe("neutral");
    expect(conclusionTone(null)).toBe("neutral");
  });
});

describe("<CiList>", () => {
  it("lists runs with outcome, where they ran, and the AI result", async () => {
    list.mockResolvedValue([run({ analysis: analysis() }), run({ id: "run-2", run_number: 6, name: "Backend tests" })]);
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    const link = await screen.findByRole("link", { name: "CI #7" });
    expect(link).toHaveAttribute("href", "https://github.com/acme/web/actions/runs/7");
    const row = link.closest("li")!;
    expect(within(row).getByText("failure")).toBeInTheDocument();
    expect(within(row).getByText(/acme\/web · main · push/)).toBeInTheDocument();
    expect(within(row).getByText("Test failure")).toBeInTheDocument();
    expect(within(row).getByText(/high confidence/)).toBeInTheDocument();
    expect(screen.getByText("Not analyzed")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View analysis" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "View analysis" })).toHaveAttribute("href", "/ci-cd/run-1");
  });

  it("starts an analysis only on click; Re-run forces a fresh one", async () => {
    list.mockResolvedValue([run({ analysis: analysis() }), run({ id: "run-2", run_number: 6 })]);
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    await screen.findByRole("link", { name: "CI #6" });
    expect(start).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Analyze" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "run-2", false));
    await user.click(screen.getByRole("button", { name: "Re-run" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "run-1", true));
  });

  it("shows no start buttons to viewers or on runs that can't be analyzed", async () => {
    list.mockResolvedValue([run({ id: "ok", conclusion: "success", analyzable: false, run_number: 8 })]);
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    expect(await screen.findByRole("link", { name: "CI #8" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Analyze|Re-run|Retry/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Not analyzed")).not.toBeInTheDocument();
  });

  it("is read-only for viewers", async () => {
    list.mockResolvedValue([run({ analysis: analysis() })]);
    renderWithQuery(<CiList orgId="org-1" canAnalyze={false} />);
    expect(await screen.findByRole("link", { name: "View analysis" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Analyze|Re-run|Retry/ })).not.toBeInTheDocument();
  });

  it("disables the button while an analysis runs", async () => {
    list.mockResolvedValue([run({ analysis: analysis({ status: "running" }) })]);
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    expect(await screen.findByRole("button", { name: "Analyzing…" })).toBeDisabled();
    expect(screen.getByText("Reading logs…")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "View analysis" })).not.toBeInTheDocument();
  });

  it("filters by repository, state and search, and passes them to the server", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    await screen.findByText("No failed runs.");
    expect(list).toHaveBeenLastCalledWith("token", "org-1", "failed", { repoId: undefined, q: "", limit: 30, offset: 0 });
    await user.selectOptions(await screen.findByLabelText("Repository"), "r2");
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("token", "org-1", "failed", expect.objectContaining({ repoId: "r2" })));
    await user.click(screen.getByRole("button", { name: "all" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("token", "org-1", "all", expect.anything()));
    await user.type(screen.getByLabelText("Search runs"), "main");
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("token", "org-1", "all", expect.objectContaining({ q: "main" })));
    expect(await screen.findByText("No runs match your search.")).toBeInTheDocument();
  });

  it("explains empty states", async () => {
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    expect(await screen.findByText("No failed runs.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "all" }));
    expect(await screen.findByText(/No CI runs yet/)).toBeInTheDocument();
  });

  it("loads more when a full page came back", async () => {
    const page = Array.from({ length: 30 }, (_, i) => run({ id: `r${i}`, run_number: i + 1, name: `Flow ${i}` }));
    list.mockResolvedValueOnce(page).mockResolvedValueOnce([run({ id: "last", name: "Last flow", run_number: 99 })]);
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    await screen.findByText(/Flow 0/);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText(/Last flow/)).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith("token", "org-1", "failed", expect.objectContaining({ offset: 30 }));
  });

  it("shows why an analysis couldn't start, and load errors with a retry", async () => {
    list.mockResolvedValue([run()]);
    start.mockRejectedValue(new ApiError("The AI provider's daily request quota is used up.", 429));
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    await user.click(await screen.findByRole("button", { name: "Analyze" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("daily request quota is used up");
  });

  it("shows a load error with a retry", async () => {
    list.mockRejectedValueOnce(new Error("boom")).mockResolvedValue([run()]);
    const user = userEvent.setup();
    renderWithQuery(<CiList orgId="org-1" canAnalyze />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load CI runs.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: "CI #7" })).toBeInTheDocument();
  });
});
