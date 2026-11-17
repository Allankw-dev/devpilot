import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import LlmUsage
from app.main import app
from tests.conftest import Person, World

API = "/api/v1"
PersonFactory = Callable[[str], Person]
NOW = datetime.now(UTC)


def add(
    factory: sessionmaker[Session],
    org_id: Any,
    *,
    feature: str = "ask_retrieval",
    model: str = "model-a",
    status: str = "ok",
    error_code: str | None = None,
    tokens_in: int = 10,
    tokens_out: int = 5,
    calls: int = 1,
    latency_ms: int = 100,
    ago: timedelta = timedelta(0),
) -> None:
    with factory() as db:
        db.add(
            LlmUsage(
                org_id=uuid.UUID(str(org_id)) if org_id is not None else None,
                provider="gemini",
                model=model,
                operation="generate",
                feature=feature,
                status=status,
                error_code=error_code,
                input_tokens=tokens_in,
                output_tokens=tokens_out,
                calls=calls,
                latency_ms=latency_ms,
                created_at=datetime.now(UTC) - ago,
            )
        )
        db.commit()


def usage(client: TestClient, world: World, who: Person | None = None, **params: Any) -> Any:
    res = client.get(
        f"{API}/orgs/{world.org_id}/ai/usage", params=params, headers=(who or world.owner).headers
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_an_org_with_no_usage_gets_zeros_and_every_day_filled_in(
    client: TestClient, world: World
) -> None:
    data = usage(client, world)
    assert data["days"] == 14 and len(data["by_day"]) == 14
    assert data["operations"] == data["provider_calls"] == data["errors"] == 0
    assert data["avg_latency_ms"] is None and data["quota_hit_at"] is None
    assert data["by_feature"] == data["by_model"] == data["errors_by_code"] == []
    assert all(d["operations"] == 0 for d in data["by_day"])
    assert data["by_day"][-1]["day"] == NOW.date().isoformat()
    assert data["by_day"][0]["day"] == (NOW.date() - timedelta(days=13)).isoformat()
    assert data["calls_last_24h"] == 0 and data["daily_limit"] is None


def test_totals_and_breakdowns_add_up(
    client: TestClient, world: World, session_factory: sessionmaker[Session]
) -> None:
    org = world.org_id
    add(session_factory, org, feature="ci", tokens_in=100, tokens_out=40, calls=1, latency_ms=200)
    add(session_factory, org, feature="ci", tokens_in=50, tokens_out=10, calls=3, latency_ms=400)
    add(
        session_factory, org, feature="review", model="model-b", status="error",
        error_code="unavailable", tokens_in=0, tokens_out=0, calls=3, latency_ms=9000,
    )  # fmt: skip
    add(session_factory, org, feature="review", model="model-b", tokens_in=7, tokens_out=3, calls=1)

    data = usage(client, world)
    assert data["operations"] == 4 and data["provider_calls"] == 8 and data["errors"] == 1
    assert (data["input_tokens"], data["output_tokens"]) == (157, 53)
    assert data["avg_latency_ms"] == 233  # failed operations are left out: (200+400+100)/3

    features = {f["feature"]: f for f in data["by_feature"]}
    assert features["ci"]["operations"] == 2 and features["ci"]["provider_calls"] == 4
    assert features["review"]["errors"] == 1 and features["review"]["provider_calls"] == 4
    assert features["ci"]["input_tokens"] == 150

    models = {m["model"]: m for m in data["by_model"]}
    assert models["model-b"]["provider_calls"] == 4 and models["model-b"]["errors"] == 1
    assert models["model-a"]["calls_last_24h"] == 4  # the ci rows
    assert data["calls_last_24h"] == 8
    assert data["errors_by_code"] == [{"code": "unavailable", "count": 1}]
    assert data["by_day"][-1]["provider_calls"] == 8 and data["by_day"][-1]["errors"] == 1


def test_breakdowns_are_sorted_busiest_first(
    client: TestClient, world: World, session_factory: sessionmaker[Session]
) -> None:
    add(session_factory, world.org_id, feature="small", calls=1)
    add(session_factory, world.org_id, feature="big", calls=5)
    add(session_factory, world.org_id, feature="medium", calls=2)
    assert [f["feature"] for f in usage(client, world)["by_feature"]] == ["big", "medium", "small"]


def test_usage_outside_the_window_is_left_out_but_the_last_24h_still_counts(
    client: TestClient, world: World, session_factory: sessionmaker[Session]
) -> None:
    add(session_factory, world.org_id, ago=timedelta(days=20))
    add(session_factory, world.org_id, ago=timedelta(hours=2))
    data = usage(client, world, days=7)
    assert data["operations"] == 1 and len(data["by_day"]) == 7
    assert usage(client, world, days=30)["operations"] == 2
    assert usage(client, world, days=30)["calls_last_24h"] == 1


def test_usage_is_grouped_by_utc_day(
    client: TestClient, world: World, session_factory: sessionmaker[Session]
) -> None:
    add(session_factory, world.org_id, ago=timedelta(days=3), calls=2)
    add(session_factory, world.org_id, ago=timedelta(days=3), calls=1)
    by_day = {d["day"]: d for d in usage(client, world, days=5)["by_day"]}
    day = (NOW - timedelta(days=3)).date().isoformat()
    assert by_day[day]["operations"] == 2 and by_day[day]["provider_calls"] == 3


def test_a_spent_quota_is_reported_with_when_it_last_happened(
    client: TestClient, world: World, session_factory: sessionmaker[Session]
) -> None:
    for hours in (30, 2):
        add(
            session_factory, world.org_id, status="error", error_code="quota_exhausted",
            ago=timedelta(hours=hours),
        )  # fmt: skip
    data = usage(client, world)
    hit = datetime.fromisoformat(data["quota_hit_at"])
    assert hit.tzinfo is not None and abs((NOW - timedelta(hours=2)) - hit) < timedelta(minutes=2)
    assert data["errors_by_code"] == [{"code": "quota_exhausted", "count": 2}]


def test_the_daily_limit_comes_from_settings(
    client: TestClient, world: World, gh_settings: Settings
) -> None:
    app.dependency_overrides[get_settings] = lambda: gh_settings.model_copy(
        update={"ai_daily_request_limit": 20}
    )
    assert usage(client, world)["daily_limit"] == 20


def test_other_orgs_and_unowned_rows_are_never_counted(
    client: TestClient,
    world: World,
    session_factory: sessionmaker[Session],
    person: PersonFactory,
) -> None:
    mallory = person("mallory@example.com")
    other = client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    add(session_factory, other["id"], calls=9)
    add(session_factory, None, calls=9)
    add(session_factory, world.org_id, calls=1)
    assert usage(client, world)["provider_calls"] == 1
    res = client.get(f"{API}/orgs/{other['id']}/ai/usage", headers=mallory.headers)
    assert res.json()["provider_calls"] == 9


def test_members_and_viewers_can_read_it_outsiders_cannot(
    client: TestClient, world: World, person: PersonFactory
) -> None:
    viewer = person("viewer@example.com")
    res = client.post(
        f"{API}/orgs/{world.org_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=world.owner.headers,
    )
    assert res.status_code in (200, 201)
    assert usage(client, world, viewer)["days"] == 14

    outsider = person("outsider@example.com")
    url = f"{API}/orgs/{world.org_id}/ai/usage"
    assert client.get(url, headers=outsider.headers).status_code == 404
    assert client.get(url).status_code == 401


@pytest.mark.parametrize("days", ["0", "91", "abc"])
def test_the_window_is_validated(client: TestClient, world: World, days: str) -> None:
    res = client.get(
        f"{API}/orgs/{world.org_id}/ai/usage", params={"days": days}, headers=world.owner.headers
    )
    assert res.status_code == 422


def test_it_works_even_when_ai_is_not_configured(client: TestClient, world: World) -> None:
    assert usage(client, world)["operations"] == 0  # reading usage never needs the provider
