import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Commit, Issue, PullRequest, PullRequestReview, Repository, ReviewFinding
from app.services.github.client import GitHubClient
from tests.ci_helpers import CiEnv, make_ci_env
from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub

API = "/api/v1"
PersonFactory = Callable[[str], Person]
NOW = datetime.now(UTC)


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> CiEnv:
    return make_ci_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def repos(env: CiEnv) -> list[Repository]:
    with env.factory() as db:
        rows = list(db.scalars(select(Repository).order_by(Repository.full_name)))
        for r in rows:
            db.expunge(r)
        return rows


def get(env: CiEnv, path: str, *, who: Person | None = None, **params: Any) -> Any:
    return env.client.get(
        f"{API}/orgs/{env.world.org_id}{path}",
        params=params,
        headers=(who or env.world.owner).headers,
    )


def ok(env: CiEnv, path: str, **params: Any) -> Any:
    res = get(env, path, **params)
    assert res.status_code == 200, res.text
    return res.json()


# ---------- repository list ----------


def test_the_repository_list_names_owner_and_description(env: CiEnv) -> None:
    rows = {r["id"]: r for r in ok(env, "/repos")}
    for repo in repos(env):
        shown = rows[str(repo.id)]
        assert shown["owner"] == repo.owner_login and shown["description"] == repo.description
        assert shown["full_name"] == f"{repo.owner_login}/{repo.name}"


# ---------- commits ----------


def seed_commits(env: CiEnv, repo: Repository, n: int, tag: str) -> None:
    with env.factory() as db:
        db.execute(delete(Commit).where(Commit.repo_id == repo.id))
        for i in range(n):
            db.add(
                Commit(
                    repo_id=repo.id,
                    sha=f"{tag}{i:039d}"[:40],
                    message_headline=f"{tag} commit {i}",
                    author_login="ada" if i % 2 == 0 else None,
                    author_name="Grace" if i % 2 else None,
                    committed_at=NOW - timedelta(hours=i),
                )
            )
        db.commit()


def test_commits_are_per_repository_newest_first_and_paged(env: CiEnv) -> None:
    a, b = repos(env)[:2]
    seed_commits(env, a, 5, "a")
    seed_commits(env, b, 2, "b")
    full = ok(env, f"/repos/{a.id}/commits")
    assert [c["message"] for c in full] == [f"a commit {i}" for i in range(5)]  # newest first
    assert {c["repository"] for c in full} == {a.full_name}
    assert full[0]["author"] == "ada" and full[1]["author"] == "Grace"  # falls back to the name
    assert [c["message"] for c in ok(env, f"/repos/{a.id}/commits", limit=2, offset=1)] == [
        "a commit 1",
        "a commit 2",
    ]
    assert [c["message"] for c in ok(env, f"/repos/{b.id}/commits")] == ["b commit 0", "b commit 1"]
    assert ok(env, f"/repos/{a.id}/commits", offset=50) == []


def test_commit_listing_is_validated_and_scoped(env: CiEnv, person: PersonFactory) -> None:
    (repo,) = repos(env)[:1]
    bad_queries: list[dict[str, Any]] = [{"limit": 0}, {"limit": 101}, {"offset": -1}]
    for bad in bad_queries:
        assert get(env, f"/repos/{repo.id}/commits", **bad).status_code == 422
    assert get(env, f"/repos/{uuid.uuid4()}/commits").status_code == 404

    mallory = person("mallory@example.com")
    other = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(
        f"{API}/orgs/{other['id']}/repos/{repo.id}/commits", headers=mallory.headers
    )
    assert res.status_code == 404  # our repository, their organization
    assert get(env, f"/repos/{repo.id}/commits", who=mallory).status_code == 404
    assert (
        env.client.get(f"{API}/orgs/{env.world.org_id}/repos/{repo.id}/commits").status_code == 401
    )


# ---------- issues ----------


def seed_issues(
    env: CiEnv, repo: Repository, titles: list[tuple[str, str]], start: int = 1000
) -> None:
    with env.factory() as db:
        db.execute(delete(Issue).where(Issue.repo_id == repo.id))
        for i, (title, state) in enumerate(titles):
            db.add(
                Issue(
                    repo_id=repo.id,
                    number=start + i,
                    title=title,
                    state=state,
                    author_login="ada",
                    html_url=f"https://github.com/x/y/issues/{start + i}",
                    comments=i,
                    gh_created_at=NOW - timedelta(days=10),
                    gh_updated_at=NOW - timedelta(hours=i),
                )
            )
        db.commit()


def test_issues_can_be_filtered_by_repository_and_state(env: CiEnv) -> None:
    a, b = repos(env)[:2]
    seed_issues(
        env, a, [("Crash on login", "open"), ("Typo in docs", "closed"), ("Slow search", "open")]
    )
    seed_issues(env, b, [("Other repo bug", "open")], start=2000)
    assert [i["title"] for i in ok(env, "/issues", repo_id=str(a.id))] == [
        "Crash on login",
        "Slow search",
    ]
    closed = ok(env, "/issues", repo_id=str(a.id), state="closed")
    assert [i["title"] for i in closed] == ["Typo in docs"] and closed[0]["state"] == "closed"
    assert len(ok(env, "/issues", repo_id=str(a.id), state="all")) == 3
    assert "Other repo bug" in [i["title"] for i in ok(env, "/issues")]  # across the organization
    first = ok(env, "/issues", repo_id=str(a.id))[0]
    assert first["repository"] == a.full_name and first["comments"] == 0
    assert first["html_url"].startswith("https://") and first["created_at"] and first["updated_at"]


