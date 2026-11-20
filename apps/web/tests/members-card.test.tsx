import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MembersCard } from "@/components/team/members-card";
import { ApiError, type Role } from "@/lib/api";
import { member, ME, ORG, renderWithQuery } from "./helpers";

const list = vi.fn();
const add = vi.fn();
const setRole = vi.fn();
const remove = vi.fn();
const push = vi.fn();
let role: Role = "owner";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: ME, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    membersApi: {
      list: (...a: unknown[]) => list(...a),
      add: (...a: unknown[]) => add(...a),
      setRole: (...a: unknown[]) => setRole(...a),
      remove: (...a: unknown[]) => remove(...a),
    },
  };
});

const self = member({ user_id: "u1", email: "ada@example.com", display_name: "Ada Lovelace", role: "owner" });
const grace = member({ user_id: "u2" });
const admin = member({ user_id: "u3", email: "linus@example.com", display_name: "Linus", role: "admin" });
const viewer = member({ user_id: "u4", email: "view@example.com", display_name: null, role: "viewer" });

beforeEach(() => {
  role = "owner";
  list.mockReset().mockResolvedValue([self, grace, admin, viewer]);
  add.mockReset().mockResolvedValue(member());
  setRole.mockReset().mockResolvedValue(member());
  remove.mockReset().mockResolvedValue(undefined);
  push.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("<MembersCard> as an owner", () => {
  it("lists members with their names, emails and a marker for you", async () => {
    renderWithQuery(<MembersCard orgId="org-1" />);
    const you = (await screen.findByText("Ada Lovelace")).closest("li")!;
    expect(within(you).getByText("you")).toBeInTheDocument();
    expect(screen.getByText(/grace@example.com/)).toBeInTheDocument();
    expect(screen.getByText("view@example.com")).toBeInTheDocument(); // no name: the email is the title
  });

  it("lets you change other people's roles but not choose your own", async () => {
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByLabelText("Role of Ada Lovelace")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Role of Grace Hopper"), "admin");
    await waitFor(() => expect(setRole).toHaveBeenCalledWith("token", "org-1", "u2", "admin"));
  });

  it("removes a member only after you confirm", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: "Remove Grace Hopper" }));
    expect(confirm).toHaveBeenCalledWith("Remove Grace Hopper from this workspace?");
    expect(remove).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Remove Grace Hopper" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("token", "org-1", "u2"));
  });

  it("adds a member by email with a chosen role", async () => {
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await screen.findByText("Ada Lovelace");
    const addButton = screen.getByRole("button", { name: "Add" });
    expect(addButton).toBeDisabled(); // an email is required
    await user.type(screen.getByLabelText("Email address"), " new@example.com ");
    await user.selectOptions(screen.getByLabelText("Role"), "viewer");
    await user.click(addButton);
    await waitFor(() => expect(add).toHaveBeenCalledWith("token", "org-1", "new@example.com", "viewer"));
    await waitFor(() => expect(screen.getByLabelText("Email address")).toHaveValue("")); // form clears on success
  });

  it("shows the server's reason when adding fails", async () => {
    add.mockRejectedValue(new ApiError("No user with that email has signed in yet. Ask them to sign up first.", 404));
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await screen.findByText("Ada Lovelace");
    await user.type(screen.getByLabelText("Email address"), "ghost@example.com");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No user with that email has signed in yet");
  });

  it("lets you leave, and takes you to the dashboard afterwards", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: "Leave" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("token", "org-1", "u1"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the last-owner rule from the server instead of leaving silently", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    remove.mockRejectedValue(new ApiError("An organization must keep at least one owner", 409));
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: "Leave" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must keep at least one owner");
    expect(push).not.toHaveBeenCalled();
  });
});

describe("<MembersCard> for other roles", () => {
  it("lets an admin manage members and viewers but not admins or owners, and grant only those roles", async () => {
    role = "admin";
    renderWithQuery(<MembersCard orgId="org-1" />);
    await screen.findByText("Ada Lovelace");
    expect(screen.getByLabelText("Role of Grace Hopper")).toBeInTheDocument();
    expect(screen.getByLabelText("Role of view@example.com")).toBeInTheDocument();
    expect(screen.queryByLabelText("Role of Linus")).not.toBeInTheDocument(); // another admin
    expect(screen.queryByRole("button", { name: "Remove Linus" })).not.toBeInTheDocument();
    const options = within(screen.getByLabelText("Role")).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Viewer", "Member"]);
  });

  it("is read-only for members: no controls, only a note", async () => {
    role = "member";
    renderWithQuery(<MembersCard orgId="org-1" />);
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByLabelText("Email address")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Only admins and owners can add or change members/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave" })).toBeInTheDocument(); // anyone may leave
  });

  it("shows a load error with a retry", async () => {
    list.mockRejectedValueOnce(new Error("boom")).mockResolvedValue([self]);
    const user = userEvent.setup();
    renderWithQuery(<MembersCard orgId="org-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load members.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
  });
});
