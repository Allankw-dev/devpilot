"""Shared setup for CI failure analysis tests."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm, get_llm_getter
from app.core.config import Settings, get_settings
from app.db.models import CiAnalysis, WorkflowRun
from app.main import app
from app.services.ci.pipeline import request_analysis, run_analysis
from app.services.github.client import GitHubClient
from app.services.llm import LLMService
from app.services.llm.usage import DbUsageRecorder
from tests.conftest import World
from tests.github_helpers import FakeGitHub, connect, make_job, make_run
from tests.llm_helpers import FakeProvider, reply

REPO = "octo-org/web"
SECRET = "AKIAIOSFODNN7EXAMPLE"

# run ids on "GitHub"
FAILED_RUN = 2
SUCCEEDED_RUN = 3
TIMED_OUT_RUN = 4
RUNNING_RUN = 5

PYTEST_LOG = "\n".join(
    [
        "2026-11-16T09:00:00.1000000Z ##[group]Run pytest -q",
        "2026-11-16T09:00:00.2000000Z pytest -q",
        "2026-11-16T09:00:00.3000000Z ##[endgroup]",
        "2026-11-16T09:00:05.0000000Z \x1b[31mFAILED\x1b[0m tests/test_login.py::test_cookie - KeyError: 'session'",
        "2026-11-16T09:00:05.1000000Z E   KeyError: 'session'",
        "2026-11-16T09:00:05.2000000Z ##[error]Process completed with exit code 1.",
    ]
)

LINT_LOG = "\n".join(
    [
        "2026-11-16T09:01:00.0000000Z ##[group]Run ruff check .",
        f"2026-11-16T09:01:00.5000000Z token = '{SECRET}'",
        "2026-11-16T09:01:01.0000000Z app/auth.py:12:5: F401 `os` imported but unused",
        "2026-11-16T09:01:01.1000000Z ##[error]Process completed with exit code 1.",
    ]
)


def analysis_json(
    *,
    summary: str = "The login test fails with a KeyError on the session.",
    category: str = "test_failure",
    cause: str = "The test reads session['session'] before the cookie is set.",
    fix: str = "Set the session cookie in the test fixture.",
    confidence: str = "high",
    evidence: list[dict[str, str]] | None = None,
    not_assessed: str = "",
) -> str:
    if evidence is None:
        evidence = [{"job": "test", "quote": "E   KeyError: 'session'"}]
    return json.dumps(
        {
            "summary": summary,
            "category": category,
            "likely_cause": cause,
            "suggested_fix": fix,
            "confidence": confidence,
            "evidence": evidence,
            "not_assessed": not_assessed,
        }
    )


@dataclass
class CiEnv:
    client: TestClient
    world: World
    fake: FakeGitHub
    github: GitHubClient
    factory: sessionmaker[Session]
    settings: Settings
    generation: FakeProvider
    llm: LLMService
    runs: dict[int, uuid.UUID]  # GitHub run id -> our id

    def script(self, *items: Any) -> None:
        self.generation.script = [reply(i) if isinstance(i, str) else i for i in items]

    def set_jobs(self, run: int, *jobs: dict[str, Any]) -> None:
        self.fake.data[REPO].setdefault("run_jobs", {})[run] = list(jobs)

    def set_log(self, job_id: int, text: str) -> None:
        self.fake.data[REPO].setdefault("job_logs", {})[job_id] = text

    def request(self, run: int = FAILED_RUN, *, force: bool = False) -> Any:
        with self.factory() as db:
            row = db.get(WorkflowRun, self.runs[run])
            assert row is not None
            req = request_analysis(db, row, None, force=force)
            db.expunge(req.analysis)
            return req

    def run(
        self,
        analysis: CiAnalysis | None = None,
        *,
        run: int = FAILED_RUN,
        final_attempt: bool = True,
        settings: Settings | None = None,
        llm: LLMService | None = None,
    ) -> str:
        analysis = analysis or self.request(run).analysis
        assert analysis.run_id is not None
        service = llm or self.llm
        return run_analysis(
            self.factory,
            self.github,
            lambda: service,
            settings or self.settings,
            analysis.id,
            analysis.run_id,
            final_attempt=final_attempt,
        )

    def analysis(self, run: int = FAILED_RUN) -> CiAnalysis:
        with self.factory() as db:
            row = db.scalars(
                select(CiAnalysis)
                .where(CiAnalysis.workflow_run_id == self.runs[run])
                .order_by(CiAnalysis.queued_at.desc())
                .limit(1)
            ).one()
            db.expunge(row)
            return row

    def prompt(self, call: int = 0) -> str:
        return self.generation.requests[call].messages[0].content

    def touch_run(self, run: int = FAILED_RUN) -> None:
        """Pretend the run changed on GitHub (what a re-run followed by a sync would record)."""
        with self.factory() as db:
            db.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == self.runs[run])
                .values(gh_updated_at=datetime.now(UTC))
            )
            db.commit()


def make_ci_env(
    client: TestClient,
    world: World,
    fake: FakeGitHub,
    gh_client: GitHubClient,
    factory: sessionmaker[Session],
    gh_settings: Settings,
    **overrides: Any,
) -> CiEnv:
    settings = gh_settings.model_copy(
        update={"gemini_api_key": SecretStr("k"), "gemini_model": "fake-model", **overrides}
    )
    fake.data[REPO]["runs"] = [
        make_run(FAILED_RUN, conclusion="failure"),
        make_run(SUCCEEDED_RUN, conclusion="success"),
        make_run(TIMED_OUT_RUN, conclusion="timed_out"),
        make_run(RUNNING_RUN, status="in_progress", conclusion=None),
    ]
    assert connect(client, fake, world.owner.headers, world.org_id).status_code == 200
    with factory() as db:
        runs = {r.run_id: r.id for r in db.scalars(select(WorkflowRun))}
    generation = FakeProvider()
    llm = LLMService(generation, recorder=DbUsageRecorder(factory), sleep=lambda _: None)
    env = CiEnv(client, world, fake, gh_client, factory, settings, generation, llm, runs)
    env.set_jobs(
        FAILED_RUN,
        make_job(201, "test", failed_step="Run tests"),
        make_job(202, "lint", failed_step="Run ruff"),
        make_job(203, "docs", conclusion="success", failed_step=None),
    )
    env.set_log(201, PYTEST_LOG)
    env.set_log(202, LINT_LOG)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: llm)
    return env
