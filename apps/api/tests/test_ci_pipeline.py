from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import CiAnalysis, LlmUsage
from app.services.ci.logs import WITHHELD
from app.services.ci.pipeline import (
    TransientCiError,
    claim_analysis,
    request_analysis,
)
from app.services.github.client import GitHubClient
from app.services.llm.errors import LLMAuthError, LLMRateLimited, LLMUnavailable
from tests.ci_helpers import (
    FAILED_RUN,
    SECRET,
    TIMED_OUT_RUN,
    CiEnv,
    analysis_json,
    make_ci_env,
)
from tests.conftest import World
from tests.github_helpers import FakeGitHub, make_job


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


# ---------- a whole analysis ----------


def test_analysis_runs_end_to_end_and_stores_everything(env: CiEnv) -> None:
    env.script(analysis_json())
    assert env.run() == "ready"

    a = env.analysis()
    assert a.status == "ready" and a.error is None and a.finished_at is not None
    assert a.category == "test_failure" and a.confidence == "high"
    assert a.summary and a.likely_cause and a.suggested_fix
    assert a.head_sha == "a" * 40 and a.model == "fake-model-v1"
    assert (a.jobs_total, a.jobs_analyzed) == (2, 2)  # the passing "docs" job is not counted
    assert (a.input_tokens, a.output_tokens) == (10, 5)
    assert a.failed_steps == [
        {"job": "test", "step": "Run tests"},
        {"job": "lint", "step": "Run ruff"},
    ]
    assert a.evidence == [{"job": "test", "quote": "E KeyError: 'session'"}]
    assert "Read the logs of 2 of 2 failed jobs." in (a.notes or "")


def test_the_model_sees_cleaned_logs_of_failed_jobs_only(env: CiEnv) -> None:
    env.script(analysis_json())
    env.run()
    prompt = env.prompt()
    assert "KeyError: 'session'" in prompt and "F401" in prompt
    assert "2026-11-16T09:00" not in prompt and "\x1b[" not in prompt  # timestamps and colours gone
    assert 'label="log of job docs"' not in prompt  # it passed
    assert "Repository: octo-org/web" in prompt and "Workflow: CI" in prompt


def test_usage_is_recorded_against_the_ci_feature(env: CiEnv, session_factory: sessionmaker[Session]) -> None:
    env.script(analysis_json())
    env.run()
    with session_factory() as db:
        row = db.scalars(select(LlmUsage).where(LlmUsage.feature == "ci")).one()
    assert row.operation == "structured" and row.org_id is not None and row.status == "ok"


# ---------- credentials ----------


def test_credential_looking_log_lines_never_reach_the_model(env: CiEnv) -> None:
    env.script(analysis_json())
    env.run()
    prompt = env.prompt()
    assert SECRET not in prompt and WITHHELD in prompt
    assert "1 line that looked like credentials were withheld" in (env.analysis().notes or "")


def test_the_github_token_is_not_sent_to_the_log_download_host(env: CiEnv) -> None:
    env.script(analysis_json())
    env.run()
    assert env.fake.log_auth and all(h is None for h in env.fake.log_auth)


# ---------- logs that can't be read ----------


def test_one_missing_log_is_reported_but_the_rest_is_still_analyzed(env: CiEnv) -> None:
    del env.fake.data["octo-org/web"]["job_logs"][202]  # expired
    env.script(analysis_json(evidence=[]))
    assert env.run() == "ready"
    a = env.analysis()
    assert (a.jobs_total, a.jobs_analyzed) == (2, 1)
    assert "No log for: lint (log expired or removed)." in (a.notes or "")
    assert 'label="log of job lint"' not in env.prompt()


def test_no_readable_log_at_all_fails_clearly_without_spending_tokens(env: CiEnv) -> None:
    env.fake.data["octo-org/web"]["job_logs"].clear()
    assert env.run() == "failed"
    a = env.analysis()
    assert a.status == "failed" and "No log could be read" in (a.error or "")
    assert env.generation.requests == []


def test_an_empty_log_counts_as_missing(env: CiEnv) -> None:
    env.set_log(201, "\n\n")
    env.set_log(202, "")
    assert env.run() == "failed" and "the log is empty" in (env.analysis().error or "")


def test_a_run_with_no_failed_jobs_explains_why(env: CiEnv) -> None:
    env.set_jobs(FAILED_RUN, make_job(203, "docs", conclusion="success", failed_step=None))
    assert env.run() == "failed"
    assert "no failed jobs" in (env.analysis().error or "").lower()
    assert env.generation.requests == []


def test_only_the_configured_number_of_jobs_is_read(env: CiEnv) -> None:
    capped = env.settings.model_copy(update={"ci_max_jobs": 1})
    env.script(analysis_json(evidence=[]))
    assert env.run(settings=capped) == "ready"
    a = env.analysis()
    assert (a.jobs_total, a.jobs_analyzed) == (2, 1)
    assert "1 more failed job over the limit." in (a.notes or "")
    assert "log of job lint" not in env.prompt()


def test_a_timed_out_run_can_be_analyzed_too(env: CiEnv) -> None:
    env.set_jobs(TIMED_OUT_RUN, make_job(401, "slow", conclusion="timed_out", failed_step="Run e2e"))
    env.set_log(401, "e2e: waiting for server\nERROR: The operation was canceled.\n")
    env.script(analysis_json(category="flaky_or_timeout", evidence=[]))
    assert env.run(run=TIMED_OUT_RUN) == "ready"
    assert env.analysis(TIMED_OUT_RUN).category == "flaky_or_timeout"


# ---------- checking the model ----------


