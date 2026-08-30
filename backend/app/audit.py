"""
The single write path for AuditLog (app/models.py) — persistent security/business
accountability, distinct from the operational logging in app/logging_config.py.

Only security- or accountability-relevant actions are recorded here, deliberately not every
pipeline event (those stay in the application log): login success/failure, authorization
denial, and metric create/delete — the real admin-mutation endpoints this app actually has.
There is no playbook CRUD, configuration-change, or suppression-review endpoint in this
codebase to audit; recording those would mean fabricating actions that don't exist.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AuditLog

MAX_DETAIL_LENGTH = 512


def record_audit(
    db: Session,
    *,
    username: str | None,
    role: str | None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    success: bool = True,
    detail: str | None = None,
) -> None:
    """Adds and commits one AuditLog row. Commits immediately (rather than relying on the
    caller's own later commit) so a denied/failed action — which often has no other reason to
    commit anything — still leaves a durable record even if the request aborts right after."""
    db.add(
        AuditLog(
            username=username,
            role=role,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            success=success,
            detail=(detail[:MAX_DETAIL_LENGTH] if detail else None),
        )
    )
    db.commit()
