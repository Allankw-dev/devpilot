import io
import os
import tarfile
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import CodeChunk, IndexedFile, Repository
from app.services.github.client import GitHubClient
from app.services.indexing.chunker import chunk_file
from app.services.indexing.pipeline import (
    FLUSH_FILES,
    TransientIndexError,
    claim_index,
    request_index,
)
from app.services.llm import LLMService
from app.services.llm.errors import (
    LLMAuthError,
    LLMNotConfigured,
    LLMRateLimited,
    LLMUnavailable,
)
from tests.conftest import World
from tests.github_helpers import FakeGitHub, make_tarball
from tests.index_helpers import DEFAULT_FILES, REPO, IndexEnv, big, make_env
from tests.llm_helpers import FakeEmbedder, FakeProvider, ListRecorder


@pytest.fixture
def env(
    client: TestClient,
    world: World,
    fake_github: FakeGitHub,
    gh_client: GitHubClient,
    session_factory: sessionmaker[Session],
    gh_settings: Settings,
) -> IndexEnv:
    return make_env(client, world, fake_github, gh_client, session_factory, gh_settings)


def settings_with(base: Settings, **changes: object) -> Settings:
    return base.model_copy(update=changes)


# ---------- a full index ----------


def test_full_index_stores_chunks_with_exact_line_ranges(env: IndexEnv) -> None:
    assert env.run() == "ready"

    chunks = env.chunks()
    assert {c.path for c in chunks} == {"app/main.py", "README.md", "src/util.ts"}
    main = [c for c in chunks if c.path == "app/main.py"]
    assert [c.symbol for c in main] == ["alpha", "beta"]
    assert all(c.language == "python" for c in main)

    source_lines = str(DEFAULT_FILES["app/main.py"]).splitlines()
    for c in main:  # the contract citations will rely on
        assert c.content == "\n".join(source_lines[c.start_line - 1 : c.end_line])
    assert all(len(c.embedding) == 768 for c in chunks)


def test_index_status_and_counts(env: IndexEnv) -> None:
    env.set_head("c")
    env.run()
    index = env.index()
    assert index.status == "ready" and index.error is None
    assert index.commit_sha == "c" * 40
    assert index.embedding_model == "fake-embed-v1"
    assert index.files_indexed == 3 and index.chunks_total == len(env.chunks())
    assert index.files_skipped == 4  # node_modules, .env, lockfile, png
    assert index.chunks_skipped == 0 and index.finished_at is not None


def test_excluded_and_secret_files_never_reach_the_embedder(env: IndexEnv) -> None:
    env.run()
    sent = "\n".join(env.embedder.texts)
    assert "AIzaSyA" not in sent and "GEMINI_API_KEY" not in sent  # from .env
    assert "module.exports" not in sent  # node_modules
    assert not any(p.startswith(("node_modules", ".env")) for p in env.paths())


def test_embedding_input_carries_the_file_path_and_symbol(env: IndexEnv) -> None:
    env.run()
    assert any(t.startswith("File: app/main.py\nSymbol: alpha\n") for t in env.embedder.texts)


def test_archive_download_goes_through_redirect_without_leaking_the_token(env: IndexEnv) -> None:
    env.run()
    assert any("/tarball/" in c for c in env.fake.calls)
    assert env.fake.codeload_auth == [None]  # the download host never saw our credentials


def test_usage_is_recorded_per_embedding_operation(env: IndexEnv) -> None:
    env.run()
    entries = [e for e in env.recorder.entries if e.operation == "embed"]
    assert entries and all(e.ctx.feature == "indexing" for e in entries)
    assert all(e.ctx.org_id is not None for e in entries)


# ---------- incremental ----------


def test_unchanged_repo_costs_no_embedding_calls_and_keeps_chunk_ids(env: IndexEnv) -> None:
    env.run()
    before = {c.id for c in env.chunks()}
    calls = env.embedder.calls

    assert env.run() == "ready"
    assert env.embedder.calls == calls  # nothing sent
    assert {c.id for c in env.chunks()} == before


