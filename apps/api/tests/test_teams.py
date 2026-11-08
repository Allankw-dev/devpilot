from collections.abc import Callable

from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from tests.conftest import Person
from tests.test_me_and_orgs import API, add, make_org

PersonFactory = Callable[[str], Person]


def make_team(client: TestClient, actor: Person, org_id: str, name: str = "Platform") -> Response:
    res: Response = client.post(
        f"{API}/orgs/{org_id}/teams", json={"name": name}, headers=actor.headers
    )
    return res


def test_team_lifecycle(client: TestClient, person: PersonFactory) -> None:
    owner, dev = person("owner@example.com"), person("dev@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev, "member")
    base = f"{API}/orgs/{org['id']}/teams"

    team = make_team(client, owner, org["id"]).json()
    assert team["member_count"] == 0

    res = client.post(
        f"{base}/{team['id']}/members", json={"user_id": str(dev.id)}, headers=owner.headers
    )
    assert res.status_code == 201 and res.json()["email"] == "dev@example.com"

    listed = client.get(base, headers=dev.headers).json()
    assert [(t["name"], t["member_count"]) for t in listed] == [("Platform", 1)]

    members = client.get(f"{base}/{team['id']}/members", headers=dev.headers).json()
    assert [m["email"] for m in members] == ["dev@example.com"]

    assert (
        client.delete(f"{base}/{team['id']}/members/{dev.id}", headers=owner.headers).status_code
        == 204
    )
    assert client.get(base, headers=owner.headers).json()[0]["member_count"] == 0
    assert client.delete(f"{base}/{team['id']}", headers=owner.headers).status_code == 204
    assert client.get(base, headers=owner.headers).json() == []


def test_only_admins_manage_teams(client: TestClient, person: PersonFactory) -> None:
    owner, member = person("owner@example.com"), person("member@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], member, "member")
    assert make_team(client, member, org["id"]).status_code == 403
    team = make_team(client, owner, org["id"]).json()
    base = f"{API}/orgs/{org['id']}/teams/{team['id']}"
    assert client.delete(base, headers=member.headers).status_code == 403
    assert (
        client.post(
            f"{base}/members", json={"user_id": str(member.id)}, headers=member.headers
        ).status_code
        == 403
    )


def test_duplicate_team_name_conflicts(client: TestClient, person: PersonFactory) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner)
    assert make_team(client, owner, org["id"]).status_code == 201
    assert make_team(client, owner, org["id"]).status_code == 409
    other = make_org(client, owner, "Other Org")
    assert make_team(client, owner, other["id"]).status_code == 201  # same name, different org


def test_team_members_must_be_org_members(client: TestClient, person: PersonFactory) -> None:
    owner, outsider = person("owner@example.com"), person("outsider@example.com")
    org = make_org(client, owner)
    team = make_team(client, owner, org["id"]).json()
    res = client.post(
        f"{API}/orgs/{org['id']}/teams/{team['id']}/members",
        json={"user_id": str(outsider.id)},
        headers=owner.headers,
    )
    assert res.status_code == 404


def test_duplicate_team_member_conflicts(client: TestClient, person: PersonFactory) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner)
    team = make_team(client, owner, org["id"]).json()
    url = f"{API}/orgs/{org['id']}/teams/{team['id']}/members"
    assert (
        client.post(url, json={"user_id": str(owner.id)}, headers=owner.headers).status_code == 201
    )
    assert (
        client.post(url, json={"user_id": str(owner.id)}, headers=owner.headers).status_code == 409
    )


def test_teams_are_isolated_between_orgs(client: TestClient, person: PersonFactory) -> None:
    a, b = person("a@example.com"), person("b@example.com")
    org_a, org_b = make_org(client, a, "Org A"), make_org(client, b, "Org B")
    team_a = make_team(client, a, org_a["id"]).json()
    # b can't see or touch a's team, even via their own org's URL
    assert client.get(f"{API}/orgs/{org_a['id']}/teams", headers=b.headers).status_code == 404
    res = client.delete(f"{API}/orgs/{org_b['id']}/teams/{team_a['id']}", headers=b.headers)
    assert res.status_code == 404


def test_removing_org_member_removes_team_memberships(
    client: TestClient, person: PersonFactory
) -> None:
    owner, dev = person("owner@example.com"), person("dev@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev)
    team = make_team(client, owner, org["id"]).json()
    url = f"{API}/orgs/{org['id']}/teams/{team['id']}/members"
    client.post(url, json={"user_id": str(dev.id)}, headers=owner.headers)

    client.delete(f"{API}/orgs/{org['id']}/members/{dev.id}", headers=owner.headers)
    assert client.get(url, headers=owner.headers).json() == []


def test_deleting_org_cascades(client: TestClient, person: PersonFactory, db: Session) -> None:
    from sqlalchemy import func, select

    from app.db.models import Membership, Team, TeamMember

    owner = person("owner@example.com")
    org = make_org(client, owner)
    team = make_team(client, owner, org["id"]).json()
    client.post(
        f"{API}/orgs/{org['id']}/teams/{team['id']}/members",
        json={"user_id": str(owner.id)},
        headers=owner.headers,
    )

    assert client.delete(f"{API}/orgs/{org['id']}", headers=owner.headers).status_code == 204
    for model in (Membership, Team, TeamMember):
        assert db.scalar(select(func.count()).select_from(model)) == 0
