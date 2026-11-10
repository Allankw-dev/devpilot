import uuid
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response

from tests.conftest import Person

PersonFactory = Callable[[str], Person]
API = "/api/v1"


def make_org(client: TestClient, owner: Person, name: str = "Acme Corp") -> dict[str, Any]:
    res = client.post(f"{API}/orgs", json={"name": name}, headers=owner.headers)
    assert res.status_code == 201, res.text
    body: dict[str, Any] = res.json()
    return body


def add(
    client: TestClient, actor: Person, org_id: str, target: Person, role: str = "member"
) -> Response:
    res: Response = client.post(
        f"{API}/orgs/{org_id}/members",
        json={"email": target.email, "role": role},
        headers=actor.headers,
    )
    return res


# ---------- authentication ----------


def test_me_requires_token(client: TestClient) -> None:
    res = client.get(f"{API}/me")
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"


def test_me_rejects_bad_token(client: TestClient) -> None:
    res = client.get(f"{API}/me", headers={"Authorization": "Bearer nonsense"})
    assert res.status_code == 401


def test_me_provisions_user_once(client: TestClient, make_token: Callable[..., str]) -> None:
    uid = uuid.uuid4()
    headers = {
        "Authorization": "Bearer "
        + make_token(uid, "New@Example.com", extra={"user_metadata": {"name": "New Dev"}})
    }
    first = client.get(f"{API}/me", headers=headers).json()
    second = client.get(f"{API}/me", headers=headers).json()
    assert first == second
    assert first["user"]["id"] == str(uid)
    assert first["user"]["email"] == "new@example.com"
    assert first["user"]["display_name"] == "New Dev"
    assert first["organizations"] == []


def test_unconfigured_auth_returns_503(client: TestClient, make_token: Callable[..., str]) -> None:
    from app.core.security import TokenVerifier, get_token_verifier
    from app.main import app

    app.dependency_overrides[get_token_verifier] = lambda: TokenVerifier(
        issuer=None, audience="authenticated"
    )
    res = client.get(f"{API}/me", headers={"Authorization": f"Bearer {make_token()}"})
    assert res.status_code == 503


# ---------- organizations ----------


def test_create_org_makes_creator_owner(client: TestClient, person: PersonFactory) -> None:
    alice = person("alice@example.com")
    org = make_org(client, alice)
    assert org["role"] == "owner"
    assert org["slug"] == "acme-corp"

    me = client.get(f"{API}/me", headers=alice.headers).json()
    assert [o["id"] for o in me["organizations"]] == [org["id"]]


def test_duplicate_names_get_unique_slugs(client: TestClient, person: PersonFactory) -> None:
    alice, bob = person("alice@example.com"), person("bob@example.com")
    a = make_org(client, alice, "Same Name")
    b = make_org(client, bob, "Same Name")
    assert a["slug"] == "same-name"
    assert b["slug"] != a["slug"] and b["slug"].startswith("same-name-")


def test_org_name_validation(client: TestClient, person: PersonFactory) -> None:
    alice = person("alice@example.com")
    for bad in ["", " ", "a", "x" * 81]:
        res = client.post(f"{API}/orgs", json={"name": bad}, headers=alice.headers)
        assert res.status_code == 422, bad


def test_non_member_gets_404_not_403(client: TestClient, person: PersonFactory) -> None:
    alice, mallory = person("alice@example.com"), person("mallory@example.com")
    org = make_org(client, alice)
    for method, path in [
        ("get", ""),
        ("get", "/members"),
        ("get", "/teams"),
        ("patch", ""),
        ("delete", ""),
    ]:
        res = client.request(
            method.upper(),
            f"{API}/orgs/{org['id']}{path}",
            headers=mallory.headers,
            json={"name": "Hijacked"} if method == "patch" else None,
        )
        assert res.status_code == 404, (method, path)


def test_list_orgs_only_shows_own(client: TestClient, person: PersonFactory) -> None:
    alice, bob = person("alice@example.com"), person("bob@example.com")
    make_org(client, alice, "Alice Co")
    make_org(client, bob, "Bob Co")
    names = [
        o["name"] for o in client.get(f"{API}/me", headers=alice.headers).json()["organizations"]
    ]
    assert names == ["Alice Co"]


def test_rename_requires_admin(client: TestClient, person: PersonFactory) -> None:
    alice, bob, carol = (person(f"{n}@example.com") for n in ("alice", "bob", "carol"))
    org = make_org(client, alice)
    add(client, alice, org["id"], bob, "member")
    add(client, alice, org["id"], carol, "admin")

    url = f"{API}/orgs/{org['id']}"
    assert client.patch(url, json={"name": "New"}, headers=bob.headers).status_code == 403
    res = client.patch(url, json={"name": "New Name"}, headers=carol.headers)
    assert res.status_code == 200 and res.json()["name"] == "New Name"


def test_only_owner_can_delete_org(client: TestClient, person: PersonFactory) -> None:
    alice, bob = person("alice@example.com"), person("bob@example.com")
    org = make_org(client, alice)
    add(client, alice, org["id"], bob, "admin")
    url = f"{API}/orgs/{org['id']}"
    assert client.delete(url, headers=bob.headers).status_code == 403
    assert client.delete(url, headers=alice.headers).status_code == 204
    assert client.get(url, headers=alice.headers).status_code == 404


# ---------- members and roles ----------


