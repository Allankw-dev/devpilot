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
from app.services.llm.errors import LLMAuthError, LLMRateLimited
from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub
from tests.review_helpers import ReviewEnv, finding, make_review_env, review_json

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
) -> ReviewEnv:
    return make_review_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def pr_url(e: ReviewEnv, number: int = 1, suffix: str = "review") -> str:
    return f"{API}/orgs/{e.world.org_id}/pull-requests/{e.prs[number]}/{suffix}"


def start(e: ReviewEnv, who: Person | None = None, number: int = 1, **body: Any) -> Response:
    return e.client.post(pr_url(e, number), json=body or None, headers=(who or e.world.owner).headers)


def add_member(e: ReviewEnv, person: PersonFactory, role: str) -> Person:
    who = person(f"{role}@example.com")
    res = e.client.post(
        f"{API}/orgs/{e.world.org_id}/members",
        json={"email": who.email, "role": role},
        headers=e.world.owner.headers,
    )
    assert res.status_code in (200, 201), res.text
    return who


def listing(e: ReviewEnv, who: Person | None = None, **params: str) -> list[dict[str, Any]]:
    res = e.client.get(
        f"{API}/orgs/{e.world.org_id}/pull-requests", params=params, headers=(who or e.world.owner).headers
    )
    assert res.status_code == 200, res.text
    out: list[dict[str, Any]] = res.json()
    return out


# ---------- listing ----------


def test_open_pull_requests_are_listed_with_no_review_yet(env: ReviewEnv) -> None:
    rows = listing(env)
    assert sorted(r["number"] for r in rows) == [1, 2]  # the merged one is not open
    first = next(r for r in rows if r["number"] == 1)
    assert first["repository"] == "octo-org/api" and first["review"] is None
    assert first["title"] == "PR 1" and first["draft"] is False and first["merged"] is False
    assert next(r for r in rows if r["number"] == 2)["draft"] is True


def test_all_states_can_be_listed_and_limits_are_validated(env: ReviewEnv) -> None:
    assert sorted(r["number"] for r in listing(env, state="all")) == [1, 2, 3]
    assert len(listing(env, state="all", limit="2")) == 2
    for bad in ({"limit": "0"}, {"limit": "101"}, {"state": "weird"}):
        res = env.client.get(
            f"{API}/orgs/{env.world.org_id}/pull-requests", params=bad, headers=env.world.owner.headers
        )
        assert res.status_code == 422


def test_the_list_summarises_each_latest_review(env: ReviewEnv) -> None:
    env.script(
        review_json(
            [finding(severity="critical"), finding(start=12, severity="low", category="bug"), finding(start=13, severity="info", category="tests")],
            risk="high",
        )
    )
    assert start(env).status_code == 202
    brief = next(r for r in listing(env) if r["number"] == 1)["review"]
    assert (brief["status"], brief["risk"], brief["open_findings"], brief["serious_findings"]) == (
        "ready", "high", 3, 1,
    )  # fmt: skip
    assert brief["stale"] is False and brief["finished_at"] is not None


