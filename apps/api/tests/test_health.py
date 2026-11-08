from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.health import get_redis
from app.db.session import get_db
from app.main import app


class FakeDb:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def execute(self, *_: object) -> None:
        if self.fail:
            raise RuntimeError("db down")


def make_client(db_fail: bool = False, redis_fail: bool = False) -> TestClient:
    cache = MagicMock()
    if redis_fail:
        cache.ping.side_effect = RuntimeError("redis down")
    app.dependency_overrides[get_db] = lambda: FakeDb(db_fail)
    app.dependency_overrides[get_redis] = lambda: cache
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def test_health_ok() -> None:
    res = make_client().get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert body["product"] == "DevPilot AI"


def test_health_db_down() -> None:
    res = make_client(db_fail=True).get("/api/v1/health")
    assert res.status_code == 503
    assert res.json()["database"] == "down"
    assert res.json()["status"] == "degraded"


def test_health_redis_down() -> None:
    res = make_client(redis_fail=True).get("/api/v1/health")
    assert res.status_code == 503
    assert res.json()["redis"] == "down"
