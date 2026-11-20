import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TeamsCard } from "@/components/team/teams-card";
import { ApiError, type Role, type Team } from "@/lib/api";
import { member, ME, ORG, renderWithQuery } from "./helpers";

const teamsList = vi.fn();
const create = vi.fn();
const removeTeam = vi.fn();
const teamMembers = vi.fn();
const addMember = vi.fn();
const removeMember = vi.fn();
const orgMembers = vi.fn();
let role: Role = "owner";

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: ME, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    membersApi: { ...actual.membersApi, list: (...a: unknown[]) => orgMembers(...a) },
    teamsApi: {
      list: (...a: unknown[]) => teamsList(...a),
      create: (...a: unknown[]) => create(...a),
      remove: (...a: unknown[]) => removeTeam(...a),
      members: (...a: unknown[]) => teamMembers(...a),
      addMember: (...a: unknown[]) => addMember(...a),
      removeMember: (...a: unknown[]) => removeMember(...a),
    },
  };
});

const team = (over: Partial<Team> = {}): Team => ({
  id: "t1", org_id: "org-1", name: "Backend", member_count: 1, created_at: "2026-01-01T00:00:00Z", ...over,
});

beforeEach(() => {
  role = "owner";
  teamsList.mockReset().mockResolvedValue([team()]);
  create.mockReset().mockResolvedValue(team({ id: "t2", name: "Frontend", member_count: 0 }));
  removeTeam.mockReset().mockResolvedValue(undefined);
  teamMembers.mockReset().mockResolvedValue([{ user_id: "u2", email: "grace@example.com", display_name: "Grace Hopper" }]);
  addMember.mockReset().mockResolvedValue({});
  removeMember.mockReset().mockResolvedValue(undefined);
  orgMembers.mockReset().mockResolvedValue([member({ user_id: "u2" }), member({ user_id: "u3", email: "linus@example.com", display_name: "Linus" })]);
});
afterEach(() => vi.restoreAllMocks());

describe("<TeamsCard>", () => {
  it("lists teams with member counts and explains when there are none", async () => {
    teamsList.mockResolvedValue([team(), team({ id: "t2", name: "Solo", member_count: 0 })]);
    renderWithQuery(<TeamsCard orgId="org-1" />);
    expect(await screen.findByRole("button", { name: /^Backend/ })).toHaveTextContent("1 member");
    expect(screen.getByRole("button", { name: /^Solo/ })).toHaveTextContent("0 members");
  });

  it("says so, and offers creation to admins only, when there are no teams", async () => {
    teamsList.mockResolvedValue([]);
    const { unmount } = renderWithQuery(<TeamsCard orgId="org-1" />);
    expect(await screen.findByText(/No teams yet\. Create one below\./)).toBeInTheDocument();
    unmount();
    role = "member";
    renderWithQuery(<TeamsCard orgId="org-1" />);
    expect(await screen.findByText(/An admin can create teams/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Team name")).not.toBeInTheDocument();
  });

  it("creates a team once the name is long enough", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await screen.findByRole("button", { name: /^Backend/ });
    const button = screen.getByRole("button", { name: "Create" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Team name"), "F");
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Team name"), "rontend");
    await user.click(button);
    await waitFor(() => expect(create).toHaveBeenCalledWith("token", "org-1", "Frontend"));
  });

  it("shows the server's message when a team name is taken", async () => {
    create.mockRejectedValue(new ApiError("A team with that name already exists", 409));
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await screen.findByRole("button", { name: /^Backend/ });
    await user.type(screen.getByLabelText("Team name"), "Backend");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already exists");
  });

  it("opens a team to show who is on it", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    const toggle = await screen.findByRole("button", { name: /^Backend/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(teamMembers).toHaveBeenCalledWith("token", "org-1", "t1");
  });

  it("offers only members who aren't on the team yet, and adds one", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: /^Backend/ }));
    const select = await screen.findByLabelText("Add a member to Backend");
    await waitFor(() => expect(within(select).getAllByRole("option")).toHaveLength(2)); // placeholder + Linus
    expect(within(select).queryByText("Grace Hopper")).not.toBeInTheDocument();
    await user.selectOptions(select, "u3");
    await user.click(screen.getByRole("button", { name: "Add to team" }));
    await waitFor(() => expect(addMember).toHaveBeenCalledWith("token", "org-1", "t1", "u3"));
  });

  it("removes someone from a team", async () => {
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: /^Backend/ }));
    await user.click(await screen.findByRole("button", { name: "Remove Grace Hopper from Backend" }));
    await waitFor(() => expect(removeMember).toHaveBeenCalledWith("token", "org-1", "t1", "u2"));
  });

  it("deletes a team only after you confirm", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: "Delete team Backend" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Delete the team “Backend”?"));
    expect(removeTeam).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Delete team Backend" }));
    await waitFor(() => expect(removeTeam).toHaveBeenCalledWith("token", "org-1", "t1"));
  });

  it("is read-only for members: they can look but not change anything", async () => {
    role = "member";
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    await user.click(await screen.findByRole("button", { name: /^Backend/ }));
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete team/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove Grace Hopper/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Add a member to Backend")).not.toBeInTheDocument();
    expect(orgMembers).not.toHaveBeenCalled(); // no reason to load the candidate list
  });

  it("shows a load error with a retry", async () => {
    teamsList.mockRejectedValueOnce(new Error("boom")).mockResolvedValue([team()]);
    const user = userEvent.setup();
    renderWithQuery(<TeamsCard orgId="org-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load teams.");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: /^Backend/ })).toBeInTheDocument();
  });
});
