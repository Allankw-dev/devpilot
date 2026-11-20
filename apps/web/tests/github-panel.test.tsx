import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GithubPanel } from "@/components/github-panel";
import { installation, renderWithQuery } from "./helpers";

const status = vi.fn();
const installUrl = vi.fn();
const sync = vi.fn();
const disconnect = vi.fn();

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return {
    ...actual,
    orgApi: {
      ...actual.orgApi,
      githubStatus: (...a: unknown[]) => status(...a),
      installUrl: (...a: unknown[]) => installUrl(...a),
      sync: (...a: unknown[]) => sync(...a),
      disconnect: (...a: unknown[]) => disconnect(...a),
    },
  };
});

beforeEach(() => {
  status.mockReset();
  installUrl.mockReset();
  sync.mockReset().mockResolvedValue({});
  disconnect.mockReset().mockResolvedValue({});
});
afterEach(() => vi.restoreAllMocks());

describe("<GithubPanel>", () => {
  it("says what is missing when GitHub isn't set up on the server", async () => {
    status.mockResolvedValue({ configured: false, missing: ["GITHUB_APP_ID", "GITHUB_PRIVATE_KEY"], installations: [] });
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    expect(await screen.findByText(/GitHub isn’t set up on the server yet/)).toBeInTheDocument();
    expect(screen.getByText("GITHUB_APP_ID, GITHUB_PRIVATE_KEY")).toBeInTheDocument(); // names only, never values
    expect(screen.queryByRole("button", { name: "Connect GitHub" })).not.toBeInTheDocument();
  });

  it("lets an admin connect GitHub when nothing is connected", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [] });
    installUrl.mockResolvedValue({ url: "https://github.com/apps/devpilot/installations/new" });
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign } as unknown as Location);
    const user = userEvent.setup();
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    await user.click(await screen.findByRole("button", { name: "Connect GitHub" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://github.com/apps/devpilot/installations/new"));
    expect(installUrl).toHaveBeenCalledWith("token", "org-1");
  });

  it("tells non-admins to ask an admin instead of offering to connect", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [] });
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin={false} />);
    expect(await screen.findByText(/An admin of this organization needs to connect GitHub/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect GitHub" })).not.toBeInTheDocument();
  });

  it("shows each connection with its sync state", async () => {
    status.mockResolvedValue({
      configured: true, missing: [],
      installations: [
        installation(),
        installation({ id: "inst-2", account_login: "paused-org", suspended: true }),
        installation({ id: "inst-3", account_login: "busy-org", sync_status: "running" }),
        installation({ id: "inst-4", account_login: "bad-org", sync_error: "GitHub rate limit reached." }),
      ],
    });
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    expect(await screen.findByText("acme-inc")).toBeInTheDocument();
    expect(screen.getByText("Suspended on GitHub")).toBeInTheDocument();
    expect(screen.getByText("Syncing…")).toBeInTheDocument();
    expect(screen.getByText("GitHub rate limit reached.")).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "Sync now" });
    expect(buttons[1]).toBeDisabled(); // suspended
    expect(buttons[2]).toBeDisabled(); // already syncing
    expect(buttons[0]).toBeEnabled();
  });

  it("syncs a connection on request", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [installation()] });
    const user = userEvent.setup();
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    await user.click(await screen.findByRole("button", { name: "Sync now" }));
    await waitFor(() => expect(sync).toHaveBeenCalledWith("token", "org-1", "inst-1"));
  });

  it("asks before disconnecting, and does nothing if you cancel", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [installation()] });
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const user = userEvent.setup();
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    await user.click(await screen.findByRole("button", { name: "Disconnect" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("Disconnect acme-inc?"));
    expect(disconnect).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(disconnect).toHaveBeenCalledWith("token", "org-1", "inst-1"));
  });

  it("gives non-admins no way to sync or disconnect", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [installation()] });
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin={false} />);
    expect(await screen.findByText("acme-inc")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sync now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disconnect" })).not.toBeInTheDocument();
  });

  it("shows errors from sync and from loading", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [installation()] });
    sync.mockRejectedValue(new Error("A sync is already running"));
    const user = userEvent.setup();
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    await user.click(await screen.findByRole("button", { name: "Sync now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A sync is already running");
  });

  it("shows a load error", async () => {
    status.mockRejectedValue(new Error("boom"));
    renderWithQuery(<GithubPanel orgId="org-1" isAdmin />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load GitHub status.");
  });
});
