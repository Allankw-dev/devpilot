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


def get_redis(settings: Settings = Depends(get_settings)) -> redis.Redis:  # noqa: B008
    return redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


@router.get("/health", response_model=HealthResponse)
def health(
    response: Response,
    settings: Settings = Depends(get_settings),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    cache: redis.Redis = Depends(get_redis),  # noqa: B008
) -> HealthResponse:
    db_status: Status = "ok"
    redis_status: Status = "ok"

    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("database health check failed")
        db_status = "down"

    try:
        cache.ping()
    except Exception:
        logger.exception("redis health check failed")
        redis_status = "down"

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
