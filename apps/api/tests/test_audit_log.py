"""The audit log: what is recorded, who can read it, and that nothing leaks across organizations."""

import logging
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.request_context import REQUEST_ID
from app.db.models import AuditLog
from app.services.audit import record_audit
from tests.conftest import Person
from tests.test_me_and_orgs import API, add, make_org
from tests.test_teams import make_team

PersonFactory = Callable[[str], Person]


def log(client: TestClient, who: Person, org_id: str, **params: Any) -> Any:
    return client.get(f"{API}/orgs/{org_id}/audit-log", params=params, headers=who.headers)


def entries(client: TestClient, who: Person, org_id: str, **params: Any) -> list[dict[str, Any]]:
    res = log(client, who, org_id, **params)
    assert res.status_code == 200, res.text
    items: list[dict[str, Any]] = res.json()["items"]
    return items


def actions(client: TestClient, who: Person, org_id: str) -> list[str]:
    """Oldest first, to read like a story."""
    return [e["action"] for e in reversed(entries(client, who, org_id))]


# ---------- what is recorded ----------


def test_creating_an_organization_is_the_first_entry(
    client: TestClient, person: PersonFactory
) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner, "Acme Corp")
    [entry] = entries(client, owner, org["id"])
    assert entry["action"] == "org.created"
    assert entry["actor_email"] == "owner@example.com" and entry["actor_id"] == str(owner.id)
    assert entry["target_type"] == "organization" and entry["target_id"] == org["id"]
    assert entry["details"] == {"name": "Acme Corp"}
    assert entry["created_at"]


