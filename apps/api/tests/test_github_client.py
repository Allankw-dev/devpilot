import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.core.config import Settings
from app.services.github.client import (
    GitHubClient,
    GitHubError,
    GitHubNotConfigured,
    GitHubRateLimited,
)
from tests.github_helpers import INSTALLATION_ID, FakeGitHub, make_repo


def test_app_jwt_is_rs256_with_short_lifetime(
    gh_client: GitHubClient, rsa_key: rsa.RSAPrivateKey
) -> None:
    token = gh_client.app_jwt()
    assert jwt.get_unverified_header(token)["alg"] == "RS256"
    claims = jwt.decode(token, rsa_key.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "12345"
    assert claims["exp"] - claims["iat"] <= 600  # GitHub's maximum


def test_unconfigured_client_refuses(fake_github: FakeGitHub) -> None:
    empty = Settings(_env_file=None)
    client = GitHubClient(empty, transport=httpx.MockTransport(fake_github.handler))
    with pytest.raises(GitHubNotConfigured):
        client.app_jwt()
    with pytest.raises(GitHubNotConfigured):
        client.exchange_code("anything")


def test_private_key_from_file_and_escaped_newlines(tmp_path, private_pem: str) -> None:  # type: ignore[no-untyped-def]
    pem_file = tmp_path / "key.pem"
    pem_file.write_text(private_pem)
    assert (
        Settings(_env_file=None, github_app_private_key_path=str(pem_file)).github_private_key()
        == private_pem
    )

    escaped = private_pem.strip().replace("\n", "\\n")
    from_env = Settings(
        _env_file=None, github_app_private_key=SecretStr(escaped)
    ).github_private_key()
    assert from_env == private_pem.strip()


def test_missing_settings_reports_names_only() -> None:
    missing = Settings(_env_file=None).github_missing_settings()
    assert "GITHUB_APP_ID" in missing and "GITHUB_WEBHOOK_SECRET" in missing
    assert "GITHUB_APP_PRIVATE_KEY_PATH" in missing


def test_installation_token_is_cached_then_refreshed(
    gh_settings: Settings, fake_github: FakeGitHub
) -> None:
    now = [time.time()]
    client = GitHubClient(
        gh_settings, transport=httpx.MockTransport(fake_github.handler), clock=lambda: now[0]
    )
    first = client.installation_token(INSTALLATION_ID)
    assert client.installation_token(INSTALLATION_ID) == first
    assert fake_github.token_requests == 1

    now[0] += 3600  # past the one-hour expiry
    assert client.installation_token(INSTALLATION_ID) != first
    assert fake_github.token_requests == 2


def test_pagination_collects_all_pages(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    for i in range(205):
        fake_github.repos[INSTALLATION_ID].append(make_repo(1000 + i, f"octo-org/r{i}"))
    items, complete = gh_client.installation_paginate(
        INSTALLATION_ID, "/installation/repositories", key="repositories", max_pages=10
    )
    assert complete and len(items) == 207  # 205 + the two standard repos

    items, complete = gh_client.installation_paginate(
        INSTALLATION_ID, "/installation/repositories", key="repositories", max_pages=1
    )
    assert not complete and len(items) == 100


def test_transient_5xx_is_retried(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    attempts = {"n": 0}
    real = fake_github.handler

    def flaky(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/installation/repositories" and attempts["n"] < 2:
            attempts["n"] += 1
            return httpx.Response(502, json={"message": "bad gateway"})
        return real(request)

    client = GitHubClient(gh_client._s, transport=httpx.MockTransport(flaky), sleep=lambda _: None)
    data = client.installation_get(INSTALLATION_ID, "/installation/repositories")
    assert data["total_count"] == 2 and attempts["n"] == 2


def test_persistent_5xx_gives_up(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    fake_github.fail["/installation/repositories"] = (503, {})
    with pytest.raises(GitHubError):
        gh_client.installation_get(INSTALLATION_ID, "/installation/repositories")


def test_rate_limit_is_distinct_error(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    fake_github.fail["/installation/repositories"] = (
        403,
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"},
    )
    with pytest.raises(GitHubRateLimited) as info:
        gh_client.installation_get(INSTALLATION_ID, "/installation/repositories")
    assert info.value.reset_at == 1893456000


def test_plain_403_is_not_a_rate_limit(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    fake_github.fail["/installation/repositories"] = (403, {})
    with pytest.raises(GitHubError) as info:
        gh_client.installation_get(INSTALLATION_ID, "/installation/repositories")
    assert not isinstance(info.value, GitHubRateLimited) and info.value.status == 403


def test_code_exchange(gh_client: GitHubClient, fake_github: FakeGitHub) -> None:
    fake_github.codes["c1"] = {INSTALLATION_ID}
    token = gh_client.exchange_code("c1")
    assert gh_client.user_installation_ids(token) == {INSTALLATION_ID}
    with pytest.raises(GitHubError) as info:  # codes are single use
        gh_client.exchange_code("c1")
    assert info.value.status == 400


def test_revoked_cached_token_is_replaced_once(
    gh_client: GitHubClient, fake_github: FakeGitHub
) -> None:
    gh_client.installation_token(INSTALLATION_ID)  # cache a token
    old_requests = fake_github.token_requests
    real = fake_github.handler
    revoked = {"done": False}

    def revoke_first(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/installation/repositories" and not revoked["done"]:
            revoked["done"] = True
            return httpx.Response(401, json={"message": "Bad credentials"})
        return real(request)

    client = GitHubClient(
        gh_client._s, transport=httpx.MockTransport(revoke_first), sleep=lambda _: None
    )
    client._tokens = dict(gh_client._tokens)
    data = client.installation_get(INSTALLATION_ID, "/installation/repositories")
    assert data["total_count"] == 2
    assert fake_github.token_requests == old_requests + 1  # exactly one fresh token
