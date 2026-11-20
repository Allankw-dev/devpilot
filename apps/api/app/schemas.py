import uuid
from datetime import date as Date
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.roles import Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None


class OrgOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrgWithRole(OrgOut):
    role: Role


class MeOut(BaseModel):
    user: UserOut
    organizations: list[OrgWithRole]


class OrgCreate(BaseModel):
    name: Name


class OrgUpdate(BaseModel):
    name: Name


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: Role
    joined_at: datetime


class MemberAdd(BaseModel):
    email: Email
    role: Role = Role.member


class MemberRoleUpdate(BaseModel):
    role: Role


class TeamCreate(BaseModel):
    name: Name


class TeamOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    member_count: int = Field(ge=0)
    created_at: datetime


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID


# ---------- GitHub ----------


class GithubInstallationOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    installation_id: int
    account_login: str
    account_type: str
    repository_selection: str
    suspended: bool
    sync_status: str
    sync_error: str | None
    last_synced_at: datetime | None
    created_at: datetime


class GithubStatusOut(BaseModel):
    configured: bool
    missing: list[str]  # names of unset settings; only shown to admins
    installations: list[GithubInstallationOut]


class InstallUrlOut(BaseModel):
    url: str


class ClaimRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)
    installation_id: int = Field(gt=0)
    state: str | None = Field(default=None, max_length=100)


class IndexOut(BaseModel):
    """Code-index state of one repository. status is none until it is first indexed."""

    status: str  # none | queued | running | ready | failed
    files: int
    chunks: int
    skipped_files: int
    skipped_chunks: int  # dropped because they looked like credentials
    indexed_at: datetime | None
    queued_at: datetime | None
    error: str | None


class RepoOut(BaseModel):
    id: uuid.UUID
    full_name: str
    owner: str
    description: str | None
    private: bool
    archived: bool
    language: str | None
    default_branch: str | None
    html_url: str
    pushed_at: datetime | None
    open_pull_requests: int
    open_issues: int
    last_commit_at: datetime | None
    ci: str  # passing | failing | running | other | none
    index: IndexOut


class CommitOut(BaseModel):
    sha: str
    message: str
    author: str | None
    repository: str
    committed_at: datetime | None
    url: str | None


class CiSummary(BaseModel):
    passing: int
    failing: int
    running: int
    other: int
    none: int


class OverviewOut(BaseModel):
    repositories: int
    open_pull_requests: int
    open_issues: int
    ci: CiSummary
    recent_commits: list[CommitOut]


# ---------- AI ----------


class AiUsageOut(BaseModel):
    days: int
    requests: int
    errors: int
    input_tokens: int
    output_tokens: int


class AiStatusOut(BaseModel):
    configured: bool
    provider: str | None
    model: str | None
    embeddings_configured: bool
    missing: list[str]  # names of unset settings; only shown to admins
    usage: AiUsageOut


class AiUsageDayOut(BaseModel):
    day: Date  # UTC
    operations: int
    provider_calls: int  # what the provider counts: retries included
    errors: int
    input_tokens: int
    output_tokens: int


class AiUsageFeatureOut(BaseModel):
    feature: str
    operations: int
    provider_calls: int
    errors: int
    input_tokens: int
    output_tokens: int


class AiUsageModelOut(BaseModel):
    model: str
    operations: int
    provider_calls: int
    errors: int
    calls_last_24h: int  # daily quotas are usually per model


class AiUsageErrorOut(BaseModel):
    code: str  # e.g. quota_exhausted, rate_limited, unavailable
    count: int


class AiUsageDetailOut(BaseModel):
    days: int
    since: Date  # first day shown (UTC)
    operations: int
    provider_calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    avg_latency_ms: int | None  # successful operations only
    calls_last_24h: int  # across all models
    daily_limit: int | None  # AI_DAILY_REQUEST_LIMIT, when set
    quota_hit_at: datetime | None  # last time the provider said a daily quota was used up
    by_day: list[AiUsageDayOut]
    by_feature: list[AiUsageFeatureOut]
    by_model: list[AiUsageModelOut]
    errors_by_code: list[AiUsageErrorOut]


class AiTestOut(BaseModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    reply: str


# ---------- code search ----------


class SearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=500)
    repository_id: uuid.UUID | None = None
    limit: int = Field(default=8, ge=1, le=20)


class SearchHit(BaseModel):
    repository_id: uuid.UUID
    repository: str
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    language: str | None
    score: float  # cosine similarity, higher is closer
    content: str
    also_in: list[str] = []  # other files holding exactly this code (copies, forks)


class SearchOut(BaseModel):
    results: list[SearchHit]


# ---------- questions about code ----------


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=1000)
    repository_id: uuid.UUID | None = None


class AskCitation(BaseModel):
    n: int  # the [n] used in the answer text
    repository_id: uuid.UUID
    repository: str
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    score: float


class AskOut(BaseModel):
    answer: str  # Markdown with [n] citations
    confidence: str  # high | medium | low
    missing_context: str
    citations: list[AskCitation]
    sources_considered: int
    model: str
    input_tokens: int
    output_tokens: int


# ---------- pull request reviews ----------


class FindingOut(BaseModel):
    id: uuid.UUID
    file: str
    start_line: int  # 0 = the whole file
    end_line: int
    category: str
    severity: str  # critical | high | medium | low | info
    confidence: str  # high | medium | low
    title: str
    explanation: str
    suggestion: str
    origin: str  # ai = the model, scan = the credential scanner
    status: str  # open | dismissed


