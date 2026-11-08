import re
import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import Role, rank
from app.db.models import Membership, Organization, Team, TeamMember, User


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return (slug or "org")[:90]


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    while db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        slug = f"{base}-{secrets.token_hex(2)}"
    return slug


def create_org(db: Session, user: User, name: str) -> Organization:
    org = Organization(name=name, slug=unique_slug(db, name), created_by=user.id)
    db.add(org)
    db.flush()
    db.add(Membership(org_id=org.id, user_id=user.id, role=Role.owner.value))
    db.flush()
    return org


def owner_count(db: Session, org_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.org_id == org_id, Membership.role == Role.owner.value)
        )
        or 0
    )


def check_can_manage(
    actor_role: Role, target_current: Role | None, target_new: Role | None
) -> None:
    """Who may add, change or remove members.

    Owners can do anything. Admins can only touch members below admin level, and can only
    grant member or viewer. Everyone else can't manage members.
    """
    if actor_role == Role.owner:
        return
    if actor_role == Role.admin:
        too_high_now = target_current is not None and rank(target_current) >= rank(Role.admin)
        too_high_new = target_new is not None and rank(target_new) >= rank(Role.admin)
        if too_high_now or too_high_new:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only an owner can manage admins and owners"
            )
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires admin role")


def guard_last_owner(
    db: Session, org_id: uuid.UUID, target_current: Role, target_new: Role | None
) -> None:
    """An organization must always keep at least one owner."""
    losing_owner = target_current == Role.owner and target_new != Role.owner
    if losing_owner and owner_count(db, org_id) <= 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An organization must keep at least one owner"
        )


def remove_member(db: Session, org_id: uuid.UUID, membership: Membership) -> None:
    team_ids = select(Team.id).where(Team.org_id == org_id)
    for tm in db.scalars(
        select(TeamMember).where(
            TeamMember.user_id == membership.user_id, TeamMember.team_id.in_(team_ids)
        )
    ):
        db.delete(tm)
    db.delete(membership)
