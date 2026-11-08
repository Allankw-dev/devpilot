from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.db.models import Membership, Organization
from app.schemas import MeOut, OrgWithRole, UserOut

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeOut)
def me(user: CurrentUser, db: DbSession) -> MeOut:
    rows = db.execute(
        select(Organization, Membership.role)
        .join(Membership, Membership.org_id == Organization.id)
        .where(Membership.user_id == user.id)
        .order_by(Organization.name)
    ).all()
    return MeOut(
        user=UserOut.model_validate(user),
        organizations=[
            OrgWithRole(
                id=org.id,
                name=org.name,
                slug=org.slug,
                created_at=org.created_at,
                role=role,
            )
            for org, role in rows
        ],
    )
