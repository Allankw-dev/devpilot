import logging
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


def test_live_never_looks_at_dependencies() -> None:
    res = make_client(db_fail=True, redis_fail=True).get("/api/v1/health/live")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_ready_when_everything_answers() -> None:
    res = make_client().get("/api/v1/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ready", "database": "ok", "redis": "ok"}


def test_not_ready_when_the_database_is_down() -> None:
    res = make_client(db_fail=True).get("/api/v1/health/ready")
    assert res.status_code == 503
    assert res.json() == {"status": "not_ready", "database": "down", "redis": "ok"}


def test_not_ready_when_redis_is_down() -> None:
    res = make_client(redis_fail=True).get("/api/v1/health/ready")
    assert res.status_code == 503
    assert res.json() == {"status": "not_ready", "database": "ok", "redis": "down"}


def test_ready_does_not_leak_the_failure_cause() -> None:
    res = make_client(db_fail=True, redis_fail=True).get("/api/v1/health/ready")
    assert "db down" not in res.text and "redis down" not in res.text


def test_a_failed_probe_is_one_short_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.api.v1.health"):
        make_client(db_fail=True, redis_fail=True).get("/api/v1/health/ready")
    db = [r for r in caplog.records if "database health check failed" in r.getMessage()]
    cache = [r for r in caplog.records if "redis health check failed" in r.getMessage()]
    assert len(db) == 1 and db[0].levelno == logging.WARNING and db[0].exc_info is None
    assert len(cache) == 1 and cache[0].exc_info is None
    assert "RuntimeError" in db[0].getMessage()
