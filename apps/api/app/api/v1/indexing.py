import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AnyMember, DbSession, JobsDep, MemberCtx, get_llm
from app.api.llm_http import llm_http_error
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import (
    EMBEDDING_COLUMN_DIMENSIONS,
    GithubInstallation,
    Repository,
    RepositoryIndex,
)
from app.jobs.dispatch import JobQueueUnavailable
from app.schemas import IndexOut, SearchHit, SearchOut, SearchRequest
from app.services.indexing.pipeline import abort_request, request_index
from app.services.indexing.retrieval import search_hits
from app.services.llm import CallContext, LLMError, LLMService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["indexing"])

Config = Annotated[Settings, Depends(get_settings)]
SNIPPET_CHARS = 2000


def index_out(row: RepositoryIndex | None) -> IndexOut:
    if row is None:
        return IndexOut(
            status="none",
            files=0,
            chunks=0,
            skipped_files=0,
            skipped_chunks=0,
            indexed_at=None,
            queued_at=None,
            error=None,
        )
    return IndexOut(
        status=row.status,
        files=row.files_indexed or 0,
        chunks=row.chunks_total or 0,
        skipped_files=row.files_skipped or 0,
        skipped_chunks=row.chunks_skipped or 0,
        indexed_at=row.finished_at if row.status == "ready" else None,
        queued_at=row.queued_at,
        error=row.error,
    )


def _repo_in_org(db: Session, org_id: uuid.UUID, repo_id: uuid.UUID) -> Repository:
    """A repository, but only if it belongs to this organization (else 404, never a hint)."""
    repo = db.scalar(
        select(Repository)
        .join(GithubInstallation, Repository.installation_id == GithubInstallation.id)
        .where(Repository.id == repo_id, GithubInstallation.org_id == org_id)
    )
    if repo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Repository not found")
    return repo


@router.get("/orgs/{org_id}/repos/{repo_id}/index", response_model=IndexOut)
def get_index(repo_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> IndexOut:
    repo = _repo_in_org(db, ctx.org.id, repo_id)
    return index_out(db.get(RepositoryIndex, repo.id))


@router.post(
    "/orgs/{org_id}/repos/{repo_id}/index",
    response_model=IndexOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_index(
    repo_id: uuid.UUID, ctx: MemberCtx, db: DbSession, settings: Config, jobs: JobsDep
) -> IndexOut:
    """Index (or re-index) a repository for code search. Costs embedding tokens, so it needs
    at least the member role. Unchanged files are skipped, so re-indexing is cheap."""
    repo = _repo_in_org(db, ctx.org.id, repo_id)

    missing = settings.embedding_missing_settings()
    wrong_size = settings.embedding_dimensions != EMBEDDING_COLUMN_DIMENSIONS
    if missing or wrong_size:
        detail = "Code indexing isn't set up on the server yet. Ask an organization admin."
        if at_least(ctx.role, Role.admin):
            detail = (
                "Missing settings: " + ", ".join(missing)
                if missing
                else f"EMBEDDING_DIMENSIONS must be {EMBEDDING_COLUMN_DIMENSIONS}."
            )
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail)
    if not repo.default_branch:
        raise HTTPException(status.HTTP_409_CONFLICT, "This repository has no default branch yet")

    run_id = request_index(db, repo.id, ctx.user.id)
    if run_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This repository is already being indexed")
    queued = index_out(db.get(RepositoryIndex, repo.id))
    try:
        jobs.index_repository(repo.id, run_id)
    except JobQueueUnavailable as exc:
        abort_request(db, repo.id, run_id, str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return queued


@router.post("/orgs/{org_id}/search", response_model=SearchOut)
def search_code(
    body: SearchRequest,
    ctx: MemberCtx,
    db: DbSession,
    llm: Annotated[LLMService, Depends(get_llm)],
) -> SearchOut:
    """Semantic code search over this organization's indexed repositories."""
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Code search needs PostgreSQL with pgvector"
        )
    if llm.embedding_model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Embeddings are not configured on the server"
        )
    if body.repository_id is not None:
        _repo_in_org(db, ctx.org.id, body.repository_id)

    try:
        embedded = llm.embed(
            [body.query],
            "query",
            CallContext(feature="code_search", org_id=ctx.org.id, user_id=ctx.user.id),
        )
    except LLMError as exc:
        raise llm_http_error(exc) from exc
    vector = embedded.vectors[0]
    if len(vector) != EMBEDDING_COLUMN_DIMENSIONS:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The embedding model returned an unexpected vector size"
        )

    found = search_hits(db, ctx.org.id, vector, body.repository_id, body.limit)
    return SearchOut(
        results=[
            SearchHit(
                repository_id=h.repo_id,
                repository=h.repository,
                path=h.path,
                start_line=h.start_line,
                end_line=h.end_line,
                symbol=h.symbol,
                language=h.language,
                score=h.score,
                content=h.content[:SNIPPET_CHARS],
                also_in=h.also_in,
            )
            for h in found
        ]
    )
