import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrationsPage } from "@/components/integrations/integrations-page";
import { installation, ORG, renderWithQuery } from "./helpers";

const status = vi.fn();
let role: "owner" | "member" = "owner";
let hasOrg = true;

vi.mock("@/lib/supabase/token", () => ({ accessToken: async () => "token" }));
vi.mock("@/components/shell/workspace-provider", () => ({
  useWorkspace: () => ({ me: {}, orgs: [], org: hasOrg ? { ...ORG, role } : null, select: vi.fn() }),
}));
vi.mock("@/components/system-status", () => ({ SystemStatus: () => <div>service status list</div> }));
vi.mock("@/components/github-panel", () => ({
  GithubPanel: ({ isAdmin }: { isAdmin: boolean }) => <div>github panel (admin: {String(isAdmin)})</div>,
}));
vi.mock("@/components/ai-panel", () => ({
  AiPanel: ({ isAdmin }: { isAdmin: boolean }) => <div>ai panel (admin: {String(isAdmin)})</div>,
}));
vi.mock("@/lib/api", async (orig) => {
  const actual = await orig<typeof import("@/lib/api")>();
  return { ...actual, orgApi: { ...actual.orgApi, githubStatus: (...a: unknown[]) => status(...a) } };
});

beforeEach(() => {
  role = "owner";
  hasOrg = true;
  status.mockReset().mockResolvedValue({ configured: true, missing: [], installations: [installation()] });
});

describe("<IntegrationsPage>", () => {
  it("asks you to create a workspace first when you have none", () => {
    hasOrg = false;
    renderWithQuery(<IntegrationsPage />);
    expect(screen.getByText(/Create a workspace on the dashboard first/)).toBeInTheDocument();
  });

  it("states that access is read-only and that secrets are never shown", () => {
    renderWithQuery(<IntegrationsPage />);
    expect(screen.getByText("read-only")).toBeInTheDocument();
    expect(screen.getByText(/never writes to GitHub/)).toBeInTheDocument();
    expect(screen.getByText(/Secret values are never shown here/)).toBeInTheDocument();
  });

  it("shows whether the server can reach what it depends on", () => {
    renderWithQuery(<IntegrationsPage />);
    expect(screen.getByRole("region", { name: "Services" })).toHaveTextContent("service status list");
  });

  it("shows the GitHub and AI provider panels, telling them whether you are an admin", () => {
    renderWithQuery(<IntegrationsPage />);
    expect(screen.getByText("github panel (admin: true)")).toBeInTheDocument();
    expect(screen.getByText("ai panel (admin: true)")).toBeInTheDocument();
  });

  it("is not admin-capable for plain members", () => {
    role = "member";
    renderWithQuery(<IntegrationsPage />);
    expect(screen.getByText("github panel (admin: false)")).toBeInTheDocument();
    expect(screen.getByText("ai panel (admin: false)")).toBeInTheDocument();
  });

  it("marks GitHub Actions available once GitHub is connected, and links to the CI/CD page", async () => {
    renderWithQuery(<IntegrationsPage />);
    expect(await screen.findByText("available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CI/CD page" })).toHaveAttribute("href", "/ci-cd");
    expect(screen.getByText(/Actions: read/)).toBeInTheDocument();
  });

  it("says GitHub Actions needs GitHub when nothing is connected", async () => {
    status.mockResolvedValue({ configured: true, missing: [], installations: [] });
    renderWithQuery(<IntegrationsPage />);
    expect(await screen.findByText("needs GitHub")).toBeInTheDocument();
    expect(screen.queryByText("available")).not.toBeInTheDocument();
  });
});
