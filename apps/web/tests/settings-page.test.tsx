import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "@/components/settings/settings-page";
import { ApiError, type Role } from "@/lib/api";
import { ME, ORG, renderWithQuery } from "./helpers";

const rename = vi.fn();
const removeWorkspace = vi.fn();
const push = vi.fn();
let role: Role = "owner";
let hasOrg = true;

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: ME, orgs: [], org: hasOrg ? { ...ORG, role } : null, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    workspaceApi: { rename: (...a: unknown[]) => rename(...a), remove: (...a: unknown[]) => removeWorkspace(...a) },
  };
});

beforeEach(() => {
  role = "owner";
  hasOrg = true;
  rename.mockReset().mockResolvedValue({ ...ORG, name: "Acme Labs" });
  removeWorkspace.mockReset().mockResolvedValue(undefined);
  push.mockReset();
});

describe("<SettingsPage>", () => {
  it("shows your profile as read-only", () => {
    renderWithQuery(<SettingsPage />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    expect(screen.getByText(/come from your sign-in provider/)).toBeInTheDocument();
  });

  it("switches and remembers the theme", async () => {
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);
    const light = screen.getByRole("radio", { name: "light" });
    expect(screen.getByRole("radio", { name: "dark" })).toHaveAttribute("aria-checked", "true");
    await user.click(light);
    expect(light).toHaveAttribute("aria-checked", "true");
    expect(document.documentElement).toHaveClass("light");
    expect(localStorage.getItem("devpilot-theme")).toBe("light");
  });

  it("lets an admin rename the workspace, but only when the name really changed", async () => {
    role = "admin";
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    const input = screen.getByLabelText("Name");
    await user.clear(input);
    await user.type(input, "A");
    expect(save).toBeDisabled(); // too short
    await user.clear(input);
    await user.type(input, "Acme Labs");
    await user.click(save);
    await waitFor(() => expect(rename).toHaveBeenCalledWith("token", "org-1", "Acme Labs"));
  });

  it("shows why a rename failed", async () => {
    rename.mockRejectedValue(new ApiError("Requires admin role", 403));
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);
    const input = screen.getByLabelText("Name");
    await user.clear(input);
    await user.type(input, "New name");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Requires admin role");
  });

  it("is read-only for members, who also see no danger zone", () => {
    role = "member";
    renderWithQuery(<SettingsPage />);
    expect(screen.getByLabelText("Name")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.getByText(/Only admins and owners can rename/)).toBeInTheDocument();
    expect(screen.queryByText("Delete this workspace")).not.toBeInTheDocument();
  });

  it("hides the danger zone from admins; only owners can delete", () => {
    role = "admin";
    renderWithQuery(<SettingsPage />);
    expect(screen.queryByText("Delete this workspace")).not.toBeInTheDocument();
  });

  it("makes an owner type the workspace name before it will delete", async () => {
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);
    const button = screen.getByRole("button", { name: "Delete workspace" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText(/Type/), "acme"); // wrong case
    expect(button).toBeDisabled();
    expect(removeWorkspace).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText(/Type/));
    await user.type(screen.getByLabelText(/Type/), "Acme");
    expect(button).toBeEnabled();
    await user.click(button);
    await waitFor(() => expect(removeWorkspace).toHaveBeenCalledWith("token", "org-1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows an error instead of leaving the page when deleting fails", async () => {
    removeWorkspace.mockRejectedValue(new ApiError("Requires owner role", 403));
    const user = userEvent.setup();
    renderWithQuery(<SettingsPage />);
    await user.type(screen.getByLabelText(/Type/), "Acme");
    await user.click(screen.getByRole("button", { name: "Delete workspace" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Requires owner role");
    expect(push).not.toHaveBeenCalled();
  });

  it("still shows your account when you have no workspace", () => {
    hasOrg = false;
    renderWithQuery(<SettingsPage />);
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText(/Create a workspace on the dashboard/)).toBeInTheDocument();
    expect(screen.queryByText("Delete this workspace")).not.toBeInTheDocument();
  });
});
