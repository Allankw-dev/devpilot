from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.models import Repository, WebhookDelivery
from app.main import app
from tests.conftest import World
from tests.github_helpers import (
    INSTALLATION_ID,
    FakeGitHub,
    connect,
    make_issue,
    make_pr,
    make_repo,
    make_run,
    post_hook,
)

API = "/api/v1"
REPO = {"id": 101, "full_name": "octo-org/api"}


def base(**extra: Any) -> dict[str, Any]:
    return {"installation": {"id": INSTALLATION_ID}, "repository": REPO, **extra}


def overview(client: TestClient, w: World) -> dict[str, Any]:
    body: dict[str, Any] = client.get(
        f"{API}/orgs/{w.org_id}/overview", headers=w.owner.headers
    ).json()
    return body


def repos(client: TestClient, w: World) -> dict[str, dict[str, Any]]:
    res = client.get(f"{API}/orgs/{w.org_id}/repos", headers=w.owner.headers)
    return {r["full_name"]: r for r in res.json()}


def ready(client: TestClient, w: World, fake: FakeGitHub) -> None:
    assert connect(client, fake, w.owner.headers, w.org_id).status_code == 200


# ---------- signature and request validation ----------


def test_ping_with_valid_signature(client: TestClient) -> None:
    res = post_hook(client, "ping", {"zen": "Keep it logically awesome."})
    assert res.status_code == 200 and res.json() == {"status": "pong"}


def test_wrong_secret_is_rejected(client: TestClient) -> None:
    assert post_hook(client, "ping", {}, secret="not-the-secret").status_code == 401


def test_missing_or_malformed_signature_is_rejected(client: TestClient) -> None:
    assert post_hook(client, "ping", {}, signature="sha256=").status_code == 401
    assert post_hook(client, "ping", {}, signature="deadbeef").status_code == 401
    res = client.post(
        f"{API}/webhooks/github",
        json={},
        headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "d"},
    )
    assert res.status_code == 401


def test_signature_must_cover_the_exact_body(client: TestClient) -> None:
    import hashlib
    import hmac

    signed = b'{"zen": "original"}'
    sig = "sha256=" + hmac.new(b"whsec-test", signed, hashlib.sha256).hexdigest()
    res = post_hook(client, "ping", {}, raw=b'{"zen": "tampered"}', signature=sig)
    assert res.status_code == 401


def test_unsigned_requests_are_never_recorded(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    post_hook(client, "ping", {}, secret="wrong", delivery="evil-1")
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(WebhookDelivery)) == 0


def test_unconfigured_secret_refuses_everything(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    assert post_hook(client, "ping", {}).status_code == 503


def test_bad_requests_after_a_valid_signature(client: TestClient) -> None:
    assert post_hook(client, "ping", {}, headers={"X-GitHub-Event": ""}).status_code == 400
    assert post_hook(client, "ping", {}, raw=b"not json").status_code == 400
    assert post_hook(client, "ping", {}, raw=b"[1, 2]").status_code == 400


def test_redelivery_is_applied_once(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    ready(client, world, fake_github)
    payload = base(action="opened", pull_request=make_pr(7))
    first = post_hook(client, "pull_request", payload, delivery="dup-1")
    again = post_hook(client, "pull_request", payload, delivery="dup-1")
    assert first.json()["status"] == "pull request recorded"
    assert again.json()["status"] == "duplicate"
    with session_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(WebhookDelivery)
                .where(WebhookDelivery.delivery_id == "dup-1")
            )
            == 1
        )


# ---------- events ----------


def test_pull_request_lifecycle(client: TestClient, world: World, fake_github: FakeGitHub) -> None:
    ready(client, world, fake_github)
    assert overview(client, world)["open_pull_requests"] == 2

    post_hook(client, "pull_request", base(action="opened", pull_request=make_pr(7)))
    assert overview(client, world)["open_pull_requests"] == 3

    post_hook(
        client,
        "pull_request",
        base(action="closed", pull_request=make_pr(7, "closed", merged=True)),
    )
    assert overview(client, world)["open_pull_requests"] == 2


def test_issue_events(client: TestClient, world: World, fake_github: FakeGitHub) -> None:
    ready(client, world, fake_github)
    post_hook(client, "issues", base(action="opened", issue=make_issue(50)))
    assert overview(client, world)["open_issues"] == 2
    post_hook(client, "issues", base(action="closed", issue=make_issue(50, "closed")))
    assert overview(client, world)["open_issues"] == 1


