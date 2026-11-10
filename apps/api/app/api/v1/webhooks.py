import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_github_client, get_session_factory_dep
from app.core.config import Settings, get_settings
from app.db.models import WebhookDelivery
from app.services.github.client import GitHubClient
from app.services.github.sync import run_sync
from app.services.github.webhooks import process_event, valid_signature

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

MAX_BODY_BYTES = 25 * 1024 * 1024  # GitHub's own payload cap


def _apply(
    factory: sessionmaker[Session],
    delivery: str,
    event: str,
    payload: dict[str, Any],
    retention: timedelta,
) -> tuple[str, list[uuid.UUID]]:
    scheduled: list[uuid.UUID] = []
    with factory() as db:
        db.add(WebhookDelivery(delivery_id=delivery, event=event))
        try:
            db.flush()
        except IntegrityError:  # GitHub redelivered something we already handled
            db.rollback()
            return "duplicate", []
        outcome = process_event(db, event, payload, scheduled.append)
        # Old ids can't be redelivered any more, so don't keep them forever.
        cutoff = datetime.now(UTC) - retention
        db.execute(delete(WebhookDelivery).where(WebhookDelivery.received_at < cutoff))
        db.commit()  # the delivery record and its effects commit together
    return outcome, scheduled


@router.post("/github")
async def github_webhook(
    request: Request,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    factory: Annotated[sessionmaker[Session], Depends(get_session_factory_dep)],
    client: Annotated[GitHubClient, Depends(get_github_client)],
) -> dict[str, str]:
    secret = (
        settings.github_webhook_secret.get_secret_value() if settings.github_webhook_secret else ""
    )
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook secret is not configured")

    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")

    # Nothing is parsed or stored until the signature over the raw bytes checks out.
    if not valid_signature(secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")

    event = request.headers.get("x-github-event")
    delivery = request.headers.get("x-github-delivery")
    if not event or not delivery or len(delivery) > 64 or len(event) > 50:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing GitHub headers")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not valid JSON") from None
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unexpected payload")

    outcome, scheduled = await run_in_threadpool(
        _apply,
        factory,
        delivery,
        event,
        payload,
        timedelta(days=settings.webhook_delivery_retention_days),
    )
    for installation_pk in scheduled:
        background.add_task(run_sync, factory, client, installation_pk)

    logger.info("github webhook event=%s delivery=%s outcome=%s", event, delivery, outcome)
    return {"status": outcome}
