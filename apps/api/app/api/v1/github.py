import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import (
    AdminCtx,
    AnyMember,
    CurrentUser,
    DbSession,
    JobsDep,
    get_github_client,
)
from app.core.config import Settings, get_settings
from app.core.roles import Role, at_least
from app.db.models import GithubConnectRequest, GithubInstallation, Membership
from app.jobs.dispatch import JobQueueUnavailable
from app.schemas import (
    ClaimRequest,
    GithubInstallationOut,
    GithubStatusOut,
    InstallUrlOut,
)
from app.services.github.client import (
    GitHubClient,
    GitHubError,
    GitHubNotConfigured,
    GitHubRateLimited,
)
from app.services.github.sync import begin_sync, release_sync

router = APIRouter(tags=["github"])

CONNECT_LINK_LIFETIME = timedelta(minutes=30)

Client = Annotated[GitHubClient, Depends(get_github_client)]
Config = Annotated[Settings, Depends(get_settings)]


def _out(i: GithubInstallation) -> GithubInstallationOut:
    return GithubInstallationOut(
        id=i.id,
        org_id=i.org_id,
        installation_id=i.installation_id,
        account_login=i.account_login,
        account_type=i.account_type,
        repository_selection=i.repository_selection,
        suspended=i.suspended_at is not None,
        sync_status=i.sync_status,
        sync_error=i.sync_error,
        last_synced_at=i.last_synced_at,
        created_at=i.created_at,
    )


def _require_configured(settings: Settings) -> None:
    missing = settings.github_missing_settings()
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GitHub integration is not configured. Missing: " + ", ".join(missing),
        )


@router.get("/orgs/{org_id}/github", response_model=GithubStatusOut)
def github_status(ctx: AnyMember, db: DbSession, settings: Config) -> GithubStatusOut:
    missing = settings.github_missing_settings()
    installations = db.scalars(
        select(GithubInstallation)
        .where(GithubInstallation.org_id == ctx.org.id)
        .order_by(GithubInstallation.created_at)
    )
    return GithubStatusOut(
        configured=not missing,
        missing=missing if at_least(ctx.role, Role.admin) else [],
        installations=[_out(i) for i in installations],
    )


@router.post("/orgs/{org_id}/github/install-url", response_model=InstallUrlOut)
def install_url(ctx: AdminCtx, db: DbSession, settings: Config) -> InstallUrlOut:
    _require_configured(settings)
    now = datetime.now(UTC)
    db.execute(delete(GithubConnectRequest).where(GithubConnectRequest.expires_at < now))
    nonce = secrets.token_urlsafe(32)
    db.add(
        GithubConnectRequest(
            nonce=nonce,
            org_id=ctx.org.id,
            user_id=ctx.user.id,
            expires_at=now + CONNECT_LINK_LIFETIME,
        )
    )
    db.commit()
    base = settings.github_web_url.rstrip("/")
    slug = quote(settings.github_app_slug or "", safe="")
    return InstallUrlOut(url=f"{base}/apps/{slug}/installations/new?state={nonce}")