def test_push_to_default_branch_records_commits(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    commit = {
        "id": "d" * 40,
        "message": "New work\n\nbody text",
        "timestamp": "2026-11-09T10:00:00Z",
        "url": "https://github.com/octo-org/api/commit/ddd",
        "author": {"name": "Octo", "username": "octo"},
    }
    res = post_hook(
        client, "push", base(ref="refs/heads/main", commits=[commit], head_commit=commit)
    )
    assert res.json()["status"] == "commits recorded"
    assert overview(client, world)["recent_commits"][0]["message"] == "New work"


def test_push_to_other_branches_is_ignored(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    commit = {"id": "f" * 40, "message": "wip", "timestamp": "2026-11-09T10:00:00Z", "author": {}}
    res = post_hook(client, "push", base(ref="refs/heads/feature-x", commits=[commit]))
    assert res.json()["status"] == "ignored: not the default branch"
    assert all(c["message"] != "wip" for c in overview(client, world)["recent_commits"])


def test_workflow_run_updates_ci_status(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    assert repos(client, world)["octo-org/api"]["ci"] == "passing"

    failing = make_run(50, conclusion="failure", created="2026-11-09T09:00:00Z")
    post_hook(client, "workflow_run", base(action="completed", workflow_run=failing))
    assert repos(client, world)["octo-org/api"]["ci"] == "failing"

    running = make_run(51, status="in_progress", conclusion=None, created="2026-11-09T10:00:00Z")
    post_hook(client, "workflow_run", base(action="requested", workflow_run=running))
    assert repos(client, world)["octo-org/api"]["ci"] == "running"


def test_default_branch_ci_wins_over_a_newer_feature_branch_run(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    feature = make_run(60, conclusion="failure", branch="feature-x", created="2026-11-09T12:00:00Z")
    post_hook(client, "workflow_run", base(action="completed", workflow_run=feature))
    assert repos(client, world)["octo-org/api"]["ci"] == "passing"


def test_repository_rename(client: TestClient, world: World, fake_github: FakeGitHub) -> None:
    ready(client, world, fake_github)
    renamed = make_repo(101, "octo-org/api-v2")
    post_hook(client, "repository", base(action="renamed", repository=renamed))
    assert "octo-org/api-v2" in repos(client, world)


def test_installation_repositories_event_triggers_a_sync(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    fake_github.add_repo(INSTALLATION_ID, make_repo(103, "octo-org/docs"))
    res = post_hook(
        client,
        "installation_repositories",
        {"action": "added", "installation": {"id": INSTALLATION_ID}},
    )
    assert res.json()["status"] == "sync scheduled"
    assert "octo-org/docs" in repos(client, world)


def test_installation_suspend_resume_and_delete(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    session_factory: sessionmaker[Session],
) -> None:
    ready(client, world, fake_github)
    inst = {"installation": {"id": INSTALLATION_ID}}

    post_hook(client, "installation", {"action": "suspend", **inst})
    status = client.get(f"{API}/orgs/{world.org_id}/github", headers=world.owner.headers).json()
    assert status["installations"][0]["suspended"] is True

    post_hook(client, "installation", {"action": "unsuspend", **inst})
    status = client.get(f"{API}/orgs/{world.org_id}/github", headers=world.owner.headers).json()
    assert status["installations"][0]["suspended"] is False

    post_hook(client, "installation", {"action": "deleted", **inst})
    status = client.get(f"{API}/orgs/{world.org_id}/github", headers=world.owner.headers).json()
    assert status["installations"] == []
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Repository)) == 0


def test_unknown_installation_and_repository_are_ignored(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    stranger = post_hook(
        client,
        "pull_request",
        {
            "action": "opened",
            "installation": {"id": 4242},
            "repository": REPO,
            "pull_request": make_pr(9),
        },
    )
    assert (
        stranger.status_code == 200 and stranger.json()["status"] == "ignored: unknown installation"
    )

    unknown_repo = post_hook(
        client,
        "pull_request",
        base(action="opened", repository={"id": 999, "full_name": "x/y"}, pull_request=make_pr(9)),
    )
    assert unknown_repo.json()["status"] == "ignored: unknown repository"
    assert overview(client, world)["open_pull_requests"] == 2


def test_unhandled_events_are_acknowledged(
    client: TestClient, world: World, fake_github: FakeGitHub
) -> None:
    ready(client, world, fake_github)
    res = post_hook(client, "star", base(action="created"))
    assert res.status_code == 200 and res.json()["status"] == "ignored: event not handled"
