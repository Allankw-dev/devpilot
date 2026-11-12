import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import AnyMember, DbSession
from app.api.v1.indexing import index_out
from app.db.models import (
    Commit,
    GithubInstallation,
    Issue,
    PullRequest,
    Repository,
    RepositoryIndex,
    WorkflowRun,
)
from app.schemas import CiSummary, CommitOut, OverviewOut, RepoOut

router = APIRouter(tags=["repositories"])


def _repos(db: Session, org_id: uuid.UUID) -> list[Repository]:
    return list(
        db.scalars(
            select(Repository)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(GithubInstallation.org_id == org_id)
            .order_by(Repository.pushed_at.desc().nulls_last(), Repository.full_name)
        )
    )


def _open_counts(
    db: Session, model: type[PullRequest] | type[Issue], ids: list[uuid.UUID]
) -> dict[Any, int]:
    if not ids:
        return {}
    rows = db.execute(
        select(model.repo_id, func.count())
        .where(model.repo_id.in_(ids), model.state == "open")
        .group_by(model.repo_id)
    ).all()
    return {repo_id: count for repo_id, count in rows}


def _ci_state(status: str | None, conclusion: str | None) -> str:
    if status != "completed":
        return "running"
    if conclusion == "success":
        return "passing"
    if conclusion in ("failure", "timed_out", "startup_failure"):
        return "failing"
    return "other"


def _latest_ci(db: Session, ids: list[uuid.UUID]) -> dict[Any, str]:
    """Latest workflow run per repo, preferring runs on the default branch."""
    if not ids:
        return {}
    rank = func.row_number().over(
        partition_by=WorkflowRun.repo_id,
        order_by=[
            case((WorkflowRun.head_branch == Repository.default_branch, 0), else_=1),
            WorkflowRun.gh_created_at.desc(),
        ],
    )
    ranked = (
        select(WorkflowRun.repo_id, WorkflowRun.status, WorkflowRun.conclusion, rank.label("rn"))
        .join(Repository, Repository.id == WorkflowRun.repo_id)
        .where(WorkflowRun.repo_id.in_(ids))
        .subquery()
    )
    rows = db.execute(
        select(ranked.c.repo_id, ranked.c.status, ranked.c.conclusion).where(ranked.c.rn == 1)
    ).all()
    return {repo_id: _ci_state(st, concl) for repo_id, st, concl in rows}


@router.get("/orgs/{org_id}/repos", response_model=list[RepoOut])
def list_repos(ctx: AnyMember, db: DbSession) -> list[RepoOut]:
    repos = _repos(db, ctx.org.id)
    ids = [r.id for r in repos]
    prs, issues, ci = (
        _open_counts(db, PullRequest, ids),
        _open_counts(db, Issue, ids),
        _latest_ci(db, ids),
    )
    indexes: dict[Any, RepositoryIndex] = {}
    if ids:
        found = db.scalars(select(RepositoryIndex).where(RepositoryIndex.repo_id.in_(ids)))
        indexes = {row.repo_id: row for row in found}
    last_commit: dict[Any, Any] = {}
    if ids:
        rows = db.execute(
            select(Commit.repo_id, func.max(Commit.committed_at))
            .where(Commit.repo_id.in_(ids))
            .group_by(Commit.repo_id)
        ).all()
        last_commit = {row[0]: row[1] for row in rows}
    return [
        RepoOut(
            id=r.id,
            full_name=r.full_name,
            private=r.private,
            archived=r.archived,
            language=r.language,
            default_branch=r.default_branch,
            html_url=r.html_url,
            pushed_at=r.pushed_at,
            open_pull_requests=prs.get(r.id, 0),
            open_issues=issues.get(r.id, 0),
            last_commit_at=last_commit.get(r.id),
            ci=ci.get(r.id, "none"),
            index=index_out(indexes.get(r.id)),
        )
        for r in repos
    ]


@router.get("/orgs/{org_id}/overview", response_model=OverviewOut)
def overview(ctx: AnyMember, db: DbSession) -> OverviewOut:
    repos = _repos(db, ctx.org.id)
    ids = [r.id for r in repos]
    ci_states = list(_latest_ci(db, ids).values())

    commits: list[CommitOut] = []
    if ids:
        rows = db.execute(
            select(Commit, Repository.full_name)
            .join(Repository, Repository.id == Commit.repo_id)
            .where(Commit.repo_id.in_(ids))
            .order_by(Commit.committed_at.desc().nulls_last())
            .limit(10)
        ).all()
        commits = [
            CommitOut(
                sha=c.sha,
                message=c.message_headline,
                author=c.author_login or c.author_name,
                repository=full_name,
                committed_at=c.committed_at,
                url=c.html_url,
            )
            for c, full_name in rows
        ]

    return OverviewOut(
        repositories=len(repos),
        open_pull_requests=sum(_open_counts(db, PullRequest, ids).values()),
        open_issues=sum(_open_counts(db, Issue, ids).values()),
        ci=CiSummary(
            passing=ci_states.count("passing"),
            failing=ci_states.count("failing"),
            running=ci_states.count("running"),
            other=ci_states.count("other"),
            none=len(ids) - len(ci_states),
        ),
        recent_commits=commits,
    )
