from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import TokenClaims
from app.db.models import User


def sync_user(db: Session, claims: TokenClaims) -> User:
    """Create the profile row on first sight of a Supabase user; keep email/name current."""
    user = db.get(User, claims.user_id)

    if user is None:
        user = User(id=claims.user_id, email=claims.email, display_name=claims.display_name)
        db.add(user)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            # Either a concurrent first request created it, or the email belongs to another id.
            existing = db.get(User, claims.user_id)
            if existing is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "An account with this email already exists"
                ) from None
            return existing
        return user

    changed = False
    if user.email != claims.email:
        user.email = claims.email
        changed = True
    if claims.display_name and user.display_name != claims.display_name:
        user.display_name = claims.display_name
        changed = True
    if changed:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That email is already used by another account"
            ) from None
    return user
