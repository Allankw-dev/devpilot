import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, case, func, select

from app.api.deps import AnyMember, DbSession
from app.core.daybucket import day_bucket, to_date
from app.db.models import (
    CiAnalysis,
    Commit,
    GithubInstallation,
    Issue,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
    WorkflowRun,
)
from app.schemas import (
    DashboardDayOut,
    DashboardIssueOut,
    DashboardOut,
    DashboardPullRequestOut,
    DashboardReviewOut,
    DashboardRunOut,
    DashboardStatsOut,
)

router = APIRouter(tags=["dashboard"])

RECENT = 5
FAILED = ("failure", "timed_out")
SERIOUS = ("critical", "high")


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)  # SQLite returns naive datetimes
    return value


@router.get("/orgs/{org_id}/dashboard", response_model=DashboardOut)
def dashboard(
    ctx: AnyMember,
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> DashboardOut:
    """Real numbers for the organization's home page: what GitHub has told us, and what the AI
    has done. Nothing here is estimated; a count of zero means zero."""
    now = datetime.now(UTC)
    first_day = now.date() - timedelta(days=days - 1)
    since = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
    in_org: ColumnElement[bool] = GithubInstallation.org_id == ctx.org.id

    installations = list(db.scalars(select(GithubInstallation).where(in_org)))
    synced = [i.last_synced_at for i in installations if i.last_synced_at is not None]

    repositories = (
        db.scalar(
            select(func.count())
            .select_from(Repository)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org)
        )
        or 0
    )
    open_prs = (
        db.scalar(
            select(func.count())
            .select_from(PullRequest)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, PullRequest.state == "open")
        )
        or 0
    )
    open_issue_count = (
        db.scalar(
            select(func.count())
            .select_from(Issue)
            .join(Repository, Repository.id == Issue.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, Issue.state == "open")
        )
        or 0
    )
    reviews_completed = (
        db.scalar(
            select(func.count())
            .select_from(PullRequestReview)
            .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(
                in_org, PullRequestReview.status == "ready", PullRequestReview.finished_at >= since
            )
        )
        or 0
    )
    ci_completed = (
        db.scalar(
            select(func.count())
            .select_from(CiAnalysis)
            .join(WorkflowRun, WorkflowRun.id == CiAnalysis.workflow_run_id)
            .join(Repository, Repository.id == WorkflowRun.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, CiAnalysis.status == "ready", CiAnalysis.finished_at >= since)
        )
        or 0
    )
    failed_runs = (
        db.scalar(
            select(func.count())
            .select_from(WorkflowRun)
            .join(Repository, Repository.id == WorkflowRun.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(
                in_org,
                WorkflowRun.status == "completed",
                WorkflowRun.conclusion.in_(FAILED),
                WorkflowRun.gh_created_at >= since,
            )
        )
        or 0
    )

    # ---- activity per day (commits and pull requests opened) ----
    commit_day = day_bucket(db, Commit.committed_at)
    commits_by_day = {
        to_date(d): int(n)
        for d, n in db.execute(
            select(commit_day, func.count())
            .select_from(Commit)
            .join(Repository, Repository.id == Commit.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, Commit.committed_at >= since)
            .group_by(commit_day)
        ).all()
        if d is not None
    }
    pr_day = day_bucket(db, PullRequest.gh_created_at)
    prs_by_day = {
        to_date(d): int(n)
        for d, n in db.execute(
            select(pr_day, func.count())
            .select_from(PullRequest)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, PullRequest.gh_created_at >= since)
            .group_by(pr_day)
        ).all()
        if d is not None
    }
    activity = [
        DashboardDayOut(
            day=first_day + timedelta(days=i),
            commits=commits_by_day.get(first_day + timedelta(days=i), 0),
            pull_requests_opened=prs_by_day.get(first_day + timedelta(days=i), 0),
        )
        for i in range(days)
    ]

    # ---- recent lists ----
    recent_prs = [
        DashboardPullRequestOut(
            id=pr.id,
            repository=full_name,
            number=pr.number,
            title=pr.title,
            author=pr.author_login,
            draft=pr.draft,
            html_url=pr.html_url,
            updated_at=_aware(pr.gh_updated_at),
        )
        for pr, full_name in db.execute(
            select(PullRequest, Repository.full_name)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, PullRequest.state == "open")
            .order_by(PullRequest.gh_updated_at.desc().nulls_last(), PullRequest.number.desc())
            .limit(RECENT)
        ).all()
    ]
    issues = [
        DashboardIssueOut(
            id=i.id,
            repository=full_name,
            number=i.number,
            title=i.title,
            author=i.author_login,
            comments=i.comments,
            html_url=i.html_url,
            updated_at=_aware(i.gh_updated_at),
        )
        for i, full_name in db.execute(
            select(Issue, Repository.full_name)
            .join(Repository, Repository.id == Issue.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, Issue.state == "open")
            .order_by(Issue.gh_updated_at.desc().nulls_last(), Issue.number.desc())
            .limit(RECENT)
        ).all()
    ]

    review_rows = db.execute(
        select(PullRequestReview, PullRequest, Repository.full_name)
        .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(in_org)
        .order_by(PullRequestReview.queued_at.desc())
        .limit(RECENT)
    ).all()
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    if review_rows:
        serious = func.sum(case((ReviewFinding.severity.in_(SERIOUS), 1), else_=0))
        for review_id, total, serious_n in db.execute(
            select(ReviewFinding.review_id, func.count(), func.coalesce(serious, 0))
            .where(
                ReviewFinding.review_id.in_([r.id for r, _, _ in review_rows]),
                ReviewFinding.status == "open",
            )
            .group_by(ReviewFinding.review_id)
        ):
            counts[review_id] = (int(total), int(serious_n))
    reviews = [
        DashboardReviewOut(
            id=r.id,
            pull_request_id=pr.id,
            repository=full_name,
            number=pr.number,
            title=pr.title,
            status=r.status,
            open_findings=counts.get(r.id, (0, 0))[0],
            serious_findings=counts.get(r.id, (0, 0))[1],
            finished_at=_aware(r.finished_at),
        )
        for r, pr, full_name in review_rows
    ]

    run_rows = db.execute(
        select(WorkflowRun, Repository.full_name)
        .join(Repository, Repository.id == WorkflowRun.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(in_org, WorkflowRun.status == "completed", WorkflowRun.conclusion.in_(FAILED))
        .order_by(WorkflowRun.gh_updated_at.desc().nulls_last(), WorkflowRun.run_id.desc())
        .limit(RECENT)
    ).all()
    latest: dict[uuid.UUID, str] = {}
    if run_rows:
        for a in db.scalars(
            select(CiAnalysis)
            .where(CiAnalysis.workflow_run_id.in_([r.id for r, _ in run_rows]))
            .order_by(CiAnalysis.queued_at.desc())
        ):
            latest.setdefault(a.workflow_run_id, a.status)
    failed = [
        DashboardRunOut(
            id=r.id,
            repository=full_name,
            name=r.name,
            branch=r.head_branch,
            conclusion=r.conclusion,
            html_url=r.html_url,
            updated_at=_aware(r.gh_updated_at),
            analysis_status=latest.get(r.id),
        )
        for r, full_name in run_rows
    ]

    return DashboardOut(
        days=days,
        since=first_day,
        github_connected=bool(installations),
        last_synced_at=_aware(max(synced)) if synced else None,
        stats=DashboardStatsOut(
            repositories=int(repositories),
            open_pull_requests=int(open_prs),
            open_issues=int(open_issue_count),
            reviews_completed=int(reviews_completed),
            ci_analyses_completed=int(ci_completed),
            failed_runs=int(failed_runs),
        ),
        activity=activity,
        recent_pull_requests=recent_prs,
        recent_reviews=reviews,
        recent_failed_runs=failed,
        open_issues=issues,
    )
