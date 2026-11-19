import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import AnyMember, DbSession
from app.db.models import GithubInstallation, Issue, Repository
from app.schemas import IssueOut

router = APIRouter(tags=["issues"])


@router.get("/orgs/{org_id}/issues", response_model=list[IssueOut])
def list_issues(
    ctx: AnyMember,
    db: DbSession,
    repo_id: uuid.UUID | None = None,
    state: Literal["open", "closed", "all"] = "open",
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[IssueOut]:
    """Issues GitHub has told us about, most recently updated first. `q` matches the title."""
    stmt = (
        select(Issue, Repository.full_name)
        .join(Repository, Repository.id == Issue.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(GithubInstallation.org_id == ctx.org.id)
        .order_by(Issue.gh_updated_at.desc().nulls_last(), Issue.number.desc())
        .limit(limit)
        .offset(offset)
    )
    if repo_id is not None:
        stmt = stmt.where(Issue.repo_id == repo_id)
    if state != "all":
        stmt = stmt.where(Issue.state == state)
    if q and q.strip():
        stmt = stmt.where(func.lower(Issue.title).contains(q.strip().lower(), autoescape=True))
    return [
        IssueOut(
            id=i.id,
            repository_id=i.repo_id,
            repository=full_name,
            number=i.number,
            title=i.title,
            state=i.state,
            author=i.author_login,
            comments=i.comments,
            html_url=i.html_url,
            created_at=i.gh_created_at,
            updated_at=i.gh_updated_at,
        )
        for i, full_name in db.execute(stmt).all()
    ]
