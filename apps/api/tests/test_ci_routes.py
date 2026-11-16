import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.jobs import tasks
from app.jobs.celery_app import celery_app
from app.jobs.context import JobResources, set_resources
from app.main import app
from app.services.github.client import GitHubClient
from app.services.llm.errors import LLMRateLimited
from tests.ci_helpers import (
    FAILED_RUN,
    RUNNING_RUN,
    SUCCEEDED_RUN,
    TIMED_OUT_RUN,
    CiEnv,
    analysis_json,
    make_ci_env,
)
from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub, make_job

API = "/api/v1"
PersonFactory = Callable[[str], Person]


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> CiEnv:
    return make_ci_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def run_url(e: CiEnv, run: int = FAILED_RUN, suffix: str = "analysis") -> str:
    return f"{API}/orgs/{e.world.org_id}/ci-runs/{e.runs[run]}/{suffix}"


def start(e: CiEnv, who: Person | None = None, run: int = FAILED_RUN, **body: Any) -> Response:
    return e.client.post(run_url(e, run), json=body or None, headers=(who or e.world.owner).headers)


def add_member(e: CiEnv, person: PersonFactory, role: str) -> Person:
    who = person(f"{role}@example.com")
    res = e.client.post(
        f"{API}/orgs/{e.world.org_id}/members",
        json={"email": who.email, "role": role},
        headers=e.world.owner.headers,
    )
    assert res.status_code in (200, 201), res.text
    return who


def listing(e: CiEnv, who: Person | None = None, **params: str) -> list[dict[str, Any]]:
    res = e.client.get(
        f"{API}/orgs/{e.world.org_id}/ci-runs", params=params, headers=(who or e.world.owner).headers
    )
    assert res.status_code == 200, res.text
    out: list[dict[str, Any]] = res.json()
    return out


def read(e: CiEnv, who: Person | None = None, run: int = FAILED_RUN) -> Any:
    return e.client.get(run_url(e, run), headers=(who or e.world.owner).headers).json()


# ---------- listing ----------


def test_failed_runs_are_listed_with_no_analysis_yet(env: CiEnv) -> None:
    rows = listing(env)
    assert sorted(r["name"] for r in rows) == ["CI", "CI"]
    assert {r["conclusion"] for r in rows} == {"failure", "timed_out"}
    assert all(r["analyzable"] and r["analysis"] is None for r in rows)
    first = next(r for r in rows if r["conclusion"] == "failure")
    assert first["repository"] == "octo-org/web" and first["branch"] == "main"
    assert first["event"] == "push" and first["html_url"].startswith("https://github.com/")


def test_all_runs_can_be_listed_and_only_failed_finished_ones_are_analyzable(env: CiEnv) -> None:
    rows = listing(env, state="all")
    by_conclusion = {(r["status"], r["conclusion"]): r["analyzable"] for r in rows}
    assert by_conclusion[("completed", "failure")] is True
    assert by_conclusion[("completed", "timed_out")] is True
    assert by_conclusion[("completed", "success")] is False
    assert by_conclusion[("in_progress", None)] is False
    assert len(listing(env, state="all", limit="2")) == 2


def test_limits_and_state_are_validated(env: CiEnv) -> None:
    for bad in ({"limit": "0"}, {"limit": "101"}, {"state": "weird"}):
        res = env.client.get(
            f"{API}/orgs/{env.world.org_id}/ci-runs", params=bad, headers=env.world.owner.headers
        )
        assert res.status_code == 422


def test_the_list_summarises_each_latest_analysis(env: CiEnv) -> None:
    env.script(analysis_json())
    assert start(env).status_code == 202
    row = next(r for r in listing(env) if r["id"] == str(env.runs[FAILED_RUN]))
    brief = row["analysis"]
    assert brief["status"] == "ready" and brief["category"] == "test_failure"
    assert brief["confidence"] == "high" and brief["stale"] is False and brief["error"] is None
    other = next(r for r in listing(env) if r["id"] == str(env.runs[TIMED_OUT_RUN]))
    assert other["analysis"] is None


