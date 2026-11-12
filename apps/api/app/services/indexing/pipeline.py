"""Indexing one repository: download a snapshot, chunk it, embed it, store it.

Design points worth knowing:

- Incremental. Each file's content hash is remembered, so an unchanged file is never chunked or
  embedded again. Only changed files cost embedding tokens.
- Resumable. Progress is committed in batches. If a run is interrupted (rate limit, crash,
  timeout), the next run skips everything already stored.
- One owner at a time. A run is claimed with an atomic UPDATE on (repo, run id), so a duplicate
  or stale job delivery does nothing, and a dead worker's run can be taken over.
- Nothing from the repository is executed. The snapshot is streamed and read in memory only;
  links, devices and odd paths are ignored; sizes are capped before anything is decompressed.
- Credentials never go to the AI provider: files that usually hold them are skipped, and any
  chunk that looks like a credential is dropped before embedding.
"""

import hashlib
import logging
import tarfile
import time
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.models import (
    EMBEDDING_COLUMN_DIMENSIONS,
    CodeChunk,
    GithubInstallation,
    IndexedFile,
    Repository,
    RepositoryIndex,
)
from app.services.github.client import GitHubClient, GitHubError, GitHubRateLimited
from app.services.indexing.chunker import Chunk, chunk_file, embedding_text
from app.services.indexing.filters import FileRules, clean_path
from app.services.indexing.languages import language_of
from app.services.indexing.secretscan import contains_secret
from app.services.llm import CallContext, LLMError, LLMNotConfigured, LLMService
from app.services.llm.errors import (
    LLMAuthError,
    LLMBadRequest,
    LLMBlocked,
    LLMInvalidOutput,
    LLMNotSupported,
    LLMRateLimited,
    LLMTimeout,
    LLMUnavailable,
)

logger = logging.getLogger(__name__)

STALE_RUNNING = timedelta(minutes=10)  # no heartbeat for this long: the worker died
STALE_QUEUED = timedelta(minutes=30)  # queued this long: the job message was probably lost
FLUSH_CHUNKS = 64  # embed and save once this many chunks are waiting...
FLUSH_FILES = 25  # ...or this many files
CHUNKER_VERSION = 1  # bump to force every file to be re-chunked
DELETE_BATCH = 500


class IndexFailed(Exception):
    """Won't succeed by retrying. The message is safe to show to users."""


class TransientIndexError(Exception):
    """Worth trying again later (rate limit, outage). Progress so far is kept."""


@dataclass(frozen=True)
class IndexLimits:
    max_file_bytes: int
    max_files: int
    max_chunks: int
    max_archive_bytes: int
    max_unpacked_bytes: int
    max_runtime_seconds: int
    extra_excludes: tuple[str, ...]

    @classmethod
    def from_settings(cls, s: Settings) -> "IndexLimits":
        archive = s.index_max_archive_mb * 1024 * 1024
        return cls(
            max_file_bytes=s.index_max_file_bytes,
            max_files=s.index_max_files,
            max_chunks=s.index_max_chunks,
            max_archive_bytes=archive,
            max_unpacked_bytes=archive * 6,  # source compresses about 4-6x; this stops bombs
            max_runtime_seconds=s.index_max_runtime_seconds,
            extra_excludes=tuple(s.index_exclude),
        )


# ---------- claiming and status (shared by the API and the worker) ----------


