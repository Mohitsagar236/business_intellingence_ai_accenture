from __future__ import annotations

import datetime as dt
import io
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

import logging

from app.audit import record_audit
from app.config import get_settings
from app.db import get_db, get_session_factory
from app.deps import get_current_user, require_roles
from app.logging_config import event
from app.models import Anomaly, Metric, Observation, SuppressedLog, User
from app.pipeline import jobs as detection_jobs
from app.pipeline import orchestrator
from app.pipeline.ingestion import IngestionError, validate_and_insert_observations
from app.pipeline.series_utils import add_confidence_band, aggregate_daily, decompose, load_observations_df
from app.schemas import (
    AnomalySummaryOut,
    DetectionJobOut,
    DetectionStageOut,
    MetricCreateIn,
    MetricDetailOut,
    MetricOut,
    MetricStatusOut,
    RunDetectionOut,
    SeriesPointOut,
    UploadResultOut,
)

router = APIRouter(prefix="/api/metrics", tags=["metrics"], dependencies=[Depends(get_current_user)])
settings = get_settings()
logger = logging.getLogger(__name__)


def _latest_activity(db: Session, metric_id: int) -> tuple[str, int | None, dt.datetime | None]:
    latest_anomaly = (
        db.query(Anomaly).filter(Anomaly.metric_id == metric_id).order_by(Anomaly.created_at.desc()).first()
    )
    latest_suppressed = (
        db.query(SuppressedLog).filter(SuppressedLog.metric_id == metric_id).order_by(SuppressedLog.created_at.desc()).first()
    )

    candidates = []
    if latest_anomaly:
        candidates.append((latest_anomaly.created_at, latest_anomaly.status, latest_anomaly.id))
    if latest_suppressed:
        label = "suppressed_data_quality" if latest_suppressed.reason == "data_quality" else "suppressed_noise"
        candidates.append((latest_suppressed.created_at, label, None))

    if not candidates:
        return "unknown", None, None

    candidates.sort(key=lambda c: c[0], reverse=True)
    created_at, status, anomaly_id = candidates[0]
    return status, anomaly_id, created_at


def _bulk_latest_activity(
    db: Session, metric_ids: list[int]
) -> dict[int, tuple[str, int | None, dt.datetime | None]]:
    """Same result as calling _latest_activity per metric, but two queries total instead of
    2N — each uses a ROW_NUMBER() window to grab only the latest anomaly/suppressed-log row
    per metric_id in one pass, avoiding an N+1 as the metric list grows."""
    if not metric_ids:
        return {}

    anomaly_rn = (
        db.query(
            Anomaly.metric_id,
            Anomaly.id,
            Anomaly.status,
            Anomaly.created_at,
            func.row_number()
            .over(partition_by=Anomaly.metric_id, order_by=Anomaly.created_at.desc())
            .label("rn"),
        )
        .filter(Anomaly.metric_id.in_(metric_ids))
        .subquery()
    )
    latest_anomalies = {
        row.metric_id: (row.created_at, row.status, row.id)
        for row in db.query(anomaly_rn).filter(anomaly_rn.c.rn == 1)
    }

    suppressed_rn = (
        db.query(
            SuppressedLog.metric_id,
            SuppressedLog.reason,
            SuppressedLog.created_at,
            func.row_number()
            .over(partition_by=SuppressedLog.metric_id, order_by=SuppressedLog.created_at.desc())
            .label("rn"),
        )
        .filter(SuppressedLog.metric_id.in_(metric_ids))
        .subquery()
    )
    latest_suppressed = {
        row.metric_id: (row.created_at, row.reason)
        for row in db.query(suppressed_rn).filter(suppressed_rn.c.rn == 1)
    }

    result: dict[int, tuple[str, int | None, dt.datetime | None]] = {}
    for metric_id in metric_ids:
        candidates = []
        if metric_id in latest_anomalies:
            candidates.append(latest_anomalies[metric_id])
        if metric_id in latest_suppressed:
            created_at, reason = latest_suppressed[metric_id]
            label = "suppressed_data_quality" if reason == "data_quality" else "suppressed_noise"
            candidates.append((created_at, label, None))

        if not candidates:
            result[metric_id] = ("unknown", None, None)
            continue

        candidates.sort(key=lambda c: c[0], reverse=True)
        created_at, status, anomaly_id = candidates[0]
        result[metric_id] = (status, anomaly_id, created_at)

    return result


