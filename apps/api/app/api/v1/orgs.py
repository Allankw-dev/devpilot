import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminCtx, AnyMember, CurrentUser, DbSession, OwnerCtx
from app.core.roles import Role
from app.db.models import Membership, Organization, User
from app.schemas import (
    MemberAdd,
    MemberOut,
    MemberRoleUpdate,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    OrgWithRole,
)
from app.services import orgs as org_service

router = APIRouter(prefix="/orgs", tags=["organizations"])


def _member_out(m: Membership) -> MemberOut:
    return MemberOut(
        user_id=m.user_id,
        email=m.user.email,
        display_name=m.user.display_name,
        role=Role(m.role),
        joined_at=m.created_at,
    )


def _org_with_role(org: Organization, role: Role) -> OrgWithRole:
    return OrgWithRole(
        id=org.id, name=org.name, slug=org.slug, created_at=org.created_at, role=role
    )


@router.post("", response_model=OrgWithRole, status_code=status.HTTP_201_CREATED)
def create_org(body: OrgCreate, user: CurrentUser, db: DbSession) -> OrgWithRole:
    try:
        org = org_service.create_org(db, user, body.name)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Please try again") from None
    return _org_with_role(org, Role.owner)


@router.get("/{org_id}", response_model=OrgWithRole)
def get_org(ctx: AnyMember) -> OrgWithRole:
    return _org_with_role(ctx.org, ctx.role)


@router.patch("/{org_id}", response_model=OrgWithRole)
def rename_org(body: OrgUpdate, ctx: AdminCtx, db: DbSession) -> OrgWithRole:
    ctx.org.name = body.name
    db.commit()
    return _org_with_role(ctx.org, ctx.role)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_org(ctx: OwnerCtx, db: DbSession) -> None:
    db.delete(ctx.org)
    db.commit()


@router.get("/{org_id}/members", response_model=list[MemberOut])
def list_members(ctx: AnyMember, db: DbSession) -> list[MemberOut]:
    members = db.scalars(
        select(Membership).where(Membership.org_id == ctx.org.id).order_by(Membership.created_at)
    ).unique()
    return [_member_out(m) for m in members]


@router.post("/{org_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def add_member(body: MemberAdd, ctx: AdminCtx, db: DbSession) -> MemberOut:
    org_service.check_can_manage(ctx.role, None, body.role)

    target = db.scalar(select(User).where(User.email == body.email))
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No user with that email has signed in yet. Ask them to sign up first.",
        )
    if db.get(Membership, (ctx.org.id, target.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That user is already a member")

    membership = Membership(org_id=ctx.org.id, user_id=target.id, role=body.role.value)
    db.add(membership)
    db.commit()
    return _member_out(membership)


def _get_membership(db: DbSession, org_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    membership = db.get(Membership, (org_id, user_id))
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return membership


@router.patch("/{org_id}/members/{user_id}", response_model=MemberOut)
def change_role(
    user_id: uuid.UUID, body: MemberRoleUpdate, ctx: AdminCtx, db: DbSession
) -> MemberOut:
    membership = _get_membership(db, ctx.org.id, user_id)
    current = Role(membership.role)
    org_service.check_can_manage(ctx.role, current, body.role)
    org_service.guard_last_owner(db, ctx.org.id, current, body.role)
    membership.role = body.role.value
    db.commit()
    return _member_out(membership)


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(user_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> None:
    membership = _get_membership(db, ctx.org.id, user_id)
    current = Role(membership.role)

    if user_id != ctx.user.id:  # removing someone else needs management rights
        org_service.check_can_manage(ctx.role, current, None)
    org_service.guard_last_owner(db, ctx.org.id, current, None)

    org_service.remove_member(db, ctx.org.id, membership)
    db.commit()


__all__ = ["router", "OrgOut"]