def test_only_changed_files_are_re_embedded(env: IndexEnv) -> None:
    env.run()
    readme_before = {c.id for c in env.chunks() if c.path == "README.md"}
    env.embedder.texts.clear()

    env.files["app/main.py"] = big("alpha") + "\n\n" + big("gamma")
    env.set_head("d")
    env.run()

    assert env.embedder.texts and all("app/main.py" in t for t in env.embedder.texts)
    assert {c.symbol for c in env.chunks() if c.path == "app/main.py"} == {"alpha", "gamma"}
    assert {c.id for c in env.chunks() if c.path == "README.md"} == readme_before  # untouched


def test_deleted_files_are_removed_and_new_files_added(env: IndexEnv) -> None:
    env.run()
    del env.files["src/util.ts"]
    env.files["lib/new.py"] = "def new_thing():\n    return 1\n"
    env.run()

    assert env.paths() == {"app/main.py", "README.md", "lib/new.py"}
    assert set(env.stored_files()) == {"app/main.py", "README.md", "lib/new.py"}


def test_a_file_that_becomes_excluded_is_dropped_from_the_index(
    env: IndexEnv, gh_settings: Settings
) -> None:
    env.run()
    assert "src/util.ts" in env.paths()
    env.run(settings=settings_with(gh_settings, index_exclude=["src"]))
    assert "src/util.ts" not in env.paths()


def test_changing_the_embedding_model_re_embeds_everything(env: IndexEnv) -> None:
    env.run()
    first = len(env.embedder.texts)

    class NewModel(FakeEmbedder):
        model = "fake-embed-v2"

    newer = NewModel()
    llm = LLMService(FakeProvider(), embedding=newer, sleep=lambda _: None)
    env.run(llm=llm)

    assert len(newer.texts) == first  # same texts, embedded again
    assert env.index().embedding_model == "fake-embed-v2"


def test_empty_repository_is_ready_with_nothing_indexed(env: IndexEnv) -> None:
    env.run()
    assert env.chunks()
    env.fake.data[REPO]["empty"] = True  # GitHub answers 409 "Git Repository is empty."
    assert env.run() == "ready"
    assert env.chunks() == [] and env.index().files_indexed == 0


# ---------- what gets stored from files ----------


def test_binary_and_non_utf8_files_are_skipped_and_bom_is_stripped(env: IndexEnv) -> None:
    env.files.clear()
    env.files.update(
        {
            "a.py": b"x = 1\x00\x01\x02\n",  # NUL bytes: binary
            "b.py": "caf\xe9 = 1\n".encode("latin-1"),  # not UTF-8
            "c.py": b"\xef\xbb\xbfvalue = 3\n",  # UTF-8 with BOM
        }
    )
    env.run()
    (chunk,) = env.chunks()
    assert chunk.path == "c.py" and chunk.content == "value = 3"


def test_chunks_that_look_like_credentials_are_dropped_before_embedding(env: IndexEnv) -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"
    leaky = big("alpha").replace("compute_alpha(0)", f"login('{secret}')")
    env.files["app/main.py"] = leaky + "\n\n" + big("beta")
    env.run()

    assert [c.symbol for c in env.chunks() if c.path == "app/main.py"] == ["beta"]
    assert secret not in "\n".join(env.embedder.texts)
    assert secret not in "".join(c.content for c in env.chunks())
    assert env.index().chunks_skipped == 1


def test_skipped_secret_chunks_stay_counted_across_incremental_runs(env: IndexEnv) -> None:
    leaky = big("alpha").replace("compute_alpha(0)", "login('AKIAIOSFODNN7EXAMPLE')")
    env.files["app/main.py"] = leaky + "\n\n" + big("beta")
    env.run()
    env.run()  # nothing changed, so main.py isn't re-chunked
    assert env.index().chunks_skipped == 1


def test_files_over_the_size_limit_are_skipped(env: IndexEnv, gh_settings: Settings) -> None:
    env.files["huge.py"] = "x = 1\n" * 100
    env.run(settings=settings_with(gh_settings, index_max_file_bytes=200))
    assert "huge.py" not in env.paths()


# ---------- limits that protect cost and memory ----------


def test_too_many_files_fails_with_a_clear_message(env: IndexEnv, gh_settings: Settings) -> None:
    assert env.run(settings=settings_with(gh_settings, index_max_files=2)) == "failed"
    index = env.index()
    assert index.status == "failed" and "more than 2 indexable files" in (index.error or "")
    assert "INDEX_EXCLUDE" in (index.error or "")


