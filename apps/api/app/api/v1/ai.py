import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app.api.deps import AdminCtx, AnyMember, DbSession, get_llm
from app.api.llm_http import llm_http_error
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import LlmUsage
from app.schemas import (
    AiStatusOut,
    AiTestOut,
    AiUsageDayOut,
    AiUsageDetailOut,
    AiUsageErrorOut,
    AiUsageFeatureOut,
    AiUsageModelOut,
    AiUsageOut,
)
from app.services.llm import CallContext, GenerationRequest, LLMService, Message
from app.services.llm.errors import LLMError

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
    except LLMError as exc:
        logger.warning("AI test failed: %s", exc.code)
        raise llm_http_error(exc) from exc

    return AiTestOut(
        ok=True,
        provider=llm.provider_name,
        model=result.model,
        latency_ms=int((time.monotonic() - started) * 1000),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        reply=result.text.strip()[:200],
    )


# ---------- usage dashboard ----------


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)  # SQLite returns naive datetimes
    return value


def _day_bucket(db: Session) -> ColumnElement[object]:
    """The UTC calendar day of a usage row, on either database."""
    if db.get_bind().dialect.name == "postgresql":
        return func.date(func.timezone("UTC", LlmUsage.created_at))
    return func.date(LlmUsage.created_at)


def _to_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])  # SQLite gives text


def _errors_sum() -> ColumnElement[int]:
    return func.coalesce(func.sum(case((LlmUsage.status == "error", 1), else_=0)), 0)


@router.get("/orgs/{org_id}/ai/usage", response_model=AiUsageDetailOut)
def ai_usage(
    ctx: AnyMember,
    db: DbSession,
    settings: Config,
    days: Annotated[int, Query(ge=1, le=90)] = 14,
) -> AiUsageDetailOut:
    """Where this organization's AI requests, tokens and errors went. Counts only calls made
    through DevPilot; the provider's own quota also counts other apps that use the same key."""
    now = datetime.now(UTC)
    first_day = now.date() - timedelta(days=days - 1)
    since = datetime(first_day.year, first_day.month, first_day.day, tzinfo=UTC)
    mine = (LlmUsage.org_id == ctx.org.id, LlmUsage.created_at >= since)

    day = _day_bucket(db)
    per_day = {
        _to_date(row[0]): row
        for row in db.execute(
            select(
                day,
                func.count(),
                func.coalesce(func.sum(LlmUsage.calls), 0),
                _errors_sum(),
                func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            )
            .where(*mine)
            .group_by(day)
        ).all()
    }
    by_day: list[AiUsageDayOut] = []
    for offset in range(days):  # every day shown, even the quiet ones
        d = first_day + timedelta(days=offset)
        row = per_day.get(d)
        by_day.append(
            AiUsageDayOut(
                day=d,
                operations=int(row[1]) if row else 0,
                provider_calls=int(row[2]) if row else 0,
                errors=int(row[3]) if row else 0,
                input_tokens=int(row[4]) if row else 0,
                output_tokens=int(row[5]) if row else 0,
            )
        )

    by_feature = [
        AiUsageFeatureOut(
            feature=f,
            operations=int(n),
            provider_calls=int(c),
            errors=int(e),
            input_tokens=int(i),
            output_tokens=int(o),
        )
        for f, n, c, e, i, o in db.execute(
            select(
                LlmUsage.feature,
                func.count(),
                func.coalesce(func.sum(LlmUsage.calls), 0),
                _errors_sum(),
                func.coalesce(func.sum(LlmUsage.input_tokens), 0),
                func.coalesce(func.sum(LlmUsage.output_tokens), 0),
            )
            .where(*mine)
            .group_by(LlmUsage.feature)
            .order_by(func.sum(LlmUsage.calls).desc(), LlmUsage.feature)
        ).all()
    ]

    last_24h = {
        m: int(c)
        for m, c in db.execute(
            select(LlmUsage.model, func.coalesce(func.sum(LlmUsage.calls), 0))
            .where(LlmUsage.org_id == ctx.org.id, LlmUsage.created_at >= now - timedelta(hours=24))
            .group_by(LlmUsage.model)
        ).all()
    }
    by_model = [
        AiUsageModelOut(
            model=m,
            operations=int(n),
            provider_calls=int(c),
            errors=int(e),
            calls_last_24h=last_24h.get(m, 0),
        )
        for m, n, c, e in db.execute(
            select(
                LlmUsage.model,
                func.count(),
                func.coalesce(func.sum(LlmUsage.calls), 0),
                _errors_sum(),
            )
            .where(*mine)
            .group_by(LlmUsage.model)
            .order_by(func.sum(LlmUsage.calls).desc(), LlmUsage.model)
        ).all()
    ]

    errors_by_code = [
        AiUsageErrorOut(code=code or "unknown", count=int(n))
        for code, n in db.execute(
            select(LlmUsage.error_code, func.count())
            .where(*mine, LlmUsage.status == "error")
            .group_by(LlmUsage.error_code)
            .order_by(func.count().desc(), LlmUsage.error_code)
        ).all()
    ]

    avg_latency = db.scalar(
        select(func.avg(LlmUsage.latency_ms)).where(*mine, LlmUsage.status == "ok")
    )
    quota_hit_at = db.scalar(
        select(func.max(LlmUsage.created_at)).where(*mine, LlmUsage.error_code == "quota_exhausted")
    )

    return AiUsageDetailOut(
        days=days,
        since=first_day,
        operations=sum(f.operations for f in by_feature),
        provider_calls=sum(f.provider_calls for f in by_feature),
        errors=sum(f.errors for f in by_feature),
        input_tokens=sum(f.input_tokens for f in by_feature),
        output_tokens=sum(f.output_tokens for f in by_feature),
        avg_latency_ms=round(float(avg_latency)) if avg_latency is not None else None,
        calls_last_24h=sum(last_24h.values()),
        daily_limit=settings.ai_daily_request_limit or None,
        quota_hit_at=_aware(quota_hit_at),
        by_day=by_day,
        by_feature=by_feature,
        by_model=by_model,
        errors_by_code=errors_by_code,
    )
