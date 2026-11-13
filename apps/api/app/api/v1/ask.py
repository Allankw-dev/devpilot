import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, MemberCtx, get_llm, get_retriever
from app.api.llm_http import llm_http_error
from app.api.v1.indexing import _repo_in_org
from app.core.config import Settings, get_settings
from app.db.models import EMBEDDING_COLUMN_DIMENSIONS, LlmUsage
from app.schemas import AskCitation, AskOut, AskRequest
from app.services.indexing.retrieval import Retriever, file_list, search_hits
from app.services.llm import CallContext, LLMError, LLMService
from app.services.qa.answer import answer_question

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ask"])

Config = Annotated[Settings, Depends(get_settings)]
FEATURE = "ask"


def _check_rate_limit(db: Session, user_id: uuid.UUID, per_minute: int) -> None:
    """Questions cost tokens, so cap how fast one person can ask. Uses the usage log, so it
    needs no extra infrastructure."""
    recent = db.scalar(
        select(func.count())
        .select_from(LlmUsage)
        .where(
            LlmUsage.user_id == user_id,
            LlmUsage.feature == FEATURE,
            LlmUsage.created_at >= datetime.now(UTC) - timedelta(seconds=60),
        )
    )
    if (recent or 0) >= per_minute:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You're asking a lot of questions. Wait a minute and try again.",
        )


@router.post("/orgs/{org_id}/ask", response_model=AskOut)
def ask(
    body: AskRequest,
    ctx: MemberCtx,
    db: DbSession,
    settings: Config,
    llm: Annotated[LLMService, Depends(get_llm)],
    retrieve: Annotated[Retriever, Depends(get_retriever)],
) -> AskOut:
    """Answer a question about this organization's indexed code, citing files and lines."""
    if retrieve is search_hits and db.get_bind().dialect.name != "postgresql":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Asking about code needs PostgreSQL with pgvector"
        )
    if llm.embedding_model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Embeddings are not configured on the server"
        )
    if body.repository_id is not None:
        _repo_in_org(db, ctx.org.id, body.repository_id)
    _check_rate_limit(db, ctx.user.id, settings.ask_rate_limit_per_minute)

    try:
        embedded = llm.embed(
            [body.question],
            "query",
            CallContext(feature="ask_retrieval", org_id=ctx.org.id, user_id=ctx.user.id),
        )
    except LLMError as exc:
        raise llm_http_error(exc) from exc
    vector = embedded.vectors[0]
    if len(vector) != EMBEDDING_COLUMN_DIMENSIONS:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The embedding model returned an unexpected vector size"
        )

    hits = retrieve(db, ctx.org.id, vector, body.repository_id, settings.ask_top_k)
    if not hits:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Nothing is indexed to answer from. Index a repository first.",
        )
    files = (
        file_list(db, ctx.org.id, body.repository_id) if body.repository_id is not None else []
    )

    try:
        answer = answer_question(
            llm,
            body.question,
            hits,
            files,
            CallContext(feature=FEATURE, org_id=ctx.org.id, user_id=ctx.user.id),
            max_context_chars=settings.ask_max_context_chars,
            max_output_tokens=settings.ask_max_output_tokens,
        )
    except LLMError as exc:
        logger.warning("Ask failed: %s", exc.code)
        raise llm_http_error(exc) from exc

    return AskOut(
        answer=answer.text,
        confidence=answer.confidence,
        missing_context=answer.missing_context,
        citations=[
            AskCitation(
                n=s.n,
                repository_id=s.hit.repo_id,
                repository=s.hit.repository,
                path=s.hit.path,
                start_line=s.hit.start_line,
                end_line=s.hit.end_line,
                symbol=s.hit.symbol,
                score=s.hit.score,
            )
            for s in answer.citations
        ],
        sources_considered=answer.sources_considered,
        model=answer.model,
        input_tokens=answer.usage.input_tokens,
        output_tokens=answer.usage.output_tokens,
    )
