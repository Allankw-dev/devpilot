import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AdminCtx, AnyMember, DbSession
from app.db.models import Membership, Team, TeamMember
from app.schemas import TeamCreate, TeamMemberAdd, TeamMemberOut, TeamOut

router = APIRouter(prefix="/orgs/{org_id}/teams", tags=["teams"])


def _get_team(db: DbSession, org_id: uuid.UUID, team_id: uuid.UUID) -> Team:
    team = db.scalar(select(Team).where(Team.id == team_id, Team.org_id == org_id))
    if team is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team not found")
    return team


def _team_out(team: Team, member_count: int) -> TeamOut:
    return TeamOut(
        id=team.id,
        org_id=team.org_id,
        name=team.name,
        member_count=member_count,
        created_at=team.created_at,
    )


@router.get("", response_model=list[TeamOut])
def list_teams(ctx: AnyMember, db: DbSession) -> list[TeamOut]:
    rows = db.execute(
        select(Team, func.count(TeamMember.user_id))
        .outerjoin(TeamMember, TeamMember.team_id == Team.id)
        .where(Team.org_id == ctx.org.id)
        .group_by(Team.id)
        .order_by(Team.name)
    ).all()
    return [_team_out(team, count) for team, count in rows]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(body: TeamCreate, ctx: AdminCtx, db: DbSession) -> TeamOut:
    team = Team(org_id=ctx.org.id, name=body.name)
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A team with that name already exists"
        ) from None
    return _team_out(team, 0)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(team_id: uuid.UUID, ctx: AdminCtx, db: DbSession) -> None:
    db.delete(_get_team(db, ctx.org.id, team_id))
    db.commit()


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
def list_team_members(team_id: uuid.UUID, ctx: AnyMember, db: DbSession) -> list[TeamMemberOut]:
    team = _get_team(db, ctx.org.id, team_id)
    members = db.scalars(
        select(TeamMember).where(TeamMember.team_id == team.id).order_by(TeamMember.created_at)
    ).unique()
    return [
        TeamMemberOut(user_id=m.user_id, email=m.user.email, display_name=m.user.display_name)
        for m in members
    ]


@router.post(
    "/{team_id}/members", response_model=TeamMemberOut, status_code=status.HTTP_201_CREATED
)
def add_team_member(
    team_id: uuid.UUID, body: TeamMemberAdd, ctx: AdminCtx, db: DbSession
) -> TeamMemberOut:
    team = _get_team(db, ctx.org.id, team_id)

    if db.get(Membership, (ctx.org.id, body.user_id)) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That user is not a member of this organization"
        )
    if db.get(TeamMember, (team.id, body.user_id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "That user is already on this team")

    tm = TeamMember(team_id=team.id, user_id=body.user_id)
    db.add(tm)
    db.commit()
    return TeamMemberOut(user_id=tm.user_id, email=tm.user.email, display_name=tm.user.display_name)


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, ctx: AdminCtx, db: DbSession
) -> None:
    team = _get_team(db, ctx.org.id, team_id)
    tm = db.get(TeamMember, (team.id, user_id))
    if tm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found")
    db.delete(tm)
    db.commit()
