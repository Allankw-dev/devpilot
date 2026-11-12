import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    """Profile mirror of a Supabase Auth user. The id is the Supabase user id (JWT `sub`)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(80))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'member', 'admin', 'owner')", name="role_valid"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_teams_org_id_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(lazy="joined")


class GithubConnectRequest(Base):
    """An admin clicked "Connect GitHub" for an org. Matched to the install callback, single use."""

    __tablename__ = "github_connect_requests"

    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GithubInstallation(Base):
    __tablename__ = "github_installations"
    __table_args__ = (
        CheckConstraint("sync_status IN ('idle', 'running', 'failed')", name="sync_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    installation_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    account_id: Mapped[int] = mapped_column(BigInteger)
    account_login: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(20))
    repository_selection: Mapped[str] = mapped_column(String(10), default="all")
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(String(10), default="idle", server_default="idle")
    sync_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_error: Mapped[str | None] = mapped_column(String(500))
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "installation_id", "github_id", name="uq_repositories_installation_id_github_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("github_installations.id", ondelete="CASCADE"), index=True
    )
    github_id: Mapped[int] = mapped_column(BigInteger)
    full_name: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(100))
    owner_login: Mapped[str] = mapped_column(String(100))
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    default_branch: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    html_url: Mapped[str] = mapped_column(String(300))
    language: Mapped[str | None] = mapped_column(String(50))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_pull_requests_repo_id_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(10))
    draft: Mapped[bool] = mapped_column(Boolean, default=False)
    merged: Mapped[bool] = mapped_column(Boolean, default=False)
    author_login: Mapped[str | None] = mapped_column(String(100))
    html_url: Mapped[str] = mapped_column(String(300))
    gh_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gh_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gh_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Issue(Base):
    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("repo_id", "number", name="uq_issues_repo_id_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(10))
    author_login: Mapped[str | None] = mapped_column(String(100))
    html_url: Mapped[str] = mapped_column(String(300))
    comments: Mapped[int] = mapped_column(Integer, default=0)
    gh_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gh_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gh_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Commit(Base):
    __tablename__ = "commits"
    __table_args__ = (UniqueConstraint("repo_id", "sha", name="uq_commits_repo_id_sha"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    sha: Mapped[str] = mapped_column(String(40))
    message_headline: Mapped[str] = mapped_column(String(300))
    author_login: Mapped[str | None] = mapped_column(String(100))
    author_name: Mapped[str | None] = mapped_column(String(200))
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    html_url: Mapped[str | None] = mapped_column(String(300))


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        UniqueConstraint("repo_id", "run_id", name="uq_workflow_runs_repo_id_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(200))
    event: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str | None] = mapped_column(String(20))
    conclusion: Mapped[str | None] = mapped_column(String(20))
    head_branch: Mapped[str | None] = mapped_column(String(200))
    head_sha: Mapped[str | None] = mapped_column(String(40))
    run_number: Mapped[int | None] = mapped_column(Integer)
    html_url: Mapped[str | None] = mapped_column(String(300))
    gh_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gh_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookDelivery(Base):
    """Processed GitHub delivery ids, so a redelivered webhook is not applied twice."""

    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event: Mapped[str] = mapped_column(String(50))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class LlmUsage(Base):
    """One row per AI operation: who used it, which model, how many tokens. Never the prompt
    or the reply, so usage tracking can't leak repository code."""

    __tablename__ = "llm_usage"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error')", name="status_valid"),
        Index("ix_llm_usage_org_id_created_at", "org_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(20))  # generate | structured | tools | embed
    feature: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(10))
    error_code: Mapped[str | None] = mapped_column(String(30))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=1)  # provider calls, retries included
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------- code indexing ----------

# The pgvector column size is fixed by migration 0005. EMBEDDING_DIMENSIONS must match it,
# so changing the size later means a new migration plus re-indexing every repository.
EMBEDDING_COLUMN_DIMENSIONS = 768
_EmbeddingType = Vector(EMBEDDING_COLUMN_DIMENSIONS).with_variant(JSON(), "sqlite")


class RepositoryIndex(Base):
    """Indexing state of one repository. No row means it was never indexed."""

    __tablename__ = "repository_indexes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'failed')", name="status_valid"
        ),
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(10))
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # identifies the job that owns it
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commit_sha: Mapped[str | None] = mapped_column(String(40))  # last fully indexed commit
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    files_indexed: Mapped[int] = mapped_column(Integer, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0)
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_skipped: Mapped[int] = mapped_column(Integer, default=0)  # looked like secrets
    error: Mapped[str | None] = mapped_column(String(500))


class IndexedFile(Base):
    """What we last indexed per file, so an unchanged file is never embedded twice."""

    __tablename__ = "indexed_files"

    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    chunks_skipped: Mapped[int] = mapped_column(Integer, default=0)  # looked like secrets


class CodeChunk(Base):
    """A piece of source code plus its embedding. Holds repository content: it is removed
    with the repository, and only ever returned to members of the owning organization."""

    __tablename__ = "code_chunks"
    __table_args__ = (
        Index("ix_code_chunks_repo_id_path", "repo_id", "path"),
        Index(
            "ix_code_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    repo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id", ondelete="CASCADE")
    )
    path: Mapped[str] = mapped_column(String(500))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    language: Mapped[str | None] = mapped_column(String(30))
    symbol: Mapped[str | None] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(_EmbeddingType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
