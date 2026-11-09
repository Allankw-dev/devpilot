from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub, connect, make_repo

API = "/api/v1"
PersonFactory = Callable[[str], Person]


def test_empty_org_has_empty_overview(client: TestClient, world: World) -> None:
    assert client.get(f"{API}/orgs/{world.org_id}/repos", headers=world.owner.headers).json() == []
    ov = client.get(f"{API}/orgs/{world.org_id}/overview", headers=world.owner.headers).json()
    assert ov["repositories"] == 0 and ov["recent_commits"] == []
    assert ov["ci"] == {"passing": 0, "failing": 0, "running": 0, "other": 0, "none": 0}


def test_non_members_get_404(client: TestClient, world: World, person: PersonFactory) -> None:
    mallory = person("mallory@example.com")
    for path in ("repos", "overview", "github"):
        res = client.get(f"{API}/orgs/{world.org_id}/{path}", headers=mallory.headers)
        assert res.status_code == 404, path


def test_viewers_can_read_but_not_manage_github(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    connect(client, fake_github, world.owner.headers, world.org_id)
    viewer = person("viewer@example.com")
    client.post(
        f"{API}/orgs/{world.org_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=world.owner.headers,
    )

    assert len(client.get(f"{API}/orgs/{world.org_id}/repos", headers=viewer.headers).json()) == 2
    assert (
        client.get(f"{API}/orgs/{world.org_id}/overview", headers=viewer.headers).status_code == 200
    )
    assert (
        client.post(
            f"{API}/orgs/{world.org_id}/github/install-url", headers=viewer.headers
        ).status_code
        == 403
    )


def test_organizations_only_see_their_own_repositories(
    client: TestClient, world: World, fake_github: FakeGitHub, person: PersonFactory
) -> None:
    fake_github.add_installation(888, login="other-org")
    fake_github.add_repo(888, make_repo(201, "other-org/secret"))

    other = person("other@example.com")
    org2 = client.post(f"{API}/orgs", json={"name": "Other"}, headers=other.headers).json()
    connect(client, fake_github, world.owner.headers, world.org_id)
    connect(client, fake_github, other.headers, org2["id"], code="c2", installation_id=888)

    mine = {
        r["full_name"]
        for r in client.get(f"{API}/orgs/{world.org_id}/repos", headers=world.owner.headers).json()
    }
    theirs = {
        r["full_name"]
        for r in client.get(f"{API}/orgs/{org2['id']}/repos", headers=other.headers).json()
    }
    assert mine == {"octo-org/api", "octo-org/web"}
    assert theirs == {"other-org/secret"}