def test_issue_search_ignores_case_and_treats_wildcards_literally(env: CiEnv) -> None:
    (a,) = repos(env)[:1]
    seed_issues(
        env, a, [("Crash on LOGIN", "open"), ("Reaches 100% CPU", "open"), ("Other", "open")]
    )
    assert [i["title"] for i in ok(env, "/issues", repo_id=str(a.id), q="login")] == [
        "Crash on LOGIN"
    ]
    assert [i["title"] for i in ok(env, "/issues", repo_id=str(a.id), q="100%")] == [
        "Reaches 100% CPU"
    ]
    assert ok(env, "/issues", repo_id=str(a.id), q="%") != ok(env, "/issues", repo_id=str(a.id))
    assert len(ok(env, "/issues", repo_id=str(a.id), q="%")) == 1  # only the title that has a %
    assert ok(env, "/issues", repo_id=str(a.id), q="   ") == ok(env, "/issues", repo_id=str(a.id))


def test_issues_are_paged_and_validated(env: CiEnv) -> None:
    (a,) = repos(env)[:1]
    seed_issues(env, a, [(f"Issue {i}", "open") for i in range(5)])
    page = ok(env, "/issues", repo_id=str(a.id), limit=2, offset=2)
    assert [i["title"] for i in page] == ["Issue 2", "Issue 3"]
    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"state": "weird"}, {"q": "x" * 101}):
        assert get(env, "/issues", **bad).status_code == 422


def test_issues_never_cross_organizations(env: CiEnv, person: PersonFactory) -> None:
    (a,) = repos(env)[:1]
    seed_issues(env, a, [("Secret roadmap", "open")])
    mallory = person("mallory@example.com")
    other = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(
        f"{API}/orgs/{other['id']}/issues", params={"repo_id": str(a.id)}, headers=mallory.headers
    )
    assert res.status_code == 200 and res.json() == []
    assert get(env, "/issues", who=mallory).status_code == 404
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/issues").status_code == 401


# ---------- pull requests ----------


def seed_prs(env: CiEnv, repo: Repository, titles: list[str], start: int = 500) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    with env.factory() as db:
        db.execute(delete(PullRequest).where(PullRequest.repo_id == repo.id))
        for i, title in enumerate(titles):
            pr = PullRequest(
                repo_id=repo.id,
                number=start + i,
                title=title,
                state="open",
                draft=False,
                merged=False,
                author_login="ada",
                html_url=f"https://github.com/x/y/pull/{start + i}",
                gh_created_at=NOW - timedelta(days=2),
                gh_updated_at=NOW - timedelta(hours=i),
            )
            db.add(pr)
            db.flush()
            ids.append(pr.id)
        db.commit()
    return ids


def test_pull_requests_can_be_filtered_searched_and_paged(env: CiEnv) -> None:
    a, b = repos(env)[:2]
    seed_prs(env, a, ["Fix login redirect", "Add dark mode", "Bump deps"])
    seed_prs(env, b, ["Other repo change"], start=900)
    mine = ok(env, "/pull-requests", repo_id=str(a.id))
    assert [p["title"] for p in mine] == ["Fix login redirect", "Add dark mode", "Bump deps"]
    assert {p["repository_id"] for p in mine} == {str(a.id)}
    assert [p["title"] for p in ok(env, "/pull-requests", repo_id=str(a.id), q="DARK")] == [
        "Add dark mode"
    ]
    page = ok(env, "/pull-requests", repo_id=str(a.id), limit=1, offset=1)
    assert [p["title"] for p in page] == ["Add dark mode"]
    assert "Other repo change" in [p["title"] for p in ok(env, "/pull-requests")]
    assert get(env, "/pull-requests", offset=-1).status_code == 422
    assert get(env, "/pull-requests", q="x" * 101).status_code == 422


def test_one_pull_request_comes_with_its_review_summary(env: CiEnv, person: PersonFactory) -> None:
    (a,) = repos(env)[:1]
    (pr_id,) = seed_prs(env, a, ["Fix login redirect"])
    assert ok(env, f"/pull-requests/{pr_id}")["review"] is None
    with env.factory() as db:
        review = PullRequestReview(
            pr_id=pr_id,
            status="ready",
            run_id=uuid.uuid4(),
            queued_at=NOW,
            finished_at=NOW,
            risk="high",
        )
        db.add(review)
        db.flush()
        for severity in ("critical", "low"):
            db.add(
                ReviewFinding(
                    review_id=review.id, file_path="a.py", category="bug", severity=severity,
                    confidence="high", title="t", explanation="e", origin="ai", status="open",
                )
            )  # fmt: skip
        db.commit()
    shown = ok(env, f"/pull-requests/{pr_id}")
    assert shown["title"] == "Fix login redirect" and shown["repository"] == a.full_name
    assert shown["review"]["status"] == "ready" and shown["review"]["risk"] == "high"
    assert (shown["review"]["open_findings"], shown["review"]["serious_findings"]) == (2, 1)

    assert get(env, f"/pull-requests/{uuid.uuid4()}").status_code == 404
    mallory = person("mallory@example.com")
    other = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(f"{API}/orgs/{other['id']}/pull-requests/{pr_id}", headers=mallory.headers)
    assert res.status_code == 404
