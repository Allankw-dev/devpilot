"""Celery tasks. Thin wrappers: the real work lives in services so it can be tested directly."""

import logging
import uuid
from typing import Any

from celery import Task

from app.jobs.celery_app import celery_app
from app.jobs.context import resources
from app.services.github.sync import run_sync
from app.services.indexing.pipeline import STALE_RUNNING, TransientIndexError, run_index
from app.services.review.pipeline import TransientReviewError, run_review

logger = logging.getLogger(__name__)

INDEX_MAX_RETRIES = 6
INDEX_HARD_TIME_LIMIT = 2 * 3600  # a backstop; the pipeline has its own, gentler runtime limit
REVIEW_MAX_RETRIES = 4
REVIEW_HARD_TIME_LIMIT = 15 * 60  # one fetch and one model call: this is generous


def retry_delay(retries: int) -> int:
    """1 min, 2, 4, 8, 10, 10... seconds to wait before the next automatic attempt."""
    return min(60 * (1 << retries), 600)


@celery_app.task(name="devpilot.sync_installation")
def sync_installation(installation_pk: str, claimed: bool = False) -> bool:
    """Sync one GitHub installation. run_sync records its own success or failure."""
    r = resources()
    return run_sync(r.factory, r.github, uuid.UUID(installation_pk), claimed=claimed)


@celery_app.task(
    bind=True,
    name="devpilot.index_repository",
    max_retries=INDEX_MAX_RETRIES,
    time_limit=INDEX_HARD_TIME_LIMIT,
)
def index_repository(self: Task[Any, Any], repo_id: str, run_id: str) -> str:
    """Index one repository. Retries on rate limits and outages, resuming where it stopped."""
    r = resources()
    final = self.request.retries >= INDEX_MAX_RETRIES
    try:
        outcome = run_index(
            r.factory,
            r.github,
            r.get_llm,
            r.settings,
            uuid.UUID(repo_id),
            uuid.UUID(run_id),
            final_attempt=final,
        )
    except TransientIndexError as exc:
        raise self.retry(exc=exc, countdown=retry_delay(self.request.retries)) from exc
    if outcome == "busy" and not final:
        # Another worker holds this run. If it died, its heartbeat goes stale and we take over.
        raise self.retry(countdown=int(STALE_RUNNING.total_seconds()) + 60)
    return outcome


@celery_app.task(
    bind=True,
    name="devpilot.review_pull_request",
    max_retries=REVIEW_MAX_RETRIES,
    time_limit=REVIEW_HARD_TIME_LIMIT,
)
def review_pull_request(self: Task[Any, Any], review_id: str, run_id: str) -> str:
    """Review one pull request. Retries on rate limits and outages."""
    r = resources()
    final = self.request.retries >= REVIEW_MAX_RETRIES
    try:
        outcome = run_review(
            r.factory,
            r.github,
            r.get_llm,
            r.settings,
            uuid.UUID(review_id),
            uuid.UUID(run_id),
            final_attempt=final,
        )
    except TransientReviewError as exc:
        raise self.retry(exc=exc, countdown=retry_delay(self.request.retries)) from exc
    if outcome == "busy" and not final:
        raise self.retry(countdown=int(STALE_RUNNING.total_seconds()) + 60)
    return outcome
