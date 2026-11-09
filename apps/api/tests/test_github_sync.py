from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Commit, GithubInstallation, PullRequest
from app.services.github.sync import STALE_AFTER, begin_sync
from tests.conftest import World
from tests.github_helpers import (
    INSTALLATION_ID,
    FakeGitHub,
    connect,
    make_commit,
    make_pr,
)

API = "/api/v1"


def installation(client: TestClient, w: World) -> dict[str, Any]:
    res = client.get(f"{API}/orgs/{w.org_id}/github", headers=w.owner.headers)
    inst: dict[str, Any] = res.json()["installations"][0]
    return inst


def resync(client: TestClient, w: World) -> dict[str, Any]:
    pk = installation(client, w)["id"]
    res = client.post(
        f"{API}/orgs/{w.org_id}/github/installations/{pk}/sync", headers=w.owner.headers
    )
    assert res.status_code == 202, res.text
    return installation(client, w)


def repos(client: TestClient, w: World) -> dict[str, dict[str, Any]]:
    res = client.get(f"{API}/orgs/{w.org_id}/repos", headers=w.owner.headers)
    return {r["full_name"]: r for r in res.json()}


def overview(client: TestClient, w: World) -> dict[str, Any]:
    res = client.get(f"{API}/orgs/{w.org_id}/overview", headers=w.owner.headers)
    body: dict[str, Any] = res.json()
    return body


def connected(client: TestClient, w: World, fake: FakeGitHub) -> None:
    assert connect(client, fake, w.owner.headers, w.org_id).status_code == 200


# ---------- what a full sync stores ----------


def test_full_sync_stores_everything_the_dashboard_needs(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    connected(client, world, fake_github)

    r = repos(client, world)
    api_repo, web_repo = r["octo-org/api"], r["octo-org/web"]
    assert api_repo["open_pull_requests"] == 2  # PR #3 is closed
    assert api_repo["open_issues"] == 1  # the PR that shows up in the issues API is not an issue
    assert api_repo["ci"] == "passing" and web_repo["ci"] == "failing"
    assert api_repo["language"] == "Python" and web_repo["language"] == "TypeScript"
    assert api_repo["last_commit_at"] is not None

    ov = overview(client, world)
    assert ov["repositories"] == 2 and ov["open_pull_requests"] == 2 and ov["open_issues"] == 1
    assert ov["ci"] == {"passing": 1, "failing": 1, "running": 0, "other": 0, "none": 0}
    assert ov["recent_commits"][0]["message"] == "Update deps"  # newest first
    assert ov["recent_commits"][0]["repository"] == "octo-org/web"


def test_commit_message_is_reduced_to_its_headline(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    fake_github.data["octo-org/api"]["commits"].append(
        make_commit("e" * 40, date="2026-11-09T00:00:00Z")
    )
    connected(client, world, fake_github)
    assert overview(client, world)["recent_commits"][0]["message"] == "Fix bug"


def test_resync_is_idempotent(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    connected(client, world, fake_github)
    with session_factory() as db:
        before = db.scalar(select(func.count()).select_from(PullRequest))
    resync(client, world)
    resync(client, world)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PullRequest)) == before


def test_changes_on_github_are_picked_up(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    connected(client, world, fake_github)
    d = fake_github.data["octo-org/api"]
    d["pulls_open"] = [make_pr(2, draft=True), make_pr(5)]  # #1 closed, #5 opened
    d["pulls_closed"] = [make_pr(1, "closed", merged=True), make_pr(3, "closed", merged=True)]
    resync(client, world)
    assert repos(client, world)["octo-org/api"]["open_pull_requests"] == 2


def test_open_item_missing_from_a_complete_listing_is_closed(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    connected(client, world, fake_github)
    # PR #2 vanished from the open list and isn't in the recent-closed list either
    fake_github.data["octo-org/api"]["pulls_open"] = [make_pr(1)]
    resync(client, world)
    assert repos(client, world)["octo-org/api"]["open_pull_requests"] == 1


def test_repo_removed_from_installation_is_deleted_with_its_data(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    connected(client, world, fake_github)
    fake_github.repos[INSTALLATION_ID] = [
        r for r in fake_github.repos[INSTALLATION_ID] if r["full_name"] != "octo-org/web"
    ]
    resync(client, world)
    assert set(repos(client, world)) == {"octo-org/api"}
    with session_factory() as db:
        assert (
            db.scalar(select(func.count()).select_from(Commit).where(Commit.sha == "c" * 40)) == 0
        )


def test_empty_repository_is_not_an_error(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    fake_github.data["octo-org/web"]["empty"] = True  # commits endpoint answers 409
    connected(client, world, fake_github)
    inst = installation(client, world)
    assert inst["sync_status"] == "idle" and inst["sync_error"] is None


# ---------- failure handling ----------


def test_rate_limit_marks_sync_failed_with_a_clear_message(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    fake_github.fail["/repos/octo-org/web/pulls"] = (
        403,
        {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1893456000"},
    )
    connected(client, world, fake_github)
    inst = installation(client, world)
    assert inst["sync_status"] == "failed" and "rate limit" in inst["sync_error"].lower()
    assert set(repos(client, world)) == {"octo-org/api", "octo-org/web"}  # the repo list is kept


def test_one_broken_repo_does_not_fail_the_whole_sync(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    fake_github.fail["/repos/octo-org/web/pulls"] = (500, {})
    connected(client, world, fake_github)
    inst = installation(client, world)
    assert inst["sync_status"] == "idle"
    assert "1 of 2" in inst["sync_error"]
    assert repos(client, world)["octo-org/api"]["open_pull_requests"] == 2


def test_installation_deleted_on_github_is_reported(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    connected(client, world, fake_github)
    fake_github.installations.pop(INSTALLATION_ID)
    inst = resync(client, world)
    assert inst["sync_status"] == "failed" and "not found on GitHub" in inst["sync_error"]


# ---------- the sync lock ----------


def test_only_one_sync_can_hold_the_slot(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    connected(client, world, fake_github)
    with session_factory() as db:
        pk = db.scalar(select(GithubInstallation.id))
        assert begin_sync(db, pk) is True
        assert begin_sync(db, pk) is False  # already running

        stale = datetime.now(UTC) - STALE_AFTER - timedelta(minutes=1)
        db.execute(update(GithubInstallation).values(sync_started_at=stale))
        db.commit()
        assert begin_sync(db, pk) is True  # crashed worker's lock is taken over
