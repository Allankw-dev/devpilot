"""Applying verified GitHub webhook events to our database.

The signature is checked by the endpoint before anything here runs. Payload text is still
treated as data: it is stored (clipped), never executed or interpreted.
"""

import hashlib
import hmac
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GithubInstallation, Repository
from app.services.github import sync


def valid_signature(secret: str, body: bytes, header: str | None) -> bool:
    """GitHub sends `X-Hub-Signature-256: sha256=<hex hmac of the raw body>`."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def _installation(db: Session, payload: dict[str, Any]) -> GithubInstallation | None:
    installation_id = (payload.get("installation") or {}).get("id")
    if installation_id is None:
        return None
    return db.scalar(
        select(GithubInstallation).where(GithubInstallation.installation_id == int(installation_id))
    )


def _repository(
    db: Session, installation: GithubInstallation, payload: dict[str, Any]
) -> Repository | None:
    repo_id = (payload.get("repository") or {}).get("id")
    if repo_id is None:
        return None
    return db.scalar(
        select(Repository).where(
            Repository.installation_id == installation.id, Repository.github_id == int(repo_id)
        )
    )


def process_event(
    db: Session,
    event: str,
    payload: dict[str, Any],
    schedule_sync: Callable[[uuid.UUID], None],
) -> str:
    """Returns a short outcome label. Unknown installations/repos are ignored, not errors."""
    if event == "ping":
        return "pong"

    installation = _installation(db, payload)
    if installation is None:
        return "ignored: unknown installation"

    action = payload.get("action")

    if event == "installation":
        if action == "deleted":
            db.delete(installation)
            return "installation removed"
        if action == "suspend":
            suspended = sync.ts((payload.get("installation") or {}).get("suspended_at"))
            installation.suspended_at = suspended or datetime.now(UTC)
            return "installation suspended"
        if action == "unsuspend":
            installation.suspended_at = None
            return "installation resumed"
        return "ignored"

    if event == "installation_repositories":
        schedule_sync(installation.id)
        return "sync scheduled"

    repo = _repository(db, installation, payload)
    if repo is None:
        return "ignored: unknown repository"

    if event == "repository":
        sync.apply_repo_fields(repo, payload["repository"])
        return "repository updated"

    if event == "push":
        ref = str(payload.get("ref", ""))
        head = payload.get("head_commit") or {}
        pushed = sync.ts(head.get("timestamp"))
        if pushed:
            repo.pushed_at = pushed
        if repo.default_branch and ref == f"refs/heads/{repo.default_branch}":
            sync.upsert_commits(
                db,
                repo.id,
                [sync.commit_from_push(c) for c in payload.get("commits", []) if c.get("id")],
            )
            return "commits recorded"
        return "ignored: not the default branch"

    if event == "pull_request" and isinstance(payload.get("pull_request"), dict):
        sync.upsert_pull_requests(db, repo.id, [payload["pull_request"]])
        return "pull request recorded"

    if event == "issues" and isinstance(payload.get("issue"), dict):
        sync.upsert_issues(db, repo.id, [payload["issue"]])
        return "issue recorded"

    if event == "workflow_run" and isinstance(payload.get("workflow_run"), dict):
        sync.upsert_workflow_runs(db, repo.id, [payload["workflow_run"]])
        return "workflow run recorded"

    return "ignored: event not handled"
