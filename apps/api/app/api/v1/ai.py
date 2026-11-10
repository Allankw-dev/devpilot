import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select

from app.api.deps import AdminCtx, AnyMember, DbSession, get_llm
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import LlmUsage
from app.schemas import AiStatusOut, AiTestOut, AiUsageOut
from app.services.llm import CallContext, GenerationRequest, LLMService, Message
from app.services.llm.errors import (
    LLMAuthError,
    LLMError,
    LLMRateLimited,
    LLMTimeout,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ai"])

USAGE_WINDOW_DAYS = 30
Config = Annotated[Settings, Depends(get_settings)]


@router.get("/orgs/{org_id}/ai", response_model=AiStatusOut)
def ai_status(ctx: AnyMember, db: DbSession, settings: Config) -> AiStatusOut:
    missing = settings.llm_missing_settings()
    provider = settings.llm_provider
    model = settings.anthropic_model if provider == "anthropic" else settings.gemini_model

    since = datetime.now(UTC) - timedelta(days=USAGE_WINDOW_DAYS)
    requests, errors, tokens_in, tokens_out = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(case((LlmUsage.status == "error", 1), else_=0)), 0),
            func.coalesce(func.sum(LlmUsage.input_tokens), 0),
            func.coalesce(func.sum(LlmUsage.output_tokens), 0),
        ).where(LlmUsage.org_id == ctx.org.id, LlmUsage.created_at >= since)
    ).one()

    return AiStatusOut(
        configured=not missing,
        provider=provider,
        model=model if not missing else None,
        embeddings_configured=not settings.embedding_missing_settings(),
        missing=missing if at_least(ctx.role, Role.admin) else [],
        usage=AiUsageOut(
            days=USAGE_WINDOW_DAYS,
            requests=int(requests),
            errors=int(errors),
            input_tokens=int(tokens_in),
            output_tokens=int(tokens_out),
        ),
    )


@router.post("/orgs/{org_id}/ai/test", response_model=AiTestOut)
def ai_test(ctx: AdminCtx, llm: Annotated[LLMService, Depends(get_llm)]) -> AiTestOut:
    """Sends one tiny prompt to check the API key and model work. Costs a few tokens."""
    started = time.monotonic()
    try:
        result = llm.generate(
            GenerationRequest(
                messages=[Message(role="user", content="Reply with the single word: OK")],
                max_output_tokens=64,
            ),
            CallContext(feature="ai_test", org_id=ctx.org.id, user_id=ctx.user.id),
        )
    except LLMAuthError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The AI provider rejected the API key, or the key can't use the configured model.",
        ) from exc
    except LLMRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "The AI provider is rate limiting us"
        ) from exc
    except LLMTimeout as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "The AI provider timed out") from exc
    except LLMError as exc:
        logger.warning("AI test failed: %s", exc.code)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The AI provider call failed ({exc.code})"
        ) from exc

    return AiTestOut(
        ok=True,
        provider=llm.provider_name,
        model=result.model,
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        reply=result.text.strip()[:200],
    )
