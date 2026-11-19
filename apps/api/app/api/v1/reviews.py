import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AnyMember, DbSession, JobsDep, MemberCtx
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import (
    GithubInstallation,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
)
from app.jobs.dispatch import JobQueueUnavailable
from app.schemas import (
    FindingOut,
    FindingUpdate,
    PullRequestOut,
    ReviewBriefOut,
    ReviewOut,
    ReviewStart,
)
from app.services.review.pipeline import abort_review, request_review
from app.services.review.review import SEVERITY_RANK

logger = logging.getLogger(__name__)
router = APIRouter(tags=["reviews"])

Config = Annotated[Settings, Depends(get_settings)]
SERIOUS = ("critical", "high")


# ---------- helpers ----------


def _pr_in_org(db: Session, org_id: uuid.UUID, pr_id: uuid.UUID) -> PullRequest:
    """A pull request, but only if its repository belongs to this organization (else 404)."""
    pr = db.scalar(
        select(PullRequest)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(PullRequest.id == pr_id, GithubInstallation.org_id == org_id)
    )
    if pr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pull request not found")
    return pr


def _stale(review: PullRequestReview, pr: PullRequest) -> bool:
    return review.status == "ready" and review.pr_updated_at != pr.gh_updated_at


def _finding_out(f: ReviewFinding) -> FindingOut:
    return FindingOut(
        id=f.id,
        file=f.file_path,
        start_line=f.start_line,
        end_line=f.end_line,
        category=f.category,
        severity=f.severity,
        confidence=f.confidence,
        title=f.title,
        explanation=f.explanation,
        suggestion=f.suggestion,
        origin=f.origin,
        status=f.status,
    )


def _review_out(db: Session, review: PullRequestReview, pr: PullRequest) -> ReviewOut:
    findings = db.scalars(select(ReviewFinding).where(ReviewFinding.review_id == review.id)).all()
    ordered = sorted(findings, key=lambda f: (SEVERITY_RANK[f.severity], f.file_path, f.start_line))
    return ReviewOut(
        id=review.id,
        pull_request_id=pr.id,
        status=review.status,
        risk=review.risk,
        summary=review.summary,
        notes=review.notes,
        head_sha=review.head_sha,
        model=review.model,
        files_total=review.files_total or 0,
        files_reviewed=review.files_reviewed or 0,
        input_tokens=review.input_tokens or 0,
        output_tokens=review.output_tokens or 0,
        queued_at=review.queued_at,
        finished_at=review.finished_at,
        error=review.error,
        stale=_stale(review, pr),
        findings=[_finding_out(f) for f in ordered],
    )


def _check_review_rate(db: Session, user_id: uuid.UUID, per_minute: int) -> None:
    """Reviews cost tokens. Counts reviews this person asked for, so even a burst of requests
    made before any finishes is limited."""
    recent = db.scalar(
        select(func.count())
        .select_from(PullRequestReview)
        .where(
            PullRequestReview.requested_by == user_id,
            PullRequestReview.queued_at >= datetime.now(UTC) - timedelta(seconds=60),
        )
    )
    if (recent or 0) >= per_minute:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You're requesting a lot of reviews. Wait a minute and try again.",
        )


# ---------- routes ----------


def _pull_request_rows(db: Session, rows: list[tuple[PullRequest, str]]) -> list[PullRequestOut]:
    """Pull requests with a summary of their newest AI review."""
    ids = [pr.id for pr, _ in rows]

    newest: dict[uuid.UUID, PullRequestReview] = {}
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    if ids:
        for review in db.scalars(
            select(PullRequestReview)
            .where(PullRequestReview.pr_id.in_(ids))
            .order_by(PullRequestReview.queued_at.desc())
        ):
            newest.setdefault(review.pr_id, review)
        review_ids = [r.id for r in newest.values()]
        if review_ids:
            for review_id, severity, n in db.execute(
                select(ReviewFinding.review_id, ReviewFinding.severity, func.count())
                .where(ReviewFinding.review_id.in_(review_ids), ReviewFinding.status == "open")
                .group_by(ReviewFinding.review_id, ReviewFinding.severity)
            ):
                total, serious = counts.get(review_id, (0, 0))
                counts[review_id] = (total + n, serious + (n if severity in SERIOUS else 0))

    out: list[PullRequestOut] = []
    for pr, full_name in rows:
        found = newest.get(pr.id)
        brief = None
        if found is not None:
            total, serious = counts.get(found.id, (0, 0))
            brief = ReviewBriefOut(
                id=found.id,
                status=found.status,
                risk=found.risk,
                open_findings=total,
                serious_findings=serious,
                finished_at=found.finished_at,
                stale=_stale(found, pr),
                error=found.error,
            )
        out.append(
            PullRequestOut(
                id=pr.id,
                repository_id=pr.repo_id,
                repository=full_name,
                number=pr.number,
                title=pr.title,
                state=pr.state,
                draft=pr.draft,
                merged=pr.merged,
                author=pr.author_login,
                html_url=pr.html_url,
                updated_at=pr.gh_updated_at,
                review=brief,
            )
        )
    return out


