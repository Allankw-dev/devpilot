import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AssistantAnswer, UserMessage } from "@/components/assistant/message";
import { answer, repo } from "./helpers";

const repos = new Map([["repo-1", repo({ id: "repo-1", html_url: "https://github.com/acme/web", default_branch: "main" })]]);
const props = { repos, canRegenerate: true, regenerating: false, onRegenerate: () => {} };

describe("<UserMessage>", () => {
  it("shows the question as plain text, never as markup", () => {
    render(<UserMessage text={"What does <b>this</b> do?\nSecond line"} />);
    expect(screen.getByText(/What does <b>this<\/b> do\?/)).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
  });
});

describe("<AssistantAnswer>", () => {
  it("shows the answer, confidence, how much was read, and the model", () => {
    render(<AssistantAnswer message={answer()} {...props} />);
    expect(screen.getByText(/Login is handled in/)).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/Based on 6 pieces of code and docs/)).toBeInTheDocument();
    expect(screen.getByText(/fake-model/)).toBeInTheDocument();
    expect(screen.getByText(/AI can be wrong/)).toBeInTheDocument();
  });

  it("links citations to the exact lines on GitHub", () => {
    render(<AssistantAnswer message={answer()} {...props} />);
    const link = screen.getByRole("link", { name: "auth/login.py:10-42" });
    expect(link).toHaveAttribute("href", "https://github.com/acme/web/blob/main/auth/login.py#L10-L42");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText("login_user", { selector: "span" })).toBeInTheDocument();
    expect(within(screen.getByRole("article")).getByRole("link", { name: "[1]" })).toHaveAttribute("href", expect.stringContaining("#L10-L42"));
  });

  it("lists a source as text when its repository's branch is unknown", () => {
    render(<AssistantAnswer message={answer()} {...props} repos={new Map()} />);
    expect(screen.queryByRole("link", { name: "auth/login.py:10-42" })).not.toBeInTheDocument();
    expect(screen.getByText("auth/login.py:10-42")).toBeInTheDocument();
  });

  it("says what the code didn't cover", () => {
    render(<AssistantAnswer message={answer({ missing_context: "How tokens expire" })} {...props} />);
    expect(screen.getByText(/Not covered by the code found:/)).toBeInTheDocument();
    expect(screen.getByText(/How tokens expire/)).toBeInTheDocument();
  });

  it("colors low confidence as a warning and copes with unknown confidence", () => {
    const { rerender } = render(<AssistantAnswer message={answer({ confidence: "low" })} {...props} />);
    expect(screen.getByText("low")).toHaveClass("text-danger");
    rerender(<AssistantAnswer message={answer({ confidence: null })} {...props} />);
    expect(screen.getByText("unknown")).toBeInTheDocument();
  });

  it("copies the answer text", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<AssistantAnswer message={answer()} {...props} />);
    await user.click(screen.getByRole("button", { name: "Copy answer" }));
    expect(writeText).toHaveBeenCalledWith("Login is handled in `login_user` [1].");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("only offers 'Generate again' when allowed, and calls it", async () => {
    const user = userEvent.setup();
    const onRegenerate = vi.fn();
    const { rerender } = render(<AssistantAnswer message={answer()} {...props} onRegenerate={onRegenerate} />);
    await user.click(screen.getByRole("button", { name: "Generate again" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
    rerender(<AssistantAnswer message={answer()} {...props} canRegenerate={false} />);
    expect(screen.queryByRole("button", { name: "Generate again" })).not.toBeInTheDocument();
  });

  it("replaces the text with a status while regenerating", () => {
    render(<AssistantAnswer message={answer({ missing_context: "x" })} {...props} regenerating />);
    expect(screen.getByRole("status")).toHaveTextContent("Generating this answer again…");
    expect(screen.queryByText(/Login is handled in/)).not.toBeInTheDocument();
    expect(screen.queryByText("Sources")).not.toBeInTheDocument();
  });

  it("never turns model text into markup", () => {
    render(<AssistantAnswer message={answer({ content: "<img src=x onerror=alert(1)> and <script>bad()</script>" })} {...props} />);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });
});
