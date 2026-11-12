"""The Celery application. Start a worker with:

    celery -A app.jobs.celery_app worker --loglevel=info --pool=solo      (Windows)
    celery -A app.jobs.celery_app worker --loglevel=info --concurrency=4  (Linux/macOS)

Jobs are only removed from the queue once they finish (acks_late), so a worker that crashes
mid-job doesn't lose it. Every task is therefore written to be safe to run twice.
"""

from celery import Celery

from app.core.config import get_settings

QUEUE = "devpilot"


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery("devpilot", broker=settings.redis_url, include=["app.jobs.tasks"])
    app.conf.update(
        task_default_queue=QUEUE,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,  # state lives in our database, not in Celery
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # one job at a time per worker slot: they are long
        worker_hijack_root_logger=False,
        broker_connection_retry_on_startup=True,
        # Fail fast when Redis is down instead of hanging the API request that enqueues a job.
        broker_transport_options={
            "visibility_timeout": 3 * 3600,  # longer than any job plus its retry delays
            "socket_connect_timeout": 3,
            "socket_timeout": 10,
        },
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = make_celery()
