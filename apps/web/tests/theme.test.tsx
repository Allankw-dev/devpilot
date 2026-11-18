import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ThemeToggle } from "@/components/shell/theme-toggle";
import { applyTheme, readTheme, THEME_INIT_SCRIPT, THEME_KEY } from "@/lib/theme";

describe("theme helpers", () => {
  it("is dark by default", () => {
    expect(readTheme()).toBe("dark");
  });

  it("applies and remembers the light theme", () => {
    applyTheme("light");
    expect(document.documentElement).toHaveClass("light");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
    expect(readTheme()).toBe("light");
    applyTheme("dark");
    expect(document.documentElement).not.toHaveClass("light");
  });

  it("the pre-paint script restores a saved light theme and leaves dark alone", () => {
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement).not.toHaveClass("light");
    localStorage.setItem(THEME_KEY, "light");
    new Function(THEME_INIT_SCRIPT)();
    expect(document.documentElement).toHaveClass("light");
  });
});

describe("<ThemeToggle>", () => {
  it("switches between themes and says what the next click does", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).toHaveClass("light");
    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).not.toHaveClass("light");
  });
});
