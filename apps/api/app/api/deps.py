import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.roles import Role, at_least
from app.core.security import AuthError, AuthUnavailable, TokenVerifier, get_token_verifier
from app.db.models import Membership, Organization, User
from app.db.session import get_db, get_session_factory
from app.services.github.client import GitHubClient
from app.services.llm.errors import LLMNotConfigured
from app.services.llm.factory import get_llm_service
from app.services.llm.service import LLMService
from app.services.users import sync_user

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    db: DbSession,
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if creds is None:
        raise unauthorized
    try:
        claims = verifier.verify(creds.credentials)
    except AuthUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except AuthError as exc:
        unauthorized.detail = str(exc)
        raise unauthorized from exc
    return sync_user(db, claims)


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass
class OrgContext:
    org: Organization
    membership: Membership
    user: User

    @property
    def role(self) -> Role:
        return Role(self.membership.role)


def get_org_context(org_id: uuid.UUID, user: CurrentUser, db: DbSession) -> OrgContext:
    """Load the org and the caller's membership. Non-members get 404, so org ids don't leak."""
    row = db.execute(
        select(Organization, Membership)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Organization.id == org_id, Membership.user_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return OrgContext(org=row[0], membership=row[1], user=user)


def require_role(minimum: Role) -> Callable[[OrgContext], OrgContext]:
    def dependency(ctx: Annotated[OrgContext, Depends(get_org_context)]) -> OrgContext:
        if not at_least(ctx.role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires {minimum.value} role")
        return ctx

    return dependency


AnyMember = Annotated[OrgContext, Depends(get_org_context)]
AdminCtx = Annotated[OrgContext, Depends(require_role(Role.admin))]
OwnerCtx = Annotated[OrgContext, Depends(require_role(Role.owner))]


@lru_cache
def get_github_client() -> GitHubClient:
    return GitHubClient(get_settings())


def get_session_factory_dep() -> sessionmaker[Session]:
    return get_session_factory()


def get_llm() -> LLMService:
    """The configured AI service, or a 503 naming the settings that are still missing."""
    try:
        return get_llm_service()
    except LLMNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
