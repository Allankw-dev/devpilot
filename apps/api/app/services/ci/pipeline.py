"""Analyzing one failed workflow run as a background job.

Same ground rules as indexing and reviews: a run is claimed atomically (so a duplicate delivery
does nothing), a transient problem leaves the analysis queued for a retry, and every failure ends
as a clear message instead of a stuck spinner. Logs are only read, never stored, and nothing is
ever posted to GitHub or re-run.
"""

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import CiAnalysis, GithubInstallation, Repository, WorkflowRun
from app.services.ci.analysis import JobInput, analyze_failure
from app.services.ci.logs import build_excerpt
from app.services.github.client import GitHubClient, GitHubError, GitHubRateLimited
from app.services.llm import CallContext, LLMError, LLMNotConfigured, LLMService
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMInvalidOutput,
    LLMQuotaExhausted,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)

logger = logging.getLogger(__name__)

STALE_RUNNING = timedelta(minutes=10)
STALE_QUEUED = timedelta(minutes=30)
MAX_JOB_PAGES = 3  # 100 jobs a page
ANALYZABLE_CONCLUSIONS = ("failure", "timed_out")
_FAILED = ("failure", "timed_out")
_SHA = re.compile(r"^[0-9a-f]{40}$")

RequestOutcome = Literal["created", "active", "cached"]


class CiFailed(Exception):
    """Won't succeed by retrying. The message is safe to show to users."""


class TransientCiError(Exception):
    """Worth trying again later (rate limit, outage)."""


@dataclass(frozen=True)
class CiRequest:
    outcome: RequestOutcome
    analysis: CiAnalysis


def is_analyzable(run: WorkflowRun) -> bool:
    """Only a finished run that failed has a failure to explain."""
    return run.status == "completed" and run.conclusion in ANALYZABLE_CONCLUSIONS


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)  # SQLite returns naive datetimes
    return value


# ---------- asking for an analysis ----------


def request_analysis(
    db: Session, run: WorkflowRun, user_id: uuid.UUID | None, *, force: bool = False
) -> CiRequest:
    """Reserve an analysis for a run, or say why none is needed:
    - "active": one is already queued or running for it,
    - "cached": the latest finished analysis is still current (the run hasn't changed since),
    - "created": a new queued analysis (not yet run)."""
    now = datetime.now(UTC)
    latest = db.scalars(
        select(CiAnalysis)
        .where(CiAnalysis.workflow_run_id == run.id)
        .order_by(CiAnalysis.queued_at.desc())
        .limit(1)
    ).first()
    if latest is not None:
        queued_at = _aware(latest.queued_at)
        heartbeat = _aware(latest.heartbeat_at)
        if latest.status == "queued" and queued_at and queued_at > now - STALE_QUEUED:
            return CiRequest("active", latest)
        if latest.status == "running" and heartbeat and heartbeat > now - STALE_RUNNING:
            return CiRequest("active", latest)
        if not force and latest.status == "ready" and latest.run_updated_at == run.gh_updated_at:
            return CiRequest("cached", latest)
    analysis = CiAnalysis(
        workflow_run_id=run.id,
        requested_by=user_id,
        status="queued",
        run_id=uuid.uuid4(),
        queued_at=now,
        run_updated_at=run.gh_updated_at,
    )
    db.add(analysis)
    try:
        db.commit()
    except IntegrityError:  # the run was deleted meanwhile
        db.rollback()
        raise
    return CiRequest("created", analysis)


