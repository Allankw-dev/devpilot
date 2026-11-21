import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.ask_flow import run_ask
from app.api.deps import AnyMember, DbSession, MemberCtx, get_llm, get_retriever
from app.api.v1.indexing import _repo_in_org
from app.core.config import Settings, get_settings
from app.db.models import Conversation, ConversationMessage, Repository
from app.schemas import (
    AskCitation,
    AskOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationMessageOut,
    ConversationOut,
    MessageCreate,
    MessagePairOut,
)
from app.services.indexing.retrieval import Retriever
from app.services.llm import LLMService

router = APIRouter(tags=["conversations"])

Config = Annotated[Settings, Depends(get_settings)]
DEFAULT_TITLE = "New conversation"
MAX_MESSAGES = 100  # keeps one thread from growing without limit
TITLE_CHARS = 60


# ---------- helpers ----------


def _own(
    db: Session, org_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    """A conversation, but only for the person who started it: everyone else gets a 404, admins
    included, because questions about code can be sensitive."""
    found = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.org_id == org_id,
            Conversation.user_id == user_id,
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return found


def _message_out(m: ConversationMessage) -> ConversationMessageOut:
    return ConversationMessageOut(
        id=m.id,
        role=m.role,
        content=m.content,
        citations=[AskCitation(**c) for c in (m.citations or [])],
        confidence=m.confidence,
        missing_context=m.missing_context,
        sources_considered=m.sources_considered,
        model=m.model,
        input_tokens=m.input_tokens or 0,
        output_tokens=m.output_tokens or 0,
        created_at=m.created_at,
    )


def _conversation_out(
    db: Session, conversation: Conversation, message_count: int | None = None
) -> ConversationOut:
    repo_name = None
    if conversation.repo_id is not None:
        repo_name = db.scalar(
            select(Repository.full_name).where(Repository.id == conversation.repo_id)
        )
    if message_count is None:
        message_count = (
            db.scalar(
                select(func.count())
                .select_from(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation.id)
            )
            or 0
        )
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        repository_id=conversation.repo_id,
        repository=repo_name,
        message_count=message_count,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


def _title_from(question: str) -> str:
    text = " ".join(question.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def _fill(message: ConversationMessage, answer: AskOut) -> None:
    message.content = answer.answer
    message.citations = [c.model_dump(mode="json") for c in answer.citations]
    message.confidence = answer.confidence
    message.missing_context = answer.missing_context
    message.sources_considered = answer.sources_considered
    message.model = answer.model
    message.input_tokens = answer.input_tokens
    message.output_tokens = answer.output_tokens


def _ordered(db: Session, conversation_id: uuid.UUID) -> list[ConversationMessage]:
    return list(
        db.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at, ConversationMessage.role.desc())
        )
    )


# ---------- routes ----------


