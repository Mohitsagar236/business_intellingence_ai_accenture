from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Anomaly, TextEvidence, User
from app.schemas import AnomalyDetailOut, AnomalySummaryOut, EvidenceOut, HypothesisOut, ReportOut, SegmentOut

router = APIRouter(prefix="/api/anomalies", tags=["anomalies"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[AnomalySummaryOut])
def list_anomalies(status: str | None = Query(default=None), db: Session = Depends(get_db)):
    # Intentionally not department-scoped: AnomalySummaryOut carries only id/status/magnitude —
    # no metric name, cause, or report content — so a cross-department KPI-health overview here
    # doesn't leak anything the per-anomaly report detail below protects.
    q = db.query(Anomaly)
    if status:
        q = q.filter(Anomaly.status == status)
    return q.order_by(Anomaly.created_at.desc()).all()


@router.get("/{anomaly_id}", response_model=AnomalyDetailOut)
def get_anomaly(
    anomaly_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    anomaly = db.get(Anomaly, anomaly_id)
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if current_user.role == "dept_head" and anomaly.report and anomaly.report.routed_to != current_user.department:
        # This is the real path report content reaches the UI through (ReportView.tsx reads
        # the anomaly detail's embedded `report`, not /api/reports/{id} directly) — the same
        # department boundary enforced in app/api/reports.py must hold here too.
        raise HTTPException(status_code=403, detail="This anomaly's report belongs to a different department")

    evidence_out = []
    for e in anomaly.evidence:
        excerpts: list[str] = []
        window_start: dt.date | None = None
        window_end: dt.date | None = None
        if e.type == "structured":
            # find_structured_correlate (evidence_mining.py) aligns candidate[date - lag_days]
            # against target[date] — so the candidate's own real window is the anomaly window
            # shifted back by that same lag, not the anomaly's own dates.
            lag = e.lag_days or 0
            window_start = anomaly.window_start - dt.timedelta(days=lag)
            window_end = anomaly.window_end - dt.timedelta(days=lag)
        elif e.ref_text_evidence_ids:
            rows = db.query(TextEvidence).filter(TextEvidence.id.in_(e.ref_text_evidence_ids)).all()
            excerpts = [r.text for r in rows]
            if rows:
                timestamps = [r.timestamp for r in rows]
                window_start, window_end = min(timestamps), max(timestamps)
        evidence_out.append(
            EvidenceOut(
                id=e.id,
                type=e.type,
                source=e.source,
                description=e.description,
                correlation=e.correlation,
                lag_days=e.lag_days,
                theme_keywords=e.theme_keywords,
                spike_ratio=e.spike_ratio,
                excerpts=excerpts,
                window_start=window_start,
                window_end=window_end,
            )
        )

    return AnomalyDetailOut(
        id=anomaly.id,
        metric_id=anomaly.metric_id,
        window_start=anomaly.window_start,
        window_end=anomaly.window_end,
        magnitude_pct=anomaly.magnitude_pct,
        significance_score=anomaly.significance_score,
        status=anomaly.status,
        created_at=anomaly.created_at,
        metric=anomaly.metric,
        segments=[SegmentOut.model_validate(s) for s in sorted(anomaly.segments, key=lambda s: -s.contribution_score)],
        evidence=evidence_out,
        hypotheses=[HypothesisOut.model_validate(h) for h in sorted(anomaly.hypotheses, key=lambda h: h.rank)],
        report=ReportOut.model_validate(anomaly.report) if anomaly.report else None,
    )
