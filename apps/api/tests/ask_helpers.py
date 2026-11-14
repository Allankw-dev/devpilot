"""Shared setup for question-answering tests."""

import json
from collections.abc import Sequence
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm, get_llm_getter, get_retriever
from app.core.config import Settings, get_settings
from app.main import app
from app.services.github.client import GitHubClient
from app.services.indexing.retrieval import Hit, Retriever
from app.services.llm import LLMService
from app.services.llm.usage import DbUsageRecorder
from tests.conftest import World
from tests.github_helpers import FakeGitHub
from tests.index_helpers import IndexEnv, big, make_env
from tests.llm_helpers import FakeEmbedder, FakeProvider, reply

FILES: dict[str, str | bytes] = {
    "auth/login.py": big("login_user", 40),
    "billing/charge.py": big("charge_invoice", 40),
    "README.md": "# Project\n\nA small service.\n",
}


def answer_json(
    text: str = "Login is handled in `login_user` [1].",
    confidence: str = "high",
    missing: str = "",
) -> str:
    return json.dumps({"answer": text, "confidence": confidence, "missing_context": missing})


class AskEnv:
    """An indexed repository plus fakes for the AI and for retrieval."""

    def __init__(self, base: IndexEnv, settings: Settings, generation: FakeProvider) -> None:
        self.base = base
        self.settings = settings
        self.generation = generation
        self.retrieval_calls: list[dict[str, Any]] = []
        self.hits: list[Hit] | None = None  # None: build from what was indexed

    @property
    def client(self) -> TestClient:
        return self.base.client

    @property
    def world(self) -> World:
        return self.base.world

    @property
    def repo_id(self) -> Any:
        return self.base.repo_id

    def script(self, *items: Any) -> None:
        self.generation.script = [
            reply(i) if isinstance(i, str) else i for i in items
        ]

    def indexed_hits(self) -> list[Hit]:
        return [
            Hit(
                repo_id=c.repo_id,
                repository="octo-org/api",
                path=c.path,
                start_line=c.start_line,
                end_line=c.end_line,
                symbol=c.symbol,
                language=c.language,
                content=c.content,
                score=round(0.9 - 0.05 * i, 4),
            )
            for i, c in enumerate(self.base.chunks())
        ]

    def retriever(self) -> Retriever:
        def fake(
            db: Session,
            org_id: Any,
            vector: Sequence[float],
            repo_id: Any,
            limit: int,
            max_per_path: int | None,
        ) -> list[Hit]:
            self.retrieval_calls.append(
                {
                    "org_id": org_id,
                    "repo_id": repo_id,
                    "limit": limit,
                    "dims": len(vector),
                    "max_per_path": max_per_path,
                }
            )
            return list(self.hits if self.hits is not None else self.indexed_hits())

        return fake

    def ask(self, who: Any = None, org: Any = None, **body: Any) -> Any:
        body.setdefault("question", "Where is login handled?")
        return self.client.post(
            f"/api/v1/orgs/{org or self.world.org_id}/ask",
            json=body,
            headers=(who or self.world.owner).headers,
        )


def make_ask_env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
    **setting_overrides: Any,
) -> AskEnv:
    configured = gh_settings.model_copy(
        update={
            "gemini_api_key": SecretStr("k"),
            "gemini_embedding_model": "fake-embed-v1",
            **setting_overrides,
        }
    )
    base = make_env(client, world, fake_github, gh_client, session_factory, configured, dict(FILES))
    assert base.run() == "ready"
    generation = FakeProvider()
    llm = LLMService(
        generation,
        embedding=FakeEmbedder(),
        recorder=DbUsageRecorder(session_factory),
        sleep=lambda _: None,
    )
    env = AskEnv(base, configured, generation)
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: llm)
    app.dependency_overrides[get_retriever] = env.retriever
    return env
