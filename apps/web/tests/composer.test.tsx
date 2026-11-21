import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "@/components/assistant/composer";

const setup = (props: Partial<React.ComponentProps<typeof Composer>> = {}) => {
  const onSend = vi.fn();
  render(<Composer pending={false} placeholder="Ask…" onSend={onSend} {...props} />);
  return { onSend, user: userEvent.setup() };
};

describe("<Composer>", () => {
  it("sends the trimmed question when you click Ask, then clears the box", async () => {
    const { onSend, user } = setup();
    await user.type(screen.getByLabelText("Question"), "  Where is login?  ");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    expect(onSend).toHaveBeenCalledWith("Where is login?");
    expect(screen.getByLabelText("Question")).toHaveValue("");
  });

  it("sends on Enter, and Shift+Enter adds a line instead", async () => {
    const { onSend, user } = setup();
    const box = screen.getByLabelText("Question");
    await user.type(box, "first line{Shift>}{Enter}{/Shift}second");
    expect(onSend).not.toHaveBeenCalled();
    expect(box).toHaveValue("first line\nsecond");
    await user.keyboard("{Enter}");
    expect(onSend).toHaveBeenCalledWith("first line\nsecond");
  });

  it("won't send anything shorter than three characters", async () => {
    const { onSend, user } = setup();
    const button = screen.getByRole("button", { name: "Ask" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Question"), "hi{Enter}");
    expect(button).toBeDisabled();
    expect(onSend).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Question"), "!");
    expect(button).toBeEnabled();
  });

  it("is blocked while an answer is pending or when disabled", async () => {
    const { onSend, user } = setup({ pending: true });
    expect(screen.getByRole("button", { name: "Thinking…" })).toBeDisabled();
    await user.type(screen.getByLabelText("Question"), "A real question{Enter}");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("can be disabled entirely", () => {
    setup({ disabled: true });
    expect(screen.getByLabelText("Question")).toBeDisabled();
  });

  it("limits the length of a question", () => {
    setup();
    expect(screen.getByLabelText("Question")).toHaveAttribute("maxlength", "1000");
  });
});
