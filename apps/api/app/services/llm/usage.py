"""Recording AI usage (tokens, latency, outcome). Never stores prompts or replies."""

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import LlmUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallContext:
    """Who and what an AI call is for. `feature` is a short label like "codebase_qa"."""

    feature: str
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


@dataclass(frozen=True)
class UsageEntry:
    ctx: CallContext
    provider: str
    model: str
    operation: str
    status: str
    error_code: str | None
    input_tokens: int
    output_tokens: int
    calls: int
    latency_ms: int


class UsageRecorder(Protocol):
    def record(self, entry: UsageEntry) -> None: ...


class NullUsageRecorder:
    def record(self, entry: UsageEntry) -> None:
        return None


class DbUsageRecorder:
    """Writes with its own session so it works from background jobs and can't disturb a
    request's transaction. A failure here is logged and swallowed: losing a usage row must
    never break the feature that was being used."""

    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory

    def record(self, entry: UsageEntry) -> None:
        try:
            with self._factory() as db:
                db.add(
                    LlmUsage(
                        org_id=entry.ctx.org_id,
                        user_id=entry.ctx.user_id,
                        provider=entry.provider[:20],
                        model=entry.model[:100],
                        operation=entry.operation[:20],
                        feature=entry.ctx.feature[:50],
                        status=entry.status,
                        error_code=entry.error_code,
                        input_tokens=entry.input_tokens,
                        output_tokens=entry.output_tokens,
                        calls=entry.calls,
                        latency_ms=entry.latency_ms,
                    )
                )
                db.commit()
        except Exception:
            logger.exception("Could not record AI usage")
