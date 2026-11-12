import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm, get_llm_getter
from app.core.config import Settings, get_settings
from app.main import app
from app.services.github.client import GitHubClient
from app.services.indexing.pipeline import request_index
from app.services.llm.errors import LLMAuthError
from tests.conftest import ON_POSTGRES, Person, World
from tests.github_helpers import FakeGitHub
from tests.index_helpers import REPO, IndexEnv, make_env

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
) -> Iterator[IndexEnv]:
    configured = gh_settings.model_copy(
        update={"gemini_api_key": SecretStr("k"), "gemini_embedding_model": "fake-embed-v1"}
    )
    e = make_env(client, world, fake_github, gh_client, session_factory, configured)
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_llm] = lambda: e.llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: e.llm)
    yield e


def url(e: IndexEnv, suffix: str = "index") -> str:
    return f"{API}/orgs/{e.world.org_id}/repos/{e.repo_id}/{suffix}"


def add_member(e: IndexEnv, person: PersonFactory, role: str) -> Person:
    who = person(f"{role}@example.com")
    res = e.client.post(
        f"{API}/orgs/{e.world.org_id}/members",
        json={"email": who.email, "role": role},
        headers=e.world.owner.headers,
    )
    assert res.status_code in (200, 201), res.text
    return who


def repo_row(e: IndexEnv) -> dict[str, object]:
    res = e.client.get(f"{API}/orgs/{e.world.org_id}/repos", headers=e.world.owner.headers)
    row: dict[str, object] = next(r for r in res.json() if r["full_name"] == REPO)
    return row


# ---------- starting and watching an index ----------


def test_not_indexed_repos_say_so(env: IndexEnv) -> None:
    row = repo_row(env)
    assert row["index"] == {
        "status": "none", "files": 0, "chunks": 0, "skipped_files": 0,
        "skipped_chunks": 0, "indexed_at": None, "queued_at": None, "error": None,
    }  # fmt: skip
    res = env.client.get(url(env), headers=env.world.owner.headers)
    assert res.status_code == 200 and res.json()["status"] == "none"


def test_starting_an_index_returns_202_then_the_job_completes(env: IndexEnv) -> None:
    res = env.client.post(url(env), headers=env.world.owner.headers)
    assert res.status_code == 202, res.text
    assert res.json()["status"] == "queued"

    done = env.client.get(url(env), headers=env.world.owner.headers).json()  # job ran after reply
    assert done["status"] == "ready" and done["chunks"] > 0 and done["files"] == 3
    assert done["indexed_at"] is not None and done["error"] is None
    assert repo_row(env)["index"] == done  # the repo list carries the same summary


