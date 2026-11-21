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

export function member(over: Partial<import("@/lib/api").Member> = {}): import("@/lib/api").Member {
  return {
    user_id: "u2",
    email: "grace@example.com",
    display_name: "Grace Hopper",
    role: "member",
    joined_at: new Date().toISOString(),
    ...over,
  };
}

export function answer(over: Partial<import("@/lib/api").AssistantMessage> = {}): import("@/lib/api").AssistantMessage {
  return {
    id: "m2",
    role: "assistant",
    content: "Login is handled in `login_user` [1].",
    citations: [
      { n: 1, repository_id: "repo-1", repository: "acme/web", path: "auth/login.py", start_line: 10, end_line: 42, symbol: "login_user", score: 0.9 },
    ],
    confidence: "high",
    missing_context: null,
    sources_considered: 6,
    model: "fake-model",
    input_tokens: 10,
    output_tokens: 5,
    created_at: new Date().toISOString(),
    ...over,
  };
}

export function question(text = "Where is login handled?", id = "m1"): import("@/lib/api").AssistantMessage {
  return { ...answer({ id, role: "user", content: text, citations: [], confidence: null, sources_considered: null, model: null }) };
}

export function conversation(over: Partial<import("@/lib/api").Conversation> = {}): import("@/lib/api").Conversation {
  return {
    id: "c1",
    title: "Where is login handled?",
    repository_id: "repo-1",
    repository: "acme/web",
    message_count: 2,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...over,
  };
}