def request_index(db: Session, repo_id: uuid.UUID, user_id: uuid.UUID | None) -> uuid.UUID | None:
    """Reserve an index run for a repository. Returns its run id, or None if one is already
    active (queued recently or running with a live heartbeat)."""
    now = datetime.now(UTC)
    run_id = uuid.uuid4()
    if db.get(RepositoryIndex, repo_id) is None:
        db.add(
            RepositoryIndex(
                repo_id=repo_id,
                status="queued",
                run_id=run_id,
                requested_by=user_id,
                queued_at=now,
            )
        )
        try:
            db.commit()
            return run_id
        except IntegrityError:  # someone else just created it
            db.rollback()
            return None
    result = cast(
        CursorResult[Any],
        db.execute(
            update(RepositoryIndex)
            .where(
                RepositoryIndex.repo_id == repo_id,
                or_(
                    RepositoryIndex.status.in_(("ready", "failed")),
                    (RepositoryIndex.status == "queued")
                    & (RepositoryIndex.queued_at < now - STALE_QUEUED),
                    (RepositoryIndex.status == "running")
                    & (RepositoryIndex.heartbeat_at < now - STALE_RUNNING),
                ),
            )
            .values(
                status="queued",
                run_id=run_id,
                requested_by=user_id,
                queued_at=now,
                error=None,
                finished_at=None,
            )
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return run_id if result.rowcount == 1 else None


def claim_index(db: Session, repo_id: uuid.UUID, run_id: uuid.UUID) -> bool:
    """Become the owner of this run. False for duplicate deliveries and superseded runs."""
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(RepositoryIndex)
            .where(
                RepositoryIndex.repo_id == repo_id,
                RepositoryIndex.run_id == run_id,
                or_(
                    RepositoryIndex.status == "queued",
                    (RepositoryIndex.status == "running")
                    & (RepositoryIndex.heartbeat_at < now - STALE_RUNNING),
                ),
            )
            .values(status="running", started_at=now, heartbeat_at=now, error=None)
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return result.rowcount == 1


def _finish(
    db: Session, repo_id: uuid.UUID, run_id: uuid.UUID, status: str, error: str | None
) -> None:
    db.execute(
        update(RepositoryIndex)
        .where(RepositoryIndex.repo_id == repo_id, RepositoryIndex.run_id == run_id)
        .values(
            status=status,
            error=error[:500] if error else None,
            finished_at=datetime.now(UTC) if status == "failed" else None,
            heartbeat_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()


def abort_request(db: Session, repo_id: uuid.UUID, run_id: uuid.UUID, message: str) -> None:
    """For callers that reserved a run but couldn't queue it (e.g. Redis was unreachable)."""
    _finish(db, repo_id, run_id, "failed", message)


# ---------- turning exceptions into retry / give-up decisions ----------


def classify(exc: Exception) -> TransientIndexError | IndexFailed | None:
    if isinstance(exc, LLMRateLimited):
        return TransientIndexError("The AI provider is rate limiting requests.")
    if isinstance(exc, LLMTimeout | LLMUnavailable):
        return TransientIndexError("The AI provider is slow or unavailable.")
    if isinstance(exc, LLMNotConfigured):
        return IndexFailed(str(exc))
    if isinstance(exc, LLMNotSupported):
        return IndexFailed("Embeddings are not configured. Set GEMINI_EMBEDDING_MODEL.")
    if isinstance(exc, LLMAuthError):
        return IndexFailed("The AI provider rejected the API key, or the key can't use the model.")
    if isinstance(exc, LLMInvalidOutput):  # our own message, safe to show
        return IndexFailed(f"The embedding model returned unusable data: {exc}")
    if isinstance(exc, LLMBadRequest | LLMBlocked):
        return IndexFailed(
            f"The embedding request was rejected ({exc.code}). Check GEMINI_EMBEDDING_MODEL."
        )
    if isinstance(exc, LLMError):
        return IndexFailed(f"AI error ({exc.code})")
    if isinstance(exc, GitHubRateLimited):
        return TransientIndexError("GitHub rate limit reached.")
    if isinstance(exc, GitHubError):
        if exc.status is None or exc.status >= 500:
            return TransientIndexError("GitHub is unreachable or failing.")
        if exc.status in (401, 403, 404, 410, 451):
            return IndexFailed(
                "GitHub denied access to this repository. Check the app's permissions "
                "(Contents: read) and that the repository is still shared with it."
            )
        if exc.status == 413:
            return IndexFailed(
                "The repository is larger than the allowed size. Exclude large folders with "
                "INDEX_EXCLUDE or raise INDEX_MAX_ARCHIVE_MB."
            )
        return IndexFailed(f"GitHub error ({exc.status}).")
    if isinstance(exc, tarfile.TarError | EOFError | zlib.error):
        return TransientIndexError("The repository download was interrupted or corrupted.")
    return None


# ---------- the run ----------


@dataclass
class _Pending:
    path: str
    content_hash: str
    language: str | None
    chunks: list[Chunk]
    skipped: int  # chunks dropped because they looked like credentials


def run_index(
    factory: sessionmaker[Session],
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    repo_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    final_attempt: bool = True,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Run one index job. Returns "ready", "failed", "skipped" (not ours or already done) or
    "busy" (this run is marked running by a worker that may be dead; try again after the
    heartbeat goes stale).

    A transient problem leaves the run queued and raises TransientIndexError so the job queue
    can retry later, unless `final_attempt` is set, in which case it is recorded as failed.
    """
    with factory() as db:
        if not claim_index(db, repo_id, run_id):
            current = db.get(RepositoryIndex, repo_id)
            if current and current.run_id == run_id and current.status == "running":
                return "busy"
            return "skipped"
        try:
            _index(db, github, get_llm, settings, repo_id, clock)
            return "ready"
        except Exception as exc:
            db.rollback()
            problem = (
                exc if isinstance(exc, IndexFailed | TransientIndexError) else classify(exc)
            )
            if problem is None:
                logger.exception("Indexing crashed for repository %s", repo_id)
                problem = IndexFailed("Unexpected error while indexing. See the server logs.")
            if isinstance(problem, TransientIndexError):
                if final_attempt:
                    _finish(db, repo_id, run_id, "failed", f"{problem} Click Re-index to continue.")
                    return "failed"
                _finish(db, repo_id, run_id, "queued", f"{problem} Retrying automatically.")
                raise problem from exc
            logger.warning("Indexing failed for repository %s: %s", repo_id, problem)
            _finish(db, repo_id, run_id, "failed", str(problem))
            return "failed"


def _index(
    db: Session,
    github: GitHubClient,
    get_llm: Callable[[], LLMService],
    settings: Settings,
    repo_id: uuid.UUID,
    clock: Callable[[], float],
) -> None:
    started = clock()
    limits = IndexLimits.from_settings(settings)
    rules = FileRules(limits.max_file_bytes, limits.extra_excludes)

    repo = db.get(Repository, repo_id)
    index = db.get(RepositoryIndex, repo_id)
    if repo is None or index is None:
        raise IndexFailed("This repository is no longer connected.")
    installation = db.get(GithubInstallation, repo.installation_id)
    if installation is None or installation.suspended_at is not None:
        raise IndexFailed("The GitHub installation is missing or suspended.")
    if not repo.default_branch:
        raise IndexFailed("This repository has no default branch yet.")
    if settings.embedding_dimensions != EMBEDDING_COLUMN_DIMENSIONS:
        raise IndexFailed(
            f"EMBEDDING_DIMENSIONS must be {EMBEDDING_COLUMN_DIMENSIONS} to match the database."
        )

    llm = get_llm()
    model = llm.embedding_model
    if model is None:
        raise IndexFailed("Embeddings are not configured. Set GEMINI_EMBEDDING_MODEL.")

    iid = installation.installation_id
    ctx = CallContext(feature="indexing", org_id=installation.org_id, user_id=index.requested_by)

    sha = github.installation_head_sha(iid, repo.full_name, repo.default_branch)
    stored = {
        f.path: f for f in db.scalars(select(IndexedFile).where(IndexedFile.repo_id == repo_id))
    }
    if sha is None:  # empty repository
        _remove_paths(db, repo_id, set(stored))
        _complete(db, index, None, model, files=0, skipped=0)
        return

    # Vectors from a different model can't be compared with new ones, so redo everything.
    reuse = {p: f for p, f in stored.items()} if index.embedding_model in (None, model) else {}

    seen: set[str] = set()
    pending: list[_Pending] = []
    pending_chunks = 0
    running_chunks = 0
    skipped_files = 0
    unpacked = 0

    def flush() -> None:
        nonlocal pending, pending_chunks
        if not pending:
            return
        texts = [embedding_text(f.path, c) for f in pending for c in f.chunks]
        vectors = llm.embed(texts, "document", ctx).vectors if texts else []
        if any(len(v) != EMBEDDING_COLUMN_DIMENSIONS for v in vectors):
            raise IndexFailed(
                f"The embedding model returns the wrong vector size (need "
                f"{EMBEDDING_COLUMN_DIMENSIONS}). Check GEMINI_EMBEDDING_MODEL."
            )
        vec = iter(vectors)
        for f in pending:
            db.execute(
                delete(CodeChunk).where(CodeChunk.repo_id == repo_id, CodeChunk.path == f.path)
            )
            db.add_all(
                CodeChunk(
                    repo_id=repo_id,
                    path=f.path,
                    start_line=c.start_line,
                    end_line=c.end_line,
                    language=f.language,
                    symbol=c.symbol,
                    content=c.text,
                    embedding=next(vec),
                )
                for c in f.chunks
            )
            db.merge(
                IndexedFile(
                    repo_id=repo_id,
                    path=f.path,
                    content_hash=f.content_hash,
                    chunk_count=len(f.chunks),
                    chunks_skipped=f.skipped,
                )
            )
        index.files_indexed = len(seen)
        index.chunks_total = running_chunks
        index.heartbeat_at = datetime.now(UTC)
        db.commit()  # progress is durable from here on
        pending, pending_chunks = [], 0

    with github.installation_archive(
        iid, repo.full_name, sha, max_bytes=limits.max_archive_bytes
    ) as stream:
        with tarfile.open(fileobj=stream, mode="r|gz") as tar:
            for member in tar:
                if not member.isreg():  # directories, links, devices: never followed
                    continue
                unpacked += member.size
                if unpacked > limits.max_unpacked_bytes:
                    raise IndexFailed(
                        "The repository is larger than the allowed size once unpacked. "
                        "Exclude large folders with INDEX_EXCLUDE."
                    )
                _, _, inner = member.name.partition("/")  # drop "<owner>-<repo>-<sha>/"
                path = clean_path(inner)
                if path is None or rules.skip_reason(path, member.size) is not None:
                    skipped_files += 1
                    continue
                handle = tar.extractfile(member)
                data = handle.read(limits.max_file_bytes + 1) if handle else b""
                text = _decode(data)
                if text is None:
                    skipped_files += 1
                    continue
                if len(seen) >= limits.max_files:
                    raise IndexFailed(
                        f"The repository has more than {limits.max_files} indexable files. "
                        "Exclude folders with INDEX_EXCLUDE or raise INDEX_MAX_FILES."
                    )
                seen.add(path)

                digest = hashlib.sha256(f"{CHUNKER_VERSION}\n".encode() + data).hexdigest()
                known = reuse.get(path)
                if known is not None and known.content_hash == digest:
                    running_chunks += known.chunk_count
                    continue

                chunks = chunk_file(text, language_of(path))
                kept = [c for c in chunks if not contains_secret(c.text)]
                running_chunks += len(kept)
                if running_chunks > limits.max_chunks:
                    raise IndexFailed(
                        f"The repository would need more than {limits.max_chunks} chunks. "
                        "Exclude folders with INDEX_EXCLUDE or raise INDEX_MAX_CHUNKS."
                    )
                pending.append(
                    _Pending(path, digest, language_of(path), kept, len(chunks) - len(kept))
                )
                pending_chunks += len(kept)
                if pending_chunks >= FLUSH_CHUNKS or len(pending) >= FLUSH_FILES:
                    flush()
                if clock() - started > limits.max_runtime_seconds:
                    flush()
                    raise TransientIndexError("Indexing is taking long; it will continue.")
    flush()

    _remove_paths(db, repo_id, set(stored) - seen)
    _complete(db, index, sha, model, files=len(seen), skipped=skipped_files)


def _decode(data: bytes) -> str | None:
    if b"\x00" in data:  # binary
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _remove_paths(db: Session, repo_id: uuid.UUID, paths: set[str]) -> None:
    listed = sorted(paths)
    for i in range(0, len(listed), DELETE_BATCH):
        batch = listed[i : i + DELETE_BATCH]
        db.execute(delete(CodeChunk).where(CodeChunk.repo_id == repo_id, CodeChunk.path.in_(batch)))
        db.execute(
            delete(IndexedFile).where(IndexedFile.repo_id == repo_id, IndexedFile.path.in_(batch))
        )
    db.commit()


def _complete(
    db: Session,
    index: RepositoryIndex,
    sha: str | None,
    model: str,
    *,
    files: int,
    skipped: int,
) -> None:
    index.status = "ready"
    index.commit_sha = sha
    index.embedding_model = model
    index.files_indexed = files
    index.files_skipped = skipped
    index.chunks_total = (
        db.scalar(
            select(func.count()).select_from(CodeChunk).where(CodeChunk.repo_id == index.repo_id)
        )
        or 0
    )
    index.chunks_skipped = int(
        db.scalar(
            select(func.coalesce(func.sum(IndexedFile.chunks_skipped), 0)).where(
                IndexedFile.repo_id == index.repo_id
            )
        )
        or 0
    )
    index.finished_at = datetime.now(UTC)
    index.heartbeat_at = datetime.now(UTC)
    index.error = None
    db.commit()
