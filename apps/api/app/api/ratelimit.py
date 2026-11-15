"""A simple per-person rate limit for AI features, based on the usage log (no extra services)."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LlmUsage


def check_rate_limit(
    db: Session, user_id: uuid.UUID, feature: str, per_minute: int, *, what: str = "requests"
) -> None:
    """Raise 429 if this person already used `feature` `per_minute` times in the last minute.
    Counts AI calls recorded in llm_usage, so a blocked request costs nothing."""
    recent = db.scalar(
        select(func.count())
        .select_from(LlmUsage)
        .where(
            LlmUsage.user_id == user_id,
            LlmUsage.feature == feature,
            LlmUsage.created_at >= datetime.now(UTC) - timedelta(seconds=60),
        )
    )
    if (recent or 0) >= per_minute:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You're sending a lot of {what}. Wait a minute and try again.",
        )