def test_add_member_rules(client: TestClient, person: PersonFactory) -> None:
    owner, admin, newbie = (person(f"{n}@example.com") for n in ("owner", "admin", "newbie"))
    org = make_org(client, owner)
    assert add(client, owner, org["id"], admin, "admin").status_code == 201

    # unknown email
    ghost = Person(lambda *a, **k: "x", "ghost@example.com")
    assert add(client, owner, org["id"], ghost).status_code == 404
    # admin can add members and viewers, but not admins or owners
    assert add(client, admin, org["id"], newbie, "admin").status_code == 403
    assert add(client, admin, org["id"], newbie, "owner").status_code == 403
    assert add(client, admin, org["id"], newbie, "viewer").status_code == 201
    # duplicates
    assert add(client, owner, org["id"], newbie, "member").status_code == 409


def test_plain_members_cannot_manage(client: TestClient, person: PersonFactory) -> None:
    owner, member, other = (person(f"{n}@example.com") for n in ("owner", "member", "other"))
    org = make_org(client, owner)
    add(client, owner, org["id"], member, "member")
    assert add(client, member, org["id"], other).status_code == 403

    url = f"{API}/orgs/{org['id']}/members/{owner.id}"
    assert client.delete(url, headers=member.headers).status_code == 403


def test_viewer_can_read_but_not_write(client: TestClient, person: PersonFactory) -> None:
    owner, viewer = person("owner@example.com"), person("viewer@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], viewer, "viewer")
    base = f"{API}/orgs/{org['id']}"
    assert client.get(f"{base}/members", headers=viewer.headers).status_code == 200
    assert client.get(f"{base}/teams", headers=viewer.headers).status_code == 200
    assert (
        client.post(f"{base}/teams", json={"name": "Core"}, headers=viewer.headers).status_code
        == 403
    )


def test_role_changes(client: TestClient, person: PersonFactory) -> None:
    owner, admin, member = (person(f"{n}@example.com") for n in ("owner", "admin", "member"))
    org = make_org(client, owner)
    add(client, owner, org["id"], admin, "admin")
    add(client, owner, org["id"], member, "member")
    base = f"{API}/orgs/{org['id']}/members"

    # admin may move member <-> viewer, but not promote to admin or touch the owner
    assert (
        client.patch(
            f"{base}/{member.id}", json={"role": "viewer"}, headers=admin.headers
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"{base}/{member.id}", json={"role": "admin"}, headers=admin.headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"{base}/{owner.id}", json={"role": "member"}, headers=admin.headers
        ).status_code
        == 403
    )
    # admin can't change their own role
    assert (
        client.patch(
            f"{base}/{admin.id}", json={"role": "owner"}, headers=admin.headers
        ).status_code
        == 403
    )
    # owner can promote
    res = client.patch(f"{base}/{member.id}", json={"role": "admin"}, headers=owner.headers)
    assert res.status_code == 200 and res.json()["role"] == "admin"
    # invalid role value
    assert (
        client.patch(f"{base}/{member.id}", json={"role": "god"}, headers=owner.headers).status_code
        == 422
    )


def test_last_owner_is_protected(client: TestClient, person: PersonFactory) -> None:
    owner, second = person("owner@example.com"), person("second@example.com")
    org = make_org(client, owner)
    base = f"{API}/orgs/{org['id']}/members"

    # sole owner can't demote or leave
    assert (
        client.patch(
            f"{base}/{owner.id}", json={"role": "admin"}, headers=owner.headers
        ).status_code
        == 409
    )
    assert client.delete(f"{base}/{owner.id}", headers=owner.headers).status_code == 409

    # with a second owner, the first may step down or leave
    add(client, owner, org["id"], second, "owner")
    assert (
        client.patch(
            f"{base}/{owner.id}", json={"role": "admin"}, headers=owner.headers
        ).status_code
        == 200
    )
    # and now `second` is the last owner again
    assert client.delete(f"{base}/{second.id}", headers=second.headers).status_code == 409


def test_member_can_leave(client: TestClient, person: PersonFactory) -> None:
    owner, member = person("owner@example.com"), person("member@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], member)
    res = client.delete(f"{API}/orgs/{org['id']}/members/{member.id}", headers=member.headers)
    assert res.status_code == 204
    assert client.get(f"{API}/orgs/{org['id']}", headers=member.headers).status_code == 404


def test_admin_can_remove_member_but_not_admin(client: TestClient, person: PersonFactory) -> None:
    owner, admin, admin2, member = (
        person(f"{n}@example.com") for n in ("owner", "admin", "admin2", "member")
    )
    org = make_org(client, owner)
    for p, role in [(admin, "admin"), (admin2, "admin"), (member, "member")]:
        add(client, owner, org["id"], p, role)
    base = f"{API}/orgs/{org['id']}/members"
    assert client.delete(f"{base}/{admin2.id}", headers=admin.headers).status_code == 403
    assert client.delete(f"{base}/{member.id}", headers=admin.headers).status_code == 204
    assert client.delete(f"{base}/{member.id}", headers=admin.headers).status_code == 404


def test_list_members(client: TestClient, person: PersonFactory) -> None:
    owner, member = person("owner@example.com"), person("member@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], member, "viewer")
    rows = client.get(f"{API}/orgs/{org['id']}/members", headers=owner.headers).json()
    assert {(r["email"], r["role"]) for r in rows} == {
        ("owner@example.com", "owner"),
        ("member@example.com", "viewer"),
    }
