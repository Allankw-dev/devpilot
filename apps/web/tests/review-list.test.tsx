import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewList, reviewActionLabel } from "@/components/code-reviews/review-list";
import type { ReviewBrief } from "@/lib/api";
import { renderWithQuery, pull, repo } from "./helpers";

const list = vi.fn();
const start = vi.fn();
const repos = vi.fn();

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => repos(...a) },
    reviewApi: { ...actual.reviewApi, list: (...a: unknown[]) => list(...a), start: (...a: unknown[]) => start(...a) },
  };
});

const brief = (over: Partial<ReviewBrief> = {}): ReviewBrief => ({
  id: "rev-1", status: "ready", risk: "high", open_findings: 3, serious_findings: 1,
  finished_at: new Date().toISOString(), stale: false, error: null, ...over,
});

beforeEach(() => {
  list.mockReset().mockResolvedValue([]);
  start.mockReset().mockResolvedValue({});
  repos.mockReset().mockResolvedValue([repo({ id: "r1", full_name: "acme/web" }), repo({ id: "r2", full_name: "acme/api" })]);
});

describe("reviewActionLabel", () => {
  it("says what the button will do", () => {
    expect(reviewActionLabel(pull())).toBe("Review");
    expect(reviewActionLabel(pull({ review: brief({ status: "failed" }) }))).toBe("Retry");
    expect(reviewActionLabel(pull({ review: brief({ stale: true }) }))).toBe("Review again");
    expect(reviewActionLabel(pull({ review: brief() }))).toBe("Re-run");
  });
});

describe("<ReviewList>", () => {
  it("shows each pull request with its review result and a link to the review", async () => {
    list.mockResolvedValue([pull({ review: brief() }), pull({ id: "pr-2", number: 8, title: "Add dark mode" })]);
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    expect(await screen.findByRole("link", { name: "Fix login redirect" })).toHaveAttribute(
      "href", "https://github.com/acme/web/pull/7",
    );
    expect(screen.getByText(/high risk/)).toBeInTheDocument();
    expect(screen.getByText(/3 findings/)).toBeInTheDocument();
    expect(screen.getByText(/1 serious/)).toBeInTheDocument();
    expect(screen.getByText("Not reviewed")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View review" })).toHaveLength(1); // only the reviewed one
    expect(screen.getByRole("link", { name: "View review" })).toHaveAttribute("href", "/code-reviews/pr-1");
  });

  it("starts a review only when you click, and re-runs ask for a fresh review", async () => {
    list.mockResolvedValue([pull({ review: brief() }), pull({ id: "pr-2", number: 8, title: "Add dark mode" })]);
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await screen.findByText("Add dark mode");
    expect(start).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Review" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "pr-2", false));
    await user.click(screen.getByRole("button", { name: "Re-run" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "pr-1", true));
  });

  it("hides the start buttons from viewers but still shows results", async () => {
    list.mockResolvedValue([pull({ review: brief() })]);
    renderWithQuery(<ReviewList orgId="org-1" canReview={false} />);
    expect(await screen.findByRole("link", { name: "View review" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review|Re-run|Retry/ })).not.toBeInTheDocument();
  });

  it("disables the button while a review is running", async () => {
    list.mockResolvedValue([pull({ review: brief({ status: "running" }) })]);
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    expect(await screen.findByRole("button", { name: "Reviewing…" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "View review" })).not.toBeInTheDocument();
  });

  it("filters by repository and passes it to the server", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await screen.findByText("No open pull requests.");
    await user.selectOptions(await screen.findByLabelText("Repository"), "r2");
    await waitFor(() =>
      expect(list).toHaveBeenLastCalledWith("token", "org-1", "open", { repoId: "r2", q: "", limit: 30, offset: 0 }),
    );
  });

  it("is already scoped to one repository when given a repoId, and has no repository filter", async () => {
    renderWithQuery(<ReviewList orgId="org-1" canReview repoId="r9" />);
    await screen.findByText("No open pull requests.");
    expect(screen.queryByLabelText("Repository")).not.toBeInTheDocument();
    expect(repos).not.toHaveBeenCalled();
    expect(list).toHaveBeenCalledWith("token", "org-1", "open", { repoId: "r9", q: "", limit: 30, offset: 0 });
  });

  it("switches between open and all pull requests", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await screen.findByText("No open pull requests.");
    await user.click(screen.getByRole("button", { name: "all" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("token", "org-1", "all", expect.anything()));
    expect(await screen.findByText("No pull requests.")).toBeInTheDocument();
  });

  it("searches titles after you stop typing", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await screen.findByText("No open pull requests.");
    await user.type(screen.getByLabelText("Search pull requests"), "login");
    await waitFor(() => expect(list).toHaveBeenLastCalledWith("token", "org-1", "open", expect.objectContaining({ q: "login" })));
    expect(await screen.findByText("No pull requests match your search.")).toBeInTheDocument();
  });

  it("loads more when a full page came back", async () => {
    const page = Array.from({ length: 30 }, (_, i) => pull({ id: `p${i}`, number: i + 1, title: `PR ${i}` }));
    list.mockResolvedValueOnce(page).mockResolvedValueOnce([pull({ id: "last", title: "The last one" })]);
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await screen.findByText("PR 0");
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("The last one")).toBeInTheDocument();
    expect(list).toHaveBeenLastCalledWith("token", "org-1", "open", expect.objectContaining({ offset: 30 }));
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("shows API errors from starting a review", async () => {
    const { ApiError } = await import("@/lib/api");
    list.mockResolvedValue([pull()]);
    start.mockRejectedValue(new ApiError("Missing settings: GEMINI_API_KEY", 503));
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    await user.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Missing settings: GEMINI_API_KEY");
  });

  it("shows a load error with a retry", async () => {
    list.mockRejectedValueOnce(new Error("boom")).mockResolvedValue([pull()]);
    const user = userEvent.setup();
    renderWithQuery(<ReviewList orgId="org-1" canReview />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load pull requests.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Fix login redirect")).toBeInTheDocument();
  });
});