def test_too_many_chunks_fails_before_paying_for_embeddings(
    env: IndexEnv, gh_settings: Settings
) -> None:
    assert env.run(settings=settings_with(gh_settings, index_max_chunks=1)) == "failed"
    assert "chunks" in (env.index().error or "")
    assert env.embedder.calls == 0


def test_runtime_limit_saves_progress_and_a_rerun_finishes_the_job(
    env: IndexEnv, gh_settings: Settings
) -> None:
    for i in range(FLUSH_FILES * 2 + 10):  # enough for several batches
        env.files[f"pkg/m{i:02d}.py"] = f"def fn{i}():\n    return {i}\n"
    short = settings_with(gh_settings, index_max_runtime_seconds=5)
    env.clock_value[0] = 0

    original = env.embedder.embed
    def tick(texts, **kw):  # type: ignore[no-untyped-def]
        env.clock_value[0] += 10  # every embedding call "takes" 10 seconds
        return original(texts, **kw)
    env.embedder.embed = tick  # type: ignore[method-assign]

    run_id = env.request()
    with pytest.raises(TransientIndexError):
        env.run(run_id, final_attempt=False, settings=short)
    assert env.index().status == "queued" and "continue" in (env.index().error or "")
    partial = len(env.chunks())
    assert 0 < partial

    env.embedder.embed = original  # type: ignore[method-assign]
    env.embedder.texts.clear()
    assert env.run(run_id, settings=short) == "ready"
    total = len(env.chunks())
    assert total > partial
    assert len(env.embedder.texts) == total - partial  # only the unfinished part was embedded


# ---------- hostile or broken archives ----------


def test_links_and_path_tricks_in_the_archive_are_ignored(env: IndexEnv) -> None:
    def extras(tar: tarfile.TarFile) -> None:
        link = tarfile.TarInfo("octo-org-api-aaaaaaa/link.py")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
        hard = tarfile.TarInfo("octo-org-api-aaaaaaa/hard.py")
        hard.type, hard.linkname = tarfile.LNKTYPE, "app/main.py"
        tar.addfile(hard)
        dev = tarfile.TarInfo("octo-org-api-aaaaaaa/dev.py")
        dev.type = tarfile.CHRTYPE
        tar.addfile(dev)
        for sneaky in ("../../evil.py", "a/../../evil2.py", "..\\evil3.py"):
            data = b"x = 'pwned'\n"
            info = tarfile.TarInfo(f"octo-org-api-aaaaaaa/{sneaky}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    env.fake.data[REPO]["archive"] = make_tarball(
        {"ok.py": "def ok():\n    return 1\n"}, prefix="octo-org-api-aaaaaaa", extra=extras
    )
    assert env.run() == "ready"
    assert env.paths() == {"ok.py"}


def test_an_archive_that_unpacks_far_beyond_its_size_is_refused(
    env: IndexEnv, gh_settings: Settings
) -> None:
    # 7 MB of zeros compresses to a few KB: a classic decompression bomb.
    env.fake.data[REPO]["archive"] = make_tarball({"bomb.py": b"\x00" * 7_000_000})
    assert env.run(settings=settings_with(gh_settings, index_max_archive_mb=1)) == "failed"
    assert "unpacked" in (env.index().error or "")


def test_an_oversized_download_is_cut_off(env: IndexEnv, gh_settings: Settings) -> None:
    env.fake.data[REPO]["archive"] = make_tarball({"noise.bin": os.urandom(2_000_000)})
    assert env.run(settings=settings_with(gh_settings, index_max_archive_mb=1)) == "failed"
    assert "larger than the allowed size" in (env.index().error or "")


def test_a_corrupt_archive_is_treated_as_a_failed_download(env: IndexEnv) -> None:
    env.fake.data[REPO]["archive"] = b"this is not a gzip file at all"
    assert env.run() == "failed"
    assert "interrupted or corrupted" in (env.index().error or "")


# ---------- failures: retry later vs. give up ----------