@router.get("", response_model=list[MetricStatusOut])
def list_metrics(db: Session = Depends(get_db)):
    metrics = db.query(Metric).order_by(Metric.department, Metric.name).all()
    activity = _bulk_latest_activity(db, [m.id for m in metrics])
    out = []
    for m in metrics:
        status, anomaly_id, checked_at = activity[m.id]
        out.append(
            MetricStatusOut(
                id=m.id,
                key=m.key,
                name=m.name,
                department=m.department,
                unit=m.unit,
                aggregation=m.aggregation,
                dimensions=m.dimensions,
                seasonality_period=m.seasonality_period,
                latest_status=status,
                latest_anomaly_id=anomaly_id,
                latest_checked_at=checked_at,
            )
        )
    return out


@router.post("", response_model=MetricOut, dependencies=[Depends(require_roles("admin"))])
def create_metric(body: MetricCreateIn, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if db.query(Metric).filter(Metric.key == body.key).one_or_none():
        raise HTTPException(status_code=409, detail=f"A metric with key '{body.key}' already exists.")
    if body.aggregation not in ("sum", "mean"):
        raise HTTPException(status_code=422, detail="aggregation must be 'sum' or 'mean'.")

    metric = Metric(
        key=body.key,
        name=body.name,
        department=body.department,
        unit=body.unit,
        aggregation=body.aggregation,
        seasonality_period=body.seasonality_period,
        dimensions=body.dimensions,
    )
    db.add(metric)
    db.commit()
    db.refresh(metric)
    event(logger, logging.INFO, "admin_metric_created", username=current_user.username, metric=metric.key)
    record_audit(db, username=current_user.username, role=current_user.role, action="metric_created", resource_type="metric", resource_id=metric.id, detail=metric.key)
    return metric


@router.delete("/{metric_id}", status_code=204, dependencies=[Depends(require_roles("admin"))])
def delete_metric(metric_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    metric_key = metric.key
    db.query(Observation).filter(Observation.metric_id == metric_id).delete()
    db.query(SuppressedLog).filter(SuppressedLog.metric_id == metric_id).delete()
    for anomaly in db.query(Anomaly).filter(Anomaly.metric_id == metric_id).all():
        db.delete(anomaly)  # ORM delete so cascade takes segments/evidence/hypotheses/report
    db.delete(metric)
    db.commit()
    event(logger, logging.INFO, "admin_metric_deleted", username=current_user.username, metric=metric_key)
    record_audit(db, username=current_user.username, role=current_user.role, action="metric_deleted", resource_type="metric", resource_id=metric_id, detail=metric_key)


@router.get("/{metric_id}", response_model=MetricDetailOut)
def get_metric(metric_id: int, db: Session = Depends(get_db)):
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    raw = load_observations_df(db, metric.id)
    observation_count = len(raw)
    insufficient_history = 0 < observation_count < 2 * metric.seasonality_period
    if raw.empty:
        series: list[SeriesPointOut] = []
    else:
        daily = aggregate_daily(raw, metric.aggregation)
        decomposed = decompose(daily, metric.seasonality_period)
        decomposed = add_confidence_band(decomposed, settings.significance_z_threshold, settings.default_window_days)
        series = [
            SeriesPointOut(
                date=row.date,
                value=row.value,
                trend=row.trend,
                seasonal=row.seasonal,
                resid=row.resid,
                ci_upper=row.ci_upper,
                ci_lower=row.ci_lower,
            )
            for row in decomposed.itertuples()
        ]

    anomalies = (
        db.query(Anomaly).filter(Anomaly.metric_id == metric.id).order_by(Anomaly.window_end.desc()).all()
    )
    status, latest_anomaly_id, checked_at = _latest_activity(db, metric.id)

    return MetricDetailOut(
        id=metric.id,
        key=metric.key,
        name=metric.name,
        department=metric.department,
        unit=metric.unit,
        aggregation=metric.aggregation,
        dimensions=metric.dimensions,
        seasonality_period=metric.seasonality_period,
        latest_status=status,
        latest_anomaly_id=latest_anomaly_id,
        latest_checked_at=checked_at,
        series=series,
        anomalies=[AnomalySummaryOut.model_validate(a) for a in anomalies],
        insufficient_history=insufficient_history,
        observation_count=observation_count,
    )


@router.post(
    "/{metric_id}/observations/upload",
    response_model=UploadResultOut,
    dependencies=[Depends(require_roles("analyst", "admin"))],
)
async def upload_observations(metric_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    file_bytes = await file.read()
    try:
        result = validate_and_insert_observations(db, metric, file_bytes, file.filename or "upload.csv")
    except IngestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return UploadResultOut(
        rows_inserted=result.rows_inserted,
        date_range_start=result.date_range[0] if result.date_range else None,
        date_range_end=result.date_range[1] if result.date_range else None,
        warnings=result.warnings,
        duplicates_skipped=result.duplicates_skipped,
    )


@router.get("/{metric_id}/observations/template", dependencies=[Depends(require_roles("analyst", "admin"))])
def observations_template(metric_id: int, db: Session = Depends(get_db)):
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")

    header = ["date", "value", *metric.dimensions, "source_system"]
    example = ["2026-01-01", "1234.56", *["example" for _ in metric.dimensions], "uploaded"]
    csv_text = ",".join(header) + "\n" + ",".join(example) + "\n"

    return StreamingResponse(
        io.StringIO(csv_text),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{metric.key}_observations_template.csv"'},
    )


def _resolve_window(window_start: dt.date | None, window_end: dt.date | None) -> tuple[dt.date | None, dt.date | None]:
    """Both bounds are optional but must arrive together — the pipeline's own "most recent
    window" default (orchestrator._latest_window) only applies when neither is given."""
    if (window_start is None) != (window_end is None):
        raise HTTPException(status_code=400, detail="window_start and window_end must both be provided, or both omitted.")
    if window_start is not None and window_end is not None and window_start > window_end:
        raise HTTPException(status_code=400, detail="window_start must be on or before window_end.")
    return window_start, window_end


@router.post("/{metric_id}/run-detection", response_model=RunDetectionOut, dependencies=[Depends(require_roles("analyst", "admin"))])
def run_detection(
    metric_id: int,
    window_start: dt.date | None = Query(default=None),
    window_end: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    window_start, window_end = _resolve_window(window_start, window_end)
    result = orchestrator.run_detection(db, metric, window_start=window_start, window_end=window_end)
    return RunDetectionOut(**result)


@router.post("/{metric_id}/detections", response_model=DetectionJobOut, dependencies=[Depends(require_roles("analyst", "admin"))])
def start_detection_job(
    metric_id: int,
    window_start: dt.date | None = Query(default=None),
    window_end: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
    session_factory=Depends(get_session_factory),
):
    """Async counterpart to run-detection, for the Detection page's stage-by-stage progress
    view — same underlying pipeline call (orchestrator.run_detection), just run on a
    background thread with its own DB session so a polling endpoint can report which real
    stage has actually completed. The synchronous /run-detection route above is unchanged and
    still used by the quick inline "Run detection" buttons elsewhere in the app."""
    metric = db.get(Metric, metric_id)
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    window_start, window_end = _resolve_window(window_start, window_end)

    job = detection_jobs.create_job(metric_id)
    thread = threading.Thread(
        target=detection_jobs.run_job, args=(job.id, session_factory, metric_id, window_start, window_end), daemon=True
    )
    thread.start()
    return DetectionJobOut(job_id=job.id, status=job.status, stages=[])


@router.get("/detections/{job_id}", response_model=DetectionJobOut)
def get_detection_job(job_id: str):
    job = detection_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Detection job not found")
    return DetectionJobOut(
        job_id=job.id,
        status=job.status,
        stages=[DetectionStageOut(stage=e.stage, ok=e.ok, detail=e.detail) for e in job.stage_events],
        result=RunDetectionOut(**job.result) if job.result else None,
        error=job.error,
    )
