"""Health endpoints.

- `/health/live`: the process is up. Touches nothing else, so a database outage never makes an
  orchestrator restart a healthy API.
- `/health/ready`: the API can do its job right now (database and Redis answer). Point load
  balancers at this one; it returns 503 when not ready.
- `/health`: the same checks with a little more detail, used by the web status page.
"""

import logging
from typing import Literal

import redis
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])

Status = Literal["ok", "down"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    product: str
    environment: str
    database: Status
    redis: Status


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Status
    redis: Status


def get_redis(settings: Settings = Depends(get_settings)) -> redis.Redis:  # noqa: B008
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


def _probe(db: Session, cache: redis.Redis) -> tuple[Status, Status]:
    """Ask the database and Redis. The cause of a failure is logged; callers only see up/down."""
    db_status: Status = "ok"
    redis_status: Status = "ok"

    # Probes run every few seconds, so a failure is one short warning line, not a traceback each
    # time. The full traceback is there at LOG_LEVEL=DEBUG.
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("database health check failed (%s)", type(exc).__name__)
        logger.debug("database health check traceback", exc_info=True)
        db_status = "down"

    try:
        cache.ping()
    except Exception as exc:
        logger.warning("redis health check failed (%s)", type(exc).__name__)
        logger.debug("redis health check traceback", exc_info=True)
        redis_status = "down"

    return db_status, redis_status


@router.get("/health/live", response_model=LiveResponse)
def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse)
def ready(
    response: Response,
    db: Session = Depends(get_db),  # noqa: B008
    cache: redis.Redis = Depends(get_redis),  # noqa: B008
) -> ReadyResponse:
    db_status, redis_status = _probe(db, cache)
    is_ready = db_status == "ok" and redis_status == "ok"
    if not is_ready:
        response.status_code = 503
    return ReadyResponse(
        status="ready" if is_ready else "not_ready", database=db_status, redis=redis_status
    )


@router.get("/health", response_model=HealthResponse)
def health(
    response: Response,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    cache: redis.Redis = Depends(get_redis),  # noqa: B008
) -> HealthResponse:
    db_status, redis_status = _probe(db, cache)
    healthy = db_status == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = 503

    return HealthResponse(
        status="ok" if healthy else "degraded",
        product=settings.product_name,
        environment=settings.environment,
        database=db_status,
        redis=redis_status,
    )