def test_rate_limit_leaves_the_run_queued_for_an_automatic_retry(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMRateLimited("slow down")
    run_id = env.request()
    with pytest.raises(TransientIndexError):
        env.run(run_id, final_attempt=False)
    index = env.index()
    assert index.status == "queued" and "Retrying automatically" in (index.error or "")

    env.embedder.fail_with = None
    assert env.run(run_id) == "ready"  # the same run picks up where it left off
    assert env.chunks()


def test_on_the_final_attempt_a_transient_problem_becomes_a_failure_users_can_retry(
    env: IndexEnv,
) -> None:
    env.embedder.fail_with = LLMUnavailable("down")
    assert env.run(final_attempt=True) == "failed"
    index = env.index()
    assert index.status == "failed" and "Click Re-index" in (index.error or "")


def test_progress_survives_a_failure_and_the_rerun_only_embeds_the_rest(env: IndexEnv) -> None:
    env.files.clear()
    for i in range(FLUSH_FILES * 2):
        env.files[f"mod/f{i:02d}.py"] = f"def f{i}():\n    return {i}\n"
    env.embedder.fail_after = 1  # the first batch is saved, then the provider goes down
    env.embedder.fail_with = LLMUnavailable("down")

    run_id = env.request()
    with pytest.raises(TransientIndexError):
        env.run(run_id, final_attempt=False)
    saved = len(env.stored_files())
    assert 0 < saved < FLUSH_FILES * 2
    assert len(env.chunks()) == saved

    env.embedder.fail_with = None
    env.embedder.texts.clear()
    assert env.run(run_id) == "ready"
    assert len(env.embedder.texts) == FLUSH_FILES * 2 - saved  # nothing paid for twice
    assert len(env.stored_files()) == FLUSH_FILES * 2


def test_a_rejected_api_key_fails_immediately_without_retries(env: IndexEnv) -> None:
    env.embedder.fail_with = LLMAuthError("bad key")
    assert env.run(final_attempt=False) == "failed"  # no exception: retrying can't help
    assert "rejected the API key" in (env.index().error or "")


def test_wrong_vector_size_is_caught_and_nothing_is_stored(env: IndexEnv) -> None:
    env.embedder.dims = 3
    class Short(FakeEmbedder):
        def vector(self, text: str) -> list[float]:
            return [1.0, 0.0, 0.0]
    llm = LLMService(FakeProvider(), embedding=Short(), sleep=lambda _: None)
    assert env.run(llm=llm) == "failed"
    assert "wrong vector size" in (env.index().error or "")
    assert env.chunks() == []


def test_embedding_dimensions_setting_must_match_the_database(
    env: IndexEnv, gh_settings: Settings
) -> None:
    assert env.run(settings=settings_with(gh_settings, embedding_dimensions=1536)) == "failed"
    assert "must be 768" in (env.index().error or "")


def test_missing_embedding_configuration_is_reported_by_setting_name(env: IndexEnv) -> None:
    def not_configured() -> LLMService:
        raise LLMNotConfigured(["GEMINI_API_KEY", "GEMINI_MODEL"])

    run_id = env.request()
    from app.services.indexing.pipeline import run_index

    result = run_index(
        env.factory, env.github, not_configured, env.settings, env.repo_id, run_id
    )
    assert result == "failed"
    assert "GEMINI_API_KEY" in (env.index().error or "")


def test_no_embedding_provider_at_all_is_a_clear_failure(env: IndexEnv) -> None:
    llm = LLMService(FakeProvider(), embedding=None, recorder=ListRecorder())
    assert env.run(llm=llm) == "failed"
    assert "GEMINI_EMBEDDING_MODEL" in (env.index().error or "")


def test_github_denying_access_is_a_clear_permanent_failure(env: IndexEnv) -> None:
    env.fake.fail["tarball"] = (404, {})
    assert env.run(final_attempt=False) == "failed"
    assert "Contents: read" in (env.index().error or "")


def test_github_outage_is_transient(env: IndexEnv) -> None:
    env.fake.fail["tarball"] = (502, {})
    run_id = env.request()
    with pytest.raises(TransientIndexError):
        env.run(run_id, final_attempt=False)
    assert env.index().status == "queued"


def test_github_rate_limit_is_transient(env: IndexEnv) -> None:
    env.fake.fail["/commits/"] = (403, {"x-ratelimit-remaining": "0"})
    with pytest.raises(TransientIndexError):
        env.run(final_attempt=False)


def test_unexpected_errors_are_logged_and_reported_generically(env: IndexEnv) -> None:
    env.embedder.fail_with = RuntimeError("internal detail /srv/secret/path")
    assert env.run() == "failed"
    error = env.index().error or ""
    assert "Unexpected error" in error and "secret" not in error


# ---------- ownership: who may run a job ----------


def test_a_second_request_while_one_is_active_is_refused(env: IndexEnv) -> None:
    first = env.request()
    with env.factory() as db:
        assert request_index(db, env.repo_id, None) is None  # still queued: refused
    assert env.index().run_id == first  # and the active run was not disturbed


def test_duplicate_and_superseded_deliveries_do_nothing(env: IndexEnv) -> None:
    run_id = env.request()
    assert env.run(run_id) == "ready"
    calls = env.embedder.calls
    assert env.run(run_id) == "skipped"  # the same message delivered twice
    assert env.run(uuid.uuid4()) == "skipped"  # a run id that was never issued
    assert env.embedder.calls == calls


def test_a_new_request_supersedes_the_previous_run(env: IndexEnv) -> None:
    env.run()
    old = env.request()
    with env.factory() as db:  # simulate the old job being lost, so a new request is allowed
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import update

        from app.db.models import RepositoryIndex

        db.execute(update(RepositoryIndex).values(queued_at=datetime.now(UTC) - timedelta(hours=1)))
        db.commit()
    new = env.request()
    assert new != old
    assert env.run(old) == "skipped"
    assert env.run(new) == "ready"


def test_a_dead_workers_run_is_taken_over_but_a_live_one_is_not(env: IndexEnv) -> None:
    run_id = env.request()
    with env.factory() as db:
        assert claim_index(db, env.repo_id, run_id)  # worker A starts
    with env.factory() as db:
        assert not claim_index(db, env.repo_id, run_id)  # a duplicate delivery can't join it
    env.age_heartbeat(minutes=30)  # worker A died long ago
    with env.factory() as db:
        assert claim_index(db, env.repo_id, run_id)  # now it can be taken over
    # The takeover above is now the live owner, so another delivery must wait, not be dropped:
    assert env.run(run_id) == "busy"


def test_requests_are_allowed_again_after_ready_failed_or_a_dead_worker(env: IndexEnv) -> None:
    run_id = env.request()
    env.run(run_id)
    for _ in range(2):  # ready, then failed
        with env.factory() as db:
            assert request_index(db, env.repo_id, None) is not None
        env.embedder.fail_with = LLMAuthError("x")
        env.run(env.index().run_id)
        env.embedder.fail_with = None
    with env.factory() as db:
        assert request_index(db, env.repo_id, None) is not None


# ---------- cleanup ----------


def test_removing_a_repository_removes_its_index(
    env: IndexEnv, session_factory: sessionmaker[Session]
) -> None:
    env.run()
    with session_factory() as db:
        db.delete(db.get(Repository, env.repo_id))
        db.commit()
        assert db.scalar(select(CodeChunk.id)) is None
        assert db.scalar(select(IndexedFile.path)) is None


def test_disconnecting_github_removes_all_indexed_code(env: IndexEnv) -> None:
    env.run()
    installs = env.client.get(
        f"/api/v1/orgs/{env.world.org_id}/github", headers=env.world.owner.headers
    ).json()["installations"]
    res = env.client.delete(
        f"/api/v1/orgs/{env.world.org_id}/github/installations/{installs[0]['id']}",
        headers=env.world.owner.headers,
    )
    assert res.status_code == 204
    assert env.chunks() == []


# ---------- sanity: the chunker and pipeline agree ----------


def test_stored_chunks_match_what_the_chunker_produces(env: IndexEnv) -> None:
    env.run()
    expected = chunk_file(str(DEFAULT_FILES["README.md"]), "markdown")
    stored = [c for c in env.chunks() if c.path == "README.md"]
    assert [(c.start_line, c.end_line, c.content) for c in stored] == [
        (c.start_line, c.end_line, c.text) for c in expected
    ]

