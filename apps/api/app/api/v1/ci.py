import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import AnyMember, DbSession, JobsDep, MemberCtx
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import CiAnalysis, GithubInstallation, Repository, WorkflowRun
from app.jobs.dispatch import JobQueueUnavailable
from app.schemas import (
    CiAnalysisBriefOut,
    CiAnalysisOut,
    CiAnalysisStart,
    CiEvidenceOut,
    CiFailedStepOut,
    CiRunOut,
)
from app.services.ci.pipeline import (
    ANALYZABLE_CONCLUSIONS,
    abort_analysis,
    is_analyzable,
    request_analysis,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ci"])

Config = Annotated[Settings, Depends(get_settings)]


# ---------- helpers ----------


def _run_in_org(db: Session, org_id: uuid.UUID, run_pk: uuid.UUID) -> WorkflowRun:
    """A workflow run, but only if its repository belongs to this organization (else 404)."""
    run = db.scalar(
        select(WorkflowRun)
        .join(Repository, Repository.id == WorkflowRun.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(WorkflowRun.id == run_pk, GithubInstallation.org_id == org_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found")
    return run


def _latest(db: Session, run_pk: uuid.UUID) -> CiAnalysis | None:
    return db.scalars(
        select(CiAnalysis)
        .where(CiAnalysis.workflow_run_id == run_pk)
        .order_by(CiAnalysis.queued_at.desc())
        .limit(1)
    ).first()


def _stale(analysis: CiAnalysis, run: WorkflowRun) -> bool:
    return analysis.status == "ready" and analysis.run_updated_at != run.gh_updated_at


def _analysis_out(analysis: CiAnalysis, run: WorkflowRun) -> CiAnalysisOut:
    return CiAnalysisOut(
        id=analysis.id,
        run_id=run.id,
        status=analysis.status,
        summary=analysis.summary,
        category=analysis.category,
        confidence=analysis.confidence,
        likely_cause=analysis.likely_cause,
        suggested_fix=analysis.suggested_fix,
        failed_steps=[CiFailedStepOut(**s) for s in analysis.failed_steps or []],
        evidence=[CiEvidenceOut(**e) for e in analysis.evidence or []],
        notes=analysis.notes,
        head_sha=analysis.head_sha,
        model=analysis.model,
        jobs_total=analysis.jobs_total or 0,
        jobs_analyzed=analysis.jobs_analyzed or 0,
        input_tokens=analysis.input_tokens or 0,
        output_tokens=analysis.output_tokens or 0,
        queued_at=analysis.queued_at,
        finished_at=analysis.finished_at,
        error=analysis.error,
        stale=_stale(analysis, run),
    )


def _check_rate(db: Session, user_id: uuid.UUID, per_minute: int) -> None:
    """Analyses cost tokens. Counts analyses this person asked for, so even a burst of requests
    made before any finishes is limited."""
    recent = db.scalar(
        select(func.count())
        .select_from(CiAnalysis)
        .where(
            CiAnalysis.requested_by == user_id,
            CiAnalysis.queued_at >= datetime.now(UTC) - timedelta(seconds=60),
        )
    )
    if (recent or 0) >= per_minute:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You're requesting a lot of analyses. Wait a minute and try again.",
        )


# ---------- routes ----------


def _run_rows(db: Session, rows: list[tuple[WorkflowRun, str]]) -> list[CiRunOut]:
    """Workflow runs with a summary of their newest AI analysis."""
    ids = [run.id for run, _ in rows]
    newest: dict[uuid.UUID, CiAnalysis] = {}
    if ids:
        for analysis in db.scalars(
            select(CiAnalysis)
            .where(CiAnalysis.workflow_run_id.in_(ids))
            .order_by(CiAnalysis.queued_at.desc())
        ):
            newest.setdefault(analysis.workflow_run_id, analysis)

    out: list[CiRunOut] = []
    for run, full_name in rows:
        found = newest.get(run.id)
        brief = None
        if found is not None:
            brief = CiAnalysisBriefOut(
                id=found.id,
                status=found.status,
                category=found.category,
                confidence=found.confidence,
                finished_at=found.finished_at,
                stale=_stale(found, run),
                error=found.error,
            )
        out.append(
            CiRunOut(
                id=run.id,
                repository_id=run.repo_id,
                repository=full_name,
                name=run.name,
                event=run.event,
                branch=run.head_branch,
                run_number=run.run_number,
                status=run.status,
                conclusion=run.conclusion,
                html_url=run.html_url,
                updated_at=run.gh_updated_at,
                analyzable=is_analyzable(run),
                analysis=brief,
            )
        )
    return out


@router.get("/orgs/{org_id}/ci-runs", response_model=list[CiRunOut])
def list_ci_runs(
    ctx: AnyMember,
    db: DbSession,
    state: Literal["failed", "all"] = "failed",
    repo_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[CiRunOut]:
    """Workflow runs, newest first. `q` matches the workflow name or the branch."""
    stmt = (
        select(WorkflowRun, Repository.full_name)
        .join(Repository, Repository.id == WorkflowRun.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(GithubInstallation.org_id == ctx.org.id)
        .order_by(WorkflowRun.gh_created_at.desc().nulls_last(), WorkflowRun.run_id.desc())
        .limit(limit)
        .offset(offset)
    )
    if state == "failed":
        stmt = stmt.where(
            WorkflowRun.status == "completed", WorkflowRun.conclusion.in_(ANALYZABLE_CONCLUSIONS)
        )
    if repo_id is not None:
        stmt = stmt.where(WorkflowRun.repo_id == repo_id)
    if q and q.strip():
        needle = q.strip().lower()
        stmt = stmt.where(
            or_(
                func.lower(func.coalesce(WorkflowRun.name, "")).contains(needle, autoescape=True),
                func.lower(func.coalesce(WorkflowRun.head_branch, "")).contains(
                    needle, autoescape=True
                ),
            )
        )
    return _run_rows(db, [(run, name) for run, name in db.execute(stmt).all()])


@router.get("/orgs/{org_id}/ci-runs/{run_pk}", response_model=CiRunOut)
def get_ci_run(run_pk: uuid.UUID, ctx: AnyMember, db: DbSession) -> CiRunOut:
    run = _run_in_org(db, ctx.org.id, run_pk)
    repo = db.get(Repository, run.repo_id)
    assert repo is not None  # the foreign key guarantees it
    return _run_rows(db, [(run, repo.full_name)])[0]


@router.get("/orgs/{org_id}/ci-runs/{run_pk}/analysis", response_model=CiAnalysisOut | None)
def get_analysis(run_pk: uuid.UUID, ctx: AnyMember, db: DbSession) -> CiAnalysisOut | None:
    run = _run_in_org(db, ctx.org.id, run_pk)
    analysis = _latest(db, run.id)
    return _analysis_out(analysis, run) if analysis else None


@router.post("/orgs/{org_id}/ci-runs/{run_pk}/analysis", response_model=CiAnalysisOut)
def start_analysis(
    run_pk: uuid.UUID,
    response: Response,
    ctx: MemberCtx,
    db: DbSession,
    settings: Config,
    jobs: JobsDep,
    body: CiAnalysisStart | None = None,
) -> CiAnalysisOut:
    """Explain why a run failed. Costs tokens, so it needs at least the member role. The
    analysis is stored here only: nothing is ever posted to GitHub and nothing is re-run."""
    run = _run_in_org(db, ctx.org.id, run_pk)
    if not is_analyzable(run):
        raise HTTPException(422, "Only a finished run that failed can be analyzed")

    missing = settings.llm_missing_settings()
    if missing:
        detail = "AI isn't set up on the server yet. Ask an organization admin."
        if at_least(ctx.role, Role.admin):
            detail = "Missing settings: " + ", ".join(missing)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    _check_rate(db, ctx.user.id, settings.ci_rate_limit_per_minute)

    request = request_analysis(db, run, ctx.user.id, force=bool(body and body.force))
    analysis = request.analysis
    if request.outcome == "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An analysis of this run is already in progress"
        )
    if request.outcome == "cached":
        response.status_code = status.HTTP_200_OK  # nothing changed since the last analysis
        return _analysis_out(analysis, run)

    assert analysis.run_id is not None
    queued = _analysis_out(analysis, run)
    try:
        jobs.analyze_ci_run(analysis.id, analysis.run_id)
    except JobQueueUnavailable as exc:
        abort_analysis(db, analysis.id, analysis.run_id, str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    response.status_code = status.HTTP_202_ACCEPTED
    return queued
