import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConversationView } from "@/components/assistant/conversation-view";
import { ApiError } from "@/lib/api";
import { answer, conversation, question, renderWithQuery, repo } from "./helpers";

const get = vi.fn();
const ask = vi.fn();
const regenerate = vi.fn();
const remove = vi.fn();
const push = vi.fn();

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    conversationApi: {
      ...actual.conversationApi,
      get: (...a: unknown[]) => get(...a),
      ask: (...a: unknown[]) => ask(...a),
      regenerate: (...a: unknown[]) => regenerate(...a),
      remove: (...a: unknown[]) => remove(...a),
    },
  };
});

const repos = new Map([["repo-1", repo({ id: "repo-1" })]]);
const detail = (messages = [question(), answer()], over = {}) => ({ ...conversation(), messages, ...over });
const view = (canAsk = true) => renderWithQuery(<ConversationView orgId="org-1" conversationId="c1" repos={repos} canAsk={canAsk} />);

beforeEach(() => {
  get.mockReset().mockResolvedValue(detail());
  ask.mockReset();
  regenerate.mockReset();
  remove.mockReset().mockResolvedValue(undefined);
  push.mockReset();
});

describe("<ConversationView>", () => {
  it("shows the title, which repository it is about, and the saved messages in order", async () => {
    view();
    expect(await screen.findByRole("heading", { name: "Where is login handled?" })).toBeInTheDocument();
    expect(screen.getByText("Asking about acme/web")).toBeInTheDocument();
    expect(screen.getByText(/Login is handled in/)).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("token", "org-1", "c1");
  });

  it("says when a conversation covers all repositories, and when it is empty", async () => {
    get.mockResolvedValue(detail([], { repository: null, repository_id: null }));
    view();
    expect(await screen.findByText("Asking across all indexed repositories")).toBeInTheDocument();
    expect(screen.getByText(/No questions yet/)).toBeInTheDocument();
  });

  it("asks a question, shows it straight away, then adds the saved answer", async () => {
    let finish: (v: unknown) => void = () => {};
    ask.mockReturnValue(new Promise((r) => (finish = r)));
    const user = userEvent.setup();
    view();
    await screen.findByText(/Login is handled in/);
    await user.type(screen.getByLabelText("Question"), "And billing?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText("And billing?")).toBeInTheDocument(); // shown while waiting
    expect(screen.getByText(/Searching the code and writing an answer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking…" })).toBeDisabled();
    get.mockResolvedValue(detail([question(), answer(), question("And billing?", "m3"), answer({ id: "m4", content: "Billing is in `charge` [1]." })]));
    finish({ user: question("And billing?", "m3"), assistant: answer({ id: "m4", content: "Billing is in `charge` [1]." }) });
    expect(await screen.findByText(/Billing is in/)).toBeInTheDocument();
    expect(screen.queryByText(/Searching the code/)).not.toBeInTheDocument();
    expect(ask).toHaveBeenCalledWith("token", "org-1", "c1", "And billing?");
  });

  it("shows the server's reason when asking fails, and lets you try the same question again", async () => {
    ask.mockRejectedValueOnce(new ApiError("Nothing is indexed to answer from. Index a repository first.", 409));
    ask.mockResolvedValue({ user: question("Retry me?", "m5"), assistant: answer({ id: "m6", content: "Done [1]." }) });
    const user = userEvent.setup();
    view();
    await screen.findByText(/Login is handled in/);
    await user.type(screen.getByLabelText("Question"), "Retry me?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nothing is indexed to answer from");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask).toHaveBeenLastCalledWith("token", "org-1", "c1", "Retry me?");
  });

  it("generates only the latest answer again, in place", async () => {
    get.mockResolvedValue(detail([question("First?", "m1"), answer({ id: "m2", content: "Old first [1]." }), question("Second?", "m3"), answer({ id: "m4", content: "Old second [1]." })]));
    regenerate.mockResolvedValue(answer({ id: "m4", content: "Fresh second [1]." }));
    const user = userEvent.setup();
    view();
    await screen.findByText(/Old second/);
    expect(screen.getAllByRole("button", { name: "Generate again" })).toHaveLength(1); // not on the older answer
    await user.click(screen.getByRole("button", { name: "Generate again" }));
    expect(await screen.findByText(/Fresh second/)).toBeInTheDocument();
    expect(screen.getByText(/Old first/)).toBeInTheDocument(); // the earlier answer is untouched
    expect(regenerate).toHaveBeenCalledWith("token", "org-1", "c1", "m4");
  });

  it("shows why regenerating failed and keeps the old answer", async () => {
    regenerate.mockRejectedValue(new ApiError("The AI provider's daily request quota is used up.", 429));
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("button", { name: "Generate again" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("daily request quota is used up");
    expect(screen.getByText(/Login is handled in/)).toBeInTheDocument();
  });

  it("deletes only after you confirm, then goes back to the start", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    view();
    await user.click(await screen.findByRole("button", { name: "Delete conversation" }));
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete conversation" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("token", "org-1", "c1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/assistant"));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("is read-only for viewers: they can read but not ask or regenerate", async () => {
    view(false);
    expect(await screen.findByText(/Login is handled in/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Question")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate again" })).not.toBeInTheDocument();
    expect(screen.getByText(/Viewers can read conversations but not ask/)).toBeInTheDocument();
  });

  it("explains that the question does not see earlier ones", async () => {
    view();
    expect(await screen.findByText(/does not see your earlier questions or answers/)).toBeInTheDocument();
  });

  it("says a missing or someone else's conversation isn't there, and retries other errors", async () => {
    get.mockRejectedValueOnce(new ApiError("Conversation not found", 404));
    const { unmount } = view();
    expect(await screen.findByRole("alert")).toHaveTextContent("doesn’t exist, or isn’t yours");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
    unmount();
    get.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(detail());
    const user = userEvent.setup();
    view();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load this conversation.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/Login is handled in/)).toBeInTheDocument();
  });
});
