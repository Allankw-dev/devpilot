import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import Conversation, ConversationMessage
from app.services.github.client import GitHubClient
from app.services.llm.errors import LLMAuthError
from tests.ask_helpers import AskEnv, answer_json, make_ask_env
from tests.conftest import Person, World
from tests.github_helpers import FakeGitHub

API = "/api/v1"
PersonFactory = Callable[[str], Person]


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> AskEnv:
    return make_ask_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def url(e: AskEnv, path: str = "") -> str:
    return f"{API}/orgs/{e.world.org_id}/conversations{path}"


def add_member(e: AskEnv, person: PersonFactory, role: str) -> Person:
    who = person(f"{role}@example.com")
    res = e.client.post(
        f"{API}/orgs/{e.world.org_id}/members",
        json={"email": who.email, "role": role},
        headers=e.world.owner.headers,
    )
    assert res.status_code in (200, 201), res.text
    return who


def new(e: AskEnv, who: Person | None = None, **body: Any) -> dict[str, Any]:
    res = e.client.post(url(e), json=body, headers=(who or e.world.owner).headers)
    assert res.status_code == 201, res.text
    out: dict[str, Any] = res.json()
    return out


def say(
    e: AskEnv, cid: str, question: str = "Where is login handled?", who: Person | None = None
) -> Any:
    return e.client.post(
        url(e, f"/{cid}/messages"),
        json={"question": question},
        headers=(who or e.world.owner).headers,
    )


def detail(e: AskEnv, cid: str, who: Person | None = None) -> Any:
    return e.client.get(url(e, f"/{cid}"), headers=(who or e.world.owner).headers)


# ---------- starting a conversation ----------


def test_a_new_conversation_starts_empty_with_a_default_title(env: AskEnv) -> None:
    conv = new(env)
    assert conv["title"] == "New conversation" and conv["message_count"] == 0
    assert conv["repository_id"] is None and conv["repository"] is None
    assert detail(env, conv["id"]).json()["messages"] == []


def test_a_conversation_can_be_about_one_repository(env: AskEnv) -> None:
    conv = new(env, repository_id=str(env.repo_id))
    assert conv["repository_id"] == str(env.repo_id) and conv["repository"] == "octo-org/api"


def test_a_repository_from_somewhere_else_is_refused(env: AskEnv) -> None:
    res = env.client.post(
        url(env), json={"repository_id": str(uuid.uuid4())}, headers=env.world.owner.headers
    )
    assert res.status_code == 404


def test_viewers_cannot_start_conversations(env: AskEnv, person: PersonFactory) -> None:
    viewer = add_member(env, person, "viewer")
    assert env.client.post(url(env), json={}, headers=viewer.headers).status_code == 403
    assert (
        env.client.get(url(env), headers=viewer.headers).json() == []
    )  # but may look (at nothing)


# ---------- asking ----------


def test_a_question_and_its_checked_answer_are_saved_together(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json("Login is in `login_user` [1].", "high"))
    res = say(env, conv["id"], "Where is login handled?")
    assert res.status_code == 201, res.text
    pair = res.json()
    assert pair["user"]["role"] == "user" and pair["user"]["content"] == "Where is login handled?"
    assert pair["user"]["citations"] == []
    a = pair["assistant"]
    assert a["role"] == "assistant" and a["content"].startswith("Login is in")
    assert a["confidence"] == "high" and a["model"] == "fake-model-v1"
    assert (a["input_tokens"], a["output_tokens"]) == (10, 5) and a["sources_considered"] > 0
    first = env.indexed_hits()[0]
    assert [(c["n"], c["path"], c["start_line"]) for c in a["citations"]] == [
        (1, first.path, first.start_line)
    ]

    got = detail(env, conv["id"]).json()
    assert [m["role"] for m in got["messages"]] == ["user", "assistant"]
    assert got["messages"][1]["citations"][0]["path"] == first.path  # citations survive a reload
    assert got["message_count"] == 2


def test_the_title_comes_from_the_first_question_only(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json(), answer_json())
    say(env, conv["id"], "  Where   is login\nhandled?  ")
    assert detail(env, conv["id"]).json()["title"] == "Where is login handled?"
    say(env, conv["id"], "And billing?")
    assert detail(env, conv["id"]).json()["title"] == "Where is login handled?"


