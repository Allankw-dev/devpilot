import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { WorkspaceSwitcher } from "@/components/shell/workspace-switcher";
import { ORG, renderWithQuery } from "./helpers";

const push = vi.fn();
const select = vi.fn();
let pathname = "/dashboard";
const beta = { ...ORG, id: "org-2", name: "Beta", role: "member" as const };

vi.mock("next/navigation", () => ({ usePathname: () => pathname, useRouter: () => ({ push }) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [ORG, beta], org: ORG, select }),
}));

beforeEach(() => {
  pathname = "/dashboard";
  push.mockClear();
  select.mockClear();
});

describe("<WorkspaceSwitcher>", () => {
  it("shows the current workspace and lists all of them with your role", async () => {
    const user = userEvent.setup();
    renderWithQuery(<WorkspaceSwitcher collapsed={false} />);
    const trigger = screen.getByRole("button", { name: /Workspace: Acme/ });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    const list = screen.getByRole("listbox", { name: "Workspaces" });
    expect(list).toHaveTextContent("Acme");
    expect(list).toHaveTextContent("Beta");
    expect(list).toHaveTextContent("member");
  });

  it("switches workspace and closes", async () => {
    const user = userEvent.setup();
    renderWithQuery(<WorkspaceSwitcher collapsed={false} />);
    await user.click(screen.getByRole("button", { name: /Workspace: Acme/ }));
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    expect(select).toHaveBeenCalledWith("org-2");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(push).not.toHaveBeenCalled(); // not on a workspace page
  });

  it("stays on a workspace page when you switch from one", async () => {
    pathname = "/orgs/org-1";
    const user = userEvent.setup();
    renderWithQuery(<WorkspaceSwitcher collapsed={false} />);
    await user.click(screen.getByRole("button", { name: /Workspace: Acme/ }));
    await user.click(screen.getByRole("button", { name: /Beta/ }));
    expect(push).toHaveBeenCalledWith("/orgs/org-2");
  });

  it("closes with Escape", async () => {
    const user = userEvent.setup();
    renderWithQuery(<WorkspaceSwitcher collapsed={false} />);
    await user.click(screen.getByRole("button", { name: /Workspace: Acme/ }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("needs a real name before it will create a workspace", async () => {
    const user = userEvent.setup();
    renderWithQuery(<WorkspaceSwitcher collapsed={false} />);
    await user.click(screen.getByRole("button", { name: /Workspace: Acme/ }));
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    await user.type(screen.getByLabelText(/New workspace/), "A");
    expect(create).toBeDisabled();
    await user.type(screen.getByLabelText(/New workspace/), "B");
    expect(create).toBeEnabled();
  });
});