@router.get("/orgs/{org_id}/conversations", response_model=list[ConversationOut])
def list_conversations(
    ctx: AnyMember,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[ConversationOut]:
    """Your own conversations in this workspace, most recently active first."""
    rows = db.execute(
        select(Conversation, Repository.full_name)
        .outerjoin(Repository, Repository.id == Conversation.repo_id)
        .where(Conversation.org_id == ctx.org.id, Conversation.user_id == ctx.user.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    ).all()
    counts: dict[uuid.UUID, int] = {}
    if rows:
        counts = {
            cid: int(n)
            for cid, n in db.execute(
                select(ConversationMessage.conversation_id, func.count())
                .where(ConversationMessage.conversation_id.in_([c.id for c, _ in rows]))
                .group_by(ConversationMessage.conversation_id)
            )
        }
    return [
        ConversationOut(
            id=c.id,
            title=c.title,
            repository_id=c.repo_id,
            repository=name,
            message_count=counts.get(c.id, 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c, name in rows
    ]


@router.post(
    "/orgs/{org_id}/conversations",
    response_model=ConversationOut,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(body: ConversationCreate, ctx: MemberCtx, db: DbSession) -> ConversationOut:
    if body.repository_id is not None:
        _repo_in_org(db, ctx.org.id, body.repository_id)
    conversation = Conversation(
        org_id=ctx.org.id, user_id=ctx.user.id, repo_id=body.repository_id, title=DEFAULT_TITLE
    )
    db.add(conversation)
    db.commit()
    return _conversation_out(db, conversation, 0)


@router.get("/orgs/{org_id}/conversations/{conversation_id}", response_model=ConversationDetailOut)
def get_conversation(
    conversation_id: uuid.UUID, ctx: AnyMember, db: DbSession
) -> ConversationDetailOut:
    conversation = _own(db, ctx.org.id, ctx.user.id, conversation_id)
    messages = _ordered(db, conversation.id)
    base = _conversation_out(db, conversation, len(messages))
    return ConversationDetailOut(**base.model_dump(), messages=[_message_out(m) for m in messages])


@router.delete(
    "/orgs/{org_id}/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_conversation(conversation_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> Response:
    conversation = _own(db, ctx.org.id, ctx.user.id, conversation_id)
    db.delete(conversation)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/orgs/{org_id}/conversations/{conversation_id}/messages",
    response_model=MessagePairOut,
    status_code=status.HTTP_201_CREATED,
)
def ask_in_conversation(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    ctx: MemberCtx,
    db: DbSession,
    settings: Config,
    llm: Annotated[LLMService, Depends(get_llm)],
    retrieve: Annotated[Retriever, Depends(get_retriever)],
) -> MessagePairOut:
    """Ask a question. The question and its answer are saved together, and only if the answer
    succeeded, so a failed attempt never leaves a half-finished thread. Each question is answered
    from the code on its own: it does not see earlier answers."""
    conversation = _own(db, ctx.org.id, ctx.user.id, conversation_id)
    existing = _ordered(db, conversation.id)
    if len(existing) >= MAX_MESSAGES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This conversation is full. Start a new conversation."
        )

    answer = run_ask(
        db=db,
        org_id=ctx.org.id,
        user_id=ctx.user.id,
        settings=settings,
        llm=llm,
        retrieve=retrieve,
        question=body.question,
        repository_id=conversation.repo_id,
    )

    now = datetime.now(UTC)
    asked = ConversationMessage(conversation_id=conversation.id, role="user", content=body.question)
    asked.created_at = now
    replied = ConversationMessage(conversation_id=conversation.id, role="assistant", content="")
    replied.created_at = now
    _fill(replied, answer)
    db.add_all([asked, replied])
    if conversation.title == DEFAULT_TITLE:
        conversation.title = _title_from(body.question)
    conversation.updated_at = now
    db.commit()
    return MessagePairOut(user=_message_out(asked), assistant=_message_out(replied))


@router.post(
    "/orgs/{org_id}/conversations/{conversation_id}/messages/{message_id}/regenerate",
    response_model=ConversationMessageOut,
)
def regenerate(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    ctx: MemberCtx,
    db: DbSession,
    settings: Config,
    llm: Annotated[LLMService, Depends(get_llm)],
    retrieve: Annotated[Retriever, Depends(get_retriever)],
) -> ConversationMessageOut:
    """Answer the last question again and replace the last answer. Costs AI tokens, so it is only
    ever done on request, and only for the most recent answer."""
    conversation = _own(db, ctx.org.id, ctx.user.id, conversation_id)
    messages = _ordered(db, conversation.id)
    last = messages[-1] if messages else None
    if last is None or last.id != message_id or last.role != "assistant" or len(messages) < 2:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only the most recent answer can be generated again"
        )
    question = messages[-2].content

    answer = run_ask(
        db=db,
        org_id=ctx.org.id,
        user_id=ctx.user.id,
        settings=settings,
        llm=llm,
        retrieve=retrieve,
        question=question,
        repository_id=conversation.repo_id,
    )
    _fill(last, answer)
    conversation.updated_at = datetime.now(UTC)
    db.commit()
    return _message_out(last)
