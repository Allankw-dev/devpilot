import { config } from "@/lib/config";

export type ServiceStatus = "ok" | "down";

export interface HealthResponse {
  status: "ok" | "degraded";
  product: string;
  environment: string;
  database: ServiceStatus;
  redis: ServiceStatus;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.apiUrl}/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });
  // /health returns a valid JSON body on 503 too, so only fail on unparseable responses
  const body = await res.json().catch(() => null);
  if (body === null) throw new ApiError(`Request failed: ${res.status}`, res.status);
  return body as T;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
};

// ---------- authenticated endpoints ----------

export type Role = "viewer" | "member" | "admin" | "owner";

export interface OrgWithRole {
  id: string;
  name: string;
  slug: string;
  created_at: string;
  role: Role;
}

export interface Me {
  user: { id: string; email: string; display_name: string | null };
  organizations: OrgWithRole[];
}

async function authed<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.apiUrl}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return body as T;
}

export const authedApi = {
  me: (token: string) => authed<Me>("/me", token),
  createOrg: (token: string, name: string) =>
    authed<OrgWithRole>("/orgs", token, { method: "POST", body: JSON.stringify({ name }) }),
};

// ---------- organizations, GitHub, repositories ----------

export interface GithubInstallation {
  id: string;
  org_id: string;
  installation_id: number;
  account_login: string;
  account_type: string;
  repository_selection: string;
  suspended: boolean;
  sync_status: "idle" | "running" | "failed";
  sync_error: string | null;
  last_synced_at: string | null;
  created_at: string;
}

export interface GithubStatus {
  configured: boolean;
  missing: string[];
  installations: GithubInstallation[];
}

export type CiState = "passing" | "failing" | "running" | "other" | "none";

export type IndexStatus = "none" | "queued" | "running" | "ready" | "failed";

export interface RepoIndex {
  status: IndexStatus;
  files: number;
  chunks: number;
  skipped_files: number;
  skipped_chunks: number; // dropped because they looked like credentials
  indexed_at: string | null;
  queued_at: string | null;
  error: string | null;
}

export interface Repo {
  id: string;
  full_name: string;
  private: boolean;
  archived: boolean;
  language: string | null;
  default_branch: string | null;
  html_url: string;
  pushed_at: string | null;
  open_pull_requests: number;
  open_issues: number;
  last_commit_at: string | null;
  ci: CiState;
  index: RepoIndex;
}

export interface Overview {
  repositories: number;
  open_pull_requests: number;
  open_issues: number;
  ci: { passing: number; failing: number; running: number; other: number; none: number };
  recent_commits: {
    sha: string;
    message: string;
    author: string | null;
    repository: string;
    committed_at: string | null;
    url: string | null;
  }[];
}

export const orgApi = {
  org: (token: string, orgId: string) => authed<OrgWithRole>(`/orgs/${orgId}`, token),
  overview: (token: string, orgId: string) => authed<Overview>(`/orgs/${orgId}/overview`, token),
  repos: (token: string, orgId: string) => authed<Repo[]>(`/orgs/${orgId}/repos`, token),
  githubStatus: (token: string, orgId: string) =>
    authed<GithubStatus>(`/orgs/${orgId}/github`, token),
  installUrl: (token: string, orgId: string) =>
    authed<{ url: string }>(`/orgs/${orgId}/github/install-url`, token, { method: "POST" }),
  sync: (token: string, orgId: string, installationId: string) =>
    authed<GithubInstallation>(`/orgs/${orgId}/github/installations/${installationId}/sync`, token, {
      method: "POST",
    }),
  disconnect: (token: string, orgId: string, installationId: string) =>
    authed<void>(`/orgs/${orgId}/github/installations/${installationId}`, token, {
      method: "DELETE",
    }),
  claim: (token: string, body: { code: string; installation_id: number; state: string | null }) =>
    authed<GithubInstallation>("/github/installations/claim", token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// ---------- AI ----------

export interface AiStatus {
  configured: boolean;
  provider: string | null;
  model: string | null;
  embeddings_configured: boolean;
  missing: string[]; // names of unset server settings; only filled in for admins
  usage: {
    days: number;
    requests: number;
    errors: number;
    input_tokens: number;
    output_tokens: number;
  };
}

export interface AiTestResult {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  reply: string;
}

export const aiApi = {
  status: (token: string, orgId: string) => authed<AiStatus>(`/orgs/${orgId}/ai`, token),
  test: (token: string, orgId: string) =>
    authed<AiTestResult>(`/orgs/${orgId}/ai/test`, token, { method: "POST" }),
};

// ---------- code index and search ----------

export interface SearchHit {
  repository_id: string;
  repository: string;
  path: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
  language: string | null;
  score: number;
  content: string;
}

export const codeApi = {
  startIndex: (token: string, orgId: string, repoId: string) =>
    authed<RepoIndex>(`/orgs/${orgId}/repos/${repoId}/index`, token, { method: "POST" }),
  search: (token: string, orgId: string, body: { query: string; repository_id?: string }) =>
    authed<{ results: SearchHit[] }>(`/orgs/${orgId}/search`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
