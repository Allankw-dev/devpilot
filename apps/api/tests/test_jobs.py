"""The Celery path: tasks, retries, and what happens when the queue is unreachable.

Celery runs in 'eager' mode here (tasks execute immediately in-process), so no Redis is needed.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from celery.exceptions import Retry
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from kombu.exceptions import OperationalError
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm, get_llm_getter
from app.core.config import Settings, get_settings
from app.db.models import GithubInstallation
from app.jobs import tasks
from app.jobs.celery_app import QUEUE, celery_app
from app.jobs.context import JobResources, set_resources
from app.jobs.dispatch import JobQueueUnavailable, Jobs
from app.main import app
from app.services.github.client import GitHubClient
from app.services.indexing.pipeline import STALE_RUNNING
from app.services.llm.errors import LLMAuthError, LLMRateLimited
from tests.conftest import World
from tests.github_helpers import FakeGitHub, connect
from tests.index_helpers import IndexEnv, make_env

API = "/api/v1"


@pytest.fixture
def eager() -> Iterator[None]:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False
    set_resources(None)


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> IndexEnv:
    configured = gh_settings.model_copy(
        update={
            "gemini_api_key": SecretStr("k"),
            "gemini_embedding_model": "fake-embed-v1",
            "job_backend": "celery",
        }
    )
    e = make_env(client, world, fake_github, gh_client, session_factory, configured)
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_llm] = lambda: e.llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: e.llm)
    set_resources(JobResources(e.factory, e.github, lambda: e.llm, configured))
    return e


def jobs_for(e: IndexEnv, backend: str = "celery") -> Jobs:
    return Jobs(
        backend=backend,  # type: ignore[arg-type]
        background=BackgroundTasks(),
        factory=e.factory,
        github=e.github,
        get_llm=lambda: e.llm,
        settings=e.settings,
    )


# ---------- configuration ----------


def test_celery_is_configured_to_not_lose_jobs() -> None:
    conf = celery_app.conf
    assert conf.task_acks_late and conf.task_reject_on_worker_lost  # re-delivered after a crash
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_serializer == "json" and list(conf.accept_content) == ["json"]
    assert conf.task_default_queue == QUEUE
    assert conf.broker_transport_options["visibility_timeout"] > 2 * 3600  # > longest job
    assert conf.broker_transport_options["socket_connect_timeout"] <= 5  # fail fast


def test_tasks_are_registered_under_stable_names() -> None:
    assert "devpilot.sync_installation" in celery_app.tasks
    assert "devpilot.index_repository" in celery_app.tasks


def test_retry_delays_back_off_and_are_capped() -> None:
    assert [tasks.retry_delay(n) for n in range(6)] == [60, 120, 240, 480, 600, 600]


# ---------- indexing through Celery ----------


@pytest.mark.usefixtures("eager")
def test_index_job_runs_through_the_task(env: IndexEnv) -> None:
    run_id = env.request()
    jobs_for(env).index_repository(env.repo_id, run_id)
    assert env.index().status == "ready" and env.chunks()


@pytest.mark.usefixtures("eager")
def test_the_same_job_delivered_twice_only_does_the_work_once(env: IndexEnv) -> None:
    run_id = env.request()
    jobs = jobs_for(env)
    jobs.index_repository(env.repo_id, run_id)
    calls = env.embedder.calls
    jobs.index_repository(env.repo_id, run_id)  # redelivery after a worker restart
    assert env.embedder.calls == calls


class RetryRecorder:
    """Stands in for Task.retry so a test can see what retry the task asked for."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Retry:
        self.requests.append(kwargs)
        return Retry("requested", when=kwargs.get("countdown"))


