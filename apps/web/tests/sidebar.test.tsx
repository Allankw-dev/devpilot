import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Sidebar } from "@/components/shell/sidebar";
import { ME, ORG } from "./helpers";

const push = vi.fn();
const refresh = vi.fn();
const signOut = vi.fn().mockResolvedValue({});
let pathname = "/dashboard";
let currentOrg: typeof ORG | null = ORG;

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push, refresh }),
}));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ clear: vi.fn() }) }));
vi.mock("@/lib/supabase/client", () => ({ createClient: () => ({ auth: { signOut } }) }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: ME, orgs: [ORG], org: currentOrg, select: vi.fn() }),
}));
vi.mock("@/components/shell/workspace-switcher", () => ({ WorkspaceSwitcher: () => <div>switcher</div> }));
vi.mock("@/components/shell/usage-meter", () => ({ UsageMeter: () => <div>usage meter</div> }));

beforeEach(() => {
  pathname = "/dashboard";
  currentOrg = ORG;
  push.mockClear();
  signOut.mockClear();
});

describe("<Sidebar>", () => {
  it("lists the pages that exist and marks the current one", () => {
    render(<Sidebar collapsed={false} />);
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav).toHaveTextContent("Dashboard");
    expect(nav).toHaveTextContent("Workspace");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Workspace" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Workspace" })).toHaveAttribute("href", "/orgs/org-1");
  });

  it("marks the workspace page active under /orgs", () => {
    pathname = "/orgs/org-1";
    render(<Sidebar collapsed={false} />);
    expect(screen.getByRole("link", { name: "Workspace" })).toHaveAttribute("aria-current", "page");
  });

  it("shows the Workspace item as unavailable until you have a workspace", () => {
    currentOrg = null;
    render(<Sidebar collapsed={false} />);
    expect(screen.queryByRole("link", { name: "Workspace" })).not.toBeInTheDocument();
    expect(screen.getByText("Workspace").closest("[aria-disabled]")).toHaveAttribute("aria-disabled", "true");
  });

  it("shows who you are, your role, and the usage meter", () => {
    render(<Sidebar collapsed={false} />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("owner")).toBeInTheDocument();
    expect(screen.getByText("usage meter")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Help and documentation" })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: "Help and documentation" })).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("keeps links reachable by name when collapsed to icons, and hides the usage meter", () => {
    render(<Sidebar collapsed onToggleCollapsed={() => {}} />);
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByText("usage meter")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-pressed", "true");
  });

  it("calls the collapse and close handlers", async () => {
    const user = userEvent.setup();
    const toggle = vi.fn();
    const close = vi.fn();
    render(<Sidebar collapsed={false} onToggleCollapsed={toggle} onClose={close} />);
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    await user.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(toggle).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
  });

  it("closes the mobile drawer after you pick a page", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(<Sidebar collapsed={false} onNavigate={onNavigate} />);
    await user.click(screen.getByRole("link", { name: "Workspace" }));
    expect(onNavigate).toHaveBeenCalled();
  });

  it("signs out and goes to the login page", async () => {
    const user = userEvent.setup();
    render(<Sidebar collapsed={false} />);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
    expect(push).toHaveBeenCalledWith("/login");
  });
});
