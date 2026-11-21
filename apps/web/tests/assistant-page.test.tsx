import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AssistantPage } from "@/components/assistant/assistant-page";
import type { Role } from "@/lib/api";
import { conversation, ORG, renderWithQuery, repo } from "./helpers";

const list = vi.fn();
const repos = vi.fn();
let search = "";
let role: Role = "owner";
let hasOrg = true;

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(search) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: hasOrg ? { ...ORG, role } : null, select: vi.fn() }),
}));
vi.mock("@/components/assistant/conversation-view", () => ({
  ConversationView: ({ conversationId, canAsk }: { conversationId: string; canAsk: boolean }) => (
    <div>conversation {conversationId} (ask: {String(canAsk)})</div>
  ),
}));
vi.mock("@/components/assistant/new-conversation", () => ({
  NewConversation: ({ repos: r, canAsk }: { repos: unknown[]; canAsk: boolean }) => (
    <div>new conversation ({r.length} repos, ask: {String(canAsk)})</div>
  ),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    orgApi: { ...actual.orgApi, repos: (...a: unknown[]) => repos(...a) },
    conversationApi: { ...actual.conversationApi, list: (...a: unknown[]) => list(...a) },
  };
});

beforeEach(() => {
  search = "";
  role = "owner";
  hasOrg = true;
  list.mockReset().mockResolvedValue([]);
  repos.mockReset().mockResolvedValue([repo()]);
});

describe("<AssistantPage>", () => {
  it("asks you to create a workspace first when you have none", () => {
    hasOrg = false;
    renderWithQuery(<AssistantPage />);
    expect(screen.getByText(/Create a workspace on the dashboard first/)).toBeInTheDocument();
  });

  it("starts a new conversation when none is selected, and says conversations are private", async () => {
    renderWithQuery(<AssistantPage />);
    expect(await screen.findByText("new conversation (1 repos, ask: true)")).toBeInTheDocument();
    expect(screen.getByText(/Your conversations are private to you/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New conversation" })).toHaveAttribute("href", "/assistant");
  });

  it("opens the selected conversation", async () => {
    search = "c=c1";
    renderWithQuery(<AssistantPage />);
    expect(await screen.findByText("conversation c1 (ask: true)")).toBeInTheDocument();
    expect(screen.queryByText(/new conversation \(/)).not.toBeInTheDocument();
  });

  it("lists your conversations with their repository and marks the open one", async () => {
    search = "c=c2";
    list.mockResolvedValue([conversation({ id: "c1", title: "Login question" }), conversation({ id: "c2", title: "Billing", repository: null, repository_id: null })]);
    renderWithQuery(<AssistantPage />);
    const first = await screen.findByRole("link", { name: /Login question/ });
    expect(first).toHaveAttribute("href", "/assistant?c=c1");
    expect(first).not.toHaveAttribute("aria-current");
    const second = screen.getByRole("link", { name: /Billing/ });
    expect(second).toHaveAttribute("aria-current", "page");
    expect(second).toHaveTextContent("All repositories");
    expect(first).toHaveTextContent("acme/web");
  });

  it("says when there are no conversations yet", async () => {
    renderWithQuery(<AssistantPage />);
    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
  });

  it("shows an error when the list can't load, but the page still works", async () => {
    list.mockRejectedValue(new Error("boom"));
    renderWithQuery(<AssistantPage />);
    expect(await screen.findByText("Couldn’t load conversations.")).toBeInTheDocument();
    expect(await screen.findByText(/new conversation \(/)).toBeInTheDocument();
  });

  it("tells viewers they can't ask", async () => {
    role = "viewer";
    renderWithQuery(<AssistantPage />);
    expect(await screen.findByText("new conversation (1 repos, ask: false)")).toBeInTheDocument();
  });
});
