import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Commit,
    Issue,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
)
from app.services.github.client import GitHubClient
from tests.ci_helpers import FAILED_RUN, CiEnv, analysis_json, make_ci_env
from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub

API = "/api/v1"
PersonFactory = Callable[[str], Person]


def get(client: TestClient, world: World, who: Person | None = None, **params: Any) -> Any:
    res = client.get(
        f"{API}/orgs/{world.org_id}/dashboard", params=params, headers=(who or world.owner).headers
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Any,
) -> CiEnv:
    return make_ci_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def test_an_org_with_no_github_gets_zeros_and_a_filled_in_calendar(
    client: TestClient, world: World
) -> None:
    data = get(client, world)
    assert data["github_connected"] is False and data["last_synced_at"] is None
    assert data["stats"] == {
        "repositories": 0,
        "open_pull_requests": 0,
        "open_issues": 0,
        "reviews_completed": 0,
        "ci_analyses_completed": 0,
        "failed_runs": 0,
    }
    assert len(data["activity"]) == 14 and all(
        d["commits"] == d["pull_requests_opened"] == 0 for d in data["activity"]
    )
    assert data["recent_pull_requests"] == data["recent_reviews"] == []
    assert data["recent_failed_runs"] == data["open_issues"] == []
    assert data["activity"][-1]["day"] == datetime.now(UTC).date().isoformat()


def test_a_connected_org_shows_what_github_actually_returned(
    env: CiEnv, session_factory: sessionmaker[Session]
) -> None:
    data = get(env.client, env.world)
    with session_factory() as db:
        repos = db.scalar(select(func.count()).select_from(Repository))
        open_prs = db.scalar(
            select(func.count()).select_from(PullRequest).where(PullRequest.state == "open")
        )
        open_issues = db.scalar(
            select(func.count()).select_from(Issue).where(Issue.state == "open")
        )
    assert data["github_connected"] is True and data["last_synced_at"] is not None
    assert repos is not None and repos > 0 and data["stats"]["repositories"] == repos
    assert data["stats"]["open_pull_requests"] == open_prs
    assert data["stats"]["open_issues"] == open_issues
    assert len(data["recent_pull_requests"]) == min(5, open_prs or 0)
    assert len(data["open_issues"]) == min(5, open_issues or 0)
    for pr in data["recent_pull_requests"]:
        assert pr["repository"] and pr["number"] and pr["html_url"].startswith("https://")


def test_failed_runs_are_listed_with_their_ai_analysis_status(env: CiEnv) -> None:
    data = get(env.client, env.world)
    runs = data["recent_failed_runs"]
    assert {r["conclusion"] for r in runs} == {"failure", "timed_out"}  # not success or running
    assert all(r["analysis_status"] is None for r in runs)

    env.script(analysis_json())
    env.run()
    data = get(env.client, env.world)
    by_id = {r["id"]: r for r in data["recent_failed_runs"]}
    assert by_id[str(env.runs[FAILED_RUN])]["analysis_status"] == "ready"
    assert data["stats"]["ci_analyses_completed"] == 1


def test_reviews_show_their_open_and_serious_finding_counts(
    env: CiEnv, session_factory: sessionmaker[Session]
) -> None:
    with session_factory() as db:
        pr = db.scalars(select(PullRequest).limit(1)).one()
        review = PullRequestReview(
            pr_id=pr.id,
            status="ready",
            run_id=uuid.uuid4(),
            queued_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db.add(review)
        db.flush()
        for severity, state in (
            ("critical", "open"),
            ("high", "open"),
            ("low", "open"),
            ("high", "dismissed"),
        ):
            db.add(
                ReviewFinding(
                    review_id=review.id,
                    file_path="a.py",
                    category="bug",
                    severity=severity,
                    confidence="high",
                    title="t",
                    explanation="e",
                    origin="ai",
                    status=state,
                )
            )
        db.commit()
    data = get(env.client, env.world)
    (shown,) = data["recent_reviews"]
    assert shown["status"] == "ready" and shown["pull_request_id"] == str(pr.id)
    assert (shown["open_findings"], shown["serious_findings"]) == (3, 2)  # dismissed one excluded
    assert data["stats"]["reviews_completed"] == 1


def test_activity_counts_commits_and_opened_pull_requests_per_utc_day(
    env: CiEnv, session_factory: sessionmaker[Session]
) -> None:
    three_days_ago = datetime.now(UTC) - timedelta(days=3)
    with session_factory() as db:
        repo = db.scalars(select(Repository).limit(1)).one()
        db.query(Commit).delete()
        for i in range(3):
            db.add(
                Commit(
                    repo_id=repo.id,
                    sha=f"{i:040d}",
                    message_headline="m",
                    committed_at=three_days_ago,
                )
            )
        db.add(
            Commit(
                repo_id=repo.id, sha="f" * 40, message_headline="old",
                committed_at=datetime.now(UTC) - timedelta(days=40),
            )
        )  # fmt: skip
        db.commit()
    data = get(env.client, env.world, days=7)
    by_day = {d["day"]: d for d in data["activity"]}
    assert len(by_day) == 7
    assert by_day[three_days_ago.date().isoformat()]["commits"] == 3
    assert sum(d["commits"] for d in data["activity"]) == 3  # the 40-day-old one is outside


def test_other_organizations_never_leak_into_the_dashboard(
    env: CiEnv, person: PersonFactory
) -> None:
    mallory = person("mallory@example.com")
    other = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(f"{API}/orgs/{other['id']}/dashboard", headers=mallory.headers)
    assert res.status_code == 200 and res.json()["stats"]["repositories"] == 0
    assert res.json()["recent_failed_runs"] == [] and res.json()["github_connected"] is False
    assert get(env.client, env.world)["stats"]["repositories"] > 0


def test_viewers_can_read_it_outsiders_cannot(env: CiEnv, person: PersonFactory) -> None:
    viewer = person("viewer@example.com")
    res = env.client.post(
        f"{API}/orgs/{env.world.org_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=env.world.owner.headers,
    )
    assert res.status_code in (200, 201)
    assert get(env.client, env.world, viewer)["github_connected"] is True

    url = f"{API}/orgs/{env.world.org_id}/dashboard"
    assert env.client.get(url, headers=person("outsider@example.com").headers).status_code == 404
    assert env.client.get(url).status_code == 401


@pytest.mark.parametrize("days", ["0", "91", "x"])
def test_the_period_is_validated(client: TestClient, world: World, days: str) -> None:
    res = client.get(
        f"{API}/orgs/{world.org_id}/dashboard", params={"days": days}, headers=world.owner.headers
    )
    assert res.status_code == 422
