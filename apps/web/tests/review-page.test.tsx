import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewPage } from "@/components/code-reviews/review-page";
import type { ReviewBrief } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { ORG, pull, renderWithQuery } from "./helpers";

const getPull = vi.fn();
const start = vi.fn();
let role: "owner" | "viewer" = "owner";

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/components/review-panel", () => ({
  ReviewPanel: ({ canEdit }: { canEdit: boolean }) => <div>findings panel (edit: {String(canEdit)})</div>,
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    reviewApi: { ...actual.reviewApi, pull: (...a: unknown[]) => getPull(...a), start: (...a: unknown[]) => start(...a) },
  };
});

const brief = (over: Partial<ReviewBrief> = {}): ReviewBrief => ({
  id: "rev-1", status: "ready", risk: "medium", open_findings: 2, serious_findings: 0,
  finished_at: new Date().toISOString(), stale: false, error: null, ...over,
});

beforeEach(() => {
  role = "owner";
  getPull.mockReset();
  start.mockReset().mockResolvedValue({});
});

describe("<ReviewPage>", () => {
  it("shows the pull request, links to GitHub, and the findings panel", async () => {
    getPull.mockResolvedValue(pull({ review: brief() }));
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByRole("heading", { name: "Fix login redirect" })).toBeInTheDocument();
    expect(screen.getByText(/acme\/web #7 · ada/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open on GitHub" })).toHaveAttribute("href", "https://github.com/acme/web/pull/7");
    expect(screen.getByText("findings panel (edit: true)")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Code reviews/ })).toHaveAttribute("href", "/code-reviews");
    expect(getPull).toHaveBeenCalledWith("token", "org-1", "pr-1");
  });

  it("explains that an unreviewed pull request has no review yet", async () => {
    getPull.mockResolvedValue(pull());
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByText(/has not been reviewed/)).toBeInTheDocument();
    expect(screen.getByText(/It uses AI tokens/)).toBeInTheDocument();
    expect(screen.queryByText(/findings panel/)).not.toBeInTheDocument();
  });

  it("starts a review when a member clicks, and Re-run asks for a fresh one", async () => {
    getPull.mockResolvedValue(pull({ review: brief() }));
    const user = userEvent.setup();
    renderWithQuery(<ReviewPage prId="pr-1" />);
    await user.click(await screen.findByRole("button", { name: "Re-run" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith("token", "org-1", "pr-1", true));
  });

  it("is read-only for viewers", async () => {
    role = "viewer";
    getPull.mockResolvedValue(pull({ review: brief() }));
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByText("findings panel (edit: false)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Review|Re-run|Retry/ })).not.toBeInTheDocument();
  });

  it("disables the button while the review runs", async () => {
    getPull.mockResolvedValue(pull({ review: brief({ status: "running" }) }));
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByRole("button", { name: "Reviewing…" })).toBeDisabled();
  });

  it("shows merged and draft states", async () => {
    getPull.mockResolvedValue(pull({ merged: true, draft: true, state: "closed" }));
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByText("merged")).toBeInTheDocument();
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.queryByText("closed")).not.toBeInTheDocument(); // merged wins over closed
  });

  it("says plainly when the pull request isn't in this workspace", async () => {
    getPull.mockRejectedValue(new ApiError("Pull request not found", 404));
    renderWithQuery(<ReviewPage prId="nope" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Pull request not found in this workspace.");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("offers a retry for other errors", async () => {
    getPull.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(pull());
    const user = userEvent.setup();
    renderWithQuery(<ReviewPage prId="pr-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load this pull request.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { name: "Fix login redirect" })).toBeInTheDocument();
  });

  it("shows why a review failed to start", async () => {
    getPull.mockResolvedValue(pull());
    start.mockRejectedValue(new ApiError("An AI review of this pull request is already in progress", 409));
    const user = userEvent.setup();
    renderWithQuery(<ReviewPage prId="pr-1" />);
    await user.click(await screen.findByRole("button", { name: "Review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already in progress");
  });
});