def test_member_changes_are_recorded_with_who_and_what(
    client: TestClient, person: PersonFactory
) -> None:
    owner, dev = person("owner@example.com"), person("dev@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev, "member")
    client.patch(
        f"{API}/orgs/{org['id']}/members/{dev.id}", json={"role": "admin"}, headers=owner.headers
    )
    client.delete(f"{API}/orgs/{org['id']}/members/{dev.id}", headers=owner.headers)

    assert actions(client, owner, org["id"]) == [
        "org.created",
        "member.added",
        "member.role_changed",
        "member.removed",
    ]
    added, changed, removed = reversed(entries(client, owner, org["id"])[:3])
    assert added["details"] == {"email": "dev@example.com", "role": "member"}
    assert added["target_id"] == str(dev.id) and added["actor_email"] == "owner@example.com"
    assert changed["details"] == {"email": "dev@example.com", "from": "member", "to": "admin"}
    assert removed["details"] == {"email": "dev@example.com", "role": "admin", "self": False}


def test_leaving_an_organization_yourself_is_marked(
    client: TestClient, person: PersonFactory
) -> None:
    owner, dev = person("owner@example.com"), person("dev@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev, "member")
    client.delete(f"{API}/orgs/{org['id']}/members/{dev.id}", headers=dev.headers)
    latest = entries(client, owner, org["id"])[0]
    assert latest["action"] == "member.removed"
    assert latest["actor_email"] == "dev@example.com" and latest["details"]["self"] is True


def test_renaming_records_the_old_and_new_name(client: TestClient, person: PersonFactory) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner, "Old Name")
    client.patch(f"{API}/orgs/{org['id']}", json={"name": "New Name"}, headers=owner.headers)
    latest = entries(client, owner, org["id"])[0]
    assert latest["action"] == "org.renamed"
    assert latest["details"] == {"from": "Old Name", "to": "New Name"}


def test_team_changes_are_recorded(client: TestClient, person: PersonFactory) -> None:
    owner, dev = person("owner@example.com"), person("dev@example.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev, "member")
    team = make_team(client, owner, org["id"], "Platform").json()
    base = f"{API}/orgs/{org['id']}/teams/{team['id']}"
    client.post(f"{base}/members", json={"user_id": str(dev.id)}, headers=owner.headers)
    client.delete(f"{base}/members/{dev.id}", headers=owner.headers)
    client.delete(base, headers=owner.headers)

    assert actions(client, owner, org["id"])[2:] == [
        "team.created",
        "team.member_added",
        "team.member_removed",
        "team.deleted",
    ]
    created = next(e for e in entries(client, owner, org["id"]) if e["action"] == "team.created")
    assert created["target_id"] == team["id"] and created["details"] == {"name": "Platform"}


def test_each_entry_carries_the_request_id_of_the_request_that_caused_it(
    client: TestClient, person: PersonFactory
) -> None:
    owner = person("owner@example.com")
    res = client.post(f"{API}/orgs", json={"name": "Acme"}, headers=owner.headers)
    [entry] = entries(client, owner, res.json()["id"])
    assert entry["request_id"] == res.headers["X-Request-ID"]


def test_actions_that_fail_leave_no_entry(client: TestClient, person: PersonFactory) -> None:
    owner, dev, stranger = person("owner@example.com"), person("dev@example.com"), person("x@e.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], dev, "member")
    # unknown email, duplicate member, a member trying to manage, a duplicate team name
    no_such = client.post(
        f"{API}/orgs/{org['id']}/members",
        json={"email": "nobody@example.com", "role": "member"},
        headers=owner.headers,
    )
    assert no_such.status_code == 404
    assert add(client, owner, org["id"], dev, "member").status_code == 409
    assert add(client, dev, org["id"], stranger, "member").status_code == 403
    make_team(client, owner, org["id"], "Platform")
    assert make_team(client, owner, org["id"], "Platform").status_code == 409

    assert actions(client, owner, org["id"]) == ["org.created", "member.added", "team.created"]


def test_deleting_an_organization_is_logged_but_not_stored(
    client: TestClient, person: PersonFactory, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner)
    with caplog.at_level(logging.INFO, logger="app.audit"):
        assert client.delete(f"{API}/orgs/{org['id']}", headers=owner.headers).status_code == 204
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 0  # went with the organization
    [line] = [
        r
        for r in caplog.records
        if r.name == "app.audit" and r.audit["action"] == "org.deleted"  # type: ignore[attr-defined]
    ]
    assert line.audit["action"] == "org.deleted"  # type: ignore[attr-defined]
    assert line.audit["org_id"] == org["id"]  # type: ignore[attr-defined]


def test_every_event_is_also_written_to_the_application_log(
    client: TestClient, person: PersonFactory, caplog: pytest.LogCaptureFixture
) -> None:
    owner = person("owner@example.com")
    with caplog.at_level(logging.INFO, logger="app.audit"):
        org = make_org(client, owner)
    [line] = [r for r in caplog.records if r.name == "app.audit"]
    assert line.audit["action"] == "org.created"  # type: ignore[attr-defined]
    assert line.audit["actor_id"] == str(owner.id)  # type: ignore[attr-defined]
    assert line.audit["target_id"] == org["id"]  # type: ignore[attr-defined]
    assert "name" not in line.audit  # type: ignore[attr-defined]  # details stay out of the log


# ---------- who can read it ----------


def test_only_admins_and_owners_can_read_it(client: TestClient, person: PersonFactory) -> None:
    owner = person("owner@example.com")
    admin, member, viewer = person("a@e.com"), person("m@e.com"), person("v@e.com")
    org = make_org(client, owner)
    add(client, owner, org["id"], admin, "admin")
    add(client, owner, org["id"], member, "member")
    add(client, owner, org["id"], viewer, "viewer")
    assert log(client, owner, org["id"]).status_code == 200
    assert log(client, admin, org["id"]).status_code == 200
    assert log(client, member, org["id"]).status_code == 403
    assert log(client, viewer, org["id"]).status_code == 403


def test_it_needs_authentication(client: TestClient, person: PersonFactory) -> None:
    org = make_org(client, person("owner@example.com"))
    assert client.get(f"{API}/orgs/{org['id']}/audit-log").status_code == 401


def test_other_organizations_cannot_see_it_and_never_appear_in_it(
    client: TestClient, person: PersonFactory
) -> None:
    owner_a, owner_b = person("a@example.com"), person("b@example.com")
    org_a = make_org(client, owner_a, "Org A")
    org_b = make_org(client, owner_b, "Org B")
    add(client, owner_b, org_b["id"], person("only-b@example.com"), "member")

    assert log(client, owner_b, org_a["id"]).status_code == 404  # not even confirmed to exist
    assert actions(client, owner_a, org_a["id"]) == ["org.created"]
    assert actions(client, owner_b, org_b["id"]) == ["org.created", "member.added"]


# ---------- paging and filtering ----------


def make_busy_org(client: TestClient, person: PersonFactory, teams: int) -> tuple[Person, str]:
    owner = person("owner@example.com")
    org = make_org(client, owner)
    for n in range(teams):
        assert make_team(client, owner, org["id"], f"Team {n}").status_code == 201
    return owner, org["id"]


def test_pages_cover_everything_once_newest_first(
    client: TestClient, person: PersonFactory
) -> None:
    owner, org_id = make_busy_org(client, person, teams=6)  # 7 entries with org.created
    seen: list[str] = []
    before: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": 3}
        if before:
            params["before"] = before
        body = log(client, owner, org_id, **params).json()
        seen += [e["id"] for e in body["items"]]
        pages += 1
        before = body["next_before"]
        if before is None:
            break
    assert pages == 3 and len(seen) == 7 and len(set(seen)) == 7
    everything = entries(client, owner, org_id)
    assert [e["id"] for e in everything] == seen
    assert [e["details"].get("name") for e in everything][:2] == [
        "Team 5",
        "Team 4",
    ]  # newest first


def test_a_full_last_page_has_no_next_marker(client: TestClient, person: PersonFactory) -> None:
    owner, org_id = make_busy_org(client, person, teams=2)  # 3 entries
    assert log(client, owner, org_id, limit=3).json()["next_before"] is None
    assert log(client, owner, org_id, limit=2).json()["next_before"] is not None


def test_filtering_by_action(client: TestClient, person: PersonFactory) -> None:
    owner, org_id = make_busy_org(client, person, teams=3)
    teams = entries(client, owner, org_id, action="team.created")
    assert len(teams) == 3 and {e["action"] for e in teams} == {"team.created"}
    assert entries(client, owner, org_id, action="no.such.thing") == []


def test_bad_paging_input_is_refused(client: TestClient, person: PersonFactory) -> None:
    owner, org_id = make_busy_org(client, person, teams=1)
    assert log(client, owner, org_id, limit=0).status_code == 422
    assert log(client, owner, org_id, limit=101).status_code == 422
    assert log(client, owner, org_id, before="not-a-uuid").status_code == 422
    assert log(client, owner, org_id, before=str(uuid.uuid4())).status_code == 400


def test_a_page_marker_from_another_organization_is_refused(
    client: TestClient, person: PersonFactory
) -> None:
    owner_a, owner_b = person("a@example.com"), person("b@example.com")
    org_a, org_b = make_org(client, owner_a, "Org A"), make_org(client, owner_b, "Org B")
    foreign = entries(client, owner_b, org_b["id"])[0]["id"]
    assert log(client, owner_a, org_a["id"], before=foreign).status_code == 400


def test_there_is_no_way_to_change_or_delete_entries(
    client: TestClient, person: PersonFactory
) -> None:
    owner = person("owner@example.com")
    org = make_org(client, owner)
    entry = entries(client, owner, org["id"])[0]
    url = f"{API}/orgs/{org['id']}/audit-log/{entry['id']}"
    for method in ("put", "patch", "delete"):
        assert client.request(method, url, headers=owner.headers).status_code in (404, 405)
    collection = f"{API}/orgs/{org['id']}/audit-log"
    for method in ("post", "put", "patch", "delete"):
        assert client.request(method, collection, headers=owner.headers).status_code == 405


# ---------- the recorder itself ----------


def test_the_recorder_keeps_details_short_and_stores_the_request_id(
    client: TestClient, person: PersonFactory, db: Session
) -> None:
    owner = person("owner@example.com")
    org_id = uuid.UUID(make_org(client, owner)["id"])
    token = REQUEST_ID.set("req-unit-0001")
    try:
        record_audit(
            db,
            org_id=org_id,
            actor_id=owner.id,
            action="test.big",
            details={"blob": "x" * 5000},
        )
        record_audit(db, org_id=org_id, actor_id=None, action="test.system", target_id=123)
        db.commit()
    finally:
        REQUEST_ID.reset(token)
    big = db.scalar(select(AuditLog).where(AuditLog.action == "test.big"))
    system = db.scalar(select(AuditLog).where(AuditLog.action == "test.system"))
    assert big is not None and big.details == {"truncated": True}
    assert big.request_id == "req-unit-0001"
    assert system is not None and system.actor_id is None and system.target_id == "123"