def test_a_long_first_question_makes_a_short_title(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json())
    say(env, conv["id"], "How does " + "the authentication flow " * 10 + "work?")
    title = detail(env, conv["id"]).json()["title"]
    assert len(title) <= 60 and title.endswith("…")


def test_the_conversations_repository_limits_where_the_answer_comes_from(env: AskEnv) -> None:
    conv = new(env, repository_id=str(env.repo_id))
    env.script(answer_json())
    say(env, conv["id"])
    assert str(env.retrieval_calls[-1]["repo_id"]) == str(env.repo_id)
    other = new(env)
    env.script(answer_json())
    say(env, other["id"])
    assert env.retrieval_calls[-1]["repo_id"] is None


def test_messages_come_back_in_the_order_they_were_asked(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json("First [1]."), answer_json("Second [1]."))
    say(env, conv["id"], "First question?")
    say(env, conv["id"], "Second question?")
    msgs = detail(env, conv["id"]).json()["messages"]
    assert [(m["role"], m["content"][:6]) for m in msgs] == [
        ("user", "First "), ("assistant", "First "), ("user", "Second"), ("assistant", "Second"),
    ]  # fmt: skip


def test_a_failed_answer_saves_nothing_and_keeps_the_default_title(env: AskEnv) -> None:
    conv = new(env)
    env.generation.script = [LLMAuthError("bad key")]
    res = say(env, conv["id"])
    assert res.status_code >= 400
    got = detail(env, conv["id"]).json()
    assert got["messages"] == [] and got["title"] == "New conversation"


def test_questions_are_validated_and_viewers_cannot_ask(env: AskEnv, person: PersonFactory) -> None:
    conv = new(env)
    for bad in ("hi", "x" * 1001):
        assert say(env, conv["id"], bad).status_code == 422
    assert env.generation.requests == []


def test_a_full_conversation_refuses_more_questions_without_spending_tokens(
    env: AskEnv, session_factory: sessionmaker[Session]
) -> None:
    conv = new(env)
    with session_factory() as db:
        for i in range(100):
            db.add(
                ConversationMessage(
                    conversation_id=uuid.UUID(conv["id"]),
                    role="user" if i % 2 == 0 else "assistant",
                    content=f"m{i}",
                )
            )
        db.commit()
    res = say(env, conv["id"])
    assert res.status_code == 409 and "full" in res.json()["detail"]
    assert env.generation.requests == []
    assert detail(env, conv["id"]).json()["message_count"] == 100


# ---------- listing ----------


def test_the_list_shows_my_conversations_newest_activity_first_with_counts(
    env: AskEnv, session_factory: sessionmaker[Session]
) -> None:
    old = new(env)
    recent = new(env, repository_id=str(env.repo_id))
    env.script(answer_json())
    say(env, recent["id"], "Recent question?")
    with session_factory() as db:  # make the first one clearly older
        db.execute(
            update(Conversation)
            .where(Conversation.id == uuid.UUID(old["id"]))
            .values(updated_at=datetime.now(UTC) - timedelta(days=3))
        )
        db.commit()
    rows = env.client.get(url(env), headers=env.world.owner.headers).json()
    assert [r["id"] for r in rows] == [recent["id"], old["id"]]
    assert rows[0]["message_count"] == 2 and rows[0]["repository"] == "octo-org/api"
    assert rows[1]["message_count"] == 0 and rows[1]["repository"] is None


def test_the_list_is_paged_and_validated(env: AskEnv) -> None:
    for _ in range(3):
        new(env)
    owner = env.world.owner.headers
    assert len(env.client.get(url(env), params={"limit": 2}, headers=owner).json()) == 2
    assert (
        len(env.client.get(url(env), params={"limit": 2, "offset": 2}, headers=owner).json()) == 1
    )
    for bad in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        assert env.client.get(url(env), params=bad, headers=owner).status_code == 422


# ---------- privacy ----------