@pytest.mark.usefixtures("eager")
def test_a_rate_limit_asks_for_a_delayed_retry_and_keeps_the_run_queued(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RetryRecorder()
    monkeypatch.setattr(tasks.index_repository, "retry", recorder)
    celery_app.conf.task_eager_propagates = False
    env.embedder.fail_with = LLMRateLimited("slow down")
    run_id = env.request()

    tasks.index_repository.apply(args=(str(env.repo_id), str(run_id)))

    assert [r["countdown"] for r in recorder.requests] == [tasks.retry_delay(0)]
    index = env.index()
    assert index.status == "queued" and "Retrying automatically" in (index.error or "")


@pytest.mark.usefixtures("eager")
def test_the_full_retry_chain_recovers_once_the_provider_does(env: IndexEnv) -> None:
    celery_app.conf.task_eager_propagates = False
    # One whole task attempt's worth of embedding calls fail (the service itself tries 3 times).
    env.embedder.fail_with = LLMRateLimited("slow down")
    env.embedder.fail_first = 3
    run_id = env.request()
    result = tasks.index_repository.apply(args=(str(env.repo_id), str(run_id)))

    assert result.result == "ready"  # retried automatically and finished
    assert env.embedder.calls > 3 and env.index().status == "ready"


@pytest.mark.usefixtures("eager")
def test_retries_run_out_and_the_failure_becomes_visible(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMRateLimited("slow down")
    run_id = env.request()
    celery_app.conf.task_eager_propagates = False
    result = tasks.index_repository.apply(
        args=(str(env.repo_id), str(run_id)), retries=tasks.INDEX_MAX_RETRIES
    )
    assert result.result == "failed"  # no Retry: this was the last allowed attempt
    index = env.index()
    assert index.status == "failed" and "Click Re-index" in (index.error or "")


@pytest.mark.usefixtures("eager")
def test_permanent_errors_are_not_retried(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMAuthError("bad key")
    run_id = env.request()
    celery_app.conf.task_eager_propagates = False
    result = tasks.index_repository.apply(args=(str(env.repo_id), str(run_id)))
    assert result.result == "failed" and not isinstance(result.result, Retry)


@pytest.mark.usefixtures("eager")
def test_a_run_held_by_a_possibly_dead_worker_is_retried_after_the_heartbeat_goes_stale(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.indexing.pipeline import claim_index

    run_id = env.request()
    with env.factory() as db:
        assert claim_index(db, env.repo_id, run_id)  # "another worker" is running it

    recorder = RetryRecorder()
    monkeypatch.setattr(tasks.index_repository, "retry", recorder)
    celery_app.conf.task_eager_propagates = False
    tasks.index_repository.apply(args=(str(env.repo_id), str(run_id)))
    # Not dropped: it asks to look again once that worker's heartbeat would have gone stale.
    assert [r["countdown"] for r in recorder.requests] == [int(STALE_RUNNING.total_seconds()) + 60]

    monkeypatch.undo()
    env.age_heartbeat(minutes=30)  # the worker really did die
    again = tasks.index_repository.apply(args=(str(env.repo_id), str(run_id)))
    assert again.result == "ready"


# ---------- syncing through Celery ----------


@pytest.mark.usefixtures("eager")
def test_sync_runs_through_the_task(env: IndexEnv) -> None:
    with env.factory() as db:
        pk = db.scalars(select(GithubInstallation.id)).one()
    assert tasks.sync_installation.apply(args=(str(pk), False)).result is True


# ---------- when the queue is down ----------


class DownQueue:
    name = "down"

    def apply_async(self, *a: Any, **k: Any) -> None:
        raise OperationalError("Connection refused")


def test_an_unreachable_queue_is_reported_not_hung_or_swallowed(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "index_repository", DownQueue())
    with pytest.raises(JobQueueUnavailable, match="Redis"):
        jobs_for(env).index_repository(env.repo_id, uuid.uuid4())


def test_starting_an_index_with_the_queue_down_gives_503_and_a_visible_failure(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "index_repository", DownQueue())
    res = env.client.post(
        f"{API}/orgs/{env.world.org_id}/repos/{env.repo_id}/index", headers=env.world.owner.headers
    )
    assert res.status_code == 503 and "Redis" in res.json()["detail"]
    state = env.index()
    assert state.status == "failed" and "Redis" in (state.error or "")  # and not stuck "queued"

    monkeypatch.undo()  # queue is back: the user can simply try again
    set_resources(JobResources(env.factory, env.github, lambda: env.llm, env.settings))
    celery_app.conf.task_always_eager = True
    try:
        again = env.client.post(
            f"{API}/orgs/{env.world.org_id}/repos/{env.repo_id}/index",
            headers=env.world.owner.headers,
        )
        assert again.status_code == 202
    finally:
        celery_app.conf.task_always_eager = False


def test_a_manual_sync_with_the_queue_down_is_503_and_not_left_running(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "sync_installation", DownQueue())
    installs = env.client.get(
        f"{API}/orgs/{env.world.org_id}/github", headers=env.world.owner.headers
    ).json()["installations"]
    res = env.client.post(
        f"{API}/orgs/{env.world.org_id}/github/installations/{installs[0]['id']}/sync",
        headers=env.world.owner.headers,
    )
    assert res.status_code == 503
    after = env.client.get(
        f"{API}/orgs/{env.world.org_id}/github", headers=env.world.owner.headers
    ).json()["installations"][0]
    assert after["sync_status"] == "failed" and "Redis" in after["sync_error"]


def test_connecting_github_with_the_queue_down_still_connects(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings.model_copy(
        update={"job_backend": "celery"}
    )
    monkeypatch.setattr(tasks, "sync_installation", DownQueue())
    res = connect(client, fake_github, world.owner.headers, world.org_id)
    assert res.status_code == 200  # the installation is saved...
    body = res.json()
    assert body["sync_status"] == "failed" and "Redis" in body["sync_error"]  # ...and says why


def test_webhooks_still_succeed_when_the_queue_is_down(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.github_helpers import post_hook

    connect(client, fake_github, world.owner.headers, world.org_id)
    app.dependency_overrides[get_settings] = lambda: gh_settings.model_copy(
        update={"job_backend": "celery"}
    )
    monkeypatch.setattr(tasks, "sync_installation", DownQueue())
    res = post_hook(
        client, "installation_repositories", {"action": "added", "installation": {"id": 777}},
        delivery="q-1",
    )  # fmt: skip
    assert res.status_code == 200  # GitHub must not be told to redeliver forever


# ---------- inline backend ----------


def test_inline_backend_defers_the_work_to_the_background_task_queue(env: IndexEnv) -> None:
    background = BackgroundTasks()
    jobs = Jobs(
        backend="inline",
        background=background,
        factory=env.factory,
        github=env.github,
        get_llm=lambda: env.llm,
        settings=env.settings,
    )
    run_id = env.request()
    jobs.index_repository(env.repo_id, run_id)
    assert len(background.tasks) == 1 and env.chunks() == []  # queued, not yet run
    import asyncio

    asyncio.run(background())
    assert env.index().status == "ready"