def test_a_failed_index_shows_why(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMAuthError("bad key")
    env.client.post(url(env), headers=env.world.owner.headers)
    state = env.client.get(url(env), headers=env.world.owner.headers).json()
    assert state["status"] == "failed" and "rejected the API key" in state["error"]
    assert state["indexed_at"] is None


def test_reindexing_after_a_failure_works(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMAuthError("bad key")
    env.client.post(url(env), headers=env.world.owner.headers)
    env.embedder.fail_with = None
    assert env.client.post(url(env), headers=env.world.owner.headers).status_code == 202
    assert env.client.get(url(env), headers=env.world.owner.headers).json()["status"] == "ready"


def test_a_repo_that_is_already_being_indexed_is_refused(env: IndexEnv) -> None:
    with env.factory() as db:
        assert request_index(db, env.repo_id, None) is not None  # queued, not yet run
    res = env.client.post(url(env), headers=env.world.owner.headers)
    assert res.status_code == 409 and "already being indexed" in res.json()["detail"]


# ---------- who may do what ----------


def test_members_can_index_viewers_cannot(
    env: IndexEnv, person: PersonFactory
) -> None:
    viewer = add_member(env, person, "viewer")
    assert env.client.post(url(env), headers=viewer.headers).status_code == 403
    assert env.client.get(url(env), headers=viewer.headers).status_code == 200  # may look

    member = add_member(env, person, "member")
    assert env.client.post(url(env), headers=member.headers).status_code == 202


def test_outsiders_and_other_organizations_get_404(env: IndexEnv, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    assert env.client.get(url(env), headers=mallory.headers).status_code == 404
    assert env.client.post(url(env), headers=mallory.headers).status_code == 404

    # Mallory's own organization must not reach into someone else's repository either.
    own = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    cross = f"{API}/orgs/{own['id']}/repos/{env.repo_id}/index"
    assert env.client.get(cross, headers=mallory.headers).status_code == 404
    assert env.client.post(cross, headers=mallory.headers).status_code == 404
    assert env.client.get(url(env), headers=env.world.owner.headers).json()["status"] == "none"


def test_unknown_repository_is_404(env: IndexEnv) -> None:
    missing = f"{API}/orgs/{env.world.org_id}/repos/{uuid.uuid4()}/index"
    assert env.client.post(missing, headers=env.world.owner.headers).status_code == 404


def test_requires_authentication(env: IndexEnv) -> None:
    assert env.client.get(url(env)).status_code == 401
    assert env.client.post(url(env)).status_code == 401


# ---------- server not set up ----------


def test_unconfigured_server_tells_admins_which_settings_and_members_only_to_ask(
    env: IndexEnv, gh_settings: Settings, person: PersonFactory
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings  # no embedding settings
    admin = env.client.post(url(env), headers=env.world.owner.headers)
    assert admin.status_code == 503
    assert "GEMINI_API_KEY" in admin.json()["detail"]
    assert "GEMINI_EMBEDDING_MODEL" in admin.json()["detail"]

    member = add_member(env, person, "member")
    res = env.client.post(url(env), headers=member.headers)
    assert res.status_code == 503 and "GEMINI" not in res.json()["detail"]


def test_nothing_is_reserved_when_the_server_is_not_set_up(
    env: IndexEnv, gh_settings: Settings
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings
    env.client.post(url(env), headers=env.world.owner.headers)
    assert env.client.get(url(env), headers=env.world.owner.headers).json()["status"] == "none"


def test_wrong_embedding_size_setting_is_reported(env: IndexEnv, gh_settings: Settings) -> None:
    bad = gh_settings.model_copy(
        update={
            "gemini_api_key": SecretStr("k"),
            "gemini_embedding_model": "m",
            "embedding_dimensions": 1536,
        }
    )
    app.dependency_overrides[get_settings] = lambda: bad
    res = env.client.post(url(env), headers=env.world.owner.headers)
    assert res.status_code == 503 and "768" in res.json()["detail"]


# ---------- search: validation and access (the ranking itself is tested on Postgres) ----------


def search(e: IndexEnv, who: Person | None = None, **body: object) -> Response:
    return e.client.post(
        f"{API}/orgs/{e.world.org_id}/search",
        json=body,
        headers=(who or e.world.owner).headers,
    )


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 501},
        {"query": "ok", "limit": 0},
        {"query": "ok", "limit": 21},
        {"query": "ok", "repository_id": "not-a-uuid"},
        {},
    ],
)
def test_search_rejects_bad_requests(env: IndexEnv, body: dict[str, object]) -> None:
    assert search(env, None, **body).status_code == 422


def test_viewers_cannot_search_and_outsiders_get_404(env: IndexEnv, person: PersonFactory) -> None:
    viewer = add_member(env, person, "viewer")
    assert search(env, viewer, query="login").status_code == 403
    mallory = person("mallory@example.com")
    assert search(env, mallory, query="login").status_code == 404


@pytest.mark.skipif(ON_POSTGRES, reason="only meaningful without pgvector")
def test_search_explains_it_needs_postgres(env: IndexEnv) -> None:
    res = search(env, query="login")
    assert res.status_code == 501
