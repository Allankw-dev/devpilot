"""Running one pull request review as a background job.

Same ground rules as indexing: a run is claimed atomically (so a duplicate delivery does
nothing), a transient problem leaves the run queued for a retry, and every failure ends as a
clear message on the review instead of a stuck spinner. Nothing is ever posted to GitHub.
"""

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import CursorResult, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import (
    GithubInstallation,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
)
from app.services.github.client import GitHubClient, GitHubError, GitHubRateLimited
from app.services.llm import CallContext, LLMError, LLMNotConfigured, LLMService
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMInvalidOutput,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)
from app.services.review.diff import select_files
from app.services.review.review import review_diff

logger = logging.getLogger(__name__)

STALE_RUNNING = timedelta(minutes=10)
STALE_QUEUED = timedelta(minutes=30)
MAX_FILE_PAGES = 10  # 100 files a page: reviews never look past the first 1000 files
_SHA = re.compile(r"^[0-9a-f]{40}$")

RequestOutcome = Literal["created", "active", "cached"]


class ReviewFailed(Exception):
    """Won't succeed by retrying. The message is safe to show to users."""


class TransientReviewError(Exception):
    """Worth trying again later (rate limit, outage)."""


@dataclass(frozen=True)
class ReviewRequest:
    outcome: RequestOutcome
    review: PullRequestReview


# ---------- asking for a review ----------


def request_review(
    db: Session, pr: PullRequest, user_id: uuid.UUID | None, *, force: bool = False
) -> ReviewRequest:
    """Reserve a review for a pull request, or say why none is needed:
    - "active": one is already queued or running for it,
    - "cached": the latest finished review is still current (the PR hasn't changed since),
    - "created": a new queued review (not yet run)."""
    now = datetime.now(UTC)
    latest = db.scalars(
        select(PullRequestReview)
        .where(PullRequestReview.pr_id == pr.id)
        .order_by(PullRequestReview.queued_at.desc())
        .limit(1)
    ).first()
    if latest is not None:
        queued_at = _aware(latest.queued_at)
        heartbeat = _aware(latest.heartbeat_at)
        if latest.status == "queued" and queued_at and queued_at > now - STALE_QUEUED:
            return ReviewRequest("active", latest)
        if latest.status == "running" and heartbeat and heartbeat > now - STALE_RUNNING:
            return ReviewRequest("active", latest)
        if (
            not force
            and latest.status == "ready"
            and latest.pr_updated_at == pr.gh_updated_at
        ):
            return ReviewRequest("cached", latest)
    review = PullRequestReview(
        pr_id=pr.id,
        requested_by=user_id,
        status="queued",
        run_id=uuid.uuid4(),
        queued_at=now,
        pr_updated_at=pr.gh_updated_at,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:  # the pull request was deleted meanwhile
        db.rollback()
        raise
    return ReviewRequest("created", review)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)  # SQLite returns naive datetimes
    return value


