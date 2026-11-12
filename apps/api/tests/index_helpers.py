"""Shared setup for indexing tests: a connected org with one repository and fake services."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import CodeChunk, IndexedFile, RepositoryIndex
from app.services.github.client import GitHubClient
from app.services.indexing.pipeline import request_index, run_index
from app.services.llm import LLMService
from tests.conftest import World
from tests.github_helpers import FakeGitHub, connect
from tests.llm_helpers import FakeEmbedder, FakeProvider, ListRecorder

REPO = "octo-org/api"


def big(name: str, lines: int = 60) -> str:
    """A Python function too big to be packed together with its neighbours."""
    body = "\n".join(f"    value_{i} = compute_{name}({i})  # padding line {i}" for i in range(lines))
    return f"def {name}(x):\n{body}\n    return x\n"


DEFAULT_FILES: dict[str, str | bytes] = {
    "app/main.py": big("alpha") + "\n\n" + big("beta"),
    "README.md": "# Title\n\nHello world, this project does things.\n",
    "src/util.ts": "export function add(a: number, b: number) { return a + b; }\n",
    "node_modules/lib/index.js": "module.exports = 1;\n",
    ".env": "GEMINI_API_KEY=AIzaSyA-1234567890abcdefghijklmnopqrstu\n",
    "package-lock.json": "{}\n",
    "assets/logo.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00",
}


@dataclass
class IndexEnv:
    client: TestClient
    world: World
    fake: FakeGitHub
    github: GitHubClient
    factory: sessionmaker[Session]
    settings: Settings
    embedder: FakeEmbedder
    llm: LLMService
    recorder: ListRecorder
    repo_id: uuid.UUID
    clock_value: list[float] = field(default_factory=lambda: [0.0])

    @property
    def files(self) -> dict[str, Any]:
        files: dict[str, Any] = self.fake.data[REPO]["files"]
        return files

    def set_head(self, sha_char: str) -> None:
        self.fake.data[REPO]["head_sha"] = sha_char * 40

    def request(self, user_id: uuid.UUID | None = None) -> uuid.UUID:
        with self.factory() as db:
            run_id = request_index(db, self.repo_id, user_id)
        assert run_id is not None
        return run_id

    def run(
        self,
        run_id: uuid.UUID | None = None,
        *,
        final_attempt: bool = True,
        settings: Settings | None = None,
        llm: LLMService | None = None,
    ) -> str:
        run_id = run_id or self.request()
        service = llm or self.llm
        return run_index(
            self.factory,
            self.github,
            lambda: service,
            settings or self.settings,
            self.repo_id,
            run_id,
            final_attempt=final_attempt,
            clock=lambda: self.clock_value[0],
        )

    # ---- reading state back ----
    def index(self) -> RepositoryIndex:
        with self.factory() as db:
            row = db.get(RepositoryIndex, self.repo_id)
            assert row is not None
            db.expunge(row)
            return row

    def chunks(self) -> list[CodeChunk]:
        with self.factory() as db:
            rows = list(
                db.scalars(
                    select(CodeChunk)
                    .where(CodeChunk.repo_id == self.repo_id)
                    .order_by(CodeChunk.path, CodeChunk.start_line)
                )
            )
            db.expunge_all()
            return rows

    def paths(self) -> set[str]:
        return {c.path for c in self.chunks()}

    def stored_files(self) -> dict[str, IndexedFile]:
        with self.factory() as db:
            rows = {f.path: f for f in db.scalars(select(IndexedFile))}
            db.expunge_all()
            return rows

    def age_heartbeat(self, minutes: int) -> None:
        with self.factory() as db:
            db.execute(
                update(RepositoryIndex)
                .where(RepositoryIndex.repo_id == self.repo_id)
                .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=minutes))
            )
            db.commit()


def make_env(
    client: TestClient,
    world: World,
    fake: FakeGitHub,
    gh_client: GitHubClient,
    factory: sessionmaker[Session],
    settings: Settings,
    files: dict[str, str | bytes] | None = None,
) -> IndexEnv:
    fake.data[REPO]["files"] = dict(DEFAULT_FILES if files is None else files)
    assert connect(client, fake, world.owner.headers, world.org_id).status_code == 200
    listing = client.get(f"/api/v1/orgs/{world.org_id}/repos", headers=world.owner.headers).json()
    repo_id = uuid.UUID(next(r["id"] for r in listing if r["full_name"] == REPO))
    embedder = FakeEmbedder()
    recorder = ListRecorder()
    llm = LLMService(
        FakeProvider(), embedding=embedder, recorder=recorder, sleep=lambda _: None
    )
    return IndexEnv(
        client, world, fake, gh_client, factory, settings, embedder, llm, recorder, repo_id
    )
