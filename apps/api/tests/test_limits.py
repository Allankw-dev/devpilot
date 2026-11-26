"""The atomic usage limiter: slots run out, windows roll over, and concurrent callers can't cheat."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import RateCounter
from app.services.limits import (
    DAY,
    MINUTE,
    enforce,
    enforce_org_daily,
    enforce_user_rate,
    try_consume,
)
from tests.conftest import ON_POSTGRES

NOON = datetime(2026, 11, 25, 12, 0, 30, tzinfo=UTC)


def rows(engine: Engine, key: str | None = None) -> list[tuple[str, int, int]]:
    with Session(engine) as s:
        query = select(RateCounter.key, RateCounter.window, RateCounter.count)
        if key:
            query = query.where(RateCounter.key == key)
        return [tuple(r) for r in s.execute(query.order_by(RateCounter.window))]


def test_slots_run_out_and_a_refusal_is_not_counted(engine: Engine) -> None:
    results = [try_consume(engine, "k", 3, MINUTE, now=NOON) for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert [r[2] for r in rows(engine, "k")] == [3]  # refusals don't push the count past the limit


@pytest.mark.parametrize("limit", [0, -1])
def test_a_limit_below_one_allows_nothing(engine: Engine, limit: int) -> None:
    assert try_consume(engine, "k", limit, MINUTE, now=NOON) is False
    assert rows(engine) == []


def test_keys_are_independent(engine: Engine) -> None:
    assert try_consume(engine, "user:a", 1, MINUTE, now=NOON) is True
    assert try_consume(engine, "user:a", 1, MINUTE, now=NOON) is False
    assert try_consume(engine, "user:b", 1, MINUTE, now=NOON) is True


def test_the_next_window_starts_fresh_and_old_windows_are_removed(engine: Engine) -> None:
    assert try_consume(engine, "k", 1, MINUTE, now=NOON) is True
    assert try_consume(engine, "k", 1, MINUTE, now=NOON) is False
    later = NOON.replace(minute=1, second=5)
    assert try_consume(engine, "k", 1, MINUTE, now=later) is True
    assert len(rows(engine, "k")) == 1  # the finished minute was cleaned up
    assert try_consume(engine, "other", 1, MINUTE, now=NOON) is True  # other keys untouched
    assert len(rows(engine)) == 2


def test_daily_windows_follow_the_utc_day(engine: Engine) -> None:
    late = datetime(2026, 11, 25, 23, 59, 59, tzinfo=UTC)
    early = datetime(2026, 11, 26, 0, 0, 1, tzinfo=UTC)
    assert try_consume(engine, "org", 1, DAY, now=late) is True
    assert try_consume(engine, "org", 1, DAY, now=late) is False
    assert try_consume(engine, "org", 1, DAY, now=early) is True


def test_enforce_raises_429_with_the_message(db: Session) -> None:
    enforce(db, "k", 1, MINUTE, "slow down")
    with pytest.raises(HTTPException) as err:
        enforce(db, "k", 1, MINUTE, "slow down")
    assert err.value.status_code == 429 and err.value.detail == "slow down"


def test_user_rate_message_names_the_feature(db: Session) -> None:
    who = uuid.uuid4()
    enforce_user_rate(db, who, "ask", 1, what="questions")
    with pytest.raises(HTTPException) as err:
        enforce_user_rate(db, who, "ask", 1, what="questions")
    assert "questions" in err.value.detail and "Wait a minute" in err.value.detail
    enforce_user_rate(db, who, "review", 1, what="reviews")  # a different feature has its own slots


def test_the_org_daily_cap_is_off_by_default(db: Session, engine: Engine) -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_org_daily_request_limit == 0
    for _ in range(5):
        enforce_org_daily(db, settings, uuid.uuid4())
    assert rows(engine) == []  # nothing was even counted


def test_the_org_daily_cap_applies_to_the_whole_organization(db: Session) -> None:
    settings = Settings(_env_file=None, ai_org_daily_request_limit=2)
    org, other = uuid.uuid4(), uuid.uuid4()
    enforce_org_daily(db, settings, org)
    enforce_org_daily(db, settings, org)
    with pytest.raises(HTTPException) as err:
        enforce_org_daily(db, settings, org)
    assert err.value.status_code == 429 and "organization" in err.value.detail
    enforce_org_daily(db, settings, other)  # another organization has its own allowance


@pytest.mark.skipif(not ON_POSTGRES, reason="needs real concurrent connections (PostgreSQL)")
def test_concurrent_callers_cannot_exceed_the_limit(engine: Engine) -> None:
    """The bug this fixes: many requests at once all saw room, because they counted finished work."""
    limit, callers = 5, 60
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(lambda _: try_consume(engine, "burst", limit, 3600, now=NOON), range(callers))
        )
    assert sum(results) == limit
    with Session(engine) as s:
        assert (
            s.scalar(select(func.max(RateCounter.count)).where(RateCounter.key == "burst")) == limit
        )
