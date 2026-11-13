"""Finding indexed code by meaning. Used by code search and by question answering.

Everything here is scoped to one organization: a chunk is only ever returned if its repository
belongs to an installation of that organization.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db.models import CodeChunk, GithubInstallation, IndexedFile, Repository

logger = logging.getLogger(__name__)

OVERFETCH = 4  # candidates per wanted result, so removing copies still leaves enough
MAX_ALSO_IN = 5
MAX_CANDIDATES = 100
_VECTOR_SETTINGS = ("hnsw.ef_search = 100", "hnsw.iterative_scan = 'relaxed_order'")


@dataclass
class Hit:
    repo_id: uuid.UUID
    repository: str
    path: str
    start_line: int
    end_line: int
    symbol: str | None
    language: str | None
    content: str
    score: float  # cosine similarity, higher is closer
    also_in: list[str] = field(default_factory=list)  # other files with exactly this code


# (db, org_id, query vector, optional repository, how many) -> best first
Retriever = Callable[[Session, uuid.UUID, Sequence[float], uuid.UUID | None, int], list[Hit]]


def _tune_vector_search(db: Session) -> None:
    """Best-effort settings so organization filtering doesn't starve the results. Older
    pgvector versions don't know some of them; that must not break the search."""
    for setting in _VECTOR_SETTINGS:
        try:
            with db.begin_nested():
                db.execute(text(f"SET LOCAL {setting}"))
        except DBAPIError:
            logger.debug("pgvector setting not available: %s", setting)


def search_hits(
    db: Session,
    org_id: uuid.UUID,
    vector: Sequence[float],
    repo_id: uuid.UUID | None,
    limit: int,
) -> list[Hit]:
    """The `limit` closest distinct pieces of code. Copies of the same code are collapsed into
    one hit that lists where else it appears."""
    _tune_vector_search(db)
    distance = CodeChunk.embedding.cosine_distance(list(vector))
    stmt = (
        select(CodeChunk, Repository.full_name, distance.label("distance"))
        .join(Repository, Repository.id == CodeChunk.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(GithubInstallation.org_id == org_id)  # never leaves the caller's organization
        .order_by(distance)
        .limit(min(limit * OVERFETCH, MAX_CANDIDATES))
    )
    if repo_id is not None:
        stmt = stmt.where(CodeChunk.repo_id == repo_id)

    hits: list[Hit] = []
    by_content: dict[str, Hit] = {}
    for chunk, full_name, dist in db.execute(stmt).all():
        first = by_content.get(chunk.content)
        if first is not None:  # the same code again: note where, don't repeat it
            where = chunk.path if first.repository == full_name else f"{full_name}: {chunk.path}"
            if len(first.also_in) < MAX_ALSO_IN and where not in first.also_in:
                first.also_in.append(where)
            continue
        if len(hits) >= limit:
            continue  # keep scanning only to credit copies of hits we already have
        hit = Hit(
            repo_id=chunk.repo_id,
            repository=full_name,
            path=chunk.path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            symbol=chunk.symbol,
            language=chunk.language,
            content=chunk.content,
            score=round(1.0 - float(dist), 4),
        )
        by_content[chunk.content] = hit
        hits.append(hit)
    return hits


def file_list(db: Session, org_id: uuid.UUID, repo_id: uuid.UUID, limit: int = 300) -> list[str]:
    """Paths of the indexed files of one repository, shallow ones first. Gives a model a map
    of the project without any file contents."""
    paths = db.scalars(
        select(IndexedFile.path)
        .join(Repository, Repository.id == IndexedFile.repo_id)
        .join(GithubInstallation, GithubInstallation.id == Repository.installation_id)
        .where(IndexedFile.repo_id == repo_id, GithubInstallation.org_id == org_id)
    ).all()
    return sorted(paths, key=lambda p: (p.count("/"), p))[:limit]
