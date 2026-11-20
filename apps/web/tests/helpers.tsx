import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

import type { CiRunRow, Me, OrgWithRole, PullRequestRow, Repo } from "@/lib/api";

export function renderWithQuery(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

export const ORG: OrgWithRole = {
  id: "org-1",
  name: "Acme",
  slug: "acme",
  created_at: "2026-01-01T00:00:00Z",
  role: "owner",
};

export const ME: Me = {
  user: { id: "u1", email: "ada@example.com", display_name: "Ada Lovelace" },
  organizations: [ORG],
};

export function repo(over: Partial<Repo> = {}): Repo {
  return {
    id: "repo-1",
    full_name: "acme/web",
    owner: "acme",
    description: "The web app",
    private: false,
    archived: false,
    language: "TypeScript",
    default_branch: "main",
    html_url: "https://github.com/acme/web",
    pushed_at: new Date().toISOString(),
    open_pull_requests: 2,
    open_issues: 3,
    last_commit_at: new Date().toISOString(),
    ci: "passing",
    index: {
      status: "none", files: 0, chunks: 0, skipped_files: 0, skipped_chunks: 0,
      indexed_at: null, queued_at: null, error: null,
    },
    ...over,
  };
}

export function pull(over: Partial<PullRequestRow> = {}): PullRequestRow {
  return {
    id: "pr-1",
    repository_id: "repo-1",
    repository: "acme/web",
    number: 7,
    title: "Fix login redirect",
    state: "open",
    draft: false,
    merged: false,
    author: "ada",
    html_url: "https://github.com/acme/web/pull/7",
    updated_at: new Date().toISOString(),
    review: null,
    ...over,
  };
}

export function run(over: Partial<CiRunRow> = {}): CiRunRow {
  return {
    id: "run-1",
    repository_id: "repo-1",
    repository: "acme/web",
    name: "CI",
    event: "push",
    branch: "main",
    run_number: 7,
    status: "completed",
    conclusion: "failure",
    html_url: "https://github.com/acme/web/actions/runs/7",
    updated_at: new Date().toISOString(),
    analyzable: true,
    analysis: null,
    ...over,
  };
}

export function installation(over: Partial<import("@/lib/api").GithubInstallation> = {}): import("@/lib/api").GithubInstallation {
  return {
    id: "inst-1",
    org_id: "org-1",
    installation_id: 777,
    account_login: "acme-inc",
    account_type: "Organization",
    repository_selection: "all",
    suspended: false,
    sync_status: "idle",
    sync_error: null,
    last_synced_at: new Date().toISOString(),
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}
