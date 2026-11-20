import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import (
    CiAnalysis,
    PullRequest,
    PullRequestReview,
    Repository,
    ReviewFinding,
    WorkflowRun,
)
from app.services.github.client import GitHubClient
from tests.ci_helpers import (
    FAILED_RUN,
    RUNNING_RUN,
    SUCCEEDED_RUN,
    TIMED_OUT_RUN,
    CiEnv,
    make_ci_env,
)
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


def fresh_runs(env: CiEnv) -> None:
    """Keep only this test's four runs and make them recent, so the period always includes them."""
    with env.factory() as db:
        keep = [env.runs[r] for r in (FAILED_RUN, SUCCEEDED_RUN, TIMED_OUT_RUN, RUNNING_RUN)]
        db.execute(delete(WorkflowRun).where(WorkflowRun.id.not_in(keep)))
        db.execute(update(WorkflowRun).values(gh_created_at=NOW - timedelta(hours=1)))
        db.commit()


def data(client: TestClient, world: World, who: Person | None = None, **params: Any) -> Any:
    res = client.get(
        f"{API}/orgs/{world.org_id}/analytics", params=params, headers=(who or world.owner).headers
    )
    assert res.status_code == 200, res.text
    return res.json()


def add_review(
    env: CiEnv, *, ago: timedelta, took: timedelta, severities: list[str], status: str = "ready"
) -> None:
    with env.factory() as db:
        pr = db.scalars(select(PullRequest).limit(1)).first()
        if pr is None:
            repo = db.scalars(select(Repository).limit(1)).one()
            pr = PullRequest(
                repo_id=repo.id, number=77, title="t", state="open", draft=False, merged=False,
                html_url="https://github.com/x/y/pull/77",
            )  # fmt: skip
            db.add(pr)
            db.flush()
        finished = NOW - ago
        review = PullRequestReview(
            pr_id=pr.id, status=status, run_id=uuid.uuid4(), queued_at=finished - took,
            started_at=finished - took, finished_at=finished,
        )  # fmt: skip
        db.add(review)
        db.flush()
        for severity in severities:
            db.add(
                ReviewFinding(
                    review_id=review.id, file_path="a.py", category="bug", severity=severity,
                    confidence="high", title="t", explanation="e", origin="ai", status="open",
                )
            )  # fmt: skip
        db.commit()


def test_an_org_with_no_activity_gets_zeros_not_made_up_numbers(
    client: TestClient, world: World
) -> None:
    out = data(client, world)
    assert out["days"] == 30 and len(out["by_day"]) == 30
    assert out["reviews_finished"] == out["ci_analyses_finished"] == 0
    assert out["runs_succeeded"] == out["runs_failed"] == 0
    assert out["ci_success_rate"] is None  # no runs: there is no rate to report
    assert out["avg_review_seconds"] is None and out["avg_ci_analysis_seconds"] is None
    assert [s["severity"] for s in out["findings_by_severity"]] == [
        "critical",
        "high",
        "medium",
        "low",
        "info",
    ]
    assert all(s["count"] == 0 for s in out["findings_by_severity"])
    assert out["by_day"][-1]["day"] == NOW.date().isoformat()


def test_ci_runs_are_counted_by_outcome_and_the_success_rate_is_computed(env: CiEnv) -> None:
    fresh_runs(env)
    out = data(env.client, env.world)
    # the fake GitHub has one success, one failure, one timed out (and one still running)
    assert (out["runs_succeeded"], out["runs_failed"]) == (1, 2)
    assert out["ci_success_rate"] == round(1 / 3, 4)
    assert sum(d["runs_failed"] for d in out["by_day"]) == 2


def test_cancelled_runs_do_not_count_for_or_against_the_success_rate(
    env: CiEnv, session_factory: sessionmaker[Session]
) -> None:
    fresh_runs(env)
    with session_factory() as db:
        db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == env.runs[SUCCEEDED_RUN])
            .values(conclusion="cancelled")
        )
        db.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == env.runs[TIMED_OUT_RUN])
            .values(conclusion="success")
        )
        db.commit()
    out = data(env.client, env.world)
    assert (out["runs_succeeded"], out["runs_failed"]) == (1, 1) and out["ci_success_rate"] == 0.5