def claim_analysis(db: Session, analysis_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(CiAnalysis)
            .where(
                CiAnalysis.id == analysis_id,
                CiAnalysis.run_id == run_id,
                or_(
                    CiAnalysis.status == "queued",
                    (CiAnalysis.status == "running")
                    & (CiAnalysis.heartbeat_at < now - STALE_RUNNING),
                ),
            )
            .values(status="running", started_at=now, heartbeat_at=now, error=None)
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return result.rowcount == 1


def _finish(
    db: Session, analysis_id: uuid.UUID, run_id: uuid.UUID, status: str, error: str | None
) -> None:
    db.execute(
        update(CiAnalysis)
        .where(CiAnalysis.id == analysis_id, CiAnalysis.run_id == run_id)
        .values(
            status=status,
            error=error[:500] if error else None,
            finished_at=datetime.now(UTC) if status == "failed" else None,
            heartbeat_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def abort_analysis(db: Session, analysis_id: uuid.UUID, run_id: uuid.UUID, message: str) -> None:
    """For callers that reserved an analysis but couldn't queue it (e.g. Redis was unreachable)."""
    _finish(db, analysis_id, run_id, "failed", message)


# ---------- what went wrong, and whether to try again ----------


def classify(exc: Exception) -> TransientCiError | CiFailed | None:
    if isinstance(exc, LLMQuotaExhausted):  # waiting minutes won't help: say so, don't retry
        return CiFailed(exc.user_message())
    if isinstance(exc, LLMRateLimited):
        return TransientCiError("The AI provider is rate limiting requests.")
    if isinstance(exc, LLMTimeout | LLMUnavailable):
        return TransientCiError("The AI provider is slow or unavailable.")
    if isinstance(exc, LLMNotConfigured):
        return CiFailed(str(exc))
    if isinstance(exc, LLMAuthError):
        return CiFailed("The AI provider rejected the API key, or the key can't use the model.")
    if isinstance(exc, LLMBlocked):
        return CiFailed("The AI provider declined to analyze this log (safety filter).")
    if isinstance(exc, LLMBadRequest):
        return CiFailed("The AI provider rejected the request. Check GEMINI_MODEL.")
    if isinstance(exc, LLMInvalidOutput):  # our own message, safe to show
        return CiFailed(f"The AI returned an analysis that could not be used: {exc}")
    if isinstance(exc, LLMError):
        return CiFailed(f"AI error ({exc.code})")
    if isinstance(exc, GitHubRateLimited):
        return TransientCiError("GitHub rate limit reached.")
    if isinstance(exc, GitHubError):
        if exc.status is None or exc.status >= 500:
            return TransientCiError("GitHub is unreachable or failing.")
        if exc.status in (401, 403, 404, 410, 451):
            return CiFailed(
                "GitHub denied access to this run. Check the app's permissions "
                "(Actions: read) and that the repository is still shared with it."
            )
        return CiFailed(f"GitHub error ({exc.status}).")
    return None


# ---------- the run ----------


def run_analysis(
    factory: sessionmaker[Session],
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    analysis_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    final_attempt: bool = True,
) -> str:
    """Run one analysis job. Returns "ready", "failed", "skipped" or "busy" (the job is marked
    running by a worker that may be dead; try again after its heartbeat goes stale). A
    transient problem raises TransientCiError unless `final_attempt`."""
    with factory() as db:
        if not claim_analysis(db, analysis_id, run_id):
            current = db.get(CiAnalysis, analysis_id)
            if current and current.run_id == run_id and current.status == "running":
                return "busy"
            return "skipped"
        try:
            _analyze(db, github, get_llm, settings, analysis_id)
            return "ready"
        except Exception as exc:
            db.rollback()
            problem = exc if isinstance(exc, CiFailed | TransientCiError) else classify(exc)
            if problem is None:
                logger.exception("CI analysis crashed for %s", analysis_id)
                problem = CiFailed("Unexpected error during the analysis. See the server logs.")
            if isinstance(problem, TransientCiError):
                if final_attempt:
                    message = f"{problem} Click Analyze to try again."
                    _finish(db, analysis_id, run_id, "failed", message)
                    return "failed"
                _finish(db, analysis_id, run_id, "queued", f"{problem} Retrying automatically.")
                raise problem from exc
            logger.warning("CI analysis %s failed: %s", analysis_id, problem)
            _finish(db, analysis_id, run_id, "failed", str(problem))
            return "failed"


NEVER_STARTED = "the job never started, so it has no log"


def _problem_for(exc: GitHubError, ran: bool) -> str:
    """Why a job's log couldn't be read. A failed job with no steps never ran at all (for example
    a runner or billing problem), which is a different story from a log that has expired."""
    if exc.status in (404, 410):
        return "log expired or removed" if ran else NEVER_STARTED
    if exc.status in (401, 403):
        return "access denied"
    if exc.status == 413:
        return "log too large"
    return f"GitHub error {exc.status}"


def _analyze(
    db: Session,
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    analysis_id: uuid.UUID,
) -> None:
    analysis = db.get(CiAnalysis, analysis_id)
    run = db.get(WorkflowRun, analysis.workflow_run_id) if analysis else None
    repo = db.get(Repository, run.repo_id) if run else None
    installation = db.get(GithubInstallation, repo.installation_id) if repo else None
    if analysis is None or run is None or repo is None or installation is None:
        raise CiFailed("This run is no longer connected.")
    if installation.suspended_at is not None:
        raise CiFailed("The GitHub installation is suspended.")

    llm = get_llm()
    iid = installation.installation_id
    listing, complete = github.installation_paginate(
        iid,
        f"/repos/{repo.full_name}/actions/runs/{run.run_id}/jobs",
        key="jobs",
        max_pages=MAX_JOB_PAGES,
    )
    failed = [j for j in listing if j.get("conclusion") in _FAILED]
    if not failed:
        raise CiFailed(
            "GitHub reports no failed jobs for this run. It may have failed before any job "
            "started, for example because of an error in the workflow file."
        )
    chosen = failed[: max(settings.ci_max_jobs, 1)]
    per_job = max(settings.ci_max_log_chars // len(chosen), 4000)

    inputs: list[JobInput] = []
    for job in chosen:
        name = str(job.get("name") or f"job {job.get('id')}")[:120]
        steps = [
            str(s.get("name") or "")[:120]
            for s in (job.get("steps") or [])
            if isinstance(s, dict) and s.get("conclusion") in _FAILED
        ]
        conclusion = str(job.get("conclusion") or "failure")
        try:
            raw, cut = github.installation_job_log(
                iid, repo.full_name, int(job["id"]), max_bytes=settings.ci_max_log_bytes
            )
        except GitHubRateLimited:
            raise
        except GitHubError as exc:
            if exc.status is None or exc.status >= 500:
                raise  # transient: try the whole analysis again later
            ran = bool(job.get("steps"))
            inputs.append(JobInput(name, conclusion, steps, None, _problem_for(exc, ran)))
            continue
        excerpt = build_excerpt(raw, max_chars=per_job, cut_before=cut)
        if not excerpt.text:
            inputs.append(JobInput(name, conclusion, steps, None, "the log is empty"))
            continue
        inputs.append(JobInput(name, conclusion, steps, excerpt))
        analysis.heartbeat_at = datetime.now(UTC)
        db.commit()

    if not any(j.excerpt is not None for j in inputs):
        why = "; ".join(f"{j.name}: {j.problem}" for j in inputs)
        hint = ""
        if any(j.problem == NEVER_STARTED for j in inputs):
            hint = (
                " Open the run on GitHub to see why: jobs that never start, for example because "
                "of a runner or billing problem, have no log."
            )
        raise CiFailed(f"No log could be read for this run ({why}).{hint}")

    result = analyze_failure(
        llm,
        repository=repo.full_name,
        workflow=run.name or "workflow",
        branch=run.head_branch or "",
        event=run.event or "",
        jobs=inputs,
        jobs_total=len(failed),
        listing_complete=complete,
        ctx=CallContext(feature="ci", org_id=installation.org_id, user_id=analysis.requested_by),
        max_output_tokens=settings.ci_max_output_tokens,
    )

    head = run.head_sha or ""
    analysis.status = "ready"
    analysis.head_sha = head if _SHA.match(head) else None
    analysis.model = result.model or None
    analysis.summary = result.summary
    analysis.category = result.category
    analysis.confidence = result.confidence
    analysis.likely_cause = result.likely_cause
    analysis.suggested_fix = result.suggested_fix
    failed_steps: list[dict[str, str | None]] = []
    for j in inputs:
        if j.failed_steps:
            failed_steps.extend({"job": j.name, "step": step} for step in j.failed_steps)
        else:
            failed_steps.append({"job": j.name, "step": None})
    analysis.failed_steps = failed_steps
    analysis.evidence = result.evidence
    analysis.notes = result.notes
    analysis.jobs_total = len(failed)
    analysis.jobs_analyzed = sum(1 for j in inputs if j.excerpt is not None)
    analysis.input_tokens = result.usage.input_tokens
    analysis.output_tokens = result.usage.output_tokens
    analysis.finished_at = datetime.now(UTC)
    analysis.heartbeat_at = datetime.now(UTC)
    analysis.error = None
    db.commit()