def test_invented_quotes_never_reach_the_stored_analysis(env: CiEnv) -> None:
    env.script(
        analysis_json(
            confidence="high",
            evidence=[
                {"job": "test", "quote": "AssertionError: totally made up"},
                {"job": "lint", "quote": "F401 `os` imported but unused"},
            ],
        )
    )
    env.run()
    a = env.analysis()
    assert a.evidence == [{"job": "lint", "quote": "F401 `os` imported but unused"}]
    assert a.confidence == "high"  # one real quote remains


def test_high_confidence_with_only_invented_quotes_becomes_medium(env: CiEnv) -> None:
    env.script(analysis_json(confidence="high", evidence=[{"job": "test", "quote": "not in the log"}]))
    env.run()
    a = env.analysis()
    assert a.evidence == [] and a.confidence == "medium"


# ---------- failures and retries ----------


def test_a_rate_limited_model_is_retried_later(env: CiEnv) -> None:
    env.generation.script = [LLMRateLimited("slow")] * 3
    analysis = env.request().analysis
    with pytest.raises(TransientCiError):
        env.run(analysis, final_attempt=False)
    a = env.analysis()
    assert a.status == "queued" and "Retrying automatically" in (a.error or "")


def test_on_the_final_attempt_a_transient_problem_becomes_a_clear_failure(env: CiEnv) -> None:
    env.generation.script = [LLMUnavailable("down")] * 3
    assert env.run(final_attempt=True) == "failed"
    a = env.analysis()
    assert a.status == "failed" and "Click Analyze to try again" in (a.error or "")


def test_a_bad_api_key_fails_without_retrying(env: CiEnv) -> None:
    env.generation.script = [LLMAuthError("nope")]
    assert env.run(final_attempt=False) == "failed"
    assert "API key" in (env.analysis().error or "")


def test_github_being_down_is_retried(env: CiEnv) -> None:
    env.fake.fail["/actions/runs/"] = (503, {})
    analysis = env.request().analysis
    with pytest.raises(TransientCiError):
        env.run(analysis, final_attempt=False)
    assert env.analysis().status == "queued"


def test_missing_actions_permission_tells_the_user_what_to_check(env: CiEnv) -> None:
    env.fake.fail["/actions/runs/"] = (403, {})
    assert env.run() == "failed"
    assert "Actions: read" in (env.analysis().error or "")


def test_a_suspended_installation_is_not_analyzed(env: CiEnv, session_factory: sessionmaker[Session]) -> None:
    from app.db.models import GithubInstallation

    with session_factory() as db:
        db.execute(update(GithubInstallation).values(suspended_at=datetime.now(UTC)))
        db.commit()
    assert env.run() == "failed" and "suspended" in (env.analysis().error or "")
    assert env.generation.requests == []


def test_an_unexpected_crash_ends_as_a_failure_not_a_stuck_spinner(env: CiEnv) -> None:
    env.generation.script = [RuntimeError("boom")]
    assert env.run() == "failed"
    assert "Unexpected error" in (env.analysis().error or "")


# ---------- running twice, and asking again ----------


def test_a_duplicate_delivery_does_nothing(env: CiEnv) -> None:
    env.script(analysis_json(), analysis_json())
    analysis = env.request().analysis
    assert env.run(analysis) == "ready"
    assert env.run(analysis) == "skipped"
    assert len(env.generation.requests) == 1


def test_a_job_that_is_running_elsewhere_is_busy_until_its_heartbeat_goes_stale(
    env: CiEnv, session_factory: sessionmaker[Session]
) -> None:
    analysis = env.request().analysis
    with session_factory() as db:
        assert claim_analysis(db, analysis.id, analysis.run_id)  # another worker starts it
        assert not claim_analysis(db, analysis.id, analysis.run_id)
    assert env.run(analysis) == "busy"

    with session_factory() as db:
        db.execute(update(CiAnalysis).values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=30)))
        db.commit()
    env.script(analysis_json())
    assert env.run(analysis) == "ready"  # the dead worker's job is taken over


def test_request_states(env: CiEnv, session_factory: sessionmaker[Session]) -> None:
    first = env.request()
    assert first.outcome == "created" and first.analysis.status == "queued"
    assert env.request().outcome == "active"  # already queued

    env.script(analysis_json())
    env.run(first.analysis)
    assert env.request().outcome == "cached"  # nothing changed on GitHub

    forced = env.request(force=True)
    assert forced.outcome == "created" and forced.analysis.id != first.analysis.id

    env.script(analysis_json())
    env.run(forced.analysis)
    env.touch_run()  # the run was re-run on GitHub
    assert env.request().outcome == "created"


def test_a_stale_queued_request_can_be_replaced(env: CiEnv, session_factory: sessionmaker[Session]) -> None:
    first = env.request()
    with session_factory() as db:
        db.execute(update(CiAnalysis).values(queued_at=datetime.now(UTC) - timedelta(hours=2)))
        db.commit()
    again = env.request()
    assert again.outcome == "created" and again.analysis.id != first.analysis.id


def test_request_analysis_for_a_deleted_run_raises(env: CiEnv, session_factory: sessionmaker[Session]) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.db.models import WorkflowRun

    with session_factory() as db:
        run = db.get(WorkflowRun, env.runs[FAILED_RUN])
        assert run is not None
        db.expunge(run)
        db.delete(db.get(WorkflowRun, env.runs[FAILED_RUN]))
        db.commit()
        # SQLite enforces the foreign key in tests (see conftest), so this must refuse.
        with pytest.raises(IntegrityError):
            request_analysis(db, run, None)
