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
  owner: string;
  description: string | null;
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

export interface AiUsageRow {
  operations: number;
  provider_calls: number; // what the provider counts: retries included
  errors: number;
  input_tokens: number;
  output_tokens: number;
}

export interface AiUsageDetail extends AiUsageRow {
  days: number;
  since: string;
  avg_latency_ms: number | null;
  calls_last_24h: number;
  daily_limit: number | null; // AI_DAILY_REQUEST_LIMIT, when the server has it set
  quota_hit_at: string | null; // last time the provider said a daily quota was used up
  by_day: (AiUsageRow & { day: string })[];
  by_feature: (AiUsageRow & { feature: string })[];
  by_model: {
    model: string;
    operations: number;
    provider_calls: number;
    errors: number;
    calls_last_24h: number;
  }[];
  errors_by_code: { code: string; count: number }[];
}

export const aiApi = {
  status: (token: string, orgId: string) => authed<AiStatus>(`/orgs/${orgId}/ai`, token),
  usage: (token: string, orgId: string, days: number) =>
    authed<AiUsageDetail>(`/orgs/${orgId}/ai/usage?days=${days}`, token),
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
  also_in: string[]; // other files holding exactly this code
}

export interface AskCitation {
  n: number; // the [n] used in the answer text
  repository_id: string;
  repository: string;
  path: string;
  start_line: number;
  end_line: number;
  symbol: string | null;
  score: number;
}

export interface AskResult {
  answer: string; // Markdown with [n] citations
  confidence: "high" | "medium" | "low";
  missing_context: string;
  citations: AskCitation[];
  sources_considered: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
}