def test_findings_are_counted_by_severity_with_every_severity_present(env: CiEnv) -> None:
    add_review(
        env,
        ago=timedelta(hours=2),
        took=timedelta(seconds=40),
        severities=["critical", "high", "high", "low"],
    )
    out = data(env.client, env.world)
    assert {s["severity"]: s["count"] for s in out["findings_by_severity"]} == {
        "critical": 1,
        "high": 2,
        "medium": 0,
        "low": 1,
        "info": 0,
    }
    assert out["reviews_finished"] == 1 and out["by_day"][-1]["reviews_finished"] == 1


def test_average_times_use_finished_work_only_and_skip_unusable_rows(env: CiEnv) -> None:
    add_review(env, ago=timedelta(hours=1), took=timedelta(seconds=30), severities=[])
    add_review(env, ago=timedelta(hours=2), took=timedelta(seconds=90), severities=[])
    add_review(
        env, ago=timedelta(hours=3), took=timedelta(seconds=9999), severities=[], status="failed"
    )
    assert (
        data(env.client, env.world)["avg_review_seconds"] == 60
    )  # (30 + 90) / 2, failed one left out

    with env.factory() as db:
        a = CiAnalysis(
            workflow_run_id=env.runs[FAILED_RUN], status="ready", run_id=uuid.uuid4(),
            queued_at=NOW, started_at=NOW - timedelta(seconds=12), finished_at=NOW,
        )  # fmt: skip
        backwards = CiAnalysis(
            workflow_run_id=env.runs[TIMED_OUT_RUN], status="ready", run_id=uuid.uuid4(),
            queued_at=NOW, started_at=NOW, finished_at=NOW - timedelta(minutes=5),
        )  # fmt: skip
        db.add_all([a, backwards])
        db.commit()
    out = data(env.client, env.world)
    assert (
        out["avg_ci_analysis_seconds"] == 12
    )  # the row that finished before it started is ignored
    assert out["ci_analyses_finished"] == 2


def test_work_outside_the_period_is_left_out(env: CiEnv) -> None:
    add_review(env, ago=timedelta(days=20), took=timedelta(seconds=10), severities=["high"])
    assert data(env.client, env.world, days=7)["reviews_finished"] == 0
    assert data(env.client, env.world, days=30)["reviews_finished"] == 1


def test_other_organizations_are_never_counted(env: CiEnv, person: PersonFactory) -> None:
    add_review(env, ago=timedelta(hours=1), took=timedelta(seconds=10), severities=["critical"])
    mallory = person("mallory@example.com")
    other = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(f"{API}/orgs/{other['id']}/analytics", headers=mallory.headers).json()
    assert (
        res["reviews_finished"] == 0 and res["runs_failed"] == 0 and res["ci_success_rate"] is None
    )
    assert (
        env.client.get(
            f"{API}/orgs/{env.world.org_id}/analytics", headers=mallory.headers
        ).status_code
        == 404
    )
    assert env.client.get(f"{API}/orgs/{env.world.org_id}/analytics").status_code == 401


def test_viewers_can_read_it_and_the_period_is_validated(env: CiEnv, person: PersonFactory) -> None:
    viewer = person("viewer@example.com")
    res = env.client.post(
        f"{API}/orgs/{env.world.org_id}/members",
        json={"email": viewer.email, "role": "viewer"},
        headers=env.world.owner.headers,
    )
    assert res.status_code in (200, 201)
    assert data(env.client, env.world, viewer)["days"] == 30
    for bad in ("0", "91", "x"):
        res = env.client.get(
            f"{API}/orgs/{env.world.org_id}/analytics",
            params={"days": bad},
            headers=env.world.owner.headers,
        )
        assert res.status_code == 422
