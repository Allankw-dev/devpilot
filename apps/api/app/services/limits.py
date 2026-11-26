"""Usage limits that concurrent requests can't slip past.

The old approach counted finished AI calls and then compared. Twenty requests arriving together all
saw "0 used" and all went ahead. Here a slot is taken with ONE atomic statement (insert the counter,
or add 1 only if it is still below the limit), so the database decides who gets the last slot.

- The slot is taken in its own short transaction, committed at once. That way the row lock is not
  held while a slow AI call runs, and a request that fails later has still used its slot (the safe
  direction: a blocked request costs nothing, an attempted one counts).
- Windows are fixed (this minute, this UTC day), not sliding: right at a boundary someone can use
  up to twice the limit across two windows. That is the price of needing no extra service.
- Window edges come from this server's clock. Several API servers need clocks within a few seconds
  of each other, which any normal host already has.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import RateCounter

MINUTE = 60
DAY = 86_400


def _bucket(now: datetime, window_seconds: int) -> int:
    return int(now.timestamp()) // window_seconds


def try_consume(
    bind: Engine | Connection,
    key: str,
    limit: int,
    window_seconds: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Take one slot of `key` in the current window. True if there was room, False if the limit
    is already reached. Safe to call from many requests and many servers at once."""
    if limit < 1:
        return False
    bucket = _bucket(now or datetime.now(UTC), window_seconds)
    dialect = bind.dialect.name
    if dialect == "postgresql":
        pg_stmt = postgresql.insert(RateCounter).values(key=key, window=bucket, count=1)
        stmt = pg_stmt.on_conflict_do_update(
            index_elements=[RateCounter.key, RateCounter.window],
            set_={"count": RateCounter.count + 1},
            where=RateCounter.count < limit,
        ).returning(RateCounter.count)
    elif dialect == "sqlite":  # used by the test suite
        lite_stmt = sqlite.insert(RateCounter).values(key=key, window=bucket, count=1)
        stmt = lite_stmt.on_conflict_do_update(
            index_elements=[RateCounter.key, RateCounter.window],
            set_={"count": RateCounter.count + 1},
            where=RateCounter.count < limit,
        ).returning(RateCounter.count)
    else:
        raise NotImplementedError(f"Usage limits need PostgreSQL or SQLite, not {dialect}")

    with Session(bind=bind) as session:
        taken = session.execute(stmt).first() is not None
        if taken:  # forget this key's finished windows so the table doesn't grow forever
            session.execute(
                delete(RateCounter).where(RateCounter.key == key, RateCounter.window < bucket)
            )
        session.commit()
    return taken


def enforce(db: Session, key: str, limit: int, window_seconds: int, message: str) -> None:
    """Take a slot or raise 429 with `message`."""
    if not try_consume(db.get_bind(), key, limit, window_seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


def enforce_user_rate(
    db: Session, user_id: uuid.UUID, feature: str, per_minute: int, *, what: str
) -> None:
    """A person may start `per_minute` requests of `feature` each minute."""
    enforce(
        db,
        f"user:{user_id}:{feature}",
        per_minute,
        MINUTE,
        f"You're requesting a lot of {what}. Wait a minute and try again.",
    )


def enforce_org_daily(db: Session, settings: Settings, org_id: uuid.UUID) -> None:
    """One organization's cap on AI requests (Ask, reviews, CI analyses) per UTC day.
    Does nothing when AI_ORG_DAILY_REQUEST_LIMIT is 0."""
    limit = settings.ai_org_daily_request_limit
    if limit <= 0:
        return
    enforce(
        db,
        f"org:{org_id}:ai-requests",
        limit,
        DAY,
        "Your organization has used its AI requests for today. They reset at midnight UTC.",
    )