export const codeApi = {
  startIndex: (token: string, orgId: string, repoId: string) =>
    authed<RepoIndex>(`/orgs/${orgId}/repos/${repoId}/index`, token, { method: "POST" }),
  ask: (token: string, orgId: string, body: { question: string; repository_id?: string }) =>
    authed<AskResult>(`/orgs/${orgId}/ask`, token, { method: "POST", body: JSON.stringify(body) }),
  search: (token: string, orgId: string, body: { query: string; repository_id?: string }) =>
    authed<{ results: SearchHit[] }>(`/orgs/${orgId}/search`, token, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};

// ---------- pull request reviews ----------

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export interface Finding {
  id: string;
  file: string;
  start_line: number; // 0 = the whole file
  end_line: number;
  category: string;
  severity: Severity;
  confidence: "high" | "medium" | "low";
  title: string;
  explanation: string;
  suggestion: string;
  origin: "ai" | "scan"; // scan = found by the credential scanner, not the model
  status: "open" | "dismissed";
}

export interface ReviewBrief {
  id: string;
  status: "queued" | "running" | "ready" | "failed";
  risk: "low" | "medium" | "high" | null;
  open_findings: number;
  serious_findings: number; // open critical or high
  finished_at: string | null;
  stale: boolean; // the pull request changed after this review
  error: string | null;
}

export interface PullRequestRow {
  id: string;
  repository_id: string;
  repository: string;
  number: number;
  title: string;
  state: string;
  draft: boolean;
  merged: boolean;
  author: string | null;
  html_url: string;
  updated_at: string | null;
  review: ReviewBrief | null;
}

export interface Review {
  id: string;
  pull_request_id: string;
  status: "queued" | "running" | "ready" | "failed";
  risk: "low" | "medium" | "high" | null;
  summary: string | null;
  notes: string | null; // what was and was not reviewed
  head_sha: string | null;
  model: string | null;
  files_total: number;
  files_reviewed: number;
  input_tokens: number;
  output_tokens: number;
  queued_at: string | null;
  finished_at: string | null;
  error: string | null;
  stale: boolean;
  findings: Finding[];
}

/** Filters and paging shared by the list endpoints. */
export interface PageOptions {
  repoId?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

function query(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    sp.set(k === "repoId" ? "repo_id" : k, String(v));
  }
  const text = sp.toString();
  return text ? `?${text}` : "";
}

export const reviewApi = {
  list: (token: string, orgId: string, state: "open" | "all", opts: PageOptions = {}) =>
    authed<PullRequestRow[]>(`/orgs/${orgId}/pull-requests${query({ state, ...opts })}`, token),
  pull: (token: string, orgId: string, prId: string) =>
    authed<PullRequestRow>(`/orgs/${orgId}/pull-requests/${prId}`, token),
  get: (token: string, orgId: string, prId: string) =>
    authed<Review | null>(`/orgs/${orgId}/pull-requests/${prId}/review`, token),
  start: (token: string, orgId: string, prId: string, force: boolean) =>
    authed<Review>(`/orgs/${orgId}/pull-requests/${prId}/review`, token, {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  setFinding: (token: string, orgId: string, findingId: string, status: "open" | "dismissed") =>
    authed<Finding>(`/orgs/${orgId}/review-findings/${findingId}`, token, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
};

// ---------- CI failure analysis ----------

export type CiCategory =
  | "test_failure"
  | "build_error"
  | "lint_or_types"
  | "dependency"
  | "configuration"
  | "infrastructure"
  | "flaky_or_timeout"
  | "unknown";

export interface CiAnalysisBrief {
  id: string;
  status: "queued" | "running" | "ready" | "failed";
  category: CiCategory | null;
  confidence: "high" | "medium" | "low" | null;
  finished_at: string | null;
  stale: boolean; // the run changed (was re-run) after this analysis
  error: string | null;
}

export interface CiRunRow {
  id: string;
  repository_id: string;
  repository: string;
  name: string | null;
  event: string | null;
  branch: string | null;
  run_number: number | null;
  status: string | null;
  conclusion: string | null;
  html_url: string | null;
  updated_at: string | null;
  analyzable: boolean; // a finished run that failed
  analysis: CiAnalysisBrief | null;
}

export interface CiAnalysis {
  id: string;
  run_id: string;
  status: "queued" | "running" | "ready" | "failed";
  summary: string | null;
  category: CiCategory | null;
  confidence: "high" | "medium" | "low" | null;
  likely_cause: string | null;
  suggested_fix: string | null;
  failed_steps: { job: string; step: string | null }[];
  evidence: { job: string; quote: string }[]; // copied from the logs and checked against them
  notes: string | null; // what was and was not read
  head_sha: string | null;
  model: string | null;
  jobs_total: number;
  jobs_analyzed: number;
  input_tokens: number;
  output_tokens: number;
  queued_at: string | null;
  finished_at: string | null;
  error: string | null;
  stale: boolean;
}

export const ciApi = {
  list: (token: string, orgId: string, state: "failed" | "all", opts: PageOptions = {}) =>
    authed<CiRunRow[]>(`/orgs/${orgId}/ci-runs${query({ state, ...opts })}`, token),
  run: (token: string, orgId: string, runId: string) =>
    authed<CiRunRow>(`/orgs/${orgId}/ci-runs/${runId}`, token),
  get: (token: string, orgId: string, runId: string) =>
    authed<CiAnalysis | null>(`/orgs/${orgId}/ci-runs/${runId}/analysis`, token),
  start: (token: string, orgId: string, runId: string, force: boolean) =>
    authed<CiAnalysis>(`/orgs/${orgId}/ci-runs/${runId}/analysis`, token, {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
};


// ---------- dashboard ----------

export interface DashboardData {
  days: number;
  since: string;
  github_connected: boolean;
  last_synced_at: string | null;
  stats: {
    repositories: number;
    open_pull_requests: number;
    open_issues: number;
    reviews_completed: number; // finished AI reviews in the period
    ci_analyses_completed: number; // finished CI analyses in the period
    failed_runs: number; // workflow runs that failed or timed out in the period
  };
  activity: { day: string; commits: number; pull_requests_opened: number }[];
  recent_pull_requests: {
    id: string;
    repository: string;
    number: number;
    title: string;
    author: string | null;
    draft: boolean;
    html_url: string;
    updated_at: string | null;
  }[];
  recent_reviews: {
    id: string;
    pull_request_id: string;
    repository: string;
    number: number;
    title: string;
    status: "queued" | "running" | "ready" | "failed";
    open_findings: number;
    serious_findings: number;
    finished_at: string | null;
  }[];
  recent_failed_runs: {
    id: string;
    repository: string;
    name: string | null;
    branch: string | null;
    conclusion: string | null;
    html_url: string | null;
    updated_at: string | null;
    analysis_status: "queued" | "running" | "ready" | "failed" | null;
  }[];
  open_issues: {
    id: string;
    repository: string;
    number: number;
    title: string;
    author: string | null;
    comments: number;
    html_url: string;
    updated_at: string | null;
  }[];
}

export const dashboardApi = {
  get: (token: string, orgId: string, days: number) =>
    authed<DashboardData>(`/orgs/${orgId}/dashboard?days=${days}`, token),
};


// ---------- repositories: commits and issues ----------

export interface CommitRow {
  sha: string;
  message: string;
  author: string | null;
  repository: string;
  committed_at: string | null;
  url: string | null;
}

export interface IssueRow {
  id: string;
  repository_id: string;
  repository: string;
  number: number;
  title: string;
  state: "open" | "closed";
  author: string | null;
  comments: number;
  html_url: string;
  created_at: string | null;
  updated_at: string | null;
}

export const repoApi = {
  commits: (token: string, orgId: string, repoId: string, opts: { limit?: number; offset?: number }) =>
    authed<CommitRow[]>(`/orgs/${orgId}/repos/${repoId}/commits${query(opts)}`, token),
};

export const issueApi = {
  list: (
    token: string,
    orgId: string,
    state: "open" | "closed" | "all",
    opts: PageOptions = {},
  ) => authed<IssueRow[]>(`/orgs/${orgId}/issues${query({ state, ...opts })}`, token),
};


// ---------- analytics ----------

export interface Analytics {
  days: number;
  since: string;
  reviews_finished: number;
  ci_analyses_finished: number;
  runs_succeeded: number;
  runs_failed: number;
  ci_success_rate: number | null; // null when there were no finished runs
  avg_review_seconds: number | null;
  avg_ci_analysis_seconds: number | null;
  findings_by_severity: { severity: "critical" | "high" | "medium" | "low" | "info"; count: number }[];
  by_day: {
    day: string;
    reviews_finished: number;
    ci_analyses_finished: number;
    runs_succeeded: number;
    runs_failed: number;
  }[];
}

export const analyticsApi = {
  get: (token: string, orgId: string, days: number) =>
    authed<Analytics>(`/orgs/${orgId}/analytics?days=${days}`, token),
};


// ---------- members, teams and workspace settings ----------

export interface Member {
  user_id: string;
  email: string;
  display_name: string | null;
  role: Role;
  joined_at: string;
}

export interface Team {
  id: string;
  org_id: string;
  name: string;
  member_count: number;
  created_at: string;
}

export interface TeamMember {
  user_id: string;
  email: string;
  display_name: string | null;
}

export const membersApi = {
  list: (token: string, orgId: string) => authed<Member[]>(`/orgs/${orgId}/members`, token),
  add: (token: string, orgId: string, email: string, role: Role) =>
    authed<Member>(`/orgs/${orgId}/members`, token, { method: "POST", body: JSON.stringify({ email, role }) }),
  setRole: (token: string, orgId: string, userId: string, role: Role) =>
    authed<Member>(`/orgs/${orgId}/members/${userId}`, token, { method: "PATCH", body: JSON.stringify({ role }) }),
  remove: (token: string, orgId: string, userId: string) =>
    authed<void>(`/orgs/${orgId}/members/${userId}`, token, { method: "DELETE" }),
};

export const teamsApi = {
  list: (token: string, orgId: string) => authed<Team[]>(`/orgs/${orgId}/teams`, token),
  create: (token: string, orgId: string, name: string) =>
    authed<Team>(`/orgs/${orgId}/teams`, token, { method: "POST", body: JSON.stringify({ name }) }),
  remove: (token: string, orgId: string, teamId: string) =>
    authed<void>(`/orgs/${orgId}/teams/${teamId}`, token, { method: "DELETE" }),
  members: (token: string, orgId: string, teamId: string) =>
    authed<TeamMember[]>(`/orgs/${orgId}/teams/${teamId}/members`, token),
  addMember: (token: string, orgId: string, teamId: string, userId: string) =>
    authed<TeamMember>(`/orgs/${orgId}/teams/${teamId}/members`, token, {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    }),
  removeMember: (token: string, orgId: string, teamId: string, userId: string) =>
    authed<void>(`/orgs/${orgId}/teams/${teamId}/members/${userId}`, token, { method: "DELETE" }),
};

export const workspaceApi = {
  rename: (token: string, orgId: string, name: string) =>
    authed<OrgWithRole>(`/orgs/${orgId}`, token, { method: "PATCH", body: JSON.stringify({ name }) }),
  remove: (token: string, orgId: string) => authed<void>(`/orgs/${orgId}`, token, { method: "DELETE" }),
};
