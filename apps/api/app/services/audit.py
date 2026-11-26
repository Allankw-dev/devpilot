"""The audit log: who did what in an organization.

`record_audit` adds a row to the caller's session, so it is committed (or rolled back) together
with the action it describes. Every event is also written to the application log (logger
`app.audit`) with the request id, which survives even when an organization and its rows are deleted.

Never put secrets, tokens, prompts, replies or code in `details`; keep it to short facts such as
a role name or a repository name.
"""

import json
import logging
import uuid

from sqlalchemy.orm import Session

from app.core.request_context import get_request_id
from app.db.models import AuditLog

logger = logging.getLogger("app.audit")

_MAX_DETAILS_CHARS = 2000


def record_audit(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: object | None = None,
    details: dict[str, object] | None = None,
    persist: bool = True,
) -> None:
    """`persist=False` writes only the log line (used when the organization is being deleted)."""
    target = str(target_id)[:64] if target_id is not None else None
    if details is not None and len(json.dumps(details, default=str)) > _MAX_DETAILS_CHARS:
        details = {"truncated": True}
    request_id = get_request_id()

    logger.info(
        action,
        extra={
            "audit": {
                "org_id": str(org_id),
                "actor_id": str(actor_id) if actor_id else None,
                "action": action,
                "target_type": target_type,
                "target_id": target,
            }
        },
    )
    if persist:
        db.add(
            AuditLog(
                org_id=org_id,
                actor_id=actor_id,
                action=action[:60],
                target_type=target_type,
                target_id=target,
                details=json.loads(json.dumps(details, default=str)) if details else None,
                request_id=request_id,
            )
        )
