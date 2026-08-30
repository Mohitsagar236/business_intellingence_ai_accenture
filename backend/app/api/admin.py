from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_roles
from app.models import AuditLog, Playbook, SuppressedLog
from app.schemas import AuditLogOut, PlaybookOut, SuppressedLogOut

# Router-level require_roles("admin") — every route below, including audit-log, inherits this.
# analyst/dept_head/executive get a 403 the same way they would for suppressed-log/playbooks;
# there is no separate check to remember to add per-route.
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_roles("admin"))])


@router.get("/suppressed-log", response_model=list[SuppressedLogOut])
def list_suppressed_log(db: Session = Depends(get_db)):
    logs = db.query(SuppressedLog).order_by(SuppressedLog.created_at.desc()).all()
    return [
        SuppressedLogOut(
            id=l.id,
            metric_id=l.metric_id,
            metric_name=l.metric.name,
            window_start=l.window_start,
            window_end=l.window_end,
            reason=l.reason,
            detail=l.detail,
            z_score=l.z_score,
            created_at=l.created_at,
        )
        for l in logs
    ]


@router.get("/playbooks", response_model=list[PlaybookOut])
def list_playbooks(db: Session = Depends(get_db)):
    return db.query(Playbook).order_by(Playbook.cause_category).all()


@router.get("/audit-log", response_model=list[AuditLogOut])
def list_audit_log(
    db: Session = Depends(get_db),
    user: str | None = Query(default=None, description="Filter by username (exact match)"),
    action: str | None = Query(default=None, description="Filter by action name (exact match)"),
    date_from: dt.date | None = Query(default=None, description="Include entries on/after this date"),
    date_to: dt.date | None = Query(default=None, description="Include entries on/before this date"),
):
    q = db.query(AuditLog)
    if user:
        q = q.filter(AuditLog.username == user)
    if action:
        q = q.filter(AuditLog.action == action)
    if date_from:
        q = q.filter(AuditLog.created_at >= dt.datetime.combine(date_from, dt.time.min))
    if date_to:
        q = q.filter(AuditLog.created_at <= dt.datetime.combine(date_to, dt.time.max))
    return q.order_by(AuditLog.created_at.desc()).limit(500).all()
