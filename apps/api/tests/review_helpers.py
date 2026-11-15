"""Shared setup for pull request review tests."""

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
from app.db.models import PullRequest, PullRequestReview, ReviewFinding
from app.main import app
from app.services.github.client import GitHubClient
from app.services.llm import LLMService
from app.services.llm.usage import DbUsageRecorder
from app.services.review.pipeline import request_review, run_review
from tests.conftest import World
from tests.github_helpers import FakeGitHub, connect, make_pr_details, make_pr_file
from tests.llm_helpers import FakeProvider, reply

REPO = "octo-org/api"
SECRET = "AKIAIOSFODNN7EXAMPLE"

AUTH_PATCH = """@@ -10,6 +10,9 @@ def login(user, password):
     user = find(user)
-    ok = check(user, password)
+    ok = user.password == password
+    if ok:
+        session["user"] = user
     return ok
 
 def logout():"""

UTIL_PATCH = "@@ -0,0 +1,3 @@\n+def helper(x):\n+    return x\n+"


def finding(
    file: str = "app/auth.py",
    start: int = 11,
    end: int = 11,
    *,
    category: str = "security",
    severity: str = "high",
    confidence: str = "high",
    title: str = "Plain-text password comparison",
    explanation: str = "Passwords are compared as plain text.",
    suggestion: str = "Compare a salted hash instead.",
) -> dict[str, Any]:
    return {
        "file": file, "start_line": start, "end_line": end, "category": category,
        "severity": severity, "confidence": confidence, "title": title,
        "explanation": explanation, "suggestion": suggestion,
    }  # fmt: skip


def review_json(
    findings: list[dict[str, Any]] | None = None,
    summary: str = "Changes how login checks a password.",
    risk: str = "medium",
    not_assessed: str = "",
) -> str:
    return json.dumps(
        {"summary": summary, "risk": risk, "findings": findings or [], "not_assessed": not_assessed}
    )


@dataclass
class ReviewEnv:
    client: TestClient
    world: World
    fake: FakeGitHub
    github: GitHubClient
    factory: sessionmaker[Session]
    settings: Settings
    generation: FakeProvider
    llm: LLMService
    prs: dict[int, uuid.UUID]  # PR number -> id

    def set_pr(self, number: int = 1, **kw: Any) -> None:
        """Define what GitHub says about a pull request."""
        files = kw.pop("files", None)
        details = make_pr_details(number, **kw)
        self.fake.data[REPO].setdefault("pr_details", {})[number] = details
        if files is not None:
            self.fake.data[REPO].setdefault("pr_files", {})[number] = files

    def script(self, *items: Any) -> None:
        self.generation.script = [reply(i) if isinstance(i, str) else i for i in items]

    def request(self, number: int = 1, *, force: bool = False) -> Any:
        with self.factory() as db:
            pr = db.get(PullRequest, self.prs[number])
            assert pr is not None
            req = request_review(db, pr, None, force=force)
            db.expunge(req.review)
            return req

    def run(
        self,
        review: PullRequestReview | None = None,
        *,
        number: int = 1,
        final_attempt: bool = True,
        settings: Settings | None = None,
        llm: LLMService | None = None,
    ) -> str:
        review = review or self.request(number).review
        assert review.run_id is not None
        service = llm or self.llm
        return run_review(
            self.factory,
            self.github,
            lambda: service,
            settings or self.settings,
            review.id,
            review.run_id,
            final_attempt=final_attempt,
        )

    def review(self, number: int = 1) -> PullRequestReview:
        with self.factory() as db:
            row = db.scalars(
                select(PullRequestReview)
                .where(PullRequestReview.pr_id == self.prs[number])
                .order_by(PullRequestReview.queued_at.desc())
                .limit(1)
            ).one()
            db.expunge(row)
            return row

    def findings(self, number: int = 1) -> list[ReviewFinding]:
        with self.factory() as db:
            rows = list(
                db.scalars(
                    select(ReviewFinding)
                    .join(PullRequestReview, PullRequestReview.id == ReviewFinding.review_id)
                    .where(PullRequestReview.pr_id == self.prs[number])
                    .order_by(ReviewFinding.file_path, ReviewFinding.start_line)
                )
            )
            db.expunge_all()
            return rows

    def prompt(self, call: int = 0) -> str:
        return self.generation.requests[call].messages[0].content

    def touch_pr(self, number: int = 1) -> None:
        """Pretend the pull request changed on GitHub (what a sync would record)."""
        with self.factory() as db:
            db.execute(
                update(PullRequest)
                .where(PullRequest.id == self.prs[number])
                .values(gh_updated_at=datetime.now(UTC))
            )
            db.commit()


def make_review_env(
    client: TestClient,
    world: World,
    fake: FakeGitHub,
    gh_client: GitHubClient,
    factory: sessionmaker[Session],
    gh_settings: Settings,
    **overrides: Any,
) -> ReviewEnv:
    settings = gh_settings.model_copy(
        update={"gemini_api_key": SecretStr("k"), "gemini_model": "fake-model", **overrides}
    )
    assert connect(client, fake, world.owner.headers, world.org_id).status_code == 200
    with factory() as db:
        prs = {p.number: p.id for p in db.scalars(select(PullRequest))}
    generation = FakeProvider()
    llm = LLMService(generation, recorder=DbUsageRecorder(factory), sleep=lambda _: None)
    env = ReviewEnv(client, world, fake, gh_client, factory, settings, generation, llm, prs)
    env.set_pr(
        1,
        title="Switch login to session cookies",
        body="Replaces token auth with cookies.",
        files=[
            make_pr_file("app/auth.py", AUTH_PATCH, deletions=1),
            make_pr_file("app/util.py", UTIL_PATCH, status="added"),
            make_pr_file("package-lock.json", "@@ -1 +1 @@\n-a\n+b"),
        ],
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: llm)
    return env
