import uuid
from datetime import datetime
from typing import Annotated

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


class RepoOut(BaseModel):
    id: uuid.UUID
    full_name: str
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


class AiTestOut(BaseModel):
    ok: bool
    provider: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    reply: str
