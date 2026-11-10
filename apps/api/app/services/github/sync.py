"""Pulling GitHub data into our database.

All upserts live here and are shared by the full sync and the webhook handlers, so both
paths store data identically. Only what the dashboards need is kept: no PR/issue bodies
and no file contents. Anything text-heavy is fetched fresh when an AI feature needs it.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import (
    Commit,
    GithubInstallation,
    Issue,
    PullRequest,
    Repository,
    WorkflowRun,
)
from app.services.github.client import GitHubClient, GitHubError, GitHubRateLimited

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=15)
MAX_REPOS_PER_SYNC = 100


# ---------- small helpers ----------


def ts(value: object) -> datetime | None:
    """GitHub sends ISO-8601 strings, and epoch seconds in a few webhook fields."""
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def clip(value: object, length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:length]


def _login(user: Any) -> str | None:
    return clip(user.get("login"), 100) if isinstance(user, dict) else None


# ---------- upserts (shared by sync and webhooks) ----------


def apply_repo_fields(repo: Repository, item: dict[str, Any]) -> None:
    owner = item.get("owner") or {}
    repo.full_name = clip(item["full_name"], 200) or ""
    repo.name = clip(item.get("name"), 100) or repo.full_name.split("/")[-1]
    repo.owner_login = clip(owner.get("login"), 100) or repo.full_name.split("/")[0]
    repo.private = bool(item.get("private", False))
    repo.archived = bool(item.get("archived", False))
    repo.default_branch = clip(item.get("default_branch"), 100)
    repo.description = clip(item.get("description"), 500)
    repo.html_url = clip(item.get("html_url"), 300) or ""
    repo.language = clip(item.get("language"), 50)
    pushed = ts(item.get("pushed_at"))
    if pushed:
        repo.pushed_at = pushed


def upsert_repositories(
    db: Session, installation: GithubInstallation, items: list[dict[str, Any]]
) -> list[Repository]:
    existing = {
        r.github_id: r
        for r in db.scalars(select(Repository).where(Repository.installation_id == installation.id))
    }
    seen: set[int] = set()
    for item in items:
        gid = int(item["id"])
        seen.add(gid)
        repo = existing.get(gid)
        if repo is None:
            repo = Repository(installation_id=installation.id, github_id=gid)
            db.add(repo)
            existing[gid] = repo
        apply_repo_fields(repo, item)
    for gid in [g for g in existing if g not in seen]:  # no longer shared with the app
        db.delete(existing.pop(gid))
    db.flush()
    return list(existing.values())


def upsert_pull_requests(db: Session, repo_id: Any, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    numbers = [int(i["number"]) for i in items]
    existing = {
        p.number: p
        for p in db.scalars(
            select(PullRequest).where(
                PullRequest.repo_id == repo_id, PullRequest.number.in_(numbers)
            )
        )
    }
    for item in items:
        number = int(item["number"])
        pr = existing.get(number)
        if pr is None:
            pr = PullRequest(repo_id=repo_id, number=number)
            db.add(pr)
            existing[number] = pr
        pr.title = clip(item.get("title"), 300) or ""
        pr.state = "open" if item.get("state") == "open" else "closed"
        pr.draft = bool(item.get("draft", False))
        pr.merged = bool(item.get("merged")) or item.get("merged_at") is not None
        pr.author_login = _login(item.get("user"))
        pr.html_url = clip(item.get("html_url"), 300) or ""
        pr.gh_created_at = ts(item.get("created_at"))
        pr.gh_updated_at = ts(item.get("updated_at"))
        pr.gh_closed_at = ts(item.get("closed_at"))


def upsert_issues(db: Session, repo_id: Any, items: list[dict[str, Any]]) -> None:
    items = [i for i in items if "pull_request" not in i]  # the issues API also lists PRs
    if not items:
        return
    numbers = [int(i["number"]) for i in items]
    existing = {
        i.number: i
        for i in db.scalars(
            select(Issue).where(Issue.repo_id == repo_id, Issue.number.in_(numbers))
        )
    }
    for item in items:
        number = int(item["number"])
        issue = existing.get(number)
        if issue is None:
            issue = Issue(repo_id=repo_id, number=number)
            db.add(issue)
            existing[number] = issue
        issue.title = clip(item.get("title"), 300) or ""
        issue.state = "open" if item.get("state") == "open" else "closed"
        issue.author_login = _login(item.get("user"))
        issue.html_url = clip(item.get("html_url"), 300) or ""
        issue.comments = int(item.get("comments") or 0)
        issue.gh_created_at = ts(item.get("created_at"))
        issue.gh_updated_at = ts(item.get("updated_at"))
        issue.gh_closed_at = ts(item.get("closed_at"))


def upsert_commits(db: Session, repo_id: Any, commits: list[dict[str, Any]]) -> None:
    """`commits` are already normalised: sha, message, author_login, author_name, at, url."""
    if not commits:
        return
    shas = [c["sha"] for c in commits]
    existing = {
        c.sha: c
        for c in db.scalars(select(Commit).where(Commit.repo_id == repo_id, Commit.sha.in_(shas)))
    }
    for c in commits:
        row = existing.get(c["sha"])
        if row is None:
            row = Commit(repo_id=repo_id, sha=c["sha"])
            db.add(row)
            existing[c["sha"]] = row
        row.message_headline = (
            clip((c["message"] or "").splitlines()[0] if c["message"] else "", 300) or ""
        )
        row.author_login = clip(c.get("author_login"), 100)
        row.author_name = clip(c.get("author_name"), 200)
        row.committed_at = c.get("at")
        row.html_url = clip(c.get("url"), 300)


def commit_from_api(item: dict[str, Any]) -> dict[str, Any]:
    commit = item.get("commit") or {}
    author = commit.get("author") or {}
    committer = commit.get("committer") or {}
    return {
        "sha": str(item["sha"]),
        "message": commit.get("message") or "",
        "author_login": _login(item.get("author")),
        "author_name": author.get("name"),
        "at": ts(author.get("date") or committer.get("date")),
        "url": item.get("html_url"),
    }


def commit_from_push(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") or {}
    return {
        "sha": str(item["id"]),
        "message": item.get("message") or "",
        "author_login": author.get("username"),
        "author_name": author.get("name"),
        "at": ts(item.get("timestamp")),
        "url": item.get("url"),
    }


def upsert_workflow_runs(db: Session, repo_id: Any, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    ids = [int(i["id"]) for i in items]
    existing = {
        r.run_id: r
        for r in db.scalars(
            select(WorkflowRun).where(WorkflowRun.repo_id == repo_id, WorkflowRun.run_id.in_(ids))
        )
    }
    for item in items:
        run_id = int(item["id"])
        run = existing.get(run_id)
        if run is None:
            run = WorkflowRun(repo_id=repo_id, run_id=run_id)
            db.add(run)
            existing[run_id] = run
        run.name = clip(item.get("name"), 200)
        run.event = clip(item.get("event"), 40)
        run.status = clip(item.get("status"), 20)
        run.conclusion = clip(item.get("conclusion"), 20)
        run.head_branch = clip(item.get("head_branch"), 200)
        run.head_sha = clip(item.get("head_sha"), 40)
        run.run_number = item.get("run_number")
        run.html_url = clip(item.get("html_url"), 300)
        run.gh_created_at = ts(item.get("created_at"))
        run.gh_updated_at = ts(item.get("updated_at"))


def close_vanished_open_items(
    db: Session, model: type[PullRequest] | type[Issue], repo_id: Any, open_numbers: set[int]
) -> None:
    """After a *complete* listing of open items, anything we still have as open has closed."""
    db.execute(
        update(model)
        .where(model.repo_id == repo_id, model.state == "open", model.number.not_in(open_numbers))
        .values(state="closed")
    )


# ---------- full sync ----------


def _soft[T](call: Callable[[], T], default: T) -> T:
    """Run a GitHub call; treat 'empty repo', 'not found', 'no permission' and 'issues
    disabled' (410, common on forks) as no data instead of failing the whole repository."""
    try:
        return call()
    except GitHubRateLimited:
        raise
    except GitHubError as exc:
        if exc.status in (403, 404, 409, 410):
            return default
        raise


