import os
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import TokenVerifier, get_token_verifier
from app.db import models  # noqa: F401
from app.db.session import Base, get_db
from app.main import app

ISSUER = "https://test-project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


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


@pytest.fixture
def client(engine: Engine, verifier: TokenVerifier) -> Iterator[TestClient]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def _get_db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_token_verifier] = lambda: verifier
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