@router.post("/github/installations/claim", response_model=GithubInstallationOut)
def claim_installation(
    body: ClaimRequest,
    user: CurrentUser,
    db: DbSession,
    client: Client,
    settings: Config,
    jobs: JobsDep,
) -> GithubInstallationOut:
    """Finish the GitHub App install. GitHub redirects the browser here with an editable
    installation_id, so it is never trusted by itself: the user must prove, with GitHub's
    one-time code, that they can actually access that installation."""
    _require_configured(settings)
    now = datetime.now(UTC)
    expired = HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "This connect link expired. Start again from your organization page.",
    )

    # 1. Which organization was this admin connecting?
    pending: GithubConnectRequest | None
    if body.state:
        pending = db.get(GithubConnectRequest, body.state)
        if pending is not None and pending.user_id != user.id:
            pending = None
    else:  # GitHub doesn't always echo `state`; fall back to this user's latest request
        pending = db.scalar(
            select(GithubConnectRequest)
            .where(GithubConnectRequest.user_id == user.id, GithubConnectRequest.expires_at > now)
            .order_by(GithubConnectRequest.created_at.desc())
        )
    if pending is None or pending.expires_at.replace(tzinfo=pending.expires_at.tzinfo or UTC) < now:
        raise expired

    membership = db.get(Membership, (pending.org_id, user.id))
    if membership is None or not at_least(Role(membership.role), Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires admin role")

    # 2. Prove this user can access the installation they are claiming.
    try:
        user_token = client.exchange_code(body.code)
        accessible = client.user_installation_ids(user_token)
        del user_token  # used once, never stored
        if body.installation_id not in accessible:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You don't have access to that GitHub installation"
            )
        info = client.get_installation(body.installation_id)
    except GitHubNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except GitHubRateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "GitHub is rate limiting us"
        ) from exc
    except GitHubError as exc:
        if exc.status is None or exc.status >= 500:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach GitHub") from exc
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "GitHub did not accept the authorization. Start again from your organization page.",
        ) from exc

    # 3. Link it (one GitHub installation belongs to exactly one organization).
    installation = db.scalar(
        select(GithubInstallation).where(GithubInstallation.installation_id == body.installation_id)
    )
    if installation is not None and installation.org_id != pending.org_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That GitHub installation is already connected to another organization",
        )
    account = info.get("account") or {}
    if installation is None:
        installation = GithubInstallation(
            org_id=pending.org_id, installation_id=body.installation_id, connected_by=user.id
        )
        db.add(installation)
    installation.account_id = int(account.get("id") or 0)
    installation.account_login = str(account.get("login") or "unknown")[:100]
    installation.account_type = str(account.get("type") or "User")[:20]
    installation.repository_selection = str(info.get("repository_selection") or "all")[:10]
    installation.suspended_at = None if not info.get("suspended_at") else now
    db.delete(pending)  # single use
    db.commit()

    if begin_sync(db, installation.id):
        db.refresh(installation)
        reported = _out(installation)  # says "running", whatever the job does next
        try:
            jobs.sync_installation(installation.id, claimed=True)
        except JobQueueUnavailable as exc:
            # The connection itself succeeded, so keep it and say why the first sync didn't start.
            release_sync(db, installation.id, str(exc))
            db.refresh(installation)
            return _out(installation)
        return reported
    return _out(installation)


def _get_installation(db: Session, ctx_org_id: uuid.UUID, pk: uuid.UUID) -> GithubInstallation:
    installation = db.scalar(
        select(GithubInstallation).where(
            GithubInstallation.id == pk, GithubInstallation.org_id == ctx_org_id
        )
    )
    if installation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "GitHub installation not found")
    return installation


@router.post(
    "/orgs/{org_id}/github/installations/{installation_pk}/sync",
    response_model=GithubInstallationOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_sync(
    installation_pk: uuid.UUID,
    ctx: AdminCtx,
    db: DbSession,
    settings: Config,
    jobs: JobsDep,
) -> GithubInstallationOut:
    _require_configured(settings)
    installation = _get_installation(db, ctx.org.id, installation_pk)
    if installation.suspended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This installation is suspended on GitHub")
    if not begin_sync(db, installation.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A sync is already running")
    db.refresh(installation)
    reported = _out(installation)
    try:
        jobs.sync_installation(installation.id, claimed=True)
    except JobQueueUnavailable as exc:
        release_sync(db, installation.id, str(exc))
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return reported


@router.delete(
    "/orgs/{org_id}/github/installations/{installation_pk}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def disconnect(installation_pk: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    """Removes the connection and our copy of its data. It does not uninstall the app on GitHub."""
    db.delete(_get_installation(db, ctx.org.id, installation_pk))
    db.commit()