def sync_repository(
    db: Session, client: GitHubClient, installation: GithubInstallation, repo: Repository
) -> None:
    iid, full = installation.installation_id, repo.full_name

    open_prs, prs_complete = client.installation_paginate(
        iid,
        f"/repos/{full}/pulls",
        {"state": "open", "sort": "updated", "direction": "desc"},
        max_pages=3,
    )
    recent_closed_prs = client.installation_get(
        iid,
        f"/repos/{full}/pulls",
        {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50},
    )
    upsert_pull_requests(db, repo.id, open_prs + recent_closed_prs)
    if prs_complete:
        close_vanished_open_items(db, PullRequest, repo.id, {int(p["number"]) for p in open_prs})

    # incomplete, so nothing is marked closed just because the listing was unavailable
    no_listing: tuple[list[dict[str, Any]], bool] = ([], False)
    listing = _soft(
        lambda: client.installation_paginate(
            iid,
            f"/repos/{full}/issues",
            {"state": "open", "sort": "updated", "direction": "desc"},
            max_pages=3,
        ),
        no_listing,
    )
    open_issues_raw, issues_complete = listing
    recent_closed_issues: list[dict[str, Any]] = _soft(
        lambda: client.installation_get(
            iid,
            f"/repos/{full}/issues",
            {"state": "closed", "sort": "updated", "direction": "desc", "per_page": 50},
        ),
        [],
    )
    open_issues = [i for i in open_issues_raw if "pull_request" not in i]
    upsert_issues(db, repo.id, open_issues + recent_closed_issues)
    if issues_complete:
        close_vanished_open_items(db, Issue, repo.id, {int(i["number"]) for i in open_issues})

    commits: list[dict[str, Any]] = _soft(
        lambda: client.installation_get(iid, f"/repos/{full}/commits", {"per_page": 30}), []
    )
    upsert_commits(db, repo.id, [commit_from_api(c) for c in commits])

    runs: dict[str, Any] = _soft(
        lambda: client.installation_get(iid, f"/repos/{full}/actions/runs", {"per_page": 20}), {}
    )
    upsert_workflow_runs(db, repo.id, runs.get("workflow_runs", []))


