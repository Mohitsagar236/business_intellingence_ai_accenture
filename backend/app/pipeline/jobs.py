"""
Detection jobs — lets the frontend poll real, per-stage progress for a single detection run
instead of a single blocking request.

The pipeline itself (orchestrator.run_detection) still executes synchronously and is not
rewritten — this module just runs that same call on a background thread and records each real
stage transition (via the `on_stage` callback orchestrator.run_detection now accepts) into an
in-memory job so a polling endpoint can report genuine progress. No stage is ever marked done
before the corresponding real pipeline code has actually returned; a window that never reaches
a stage (e.g. suppressed at Data Quality) simply never emits an event for the stages after it.

In-memory and per-process by design — this is a local reference implementation with no queue/
worker infrastructure, so job state doesn't need to survive a restart or be shared across
processes, matching the app's existing SQLite-by-default, single-process deployment model.
"""
from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass, field

STAGES: list[str] = [
    "data_quality",
    "baseline_analysis",
    "anomaly_detection",
    "segmentation",
    "structured_evidence",
    "nlp_evidence",
    "convergence",
    "recommendation",
]


@dataclass
class StageEvent:
    stage: str
    ok: bool
    detail: str | None = None


@dataclass
class DetectionJob:
    id: str
    metric_id: int
    status: str = "running"  # running | done | failed
    stage_events: list[StageEvent] = field(default_factory=list)
    result: dict | None = None
    error: str | None = None


_jobs: dict[str, DetectionJob] = {}
_lock = threading.Lock()


def create_job(metric_id: int) -> DetectionJob:
    job = DetectionJob(id=uuid.uuid4().hex, metric_id=metric_id)
    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> DetectionJob | None:
    with _lock:
        return _jobs.get(job_id)


def _record_stage(job: DetectionJob, stage: str, ok: bool, detail: str | None) -> None:
    with _lock:
        job.stage_events.append(StageEvent(stage=stage, ok=ok, detail=detail))


def run_job(
    job_id: str,
    session_factory,
    metric_id: int,
    window_start: dt.date | None = None,
    window_end: dt.date | None = None,
) -> None:
    """Runs on a background thread — session_factory() must produce a fresh Session bound to
    its own connection, since the request that started the job has already returned."""
    from app.models import Metric
    from app.pipeline.orchestrator import run_detection

    job = get_job(job_id)
    if job is None:
        return

    db = session_factory()
    try:
        metric = db.get(Metric, metric_id)
        if metric is None:
            job.status = "failed"
            job.error = "Metric not found"
            return

        def on_stage(stage: str, ok: bool, detail: str | None = None) -> None:
            _record_stage(job, stage, ok, detail)

        result = run_detection(db, metric, window_start=window_start, window_end=window_end, on_stage=on_stage)
        with _lock:
            job.result = result
            job.status = "done"
    except Exception as exc:  # noqa: BLE001 — surfaced to the client via job.error, not swallowed silently
        with _lock:
            job.status = "failed"
            job.error = str(exc)
    finally:
        db.close()
