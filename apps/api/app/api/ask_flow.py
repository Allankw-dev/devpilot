"""One question answered from the organization's indexed code (`/ask` and conversations)."""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.llm_http import llm_http_error
from app.api.ratelimit import check_rate_limit
from app.api.v1.indexing import _repo_in_org
from app.core.config import Settings
from app.db.models import EMBEDDING_COLUMN_DIMENSIONS
from app.schemas import AskCitation, AskOut
from app.services.indexing.retrieval import Retriever, file_list, search_hits
from app.services.llm import CallContext, LLMError, LLMService
from app.services.qa.answer import answer_question

logger = logging.getLogger(__name__)

FEATURE = "ask"


def run_ask(
    *,
    db: Session,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    settings: Settings,
    llm: LLMService,
    retrieve: Retriever,
    question: str,
    repository_id: uuid.UUID | None,
) -> AskOut:
    """Find the relevant code, answer, and check the citations. Raises HTTPException with a clear
    message for anything the caller can act on (nothing indexed, AI not set up, quota, ...)."""
    if retrieve is search_hits and db.get_bind().dialect.name != "postgresql":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED, "Asking about code needs PostgreSQL with pgvector"
        )
    if llm.embedding_model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Embeddings are not configured on the server"
        )
    if repository_id is not None:
        _repo_in_org(db, org_id, repository_id)
    check_rate_limit(db, user_id, FEATURE, settings.ask_rate_limit_per_minute, what="questions")

    try:
        embedded = llm.embed(
            [question],
            "query",
            CallContext(feature="ask_retrieval", org_id=org_id, user_id=user_id),
        )
    except LLMError as exc:
        raise llm_http_error(exc) from exc
    vector = embedded.vectors[0]
    if len(vector) != EMBEDDING_COLUMN_DIMENSIONS:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "The embedding model returned an unexpected vector size"
        )

    hits = retrieve(
        db, org_id, vector, repository_id, settings.ask_top_k, settings.ask_max_chunks_per_file
    )
    if not hits:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Nothing is indexed to answer from. Index a repository first.",
        )
    files = file_list(db, org_id, repository_id) if repository_id is not None else []

    try:
        answer = answer_question(
            llm,
            question,
            hits,
            files,
            CallContext(feature=FEATURE, org_id=org_id, user_id=user_id),
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
