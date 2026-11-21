from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.ask_flow import run_ask
from app.api.deps import DbSession, MemberCtx, get_llm, get_retriever
from app.core.config import Settings, get_settings
from app.schemas import AskOut, AskRequest
from app.services.indexing.retrieval import Retriever
from app.services.llm import LLMService

router = APIRouter(tags=["ask"])

Config = Annotated[Settings, Depends(get_settings)]


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
    return run_ask(
        db=db,
        org_id=ctx.org.id,
        user_id=ctx.user.id,
        settings=settings,
        llm=llm,
        retrieve=retrieve,
        question=body.question,
        repository_id=body.repository_id,
    )
