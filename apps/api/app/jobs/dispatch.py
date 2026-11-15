"""Starting background jobs from the API.

Two backends (setting JOB_BACKEND):
- celery: put the job on the Redis queue for a worker. Needs a running worker.
- inline: run it in this process right after the response. Simple, but a job is lost if the
  API restarts, and a long job occupies a server thread. For a quick start and for tests.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Literal

from fastapi import BackgroundTasks
from kombu.exceptions import KombuError
from redis.exceptions import RedisError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.services.github.client import GitHubClient
from app.services.github.sync import run_sync
from app.services.indexing.pipeline import run_index
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

# Give up quickly when Redis is down so the API answers instead of hanging.
PUBLISH_RETRY = {"max_retries": 1, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}


class JobQueueUnavailable(Exception):
    """The job queue (Redis) could not be reached."""


class Jobs:
    def __init__(
        self,
        *,
        backend: Literal["celery", "inline"],
        background: BackgroundTasks,
        factory: sessionmaker[Session],
        github: GitHubClient,
        get_llm: Callable[[], LLMService],
        settings: Settings,
    ) -> None:
        self._backend = backend
        self._background = background
        self._factory = factory
        self._github = github
        self._get_llm = get_llm
        self._settings = settings

    def sync_installation(self, installation_pk: uuid.UUID, *, claimed: bool) -> None:
        if self._backend == "inline":
            self._background.add_task(
                run_sync, self._factory, self._github, installation_pk, claimed=claimed
            )
            return
        from app.jobs.tasks import sync_installation

        self._publish(sync_installation, str(installation_pk), claimed)

    def index_repository(self, repo_id: uuid.UUID, run_id: uuid.UUID) -> None:
        if self._backend == "inline":
            self._background.add_task(
                run_index,
                self._factory,
                self._github,
                self._get_llm,
                self._settings,
                repo_id,
                run_id,
                final_attempt=True,  # nothing would retry it later
            )
            return
        from app.jobs.tasks import index_repository

        self._publish(index_repository, str(repo_id), str(run_id))

    @staticmethod
    def _publish(task: object, *args: object) -> None:
        try:
            task.apply_async(args=args, retry=True, retry_policy=PUBLISH_RETRY)  # type: ignore[attr-defined]
        except (KombuError, RedisError, OSError) as exc:
            logger.error("Could not enqueue %s: %s", getattr(task, "name", task), exc)
            raise JobQueueUnavailable("The job queue is not reachable. Is Redis running?") from exc
