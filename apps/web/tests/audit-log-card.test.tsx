import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditLogCard } from "@/components/team/audit-log-card";
import { ApiError, type AuditEntry, type AuditPage, type Role } from "@/lib/api";
import { ME, ORG, renderWithQuery } from "./helpers";

const list = vi.fn();
let role: Role = "owner";

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: ME, orgs: [], org: { ...ORG, role }, select: vi.fn() }),
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, auditApi: { list: (...a: unknown[]) => list(...a) } };
});

const entry = (over: Partial<AuditEntry> = {}): AuditEntry => ({
  id: "e1",
  action: "member.added",
  actor_id: "u1",
  actor_email: "ada@example.com",
  actor_name: "Ada Lovelace",
  target_type: "user",
  target_id: "u2",
  details: { email: "grace@example.com", role: "member" },
  request_id: "req-12345678",
  created_at: new Date().toISOString(),
  ...over,
});
const page = (items: AuditEntry[], next: string | null = null): AuditPage => ({ items, next_before: next });

beforeEach(() => {
  role = "owner";
  list.mockReset().mockResolvedValue(page([entry()]));
});
afterEach(() => vi.restoreAllMocks());

describe("<AuditLogCard>", () => {
  it("lists who did what, newest first, as plain sentences", async () => {
    list.mockResolvedValue(
      page([
        entry({ id: "e2", action: "member.role_changed", details: { email: "grace@example.com", from: "member", to: "admin" } }),
        entry(),
      ]),
    );
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    const items = await screen.findAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Ada Lovelace changed grace@example.com from member to admin");
    expect(items[1]).toHaveTextContent("Ada Lovelace added grace@example.com as member");
    expect(list).toHaveBeenCalledWith("token", "org-1", undefined);
  });

  it("puts the request id in the tooltip so it can be matched to the server log", async () => {
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    const time = (await screen.findByRole("listitem")).querySelector("time");
    expect(time?.getAttribute("title")).toContain("request req-12345678");
  });

  it.each(["member", "viewer"] as Role[])("is not shown to a %s and never asks the API", async (r) => {
    role = r;
    const { container } = renderWithQuery(<AuditLogCard orgId="org-1" />);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(container).toBeEmptyDOMElement();
    expect(list).not.toHaveBeenCalled();
  });

  it("is shown to admins", async () => {
    role = "admin";
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    expect(await screen.findByText(/Ada Lovelace/)).toBeInTheDocument();
  });

  it("says so when nothing has been recorded", async () => {
    list.mockResolvedValue(page([]));
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    expect(await screen.findByText("Nothing recorded yet.")).toBeInTheDocument();
  });

  it("shows loading, then an error if the request fails", async () => {
    list.mockRejectedValue(new ApiError("boom", 500));
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load the audit log.");
  });

  it("loads older entries on request, using the marker from the last page", async () => {
    list.mockResolvedValueOnce(page([entry({ id: "e2" })], "marker-1")).mockResolvedValueOnce(
      page([entry({ id: "e1", actor_name: null, actor_email: "old@example.com" })]),
    );
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Load older entries" }));
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
    expect(list).toHaveBeenLastCalledWith("token", "org-1", "marker-1");
    expect(screen.queryByRole("button", { name: "Load older entries" })).not.toBeInTheDocument();
  });

  it("shows a removed user's entries without breaking", async () => {
    list.mockResolvedValue(page([entry({ actor_id: null, actor_name: null, actor_email: null })]));
    renderWithQuery(<AuditLogCard orgId="org-1" />);
    expect(await screen.findByText("A removed user")).toBeInTheDocument();
  });

  it("renders names typed by users as text, never as markup", async () => {
    list.mockResolvedValue(
      page([entry({ action: "team.created", details: { name: "<img src=x onerror=alert(1)>" } })]),
    );
    const { container } = renderWithQuery(<AuditLogCard orgId="org-1" />);
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});
