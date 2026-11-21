import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EXAMPLES, NewConversation } from "@/components/assistant/new-conversation";
import { ApiError } from "@/lib/api";
import { renderWithQuery, repo } from "./helpers";

const create = vi.fn();
const ask = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, conversationApi: { ...actual.conversationApi, create: (...a: unknown[]) => create(...a), ask: (...a: unknown[]) => ask(...a) } };
});

const ready = { ...repo().index, status: "ready" as const };
const repos = [repo({ id: "r1", full_name: "acme/web", index: ready }), repo({ id: "r2", full_name: "acme/api" })]; // r2 not indexed

beforeEach(() => {
  create.mockReset().mockResolvedValue({ id: "c9" });
  ask.mockReset().mockResolvedValue({});
  push.mockReset();
});

describe("<NewConversation>", () => {
  it("asks you to index a repository first when none is indexed", () => {
    renderWithQuery(<NewConversation orgId="org-1" repos={[repo()]} canAsk />);
    expect(screen.getByText("Index a repository to start asking")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to repositories" })).toHaveAttribute("href", "/repositories");
    expect(screen.queryByLabelText("Question")).not.toBeInTheDocument();
  });

  it("only offers indexed repositories", () => {
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk />);
    const options = within(screen.getByLabelText("Repository")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["All indexed repositories", "acme/web"]);
  });

  it("creates the conversation, asks, and opens it", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk />);
    await user.selectOptions(screen.getByLabelText("Repository"), "r1");
    await user.type(screen.getByLabelText("Question"), "Where is login handled?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/assistant?c=c9"));
    expect(create).toHaveBeenCalledWith("token", "org-1", "r1");
    expect(ask).toHaveBeenCalledWith("token", "org-1", "c9", "Where is login handled?");
  });

  it("asks across all repositories when none is chosen", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk />);
    await user.type(screen.getByLabelText("Question"), "How is billing done?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("token", "org-1", undefined));
  });

  it("starts from an example question with one click", async () => {
    const user = userEvent.setup();
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk />);
    await user.click(screen.getByRole("button", { name: EXAMPLES[1] }));
    await waitFor(() => expect(ask).toHaveBeenCalledWith("token", "org-1", "c9", EXAMPLES[1]));
  });

  it("shows the server's reason and retries into the same conversation, not a new one", async () => {
    ask.mockRejectedValueOnce(new ApiError("The AI provider's daily request quota is used up.", 429));
    const user = userEvent.setup();
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk />);
    await user.type(screen.getByLabelText("Question"), "Where is login handled?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("daily request quota is used up");
    expect(push).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/assistant?c=c9"));
    expect(create).toHaveBeenCalledTimes(1); // no orphan conversations
    expect(ask).toHaveBeenCalledTimes(2);
  });

  it("is read-only for viewers", () => {
    renderWithQuery(<NewConversation orgId="org-1" repos={repos} canAsk={false} />);
    expect(screen.getByText(/Viewers can read conversations but not ask/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Question")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: EXAMPLES[0] })).not.toBeInTheDocument();
  });
});
