import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.roles import Role

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    display_name: str | None


class OrgOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrgWithRole(OrgOut):
    role: Role


class MeOut(BaseModel):
    user: UserOut
    organizations: list[OrgWithRole]


class OrgCreate(BaseModel):
    name: Name


class OrgUpdate(BaseModel):
    name: Name


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None
    role: Role
    joined_at: datetime


class MemberAdd(BaseModel):
    email: Email
    role: Role = Role.member


class MemberRoleUpdate(BaseModel):
    role: Role


class TeamCreate(BaseModel):
    name: Name


class TeamOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    member_count: int = Field(ge=0)
    created_at: datetime


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str | None


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID
