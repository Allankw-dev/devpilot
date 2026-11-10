from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm
from app.core.config import Settings, get_settings
from app.main import app
from app.services.llm import LLMService
from app.services.llm.errors import LLMAuthError, LLMNotConfigured, LLMRateLimited, LLMTimeout
from app.services.llm.usage import DbUsageRecorder
from tests.conftest import Person, World
from tests.llm_helpers import FakeProvider, reply

API = "/api/v1"
PersonFactory = Callable[[str], Person]

CONFIGURED = Settings(
    _env_file=None, gemini_api_key=SecretStr("k"), gemini_model="some-model"
)


@pytest.fixture
def configured(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: CONFIGURED


@pytest.fixture
def fake_llm(
    client: TestClient, session_factory: sessionmaker[Session]
) -> Iterator[FakeProvider]:
    provider = FakeProvider()
    service = LLMService(
        provider, recorder=DbUsageRecorder(session_factory), sleep=lambda _: None
    )
    app.dependency_overrides[get_llm] = lambda: service
    yield provider


def status_of(client: TestClient, w: World, who: Person | None = None) -> dict[str, object]:
    res = client.get(f"{API}/orgs/{w.org_id}/ai", headers=(who or w.owner).headers)
    assert res.status_code == 200, res.text
    body: dict[str, object] = res.json()
    return body


# ---------- status ----------


def test_not_configured_lists_what_is_missing_for_admins(client: TestClient, world: World) -> None:
    body = status_of(client, world)
    assert body["configured"] is False
    assert body["missing"] == ["GEMINI_API_KEY", "GEMINI_MODEL"]
    assert body["model"] is None
    assert body["usage"] == {
        "days": 30, "requests": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0
    }


def test_missing_setting_names_are_hidden_from_non_admins(
    client: TestClient, world: World, person: PersonFactory
) -> None:
    viewer = person("viewer@example.com")
    client.post(
        f"{API}/orgs/{world.org_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=world.owner.headers,
    )
    assert status_of(client, world, viewer)["missing"] == []


def test_configured_status_shows_provider_and_model_but_never_the_key(
    client: TestClient, world: World, configured: None
) -> None:
    body = status_of(client, world)
    assert body["configured"] is True and body["provider"] == "gemini"
    assert body["model"] == "some-model" and body["embeddings_configured"] is False
    assert "k" not in {str(v) for v in body.values() if isinstance(v, str)} - {"gemini"}


def test_non_members_get_404(client: TestClient, world: World, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    assert client.get(f"{API}/orgs/{world.org_id}/ai", headers=mallory.headers).status_code == 404
    res = client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=mallory.headers)
    assert res.status_code == 404


def test_requires_authentication(client: TestClient, world: World) -> None:
    assert client.get(f"{API}/orgs/{world.org_id}/ai").status_code == 401


# ---------- the connection test ----------


def test_connection_test_calls_the_model_and_usage_shows_up(
    client: TestClient, world: World, configured: None, fake_llm: FakeProvider
) -> None:
    fake_llm.script = [reply("OK", tokens=(8, 2))]
    res = client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=world.owner.headers)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["reply"] == "OK" and body["provider"] == "fake"
    assert (body["input_tokens"], body["output_tokens"]) == (8, 2)

    usage = status_of(client, world)["usage"]
    assert usage == {
        "days": 30, "requests": 1, "errors": 0, "input_tokens": 8, "output_tokens": 2
    }


def test_failed_calls_count_as_errors(
    client: TestClient, world: World, configured: None, fake_llm: FakeProvider
) -> None:
    fake_llm.script = [LLMAuthError("bad key")]
    client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=world.owner.headers)
    usage = status_of(client, world)["usage"]
    assert usage["requests"] == 1 and usage["errors"] == 1  # type: ignore[index]


def test_usage_is_per_organization(
    client: TestClient, world: World, configured: None, fake_llm: FakeProvider, person: PersonFactory
) -> None:
    fake_llm.script = [reply("OK")]
    client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=world.owner.headers)

    other = person("other@example.com")
    org2 = client.post(f"{API}/orgs", json={"name": "Other"}, headers=other.headers).json()
    res = client.get(f"{API}/orgs/{org2['id']}/ai", headers=other.headers).json()
    assert res["usage"]["requests"] == 0


@pytest.mark.parametrize(
    ("error", "code", "must_not_contain"),
    [
        (LLMAuthError("AIza-secret-key rejected"), 502, "AIza"),
        (LLMRateLimited("slow"), 429, ""),
        (LLMTimeout("slow"), 504, ""),
    ],
)
def test_provider_failures_map_to_clean_http_errors(
    client: TestClient,
    world: World,
    configured: None,
    fake_llm: FakeProvider,
    error: Exception,
    code: int,
    must_not_contain: str,
) -> None:
    fake_llm.script = [error] * 3
    res = client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=world.owner.headers)
    assert res.status_code == code
    if must_not_contain:
        assert must_not_contain not in res.text


def test_connection_test_when_not_configured_is_503_with_names_only(
    client: TestClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> LLMService:
        raise LLMNotConfigured(["GEMINI_API_KEY", "GEMINI_MODEL"])

    monkeypatch.setattr("app.api.deps.get_llm_service", broken)
    res = client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=world.owner.headers)
    assert res.status_code == 503 and "GEMINI_API_KEY" in res.json()["detail"]


def test_only_admins_can_run_the_connection_test(
    client: TestClient, world: World, configured: None, fake_llm: FakeProvider, person: PersonFactory
) -> None:
    member = person("member@example.com")
    client.post(
        f"{API}/orgs/{world.org_id}/members",
        json={"email": member.email, "role": "member"},
        headers=world.owner.headers,
    )
    fake_llm.script = [reply("OK")]
    res = client.post(f"{API}/orgs/{world.org_id}/ai/test", headers=member.headers)
    assert res.status_code == 403 and fake_llm.requests == []  # model was never called