def claim_review(db: Session, review_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(PullRequestReview)
            .where(
                PullRequestReview.id == review_id,
                PullRequestReview.run_id == run_id,
                or_(
                    PullRequestReview.status == "queued",
                    (PullRequestReview.status == "running")
                    & (PullRequestReview.heartbeat_at < now - STALE_RUNNING),
                ),
            )
            .values(status="running", started_at=now, heartbeat_at=now, error=None)
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return result.rowcount == 1


def _finish(
    db: Session, review_id: uuid.UUID, run_id: uuid.UUID, status: str, error: str | None
) -> None:
    db.execute(
        update(PullRequestReview)
        .where(PullRequestReview.id == review_id, PullRequestReview.run_id == run_id)
        .values(
            status=status,
            error=error[:500] if error else None,
            finished_at=datetime.now(UTC) if status == "failed" else None,
            heartbeat_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def abort_review(db: Session, review_id: uuid.UUID, run_id: uuid.UUID, message: str) -> None:
    """For callers that reserved a review but couldn't queue it (e.g. Redis was unreachable)."""
    _finish(db, review_id, run_id, "failed", message)


# ---------- what went wrong, and whether to try again ----------


def classify(exc: Exception) -> TransientReviewError | ReviewFailed | None:
    if isinstance(exc, LLMRateLimited):
        return TransientReviewError("The AI provider is rate limiting requests.")
    if isinstance(exc, LLMTimeout | LLMUnavailable):
        return TransientReviewError("The AI provider is slow or unavailable.")
    if isinstance(exc, LLMNotConfigured):
        return ReviewFailed(str(exc))
    if isinstance(exc, LLMAuthError):
        return ReviewFailed("The AI provider rejected the API key, or the key can't use the model.")
    if isinstance(exc, LLMBlocked):
        return ReviewFailed("The AI provider declined to review this change (safety filter).")
    if isinstance(exc, LLMBadRequest):
        return ReviewFailed("The AI provider rejected the request. Check GEMINI_MODEL.")
    if isinstance(exc, LLMInvalidOutput):  # our own message, safe to show
        return ReviewFailed(f"The AI returned a review that could not be used: {exc}")
    if isinstance(exc, LLMError):
        return ReviewFailed(f"AI error ({exc.code})")
    if isinstance(exc, GitHubRateLimited):
        return TransientReviewError("GitHub rate limit reached.")
    if isinstance(exc, GitHubError):
        if exc.status is None or exc.status >= 500:
            return TransientReviewError("GitHub is unreachable or failing.")
        if exc.status in (401, 403, 404, 410, 451):
            return ReviewFailed(
                "GitHub denied access to this pull request. Check the app's permissions "
                "(Pull requests: read) and that the repository is still shared with it."
            )
        return ReviewFailed(f"GitHub error ({exc.status}).")
    return None


# ---------- the run ----------


def run_review(
    factory: sessionmaker[Session],
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    review_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    final_attempt: bool = True,
) -> str:
    """Run one review job. Returns "ready", "failed", "skipped" or "busy" (the run is marked
    running by a worker that may be dead; try again after its heartbeat goes stale). A
    transient problem raises TransientReviewError unless `final_attempt`."""
    with factory() as db:
        if not claim_review(db, review_id, run_id):
            current = db.get(PullRequestReview, review_id)
            if current and current.run_id == run_id and current.status == "running":
                return "busy"
            return "skipped"
        try:
            _review(db, github, get_llm, settings, review_id)
            return "ready"
        except Exception as exc:
            db.rollback()
            problem = (
                exc if isinstance(exc, ReviewFailed | TransientReviewError) else classify(exc)
            )
            if problem is None:
                logger.exception("Review crashed for %s", review_id)
                problem = ReviewFailed("Unexpected error during the review. See the server logs.")
            if isinstance(problem, TransientReviewError):
                if final_attempt:
                    message = f"{problem} Click Review to try again."
                    _finish(db, review_id, run_id, "failed", message)
                    return "failed"
                _finish(db, review_id, run_id, "queued", f"{problem} Retrying automatically.")
                raise problem from exc
            logger.warning("Review %s failed: %s", review_id, problem)
            _finish(db, review_id, run_id, "failed", str(problem))
            return "failed"


def _review(
    db: Session,
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    review_id: uuid.UUID,
) -> None:
    review = db.get(PullRequestReview, review_id)
    pr = db.get(PullRequest, review.pr_id) if review else None
    repo = db.get(Repository, pr.repo_id) if pr else None
    installation = db.get(GithubInstallation, repo.installation_id) if repo else None
    if review is None or pr is None or repo is None or installation is None:
        raise ReviewFailed("This pull request is no longer connected.")
    if installation.suspended_at is not None:
        raise ReviewFailed("The GitHub installation is suspended.")

    llm = get_llm()
    iid = installation.installation_id
    details = github.installation_get(iid, f"/repos/{repo.full_name}/pulls/{pr.number}")
    head = details.get("head") or {}
    head_sha = str(head.get("sha") or "")
    files, complete = github.installation_paginate(
        iid, f"/repos/{repo.full_name}/pulls/{pr.number}/files", max_pages=MAX_FILE_PAGES
    )
    selection = select_files(
        files,
        max_files=settings.review_max_files,
        max_chars=settings.review_max_diff_chars,
        complete=complete,
    )
    review.heartbeat_at = datetime.now(UTC)
    db.commit()

    result = review_diff(
        llm,
        title=str(details.get("title") or pr.title),
        body=str(details.get("body") or ""),
        base=str((details.get("base") or {}).get("ref") or ""),
        head=str(head.get("ref") or ""),
        repository=repo.full_name,
        sel=selection,
        ctx=CallContext(feature="review", org_id=installation.org_id, user_id=review.requested_by),
        max_output_tokens=settings.review_max_output_tokens,
        max_findings=settings.review_max_findings,
    )

    db.execute(delete(ReviewFinding).where(ReviewFinding.review_id == review.id))
    db.add_all(
        ReviewFinding(
            review_id=review.id,
            file_path=f.file,
            start_line=f.start_line,
            end_line=f.end_line,
            category=f.category,
            severity=f.severity,
            confidence=f.confidence,
            title=f.title,
            explanation=f.explanation,
            suggestion=f.suggestion,
            origin=f.origin,
            status="open",
        )
        for f in result.findings
    )
    review.status = "ready"
    review.head_sha = head_sha if _SHA.match(head_sha) else None
    review.model = result.model or None
    review.summary = result.summary
    review.risk = result.risk
    review.notes = result.notes
    review.files_total = selection.total
    review.files_reviewed = selection.reviewed
    review.input_tokens = result.usage.input_tokens
    review.output_tokens = result.usage.output_tokens
    review.finished_at = datetime.now(UTC)
    review.heartbeat_at = datetime.now(UTC)
    review.error = None
    db.commit()