class FindingUpdate(BaseModel):
    status: Literal["open", "dismissed"]


class ReviewStart(BaseModel):
    force: bool = False  # review again even if the pull request has not changed


class ReviewBriefOut(BaseModel):
    id: uuid.UUID
    status: str  # queued | running | ready | failed
    risk: str | None
    open_findings: int
    serious_findings: int  # open critical or high
    finished_at: datetime | None
    stale: bool  # the pull request changed after this review
    error: str | None


class PullRequestOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    repository: str
    number: int
    title: str
    state: str
    draft: bool
    merged: bool
    author: str | None
    html_url: str
    updated_at: datetime | None
    review: ReviewBriefOut | None


class ReviewOut(BaseModel):
    id: uuid.UUID
    pull_request_id: uuid.UUID
    status: str
    risk: str | None
    summary: str | None
    notes: str | None  # what was and wasn't reviewed
    head_sha: str | None
    model: str | None
    files_total: int
    files_reviewed: int
    input_tokens: int
    output_tokens: int
    queued_at: datetime | None
    finished_at: datetime | None
    error: str | None
    stale: bool
    findings: list[FindingOut]


# ---------- CI failure analysis ----------


class CiAnalysisStart(BaseModel):
    force: bool = False  # analyze again even if the run has not changed


class CiAnalysisBriefOut(BaseModel):
    id: uuid.UUID
    status: str  # queued | running | ready | failed
    category: str | None
    confidence: str | None
    finished_at: datetime | None
    stale: bool  # the run changed (was re-run) after this analysis
    error: str | None


class CiRunOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    repository: str
    name: str | None
    event: str | None
    branch: str | None
    run_number: int | None
    status: str | None
    conclusion: str | None
    html_url: str | None
    updated_at: datetime | None
    analyzable: bool  # a finished run that failed
    analysis: CiAnalysisBriefOut | None


class CiFailedStepOut(BaseModel):
    job: str
    step: str | None


class CiEvidenceOut(BaseModel):
    job: str
    quote: str  # copied from the log and checked against it


class CiAnalysisOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID  # our workflow run record
    status: str  # queued | running | ready | failed
    summary: str | None
    category: str | None
    confidence: str | None
    likely_cause: str | None
    suggested_fix: str | None
    failed_steps: list[CiFailedStepOut]
    evidence: list[CiEvidenceOut]
    notes: str | None  # what was and wasn't read
    head_sha: str | None
    model: str | None
    jobs_total: int
    jobs_analyzed: int
    input_tokens: int
    output_tokens: int
    queued_at: datetime | None
    finished_at: datetime | None
    error: str | None
    stale: bool


# ---------- dashboard ----------


class DashboardStatsOut(BaseModel):
    repositories: int
    open_pull_requests: int
    open_issues: int
    reviews_completed: int  # finished AI reviews in the period
    ci_analyses_completed: int  # finished CI analyses in the period
    failed_runs: int  # workflow runs that failed or timed out in the period


class DashboardDayOut(BaseModel):
    day: Date  # UTC
    commits: int
    pull_requests_opened: int


class DashboardPullRequestOut(BaseModel):
    id: uuid.UUID
    repository: str
    number: int
    title: str
    author: str | None
    draft: bool
    html_url: str
    updated_at: datetime | None


class DashboardIssueOut(BaseModel):
    id: uuid.UUID
    repository: str
    number: int
    title: str
    author: str | None
    comments: int
    html_url: str
    updated_at: datetime | None


class DashboardReviewOut(BaseModel):
    id: uuid.UUID
    pull_request_id: uuid.UUID
    repository: str
    number: int
    title: str
    status: str  # queued | running | ready | failed
    open_findings: int
    serious_findings: int  # critical or high
    finished_at: datetime | None


class DashboardRunOut(BaseModel):
    id: uuid.UUID
    repository: str
    name: str | None
    branch: str | None
    conclusion: str | None
    html_url: str | None
    updated_at: datetime | None
    analysis_status: str | None  # latest AI analysis of this run, if any


class DashboardOut(BaseModel):
    days: int
    since: Date
    github_connected: bool  # at least one GitHub installation is connected
    last_synced_at: datetime | None
    stats: DashboardStatsOut
    activity: list[DashboardDayOut]
    recent_pull_requests: list[DashboardPullRequestOut]
    recent_reviews: list[DashboardReviewOut]
    recent_failed_runs: list[DashboardRunOut]
    open_issues: list[DashboardIssueOut]


# ---------- issues ----------


class IssueOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    repository: str
    number: int
    title: str
    state: str  # open | closed
    author: str | None
    comments: int
    html_url: str
    created_at: datetime | None
    updated_at: datetime | None


# ---------- analytics ----------


class AnalyticsDayOut(BaseModel):
    day: Date  # UTC
    reviews_finished: int
    ci_analyses_finished: int
    runs_succeeded: int
    runs_failed: int  # failure or timed out


class AnalyticsSeverityOut(BaseModel):
    severity: str  # critical | high | medium | low | info
    count: int


class AnalyticsOut(BaseModel):
    days: int
    since: Date
    reviews_finished: int
    ci_analyses_finished: int
    runs_succeeded: int
    runs_failed: int
    ci_success_rate: float | None  # succeeded / (succeeded + failed); None when there were none
    avg_review_seconds: int | None  # from start to finish, finished reviews only
    avg_ci_analysis_seconds: int | None
    findings_by_severity: list[AnalyticsSeverityOut]  # every severity, even when zero
    by_day: list[AnalyticsDayOut]
