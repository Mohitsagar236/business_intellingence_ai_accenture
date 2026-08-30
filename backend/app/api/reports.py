from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Report, User
from app.schemas import ReportListItemOut, ReportOut

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ReportListItemOut])
def list_reports(
    department: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Report)
    if current_user.role == "dept_head":
        # Authoritative scoping comes from the authenticated user's own department, never from
        # a client-supplied query param — a dept_head must not be able to read another
        # department's reports by passing ?department=<other>.
        q = q.filter(Report.routed_to == current_user.department)
    elif department:
        q = q.filter(Report.routed_to == department)
    reports = q.order_by(Report.created_at.desc()).all()
    return [
        ReportListItemOut(
            id=r.id,
            anomaly_id=r.anomaly_id,
            status=r.status,
            routed_to=r.routed_to,
            created_at=r.created_at,
            metric_name=r.anomaly.metric.name,
            problem_statement=r.problem_statement,
        )
        for r in reports
    ]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if current_user.role == "dept_head" and report.routed_to != current_user.department:
        raise HTTPException(status_code=403, detail="This report belongs to a different department")
    return report