def test_listing_is_scoped_to_the_organization(env: CiEnv, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    res = env.client.get(f"{API}/orgs/{own['id']}/ci-runs", headers=mallory.headers)
    assert res.status_code == 200 and res.json() == []
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/ci-runs", headers=mallory.headers).status_code == 404


# ---------- starting and reading an analysis ----------


def test_starting_an_analysis_returns_202_and_the_job_runs(env: CiEnv) -> None:
    env.script(analysis_json())
    res = start(env)
    assert res.status_code == 202
    assert res.json()["status"] == "queued"  # what was reserved; the job ran right after

    got = read(env)
    assert got["status"] == "ready" and got["category"] == "test_failure"
    assert got["summary"] and got["likely_cause"] and got["suggested_fix"]
    assert got["failed_steps"] == [
        {"job": "test", "step": "Run tests"},
        {"job": "lint", "step": "Run ruff"},
    ]
    assert got["evidence"] == [{"job": "test", "quote": "E KeyError: 'session'"}]
    assert (got["jobs_total"], got["jobs_analyzed"]) == (2, 2) and got["stale"] is False
    assert got["run_id"] == str(env.runs[FAILED_RUN]) and got["head_sha"] == "a" * 40


def test_no_analysis_yet_reads_as_null(env: CiEnv) -> None:
    assert read(env) is None


def test_an_unchanged_run_reuses_the_last_analysis_without_spending_tokens(env: CiEnv) -> None:
    env.script(analysis_json())
    start(env)
    again = start(env)
    assert again.status_code == 200 and again.json()["status"] == "ready"
    assert len(env.generation.requests) == 1


def test_force_analyzes_again_and_a_re_run_makes_the_analysis_stale(env: CiEnv) -> None:
    env.script(analysis_json(), analysis_json())
    start(env)
    assert start(env, force=True).status_code == 202
    assert len(env.generation.requests) == 2

    env.touch_run()
    assert read(env)["stale"] is True
    row = next(r for r in listing(env) if r["id"] == str(env.runs[FAILED_RUN]))
    assert row["analysis"]["stale"] is True


def test_an_analysis_already_in_progress_is_a_409(env: CiEnv) -> None:
    assert env.request().outcome == "created"  # reserved, not yet run
    res = start(env)
    assert res.status_code == 409 and "already in progress" in res.json()["detail"]


def test_a_failed_analysis_shows_why_and_can_be_retried(env: CiEnv) -> None:
    env.fake.data["octo-org/web"]["job_logs"].clear()
    assert start(env).status_code == 202
    got = read(env)
    assert got["status"] == "failed" and "No log could be read" in got["error"]

    env.set_log(201, "ERROR: build broke\n")
    env.set_log(202, "ERROR: lint broke\n")
    env.script(analysis_json(evidence=[]))
    assert start(env).status_code == 202
    assert read(env)["status"] == "ready"


def test_only_finished_failed_runs_can_be_analyzed(env: CiEnv) -> None:
    for run in (SUCCEEDED_RUN, RUNNING_RUN):
        res = start(env, run=run)
        assert res.status_code == 422 and "failed" in res.json()["detail"]
    assert env.generation.requests == []
    assert read(env, run=SUCCEEDED_RUN) is None


def test_a_timed_out_run_can_be_started(env: CiEnv) -> None:
    env.set_jobs(TIMED_OUT_RUN, make_job(401, "slow", conclusion="timed_out"))
    env.set_log(401, "ERROR: The operation was canceled.\n")
    env.script(analysis_json(category="flaky_or_timeout", evidence=[]))
    assert start(env, run=TIMED_OUT_RUN).status_code == 202
    assert read(env, run=TIMED_OUT_RUN)["category"] == "flaky_or_timeout"


# ---------- who may do what ----------


def test_members_can_analyze_viewers_can_only_read(env: CiEnv, person: PersonFactory) -> None:
    env.script(analysis_json())
    viewer = add_member(env, person, "viewer")
    assert start(env, viewer).status_code == 403
    assert env.generation.requests == []
    assert env.client.get(run_url(env), headers=viewer.headers).status_code == 200
    assert len(listing(env, viewer)) == 2

    member = add_member(env, person, "member")
    assert start(env, member).status_code == 202


def test_outsiders_and_other_organizations_get_404(env: CiEnv, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    assert start(env, mallory).status_code == 404
    assert env.client.get(run_url(env), headers=mallory.headers).status_code == 404
    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    cross = f"{API}/orgs/{own['id']}/ci-runs/{env.runs[FAILED_RUN]}/analysis"
    assert env.client.post(cross, headers=mallory.headers).status_code == 404  # their org, our run
    assert env.client.get(cross, headers=mallory.headers).status_code == 404
    assert env.generation.requests == []


def test_unknown_run_and_missing_login(env: CiEnv) -> None:
    missing = f"{API}/orgs/{env.world.org_id}/ci-runs/{uuid.uuid4()}/analysis"
    assert env.client.post(missing, headers=env.world.owner.headers).status_code == 404
    assert env.client.post(run_url(env)).status_code == 401
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/ci-runs").status_code == 401


# ---------- guard rails ----------


def test_analyses_are_rate_limited_per_person(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
    person: PersonFactory,
) -> None:
    env = make_ci_env(
        client, world, fake_github, gh_client, session_factory, gh_settings,
        ci_rate_limit_per_minute=2,
    )  # fmt: skip
    env.set_jobs(TIMED_OUT_RUN, make_job(401, "slow", conclusion="timed_out"))
    env.set_log(401, "ERROR: timeout\n")
    env.script(analysis_json(evidence=[]), analysis_json(evidence=[]), analysis_json(evidence=[]))
    assert start(env, run=FAILED_RUN).status_code == 202
    assert start(env, run=TIMED_OUT_RUN).status_code == 202
    third = start(env, run=FAILED_RUN, force=True)
    assert third.status_code == 429 and "analyses" in third.json()["detail"]
    other = add_member(env, person, "member")
    assert start(env, other, run=FAILED_RUN, force=True).status_code == 202  # someone else is fine


def test_unconfigured_ai_tells_admins_what_is_missing_and_members_to_ask(
    env: CiEnv, gh_settings: Settings, person: PersonFactory
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings  # no GEMINI settings
    admin = start(env)
    assert admin.status_code == 503 and "GEMINI_API_KEY" in admin.json()["detail"]
    member = add_member(env, person, "member")
    res = start(env, member)
    assert res.status_code == 503 and "GEMINI" not in res.json()["detail"]
    assert read(env) is None  # nothing was reserved


def test_the_job_queue_being_down_is_reported_and_not_left_queued(
    env: CiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kombu.exceptions import OperationalError

    class Down:
        name = "down"

        def apply_async(self, *a: Any, **k: Any) -> None:
            raise OperationalError("Connection refused")

    app.dependency_overrides[get_settings] = lambda: env.settings.model_copy(
        update={"job_backend": "celery"}
    )
    monkeypatch.setattr(tasks, "analyze_ci_run", Down())
    res = start(env)
    assert res.status_code == 503 and "Redis" in res.json()["detail"]
    got = read(env)
    assert got["status"] == "failed" and "Redis" in got["error"]  # visible, not a stuck spinner


# ---------- through Celery ----------


def test_analyses_run_through_celery_when_a_worker_is_used(env: CiEnv) -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        set_resources(JobResources(env.factory, env.github, lambda: env.llm, env.settings))
        app.dependency_overrides[get_settings] = lambda: env.settings.model_copy(
            update={"job_backend": "celery"}
        )
        env.script(analysis_json())
        assert start(env).status_code == 202
        assert read(env)["status"] == "ready"
    finally:
        celery_app.conf.task_always_eager = False
        set_resources(None)


def test_the_ci_task_asks_for_a_delayed_retry_on_a_rate_limit(
    env: CiEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from celery.exceptions import Retry

    asked: list[Any] = []

    def fake_retry(**kwargs: Any) -> Retry:
        asked.append(kwargs.get("countdown"))
        return Retry("requested", when=kwargs.get("countdown"))

    monkeypatch.setattr(tasks.analyze_ci_run, "retry", fake_retry)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    set_resources(JobResources(env.factory, env.github, lambda: env.llm, env.settings))
    try:
        env.generation.script = [LLMRateLimited("slow")] * 3
        analysis = env.request().analysis
        tasks.analyze_ci_run.apply(args=(str(analysis.id), str(analysis.run_id)))
    finally:
        celery_app.conf.task_always_eager = False
        set_resources(None)
    assert asked == [tasks.retry_delay(0)]
    assert env.analysis().status == "queued"  # waiting for the retry, not failed
