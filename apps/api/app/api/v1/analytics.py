from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.api.deps import AnyMember, DbSession
from app.core.daybucket import day_bucket, to_date
from app.db.models import (
    CiAnalysis,
    GithubInstallation,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
    WorkflowRun,
)
from app.schemas import AnalyticsDayOut, AnalyticsOut, AnalyticsSeverityOut

router = APIRouter(tags=["analytics"])

SEVERITIES = ("critical", "high", "medium", "low", "info")
FAILED = ("failure", "timed_out")
MAX_DURATION_ROWS = 5000


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)  # SQLite returns naive datetimes


def _average_seconds(pairs: list[tuple[datetime | None, datetime | None]]) -> int | None:
    """Mean time from start to finish. Rows missing a time, or finishing before they started, are
    skipped rather than guessed at."""
    spans = [
        (_aware(end) - _aware(begin)).total_seconds()
        for begin, end in pairs
        if begin is not None and end is not None and end >= begin
    ]
    return round(sum(spans) / len(spans)) if spans else None


@router.get("/orgs/{org_id}/analytics", response_model=AnalyticsOut)
def analytics(
    ctx: AnyMember,
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> AnalyticsOut:
    """What the AI and CI have done over a period. These are activity counts, not a measure of
    developer productivity."""
    now = datetime.now(UTC)
    first_day: date = now.date() - timedelta(days=days - 1)
    since = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
    in_org = GithubInstallation.org_id == ctx.org.id

    review_day = day_bucket(db, PullRequestReview.finished_at)
    reviews_by_day = {
        to_date(d): int(n)
        for d, n in db.execute(
            select(review_day, func.count())
            .select_from(PullRequestReview)
            .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(
                in_org, PullRequestReview.status == "ready", PullRequestReview.finished_at >= since
            )
            .group_by(review_day)
        ).all()
        if d is not None
    }
    analysis_day = day_bucket(db, CiAnalysis.finished_at)
    analyses_by_day = {
        to_date(d): int(n)
        for d, n in db.execute(
            select(analysis_day, func.count())
            .select_from(CiAnalysis)
            .join(WorkflowRun, WorkflowRun.id == CiAnalysis.workflow_run_id)
            .join(Repository, Repository.id == WorkflowRun.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, CiAnalysis.status == "ready", CiAnalysis.finished_at >= since)
            .group_by(analysis_day)
        ).all()
        if d is not None
    }
    run_day = day_bucket(db, WorkflowRun.gh_created_at)
    ok = func.coalesce(func.sum(case((WorkflowRun.conclusion == "success", 1), else_=0)), 0)
    bad = func.coalesce(func.sum(case((WorkflowRun.conclusion.in_(FAILED), 1), else_=0)), 0)
    runs_by_day = {
        to_date(d): (int(good), int(failed))
        for d, good, failed in db.execute(
            select(run_day, ok, bad)
            .select_from(WorkflowRun)
            .join(Repository, Repository.id == WorkflowRun.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(in_org, WorkflowRun.status == "completed", WorkflowRun.gh_created_at >= since)
            .group_by(run_day)
        ).all()
        if d is not None
    }

    by_day = [
        AnalyticsDayOut(
            day=first_day + timedelta(days=i),
            reviews_finished=reviews_by_day.get(first_day + timedelta(days=i), 0),
            ci_analyses_finished=analyses_by_day.get(first_day + timedelta(days=i), 0),
            runs_succeeded=runs_by_day.get(first_day + timedelta(days=i), (0, 0))[0],
            runs_failed=runs_by_day.get(first_day + timedelta(days=i), (0, 0))[1],
        )
        for i in range(days)
    ]

    severity_counts = {
        severity: int(n)
        for severity, n in db.execute(
            select(ReviewFinding.severity, func.count())
            .select_from(ReviewFinding)
            .join(PullRequestReview, PullRequestReview.id == ReviewFinding.review_id)
            .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
            .join(Repository, Repository.id == PullRequest.repo_id)
            .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
            .where(
                in_org, PullRequestReview.status == "ready", PullRequestReview.finished_at >= since
            )
            .group_by(ReviewFinding.severity)
        ).all()
    }

    review_times = db.execute(
        select(PullRequestReview.started_at, PullRequestReview.finished_at)
        .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(in_org, PullRequestReview.status == "ready", PullRequestReview.finished_at >= since)
        .limit(MAX_DURATION_ROWS)
    ).all()
    analysis_times = db.execute(
        select(CiAnalysis.started_at, CiAnalysis.finished_at)
        .join(WorkflowRun, WorkflowRun.id == CiAnalysis.workflow_run_id)
        .join(Repository, Repository.id == WorkflowRun.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(in_org, CiAnalysis.status == "ready", CiAnalysis.finished_at >= since)
        .limit(MAX_DURATION_ROWS)
    ).all()

    succeeded = sum(d.runs_succeeded for d in by_day)
    failed = sum(d.runs_failed for d in by_day)
    return AnalyticsOut(
        days=days,
        since=first_day,
        reviews_finished=sum(d.reviews_finished for d in by_day),
        ci_analyses_finished=sum(d.ci_analyses_finished for d in by_day),
        runs_succeeded=succeeded,
        runs_failed=failed,
        ci_success_rate=round(succeeded / (succeeded + failed), 4) if succeeded + failed else None,
        avg_review_seconds=_average_seconds([(a, b) for a, b in review_times]),
        avg_ci_analysis_seconds=_average_seconds([(a, b) for a, b in analysis_times]),
        findings_by_severity=[
            AnalyticsSeverityOut(severity=s, count=severity_counts.get(s, 0)) for s in SEVERITIES
        ],
        by_day=by_day,
    )
