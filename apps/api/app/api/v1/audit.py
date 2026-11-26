import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, or_, select

from app.api.deps import AdminCtx, DbSession
from app.db.models import AuditLog, User
from app.schemas import AuditLogOut, AuditLogPage

router = APIRouter(tags=["audit"])


@router.get("/orgs/{org_id}/audit-log", response_model=AuditLogPage)
def list_audit_log(
    ctx: AdminCtx,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[
        uuid.UUID | None, Query(description="`next_before` from the previous page")
    ] = None,
    action: Annotated[str | None, Query(max_length=60, description="Only this action")] = None,
) -> AuditLogPage:
    """Who did what in this organization, newest first. Admins and owners only. Read-only: nothing
    in the API edits or deletes an entry."""
    query = (
        select(AuditLog, User)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.org_id == ctx.org.id)
    )
    if action:
        query = query.where(AuditLog.action == action)
    if before is not None:
        cursor = db.scalar(
            select(AuditLog).where(AuditLog.id == before, AuditLog.org_id == ctx.org.id)
        )
        if cursor is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown page marker")
        query = query.where(
            or_(
                AuditLog.created_at < cursor.created_at,
                and_(AuditLog.created_at == cursor.created_at, AuditLog.id < cursor.id),
            )
        )
    rows = db.execute(
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    ).all()

    page = rows[:limit]
    return AuditLogPage(
        items=[
            AuditLogOut(
                id=entry.id,
                action=entry.action,
                actor_id=entry.actor_id,
                actor_email=actor.email if actor else None,
                actor_name=actor.display_name if actor else None,
                target_type=entry.target_type,
                target_id=entry.target_id,
                details=entry.details,
                request_id=entry.request_id,
                created_at=entry.created_at,
            )
            for entry, actor in page
        ],
        next_before=page[-1][0].id if len(rows) > limit else None,
    )