def test_nobody_else_can_see_read_ask_in_or_delete_my_conversation_not_even_admins(
    env: AskEnv, person: PersonFactory
) -> None:
    conv = new(env)
    env.script(answer_json())
    say(env, conv["id"], "A private question?")
    for role in ("admin", "member", "viewer"):
        other = add_member(env, person, role)
        assert env.client.get(url(env), headers=other.headers).json() == []
        assert detail(env, conv["id"], other).status_code == 404
        assert say(env, conv["id"], who=other).status_code in (403, 404)
        assert (
            env.client.delete(url(env, f"/{conv['id']}"), headers=other.headers).status_code == 404
        )
    assert detail(env, conv["id"]).json()["message_count"] == 2  # untouched


def test_other_organizations_cannot_reach_it(env: AskEnv, person: PersonFactory) -> None:
    conv = new(env)
    mallory = person("mallory@example.com")
    theirs = env.client.post(f"{API}/orgs", json={"name": "Evil"}, headers=mallory.headers).json()
    res = env.client.get(
        f"{API}/orgs/{theirs['id']}/conversations/{conv['id']}", headers=mallory.headers
    )
    assert res.status_code == 404
    assert (
        env.client.get(f"{API}/orgs/{theirs['id']}/conversations", headers=mallory.headers).json()
        == []
    )
    assert env.client.get(url(env), headers=mallory.headers).status_code == 404
    assert env.client.get(url(env)).status_code == 401
    assert detail(env, str(uuid.uuid4())).status_code == 404


# ---------- delete ----------


def test_deleting_a_conversation_removes_its_messages(
    env: AskEnv, session_factory: sessionmaker[Session]
) -> None:
    conv = new(env)
    env.script(answer_json())
    say(env, conv["id"])
    assert (
        env.client.delete(url(env, f"/{conv['id']}"), headers=env.world.owner.headers).status_code
        == 204
    )
    assert detail(env, conv["id"]).status_code == 404
    with session_factory() as db:
        left = db.scalar(select(func.count()).select_from(ConversationMessage))
    assert left == 0


# ---------- regenerate ----------


def test_the_last_answer_can_be_generated_again_in_place(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json("Old answer [1].", "low"), answer_json("Better answer [1].", "high"))
    pair = say(env, conv["id"], "Where is login handled?").json()
    assistant_id = pair["assistant"]["id"]

    res = env.client.post(
        url(env, f"/{conv['id']}/messages/{assistant_id}/regenerate"),
        headers=env.world.owner.headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == assistant_id and res.json()["content"].startswith("Better answer")
    assert res.json()["confidence"] == "high"
    msgs = detail(env, conv["id"]).json()["messages"]
    assert len(msgs) == 2 and msgs[1]["content"].startswith("Better answer")
    assert msgs[0]["content"] == "Where is login handled?"  # the question is unchanged
    assert (
        "Where is login handled?" in env.generation.requests[-1].messages[-1].content
    )  # and was asked again


def test_only_the_most_recent_answer_can_be_regenerated(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json(), answer_json())
    first = say(env, conv["id"], "First question?").json()
    second = say(env, conv["id"], "Second question?").json()
    base = url(env, f"/{conv['id']}/messages")
    owner = env.world.owner.headers
    assert (
        env.client.post(f"{base}/{first['assistant']['id']}/regenerate", headers=owner).status_code
        == 409
    )
    assert (
        env.client.post(f"{base}/{second['user']['id']}/regenerate", headers=owner).status_code
        == 409
    )
    assert env.client.post(f"{base}/{uuid.uuid4()}/regenerate", headers=owner).status_code == 409
    assert len(env.generation.requests) == 2  # nothing was spent on the refused ones


def test_regenerating_in_an_empty_conversation_is_refused(env: AskEnv) -> None:
    conv = new(env)
    res = env.client.post(
        url(env, f"/{conv['id']}/messages/{uuid.uuid4()}/regenerate"),
        headers=env.world.owner.headers,
    )
    assert res.status_code == 409


def test_a_failed_regeneration_keeps_the_old_answer(env: AskEnv) -> None:
    conv = new(env)
    env.script(answer_json("Original answer [1]."))
    assistant_id = say(env, conv["id"]).json()["assistant"]["id"]
    env.generation.script = [LLMAuthError("bad key")]
    res = env.client.post(
        url(env, f"/{conv['id']}/messages/{assistant_id}/regenerate"),
        headers=env.world.owner.headers,
    )
    assert res.status_code >= 400
    assert detail(env, conv["id"]).json()["messages"][1]["content"].startswith("Original answer")