def begin_sync(db: Session, installation_pk: Any) -> bool:
    """Atomically claim the sync slot. False if another sync is already running."""
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        db.execute(
            update(GithubInstallation)
            .where(
                GithubInstallation.id == installation_pk,
                or_(
                    GithubInstallation.sync_status != "running",
                    GithubInstallation.sync_started_at < now - STALE_AFTER,
                ),
            )
            .values(sync_status="running", sync_started_at=now, sync_error=None)
            # the database does the comparison; don't re-evaluate it in Python on loaded rows
            .execution_options(synchronize_session=False)
        ),
    )
    db.commit()
    return result.rowcount == 1


def run_sync(
    factory: sessionmaker[Session],
    client: GitHubClient,
    installation_pk: Any,
    *,
    claimed: bool = False,
) -> bool:
    """Sync one installation. Safe to run as a background task: it owns its session.

    `claimed=True` means the caller already called begin_sync(), so an API response could
    report "running" straight away.
    """
    with factory() as db:
        if not claimed and not begin_sync(db, installation_pk):
            return False

        status, error = "idle", None
        try:
            installation = db.get(GithubInstallation, installation_pk)
            if installation is None:
                return False
            error = _sync_installation(db, client, installation)
        except GitHubRateLimited as exc:
            db.rollback()
            status = "failed"
            when = (
                datetime.fromtimestamp(exc.reset_at, UTC).strftime("%H:%M UTC")
                if exc.reset_at
                else "later"
            )
            error = f"GitHub rate limit reached. Try again after {when}."
        except GitHubError as exc:
            db.rollback()
            status = "failed"
            error = (
                "This installation was not found on GitHub. Reconnect it."
                if exc.status == 404
                else clip(f"GitHub error: {exc}", 500)
            )
        except Exception:
            db.rollback()
            logger.exception("GitHub sync crashed")
            status, error = "failed", "Unexpected error during sync"

        installation = db.get(GithubInstallation, installation_pk)
        if installation is not None:
            installation.sync_status = status
            installation.sync_error = error
            if status == "idle":
                installation.last_synced_at = datetime.now(UTC)
            db.commit()
        return status == "idle"


def _sync_installation(
    db: Session, client: GitHubClient, installation: GithubInstallation
) -> str | None:
    items, _ = client.installation_paginate(
        installation.installation_id, "/installation/repositories", key="repositories", max_pages=10
    )
    repos = upsert_repositories(db, installation, items)
    db.commit()

    repos.sort(key=lambda r: r.pushed_at.timestamp() if r.pushed_at else 0, reverse=True)
    failures = 0
    for repo in repos[:MAX_REPOS_PER_SYNC]:
        try:
            sync_repository(db, client, installation, repo)
            db.commit()
        except GitHubRateLimited:
            raise
        except GitHubError:
            db.rollback()
            failures += 1
            logger.warning("Could not sync repository %s", repo.full_name)
    if failures:
        total = min(len(repos), MAX_REPOS_PER_SYNC)
        return f"{failures} of {total} repositories could not be fully synced"
    if len(repos) > MAX_REPOS_PER_SYNC:
        return f"Synced the {MAX_REPOS_PER_SYNC} most recently active of {len(repos)} repositories"
    return None
