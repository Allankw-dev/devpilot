from enum import StrEnum


class Role(StrEnum):
    viewer = "viewer"
    member = "member"
    admin = "admin"
    owner = "owner"


_RANK = {Role.viewer: 1, Role.member: 2, Role.admin: 3, Role.owner: 4}


def rank(role: Role | str) -> int:
    return _RANK[Role(role)]


def at_least(role: Role | str, minimum: Role) -> bool:
    return rank(role) >= rank(minimum)