@router.get("/orgs/{org_id}/pull-requests", response_model=list[PullRequestOut])
def list_pull_requests(
    ctx: AnyMember,
    db: DbSession,
    state: Literal["open", "all"] = "open",
    repo_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[PullRequestOut]:
    """Pull requests, most recently updated first. `q` matches the title."""
    stmt = (
        select(PullRequest, Repository.full_name)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(GithubInstallation.org_id == ctx.org.id)
        .order_by(PullRequest.gh_updated_at.desc().nulls_last(), PullRequest.number.desc())
        .limit(limit)
        .offset(offset)
    )
    if state == "open":
        stmt = stmt.where(PullRequest.state == "open")
    if repo_id is not None:
        stmt = stmt.where(PullRequest.repo_id == repo_id)
    if q and q.strip():
        needle = q.strip().lower()
        stmt = stmt.where(func.lower(PullRequest.title).contains(needle, autoescape=True))
    return _pull_request_rows(db, [(pr, name) for pr, name in db.execute(stmt).all()])


@router.get("/orgs/{org_id}/pull-requests/{pr_id}", response_model=PullRequestOut)
def get_pull_request(pr_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> PullRequestOut:
    pr = _pr_in_org(db, ctx.org.id, pr_id)
    repo = db.get(Repository, pr.repo_id)
    assert repo is not None  # the foreign key guarantees it
    return _pull_request_rows(db, [(pr, repo.full_name)])[0]


@router.get("/orgs/{org_id}/pull-requests/{pr_id}/review", response_model=ReviewOut | None)
def get_review(pr_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> ReviewOut | None:
    pr = _pr_in_org(db, ctx.org.id, pr_id)
    review = db.scalars(
        select(PullRequestReview)
        .where(PullRequestReview.pr_id == pr.id)
        .order_by(PullRequestReview.queued_at.desc())
        .limit(1)
    ).first()
    return _review_out(db, review, pr) if review else None


@router.post("/orgs/{org_id}/pull-requests/{pr_id}/review", response_model=ReviewOut)
def start_review(
    pr_id: uuid.UUID,
    response: Response,
    ctx: MemberCtx,
    db: DbSession,
    settings: Config,
    jobs: JobsDep,
    body: ReviewStart | None = None,
) -> ReviewOut:
    """Review a pull request. Costs tokens, so it needs at least the member role. The review
    is stored here only: nothing is ever posted to GitHub."""
    pr = _pr_in_org(db, ctx.org.id, pr_id)

    missing = settings.llm_missing_settings()
    if missing:
        detail = "AI isn't set up on the server yet. Ask an organization admin."
        if at_least(ctx.role, Role.admin):
            detail = "Missing settings: " + ", ".join(missing)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    _check_review_rate(db, ctx.user.id, settings.review_rate_limit_per_minute)

    request = request_review(db, pr, ctx.user.id, force=bool(body and body.force))
    review = request.review
    if request.outcome == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A review of this pull request is already in progress"
        )
    if request.outcome == "cached":
        response.status_code = status.HTTP_200_OK  # nothing changed since the last review
        return _review_out(db, review, pr)

    assert review.run_id is not None
    queued = _review_out(db, review, pr)
    try:
        jobs.review_pull_request(review.id, review.run_id)
    except JobQueueUnavailable as exc:
        abort_review(db, review.id, review.run_id, str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    response.status_code = status.HTTP_202_ACCEPTED
    return queued


@router.patch("/orgs/{org_id}/review-findings/{finding_id}", response_model=FindingOut)
def update_finding(
    finding_id: uuid.UUID, body: FindingUpdate, ctx: MemberCtx, db: DbSession
) -> FindingOut:
    """Dismiss a finding (or reopen it). Only affects what DevPilot shows."""
    finding = db.scalar(
        select(ReviewFinding)
        .join(PullRequestReview, PullRequestReview.id == ReviewFinding.review_id)
        .join(PullRequest, PullRequest.id == PullRequestReview.pr_id)
        .join(Repository, Repository.id == PullRequest.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(ReviewFinding.id == finding_id, GithubInstallation.org_id == ctx.org.id)
    )
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    finding.status = body.status
    db.commit()
    return _finding_out(finding)
