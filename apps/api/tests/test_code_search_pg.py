"""Code search against real pgvector. Skipped unless the suite runs on PostgreSQL:

    TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/devpilot_test pytest
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_llm, get_llm_getter
from app.core.config import Settings, get_settings
from app.main import app
from app.services.github.client import GitHubClient
from app.services.indexing import retrieval
from app.services.indexing.pipeline import request_index, run_index
from app.services.indexing.retrieval import search_hits
from app.services.llm import LLMService
from tests.ask_helpers import answer_json
from tests.conftest import ON_POSTGRES, Person, World
from tests.github_helpers import FakeGitHub, connect, make_repo
from tests.index_helpers import REPO, IndexEnv, make_env
from tests.llm_helpers import FakeProvider, reply

pytestmark = pytest.mark.skipif(not ON_POSTGRES, reason="needs PostgreSQL with pgvector")

API = "/api/v1"

AUTH_PY = '''def login_user(username, password):
    """Authenticate a user, check credentials and start a session token."""
    session = create_session_token(username)
    verify_credentials(username, password)
    return session
'''
BILLING_PY = '''def charge_invoice(customer, amount):
    """Create a stripe invoice, charge the card and send a refund if it fails."""
    invoice = stripe_invoice(customer, amount)
    return refund_if_failed(invoice)
'''


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> Iterator[IndexEnv]:
    configured = gh_settings.model_copy(
        update={"gemini_api_key": SecretStr("k"), "gemini_embedding_model": "fake-embed-v1"}
    )
    files: dict[str, str | bytes] = {"auth/login.py": AUTH_PY, "billing/charge.py": BILLING_PY}
    e = make_env(client, world, fake_github, gh_client, session_factory, configured, files)
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_llm] = lambda: e.llm
    app.dependency_overrides[get_llm_getter] = lambda: (lambda: e.llm)
    assert e.run() == "ready"
    yield e


def search(
    e: IndexEnv, who: Person | None = None, org: str | None = None, **body: object
) -> Response:
    return e.client.post(
        f"{API}/orgs/{org or e.world.org_id}/search",
        json=body,
        headers=(who or e.world.owner).headers,
    )


def test_the_most_relevant_chunk_comes_first_with_full_location(env: IndexEnv) -> None:
    res = search(env, query="authenticate user credentials session token")
    assert res.status_code == 200, res.text
    hits = res.json()["results"]
    assert [h["path"] for h in hits][0] == "auth/login.py"
    top = hits[0]
    assert top["repository"] == REPO and top["symbol"] == "login_user"
    assert top["start_line"] == 1 and top["end_line"] >= 4 and top["language"] == "python"
    assert "verify_credentials" in top["content"]
    assert hits[0]["score"] > hits[1]["score"]  # ordered best first


def test_billing_questions_find_billing_code(env: IndexEnv) -> None:
    hits = search(env, query="stripe invoice refund").json()["results"]
    assert hits[0]["path"] == "billing/charge.py"


def test_identical_text_scores_close_to_one(env: IndexEnv) -> None:
    chunk_text = "File: auth/login.py\nSymbol: login_user\n\n" + AUTH_PY.rstrip("\n")
    hits = search(env, query=chunk_text).json()["results"]
    assert hits[0]["score"] > 0.99


def test_limit_and_repository_filter(env: IndexEnv) -> None:
    assert len(search(env, query="invoice session", limit=1).json()["results"]) == 1
    only = search(env, query="invoice", repository_id=str(env.repo_id)).json()["results"]
    assert only and all(h["repository_id"] == str(env.repo_id) for h in only)


def test_a_repository_with_nothing_indexed_returns_no_results(
    env: IndexEnv, world: World, fake_github: FakeGitHub
) -> None:
    with env.factory() as db:
        db.execute(text("DELETE FROM code_chunks"))
        db.commit()
    assert search(env, query="anything at all").json() == {"results": []}


# ---------- one organization can never see another's code ----------


def test_search_never_crosses_organizations(
    env: IndexEnv, fake_github: FakeGitHub, person: Callable[[str], Person]
) -> None:
    mallory: Person = person("mallory@example.com")
    org2 = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()

    fake_github.add_installation(888, login="evil-org")
    fake_github.add_repo(
        888,
        make_repo(301, "evil-org/vault"),
        files={"vault.py": "def launch_codes():\n    return 'topsecret launch codes'\n"},
    )
    assert connect(env.client, fake_github, mallory.headers, org2["id"], installation_id=888).status_code == 200
    listing = env.client.get(f"{API}/orgs/{org2['id']}/repos", headers=mallory.headers).json()
    evil_repo = uuid.UUID(listing[0]["id"])
    with env.factory() as db:
        run_id = request_index(db, evil_repo, None)
    assert run_id is not None
    assert (
        run_index(env.factory, env.github, lambda: env.llm, env.settings, evil_repo, run_id)
        == "ready"
    )

    # The first organization asks for exactly that content and gets none of it...
    mine = search(env, query="topsecret launch codes").json()["results"]
    assert all(h["repository"] == REPO for h in mine)
    assert not any("topsecret" in h["content"] for h in mine)
    # ...and cannot name the other organization's repository either.
    assert search(env, query="launch", repository_id=str(evil_repo)).status_code == 404
    # The other organization sees its own code, and none of ours.
    theirs = search(env, mallory, org=org2["id"], query="topsecret launch codes").json()["results"]
    assert theirs and all(h["repository"] == "evil-org/vault" for h in theirs)
    ours = search(env, mallory, org=org2["id"], query="authenticate user credentials").json()
    assert all(h["repository"] == "evil-org/vault" for h in ours["results"])
    # And cannot search an organization they don't belong to.
    assert search(env, mallory, org=str(env.world.org_id), query="x").status_code == 404


# ---------- database facts ----------


def test_chunks_have_an_hnsw_cosine_index(env: IndexEnv) -> None:
    with env.factory() as db:
        definition = db.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_code_chunks_embedding'")
        ).scalar_one()
    assert "hnsw" in definition and "vector_cosine_ops" in definition


def test_search_still_works_if_a_pgvector_setting_is_unknown(
    env: IndexEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Older pgvector versions reject some settings; that must not abort the search.
    monkeypatch.setattr(
        retrieval,
        "_VECTOR_SETTINGS",
        ("hnsw.setting_that_does_not_exist = 1", "hnsw.ef_search = 100"),
    )
    res = search(env, query="stripe invoice refund")
    assert res.status_code == 200 and res.json()["results"]


# ---------- copies of the same code ----------


def test_identical_code_in_several_files_is_shown_once_with_the_other_places_listed(
    env: IndexEnv,
) -> None:
    env.files["auth/login_copy.py"] = AUTH_PY  # an exact copy, like "Bank program.py" twice
    env.files["old/login_backup.py"] = AUTH_PY
    env.set_head("b")
    assert env.run() == "ready"

    hits = search(env, query="authenticate user credentials session token").json()["results"]
    paths = [h["path"] for h in hits]
    assert sum(AUTH_PY.rstrip("\n") == h["content"] for h in hits) == 1  # one hit for that code
    top = hits[0]
    assert top["path"] in {"auth/login.py", "auth/login_copy.py", "old/login_backup.py"}
    assert sorted([top["path"], *top["also_in"]]) == [
        "auth/login.py", "auth/login_copy.py", "old/login_backup.py",
    ]  # fmt: skip
    assert len(paths) == len(set(paths))


def test_copies_do_not_use_up_the_requested_number_of_results(env: IndexEnv) -> None:
    for i in range(4):
        env.files[f"copies/login_{i}.py"] = AUTH_PY
    env.set_head("c")
    assert env.run() == "ready"

    hits = search(env, query="authenticate user credentials session token", limit=2).json()[
        "results"
    ]
    assert len(hits) == 2  # two different pieces of code, not one repeated
    assert hits[0]["content"] != hits[1]["content"]


def test_unique_code_has_no_also_in(env: IndexEnv) -> None:
    hits = search(env, query="stripe invoice refund").json()["results"]
    assert all(h["also_in"] == [] for h in hits)


# ---------- asking questions, with real vector search ----------


def _ask(e: IndexEnv, gen: FakeProvider, who: Person | None = None, org: str | None = None, **body: object) -> Response:  # noqa: E501
    llm = LLMService(gen, embedding=e.embedder, sleep=lambda _: None)
    app.dependency_overrides[get_llm] = lambda: llm
    body.setdefault("question", "authenticate user credentials session token")
    return e.client.post(
        f"{API}/orgs/{org or e.world.org_id}/ask",
        json=body,
        headers=(who or e.world.owner).headers,
    )


def test_asking_finds_the_right_code_by_meaning_and_cites_it(env: IndexEnv) -> None:
    gen = FakeProvider([reply(answer_json("Login is done in `login_user` [1]."))])
    res = _ask(env, gen)
    assert res.status_code == 200, res.text

    prompt = gen.requests[0].messages[0].content
    first_source = prompt.split("source 1 - ", 1)[1].split("</untrusted_content>", 1)[0]
    assert "auth/login.py" in first_source and "def login_user" in first_source  # best match first
    (citation,) = res.json()["citations"]
    assert citation["path"] == "auth/login.py" and citation["symbol"] == "login_user"
    assert citation["start_line"] == 1


def test_asking_never_shows_the_model_another_organizations_code(
    env: IndexEnv, fake_github: FakeGitHub, person: Callable[[str], Person]
) -> None:
    mallory: Person = person("mallory@example.com")
    org2 = env.client.post(f"{API}/orgs", json={"name": "Evil Corp"}, headers=mallory.headers).json()
    fake_github.add_installation(888, login="evil-org")
    fake_github.add_repo(
        888,
        make_repo(301, "evil-org/vault"),
        files={"vault.py": "def authenticate_launch():\n    return 'topsecret launch codes'\n"},
    )
    assert connect(env.client, fake_github, mallory.headers, org2["id"], installation_id=888).status_code == 200
    listing = env.client.get(f"{API}/orgs/{org2['id']}/repos", headers=mallory.headers).json()
    evil_repo = uuid.UUID(listing[0]["id"])
    with env.factory() as db:
        run_id = request_index(db, evil_repo, None)
    assert run_id is not None
    run_index(env.factory, env.github, lambda: env.llm, env.settings, evil_repo, run_id)

    # Our organization asks a question that matches the other organization's code very well.
    gen = FakeProvider([reply(answer_json("done [1]"))])
    res = _ask(env, gen, question="authenticate launch topsecret codes")
    assert res.status_code == 200
    prompt = gen.requests[0].messages[0].content
    for marker in ("authenticate_launch", "launch codes'", "evil-org", "vault.py"):
        assert marker not in prompt  # none of the other organization's code or names

    # And the other organization cannot aim a question at ours.
    own = _ask(env, FakeProvider([reply(answer_json())]), mallory, org2["id"], repository_id=str(env.repo_id))
    assert own.status_code == 404


# ---------- one long file cannot crowd out the rest ----------


def test_a_long_readme_cannot_fill_every_slot_when_files_are_capped(env: IndexEnv) -> None:
    section = "authenticate user credentials session token. " * 30
    env.files["README.md"] = "# Title\n\n" + "\n\n".join(
        f"## Section {i}\n\n{section}" for i in range(8)
    )
    env.set_head("d")
    assert env.run() == "ready"

    vector = env.embedder.vector("authenticate user credentials session token")
    org = uuid.UUID(str(env.world.org_id))
    with env.factory() as db:
        uncapped = search_hits(db, org, vector, None, 8)
        capped = search_hits(db, org, vector, None, 8, max_per_path=2)

    assert sum(h.path == "README.md" for h in uncapped) > 2  # the problem, shown
    assert sum(h.path == "README.md" for h in capped) <= 2  # the fix
    assert "auth/login.py" in {h.path for h in capped}  # real code makes it into the answer
