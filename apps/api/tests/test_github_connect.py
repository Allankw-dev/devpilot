from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import GithubConnectRequest, GithubInstallation, Repository
from app.main import app
from tests.conftest import Person, World
from tests.github_helpers import (
    INSTALLATION_ID,
    FakeGitHub,
    connect,
    make_repo,
    start_connect,
)

API = "/api/v1"
PersonFactory = Callable[[str], Person]


def status_of(client: TestClient, w: World) -> dict:  # type: ignore[type-arg]
    res = client.get(f"{API}/orgs/{w.org_id}/github", headers=w.owner.headers)
    assert res.status_code == 200
    return res.json()  # type: ignore[no-any-return]


def add_member(client: TestClient, w: World, who: Person, role: str) -> None:
    res = client.post(
        f"{API}/orgs/{w.org_id}/members",
        json={"email": who.email, "role": role},
        headers=w.owner.headers,
    )
    assert res.status_code == 201, res.text


# ---------- configuration ----------


def test_unconfigured_shows_missing_names_to_admins_only(
    client: TestClient, world: World, person: PersonFactory
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    member = person("member@example.com")
    add_member(client, world, member, "member")

    admin_view = status_of(client, world)
    assert admin_view["configured"] is False
    assert "GITHUB_APP_ID" in admin_view["missing"]

    member_view = client.get(f"{API}/orgs/{world.org_id}/github", headers=member.headers).json()
    assert member_view["configured"] is False and member_view["missing"] == []


def test_install_url_needs_configuration(client: TestClient, world: World) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    res = client.post(f"{API}/orgs/{world.org_id}/github/install-url", headers=world.owner.headers)
    assert res.status_code == 503 and "GITHUB_APP_ID" in res.json()["detail"]


def test_install_url_points_at_the_app_and_is_admin_only(
    client: TestClient, world: World, person: PersonFactory
) -> None:
    res = client.post(f"{API}/orgs/{world.org_id}/github/install-url", headers=world.owner.headers)
    assert res.status_code == 200
    assert res.json()["url"].startswith(
        "https://github.com/apps/devpilot-test/installations/new?state="
    )

    member = person("member@example.com")
    add_member(client, world, member, "member")
    denied = client.post(f"{API}/orgs/{world.org_id}/github/install-url", headers=member.headers)
    assert denied.status_code == 403


# ---------- claiming an installation ----------


def test_connect_happy_path_syncs_in_background(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    res = connect(client, fake_github, world.owner.headers, world.org_id)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["account_login"] == "octo-org" and body["account_type"] == "Organization"
    assert body["installation_id"] == INSTALLATION_ID
    assert body["org_id"] == world.org_id
    assert body["sync_status"] == "running"  # the response reports the sync as started

    installation = status_of(client, world)["installations"][0]
    assert installation["sync_status"] == "idle" and installation["last_synced_at"] is not None
    repos = client.get(f"{API}/orgs/{world.org_id}/repos", headers=world.owner.headers).json()
    assert {r["full_name"] for r in repos} == {"octo-org/api", "octo-org/web"}


def test_connect_works_when_github_does_not_echo_state(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    res = connect(client, fake_github, world.owner.headers, world.org_id, with_state=False)
    assert res.status_code == 200, res.text


def test_connect_requires_login(client: TestClient) -> None:
    res = client.post(f"{API}/github/installations/claim", json={"code": "x", "installation_id": 1})
    assert res.status_code == 401


def test_cannot_claim_an_installation_the_user_cannot_access(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    """The installation_id in GitHub's redirect is editable. The one-time code proves access."""
    fake_github.add_installation(999, login="victim-org")
    res = connect(
        client,
        fake_github,
        world.owner.headers,
        world.org_id,
        installation_id=999,
        accessible={INSTALLATION_ID},  # attacker only has access to 777
    )
    assert res.status_code == 403
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(GithubInstallation)) == 0


def test_bad_or_reused_code_is_rejected(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    state = start_connect(client, world.owner.headers, world.org_id)
    res = client.post(
        f"{API}/github/installations/claim",
        json={"code": "forged", "installation_id": INSTALLATION_ID, "state": state},
        headers=world.owner.headers,
    )
    assert res.status_code == 400


def test_state_from_another_user_is_rejected(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    mallory = person("mallory@example.com")
    state = start_connect(client, world.owner.headers, world.org_id)
    fake_github.codes["c"] = {INSTALLATION_ID}
    res = client.post(
        f"{API}/github/installations/claim",
        json={"code": "c", "installation_id": INSTALLATION_ID, "state": state},
        headers=mallory.headers,
    )
    assert res.status_code == 400


def test_expired_connect_request_is_rejected(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    state = start_connect(client, world.owner.headers, world.org_id)
    with session_factory() as db:
        db.execute(
            update(GithubConnectRequest).values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        db.commit()
    fake_github.codes["c"] = {INSTALLATION_ID}
    res = client.post(
        f"{API}/github/installations/claim",
        json={"code": "c", "installation_id": INSTALLATION_ID, "state": state},
        headers=world.owner.headers,
    )
    assert res.status_code == 400 and "expired" in res.json()["detail"]


def test_role_is_rechecked_at_claim_time(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    admin = person("admin@example.com")
    add_member(client, world, admin, "admin")
    state = start_connect(client, admin.headers, world.org_id)
    client.patch(
        f"{API}/orgs/{world.org_id}/members/{admin.id}",
        json={"role": "viewer"},
        headers=world.owner.headers,
    )
    fake_github.codes["c"] = {INSTALLATION_ID}
    res = client.post(
        f"{API}/github/installations/claim",
        json={"code": "c", "installation_id": INSTALLATION_ID, "state": state},
        headers=admin.headers,
    )
    assert res.status_code == 403


def test_one_installation_cannot_serve_two_organizations(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    assert connect(client, fake_github, world.owner.headers, world.org_id).status_code == 200

    other = person("other@example.com")
    org2 = client.post(f"{API}/orgs", json={"name": "Other"}, headers=other.headers).json()
    res = connect(client, fake_github, other.headers, org2["id"], code="code2")
    assert res.status_code == 409


def test_reconnecting_the_same_org_updates_instead_of_duplicating(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    assert connect(client, fake_github, world.owner.headers, world.org_id).status_code == 200
    assert (
        connect(client, fake_github, world.owner.headers, world.org_id, code="c2").status_code
        == 200
    )
    assert len(status_of(client, world)["installations"]) == 1


def test_connect_request_is_single_use(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    assert connect(client, fake_github, world.owner.headers, world.org_id).status_code == 200
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(GithubConnectRequest)) == 0


# ---------- manage ----------


def test_disconnect_removes_data_and_is_admin_only(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    person: PersonFactory,
    session_factory: sessionmaker[Session],
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    pk = status_of(client, world)["installations"][0]["id"]
    url = f"{API}/orgs/{world.org_id}/github/installations/{pk}"

    member = person("member@example.com")
    add_member(client, world, member, "member")
    assert client.delete(url, headers=member.headers).status_code == 403

    assert client.delete(url, headers=world.owner.headers).status_code == 204
    assert status_of(client, world)["installations"] == []
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Repository)) == 0


def test_cannot_touch_another_orgs_installation(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    pk = status_of(client, world)["installations"][0]["id"]

    other = person("other@example.com")
    org2 = client.post(f"{API}/orgs", json={"name": "Other"}, headers=other.headers).json()
    for method, suffix in (("DELETE", ""), ("POST", "/sync")):
        res = client.request(
            method,
            f"{API}/orgs/{org2['id']}/github/installations/{pk}{suffix}",
            headers=other.headers,
        )
        assert res.status_code == 404


def test_manual_sync_lifecycle(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    pk = status_of(client, world)["installations"][0]["id"]
    url = f"{API}/orgs/{world.org_id}/github/installations/{pk}/sync"

    res = client.post(url, headers=world.owner.headers)
    assert res.status_code == 202 and res.json()["sync_status"] == "running"
    assert status_of(client, world)["installations"][0]["sync_status"] == "idle"  # finished

    with session_factory() as db:  # a sync that is genuinely in progress blocks another
        db.execute(
            update(GithubInstallation).values(
                sync_status="running", sync_started_at=datetime.now(UTC)
            )
        )
        db.commit()
    assert client.post(url, headers=world.owner.headers).status_code == 409

    with session_factory() as db:  # ...but a crashed one (stale lock) does not
        db.execute(
            update(GithubInstallation).values(
                sync_started_at=datetime.now(UTC) - timedelta(minutes=20)
            )
        )
        db.commit()
    assert client.post(url, headers=world.owner.headers).status_code == 202


def test_suspended_installation_is_not_synced(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    pk = status_of(client, world)["installations"][0]["id"]
    with session_factory() as db:
        db.execute(update(GithubInstallation).values(suspended_at=datetime.now(UTC)))
        db.commit()
    res = client.post(
        f"{API}/orgs/{world.org_id}/github/installations/{pk}/sync", headers=world.owner.headers
    )
    assert res.status_code == 409


def test_new_repo_added_on_github_appears_after_sync(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    fake_github.add_repo(INSTALLATION_ID, make_repo(103, "octo-org/docs"))
    pk = status_of(client, world)["installations"][0]["id"]
    client.post(
        f"{API}/orgs/{world.org_id}/github/installations/{pk}/sync", headers=world.owner.headers
    )
    repos = client.get(f"{API}/orgs/{world.org_id}/repos", headers=world.owner.headers).json()
    assert len(repos) == 3