def test_listing_is_scoped_to_the_organization(env: ReviewEnv, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    res = env.client.get(f"{API}/orgs/{own['id']}/pull-requests", headers=mallory.headers)
    assert res.status_code == 200 and res.json() == []
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/pull-requests", headers=mallory.headers).status_code == 404


# ---------- starting and reading a review ----------


def test_starting_a_review_returns_202_and_the_job_runs(env: ReviewEnv) -> None:
    env.script(review_json([finding(start=11, end=12)], summary="Login change.", risk="high"))
    res = start(env)
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "queued" and res.json()["findings"] == []

    done = env.client.get(pr_url(env), headers=env.world.owner.headers).json()
    assert done["status"] == "ready" and done["summary"] == "Login change." and done["risk"] == "high"
    assert done["files_total"] == 3 and done["files_reviewed"] == 2 and done["head_sha"] == "c" * 40
    assert done["model"] == "fake-model-v1" and done["stale"] is False
    (f,) = done["findings"]
    assert (f["file"], f["start_line"], f["end_line"], f["severity"], f["origin"], f["status"]) == (
        "app/auth.py", 11, 12, "high", "ai", "open",
    )  # fmt: skip
    assert f["title"] and f["explanation"] and f["suggestion"] and f["confidence"] == "high"


def test_findings_come_back_most_severe_first(env: ReviewEnv) -> None:
    env.script(
        review_json(
            [
                finding(start=13, severity="low", category="bug", title="minor"),
                finding(start=11, severity="critical", title="worst"),
                finding(start=12, severity="medium", category="logic", title="middle"),
            ]
        )
    )
    start(env)
    titles = [f["title"] for f in env.client.get(pr_url(env), headers=env.world.owner.headers).json()["findings"]]
    assert titles == ["worst", "middle", "minor"]


def test_no_review_yet_reads_as_null(env: ReviewEnv) -> None:
    res = env.client.get(pr_url(env), headers=env.world.owner.headers)
    assert res.status_code == 200 and res.json() is None


def test_an_unchanged_pull_request_reuses_the_last_review_without_spending_tokens(env: ReviewEnv) -> None:
    env.script(review_json([finding()]))
    first = start(env)
    assert first.status_code == 202
    calls = len(env.generation.requests)

    again = start(env)
    assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
    assert len(env.generation.requests) == calls  # nothing was sent to the model


def test_force_reviews_again_and_a_changed_pull_request_goes_stale(env: ReviewEnv) -> None:
    env.script(review_json([finding()]), review_json([]))
    first = start(env).json()
    env.touch_pr(1)  # new commits arrive and a sync records them
    stale = env.client.get(pr_url(env), headers=env.world.owner.headers).json()
    assert stale["stale"] is True and stale["id"] == first["id"]
    assert next(r for r in listing(env) if r["number"] == 1)["review"]["stale"] is True

    second = start(env)  # stale, so no need to force
    assert second.status_code == 202 and second.json()["id"] != first["id"]
    env.script(review_json([]))
    forced = start(env, force=True)
    assert forced.status_code == 202 and forced.json()["id"] not in (first["id"], second.json()["id"])


def test_a_review_already_in_progress_is_a_409(env: ReviewEnv) -> None:
    env.request()  # queued, not yet run
    res = start(env)
    assert res.status_code == 409 and "already in progress" in res.json()["detail"]
    assert env.generation.requests == []


def test_a_failed_review_shows_why_and_can_be_retried(env: ReviewEnv) -> None:
    env.generation.script = [LLMAuthError("bad key")]
    start(env)
    got = env.client.get(pr_url(env), headers=env.world.owner.headers).json()
    assert got["status"] == "failed" and "rejected the API key" in got["error"]
    env.script(review_json())
    assert start(env).status_code == 202
    assert env.client.get(pr_url(env), headers=env.world.owner.headers).json()["status"] == "ready"


# ---------- who may do what ----------


def test_members_can_review_viewers_can_only_read(env: ReviewEnv, person: PersonFactory) -> None:
    env.script(review_json())
    viewer = add_member(env, person, "viewer")
    assert start(env, viewer).status_code == 403
    assert env.generation.requests == []
    assert env.client.get(pr_url(env), headers=viewer.headers).status_code == 200
    assert len(listing(env, viewer)) == 2

    member = add_member(env, person, "member")
    assert start(env, member).status_code == 202


def test_outsiders_and_other_organizations_get_404(env: ReviewEnv, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    assert start(env, mallory).status_code == 404
    assert env.client.get(pr_url(env), headers=mallory.headers).status_code == 404
    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    cross = f"{API}/orgs/{own['id']}/pull-requests/{env.prs[1]}/review"
    assert env.client.post(cross, headers=mallory.headers).status_code == 404
    assert env.client.get(cross, headers=mallory.headers).status_code == 404
    assert env.generation.requests == []


def test_unknown_pull_request_and_missing_login(env: ReviewEnv) -> None:
    missing = f"{API}/orgs/{env.world.org_id}/pull-requests/{uuid.uuid4()}/review"
    assert env.client.post(missing, headers=env.world.owner.headers).status_code == 404
    assert env.client.post(pr_url(env)).status_code == 401
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/pull-requests").status_code == 401


# ---------- guard rails ----------


def test_reviews_are_rate_limited_per_person(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
    person: PersonFactory,
) -> None:
    env = make_review_env(
        client, world, fake_github, gh_client, session_factory, gh_settings,
        review_rate_limit_per_minute=2,
    )  # fmt: skip
    env.set_pr(2, files=[])
    env.script(review_json(), review_json(), review_json())
    assert start(env, number=1).status_code == 202
    assert start(env, number=2).status_code == 202
    third = start(env, number=1, force=True)
    assert third.status_code == 429 and "reviews" in third.json()["detail"]
    other = add_member(env, person, "member")
    assert start(env, other, number=1, force=True).status_code == 202  # someone else is unaffected


def test_unconfigured_ai_tells_admins_what_is_missing_and_members_to_ask(
    env: ReviewEnv, gh_settings: Settings, person: PersonFactory
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings  # no GEMINI settings
    admin = start(env)
    assert admin.status_code == 503 and "GEMINI_API_KEY" in admin.json()["detail"]
    member = add_member(env, person, "member")
    res = start(env, member)
    assert res.status_code == 503 and "GEMINI" not in res.json()["detail"]
    assert env.client.get(pr_url(env), headers=env.world.owner.headers).json() is None  # nothing reserved


def test_the_job_queue_being_down_is_reported_and_not_left_queued(
    env: ReviewEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kombu.exceptions import OperationalError

    class Down:
        name = "down"

        def apply_async(self, *a: Any, **k: Any) -> None:
            raise OperationalError("Connection refused")

    app.dependency_overrides[get_settings] = lambda: env.settings.model_copy(update={"job_backend": "celery"})
    monkeypatch.setattr(tasks, "review_pull_request", Down())
    res = start(env)
    assert res.status_code == 503 and "Redis" in res.json()["detail"]
    got = env.client.get(pr_url(env), headers=env.world.owner.headers).json()
    assert got["status"] == "failed" and "Redis" in got["error"]  # visible, not a stuck spinner


def test_reviews_run_through_celery_when_a_worker_is_used(env: ReviewEnv) -> None:
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    try:
        set_resources(JobResources(env.factory, env.github, lambda: env.llm, env.settings))
        app.dependency_overrides[get_settings] = lambda: env.settings.model_copy(update={"job_backend": "celery"})
        env.script(review_json([finding()]))
        assert start(env).status_code == 202
        got = env.client.get(pr_url(env), headers=env.world.owner.headers).json()
        assert got["status"] == "ready" and len(got["findings"]) == 1
    finally:
        celery_app.conf.task_always_eager = False
        set_resources(None)


# ---------- dismissing findings ----------


def finding_id(e: ReviewEnv) -> str:
    return str(e.client.get(pr_url(e), headers=e.world.owner.headers).json()["findings"][0]["id"])


def patch(e: ReviewEnv, fid: str, who: Person | None = None, **body: Any) -> Response:
    return e.client.patch(
        f"{API}/orgs/{e.world.org_id}/review-findings/{fid}", json=body, headers=(who or e.world.owner).headers
    )


def test_a_finding_can_be_dismissed_and_reopened_and_counts_follow(env: ReviewEnv) -> None:
    env.script(review_json([finding(severity="critical")]))
    start(env)
    fid = finding_id(env)
    assert next(r for r in listing(env) if r["number"] == 1)["review"]["serious_findings"] == 1

    res = patch(env, fid, status="dismissed")
    assert res.status_code == 200 and res.json()["status"] == "dismissed"
    brief = next(r for r in listing(env) if r["number"] == 1)["review"]
    assert (brief["open_findings"], brief["serious_findings"]) == (0, 0)

    assert patch(env, fid, status="open").json()["status"] == "open"
    assert next(r for r in listing(env) if r["number"] == 1)["review"]["open_findings"] == 1


def test_finding_updates_are_restricted_and_validated(env: ReviewEnv, person: PersonFactory) -> None:
    env.script(review_json([finding()]))
    start(env)
    fid = finding_id(env)
    viewer = add_member(env, person, "viewer")
    assert patch(env, fid, viewer, status="dismissed").status_code == 403
    assert patch(env, fid, status="deleted").status_code == 422
    assert patch(env, str(uuid.uuid4()), status="dismissed").status_code == 404
    mallory = person("mallory@example.com")
    assert patch(env, fid, mallory, status="dismissed").status_code == 404

    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    cross = env.client.patch(
        f"{API}/orgs/{own['id']}/review-findings/{fid}", json={"status": "dismissed"}, headers=mallory.headers
    )
    assert cross.status_code == 404  # their own org, but our finding
    assert env.client.get(pr_url(env), headers=env.world.owner.headers).json()["findings"][0]["status"] == "open"


# ---------- retries (Celery asks for a delayed retry on a rate limit) ----------


def test_the_review_task_asks_for_a_delayed_retry_on_a_rate_limit(
    env: ReviewEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    from celery.exceptions import Retry

    asked: list[Any] = []

    def fake_retry(**kwargs: Any) -> Retry:
        asked.append(kwargs.get("countdown"))
        return Retry("requested", when=kwargs.get("countdown"))

    monkeypatch.setattr(tasks.review_pull_request, "retry", fake_retry)
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    set_resources(JobResources(env.factory, env.github, lambda: env.llm, env.settings))
    try:
        env.generation.script = [LLMRateLimited("slow")] * 3
        review = env.request().review
        tasks.review_pull_request.apply(args=(str(review.id), str(review.run_id)))
    finally:
        celery_app.conf.task_always_eager = False
        set_resources(None)
    assert asked == [tasks.retry_delay(0)]
    assert env.review().status == "queued"  # waiting for the retry, not failed
