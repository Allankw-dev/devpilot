import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_github_client, get_session_factory_dep
from app.core.config import Settings, get_settings
from app.core.security import TokenVerifier, get_token_verifier
from app.db import models  # noqa: F401
from app.db.session import Base, get_db
from app.main import app
from app.services.github.client import GitHubClient
from tests.github_helpers import (
    CLIENT_ID,
    CLIENT_SECRET,
    WEBHOOK_SECRET,
    FakeGitHub,
    standard_world,
)

ISSUER = "https://test-project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


ON_POSTGRES = os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")


@pytest.fixture
def engine() -> Iterator[Engine]:
    """SQLite in memory by default; set TEST_DATABASE_URL to run the suite on Postgres."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        eng = create_engine(url)
    else:
        eng = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn: Any, _: Any) -> None:
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    if eng.dialect.name == "postgresql":  # the embedding column needs pgvector
        with eng.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with sessionmaker(bind=engine, expire_on_commit=False)() as session:
        yield session


@dataclass
class _Key:
    key: Any


class FakeJwks:
    """Stands in for PyJWKClient: always hands back the test public key."""

    def __init__(self, public_key: Any) -> None:
        self._public = public_key

    def get_signing_key_from_jwt(self, token: str) -> _Key:
        return _Key(self._public)


@pytest.fixture(scope="session")
def private_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def make_token(private_key: ec.EllipticCurvePrivateKey) -> Callable[..., str]:
    def _make(
        user_id: uuid.UUID | str | None = None,
        email: str | None = "dev@example.com",
        *,
        key: Any = None,
        alg: str = "ES256",
        audience: str = AUDIENCE,
        issuer: str = ISSUER,
        expires_in: int = 3600,
        extra: dict[str, Any] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "sub": str(user_id or uuid.uuid4()),
            "aud": audience,
            "iss": issuer,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in,
            "role": "authenticated",
        }
        if email is not None:
            payload["email"] = email
        payload.update(extra or {})
        return jwt.encode(payload, key or private_key, algorithm=alg)

    return _make


@pytest.fixture
def verifier(private_key: ec.EllipticCurvePrivateKey) -> TokenVerifier:
    return TokenVerifier(
        issuer=ISSUER, audience=AUDIENCE, jwks_client=FakeJwks(private_key.public_key())
    )


@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def private_pem(rsa_key: rsa.RSAPrivateKey) -> str:
    return rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def gh_settings(private_pem: str) -> Settings:
    """Fully configured GitHub settings. _env_file=None so a developer's real .env never leaks in."""
    return Settings(
        _env_file=None,
        github_app_id="12345",
        github_app_slug="devpilot-test",
        github_client_id=CLIENT_ID,
        github_client_secret=SecretStr(CLIENT_SECRET),
        github_webhook_secret=SecretStr(WEBHOOK_SECRET),
        github_app_private_key=SecretStr(private_pem),
        job_backend="inline",  # jobs run in-process; the Celery path has its own tests
    )


@pytest.fixture
def fake_github(rsa_key: rsa.RSAPrivateKey) -> FakeGitHub:
    fake = FakeGitHub(rsa_key.public_key())
    standard_world(fake)
    return fake


@pytest.fixture
def gh_client(gh_settings: Settings, fake_github: FakeGitHub) -> GitHubClient:
    return GitHubClient(
        gh_settings, transport=httpx.MockTransport(fake_github.handler), sleep=lambda _: None
    )


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    verifier: TokenVerifier,
    gh_settings: Settings,
    gh_client: GitHubClient,
) -> Iterator[TestClient]:
    def _get_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_token_verifier] = lambda: verifier
    app.dependency_overrides[get_settings] = lambda: gh_settings
    app.dependency_overrides[get_github_client] = lambda: gh_client
    app.dependency_overrides[get_session_factory_dep] = lambda: session_factory
    yield TestClient(app)
    app.dependency_overrides.clear()


class Person:
    """A signed-in test user: stable id per email, ready-made auth headers."""

    def __init__(self, make_token: Callable[..., str], email: str) -> None:
        self.email = email
        self.id = uuid.uuid5(uuid.NAMESPACE_DNS, email)
        self.headers = {"Authorization": f"Bearer {make_token(self.id, email)}"}


@pytest.fixture
def person(make_token: Callable[..., str], client: TestClient) -> Callable[[str], Person]:
    def _person(email: str) -> Person:
        p = Person(make_token, email)
        assert client.get("/api/v1/me", headers=p.headers).status_code == 200  # provisions user
        return p

    return _person


@dataclass
class World:
    owner: Person
    org_id: str


@pytest.fixture
def world(client: TestClient, person: Callable[[str], Person]) -> World:
    owner = person("owner@example.com")
    res = client.post("/api/v1/orgs", json={"name": "Acme"}, headers=owner.headers)
    assert res.status_code == 201
    return World(owner=owner, org_id=res.json()["id"])
