"""
Orchestrator — wires Stages 2-4 together for one metric/window (Design Doc §4, "End-to-End
Data Flow"). Fails closed throughout: a suppressed window never becomes an Anomaly row, and
an anomaly whose evidence doesn't converge never becomes a single fabricated cause.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_config import event
from app.models import Anomaly, Evidence, Hypothesis, Metric, Report, Segment, SuppressedLog
from app.pipeline import convergence, evidence_mining, noise_filter, playbooks, router, segmentation
from app.pipeline.narrative import EvidencePackItem, generate_cause_and_confidence
from app.pipeline.series_utils import aggregate_daily, decompose, filter_by_dims, load_observations_df

settings = get_settings()
logger = logging.getLogger(__name__)


def _latest_window(db: Session, metric: Metric) -> tuple[dt.date, dt.date]:
    raw = load_observations_df(db, metric.id)
    latest = max(raw["date"])
    window_end = latest if isinstance(latest, dt.date) else latest.date()
    window_start = window_end - dt.timedelta(days=settings.default_window_days - 1)
    return window_start, window_end


def _clear_previous_result(db: Session, metric: Metric, window_start: dt.date, window_end: dt.date) -> None:
    """Re-running detection on a window already evaluated replaces that result rather than
    accumulating duplicates. Existing Anomaly rows are deleted one at a time through the ORM
    session (not a bulk Query.delete()) so the cascade="all, delete-orphan" relationships
    actually fire and take segments/evidence/hypotheses/report with them."""
    existing = (
        db.query(Anomaly)
        .filter(Anomaly.metric_id == metric.id, Anomaly.window_start == window_start, Anomaly.window_end == window_end)
        .all()
    )
    for anomaly in existing:
        db.delete(anomaly)

    db.query(SuppressedLog).filter(
        SuppressedLog.metric_id == metric.id, SuppressedLog.window_start == window_start, SuppressedLog.window_end == window_end
    ).delete()
    db.flush()


def _emit(on_stage: Callable[[str, bool, str | None], None] | None, stage: str, ok: bool, detail: str | None = None) -> None:
    if on_stage is not None:
        on_stage(stage, ok, detail)


def run_detection(
    db: Session,
    metric: Metric,
    window_start: dt.date | None = None,
    window_end: dt.date | None = None,
    on_stage: Callable[[str, bool, str | None], None] | None = None,
) -> dict:
    if window_start is None or window_end is None:
        raw = load_observations_df(db, metric.id)
        if raw.empty:
            event(logger, logging.INFO, "detection_skipped", metric=metric.key, reason="no_data")
            return {"status": "no_data", "detail": "No observations have been uploaded for this metric yet."}
        window_start, window_end = _latest_window(db, metric)

    event(logger, logging.INFO, "detection_started", metric=metric.key, window=f"{window_start}:{window_end}")
    _clear_previous_result(db, metric, window_start, window_end)

    # --- Stage 2: Noise Filtering ------------------------------------------------------
    dq = noise_filter.check_data_quality(db, metric, window_start, window_end)
    if not dq.ok:
        _emit(on_stage, "data_quality", False, dq.detail)
        log = SuppressedLog(
            metric_id=metric.id,
            window_start=window_start,
            window_end=window_end,
            reason="data_quality",
            detail=dq.detail or "",
        )
        db.add(log)
        db.commit()
        event(logger, logging.INFO, "detection_suppressed", metric=metric.key, reason="data_quality")
        return {"status": "suppressed_data_quality", "suppressed_log_id": log.id, "detail": dq.detail}
    _emit(on_stage, "data_quality", True, "No data-quality issues found in this window.")

    sig = noise_filter.run_significance_check(db, metric, window_start, window_end)
    _emit(on_stage, "baseline_analysis", True, f"Baseline forecast computed from history (z={sig.z_score:.2f}, n={sig.sample_size}).")
    if not sig.is_significant:
        _emit(on_stage, "anomaly_detection", False, f"Deviation of {sig.magnitude_pct:+.1f}% did not clear the significance threshold.")
        log = SuppressedLog(
            metric_id=metric.id,
            window_start=window_start,
            window_end=window_end,
            reason="not_significant",
            detail=(
                f"Deviation of {sig.magnitude_pct:+.1f}% (z={sig.z_score:.2f}, n={sig.sample_size}) "
                f"did not clear the significance threshold — logged silently, no report issued."
            ),
            z_score=sig.z_score,
        )
        db.add(log)
        db.commit()
        event(logger, logging.INFO, "detection_suppressed", metric=metric.key, reason="not_significant", z_score=round(sig.z_score, 2))
        return {"status": "suppressed_noise", "suppressed_log_id": log.id, "z_score": sig.z_score}
    _emit(on_stage, "anomaly_detection", True, f"Significant deviation confirmed: {sig.magnitude_pct:+.1f}% (z={sig.z_score:.2f}).")

    # --- Stage 3a: Segmentation ---------------------------------------------------------
    segment_results = segmentation.run_segmentation(db, metric, window_start, window_end, sig.magnitude_pct)
    primary_dims = segmentation.primary_segment_dims(segment_results)
    scope_detail = ", ".join(f"{k}={v}" for k, v in primary_dims.items()) if primary_dims else "no dominant segment isolated"
    _emit(on_stage, "segmentation", bool(primary_dims), scope_detail)
    event(logger, logging.INFO, "segmentation_completed", metric=metric.key, segment=scope_detail)

    # --- Stage 3b: Parallel Evidence Mining ---------------------------------------------
    raw = load_observations_df(db, metric.id)
    filtered = filter_by_dims(raw, primary_dims if primary_dims else None)
    daily = aggregate_daily(filtered, metric.aggregation)
    target_series = decompose(daily, metric.seasonality_period)

    all_metrics = db.query(Metric).all()
    structured = evidence_mining.find_structured_correlate(
        db, metric, target_series, primary_dims, window_start, window_end, all_metrics
    )
    _emit(
        on_stage,
        "structured_evidence",
        structured is not None,
        structured.description if structured else "No co-moving structured metric found in this segment/window.",
    )
    event(logger, logging.INFO, "structured_evidence_search_completed", metric=metric.key, found=structured is not None)

    themes = evidence_mining.mine_themes(db, primary_dims, window_start, window_end)
    _emit(
        on_stage,
        "nlp_evidence",
        bool(themes),
        f"{len(themes)} theme(s) found in unstructured evidence." if themes else "No text-theme spike found in this segment/window.",
    )
    event(logger, logging.INFO, "nlp_evidence_search_completed", metric=metric.key, themes_found=len(themes))

    # --- Stage 3c: Convergence Check ------------------------------------------------------
    hypotheses_result = convergence.run_convergence(structured, themes)
    top = hypotheses_result[0]
    anomaly_status = "validated" if top.status == "validated" else "ambiguous"
    _emit(
        on_stage,
        "convergence",
        anomaly_status == "validated",
        f"{top.cause_display}: {top.status}" if anomaly_status == "validated" else "No single cause converges — ambiguous, ranked hypotheses kept.",
    )
    if anomaly_status == "validated":
        event(logger, logging.INFO, "convergence_completed", metric=metric.key, status="validated", cause=top.cause_category)
    else:
        event(
            logger,
            logging.INFO,
            "convergence_completed",
            metric=metric.key,
            status="ambiguous",
            reason="no_single_structured_and_text_signal_converged",
            hypotheses=len(hypotheses_result),
        )

    # --- Persist Anomaly + Segments -------------------------------------------------------
    anomaly = Anomaly(
        metric_id=metric.id,
        window_start=window_start,
        window_end=window_end,
        magnitude_pct=sig.magnitude_pct,
        significance_score=sig.z_score,
        status=anomaly_status,
    )
    db.add(anomaly)
    db.flush()

    for s in segment_results:
        db.add(
            Segment(
                anomaly_id=anomaly.id,
                dimension=s.dimension,
                value=s.value,
                contribution_score=s.contribution_score,
                is_primary=s.is_primary,
            )
        )

    # --- Persist Evidence rows, then wire Hypotheses to them ------------------------------
    evidence_by_key: dict[str, Evidence] = {}

    def _structured_evidence(cand) -> Evidence:
        key = f"structured:{cand.metric_key}"
        if key not in evidence_by_key:
            e = Evidence(
                anomaly_id=anomaly.id,
                type="structured",
                source=cand.metric_key,
                description=cand.description,
                correlation=cand.correlation,
                lag_days=cand.lag_days,
            )
            db.add(e)
            db.flush()
            evidence_by_key[key] = e
        return evidence_by_key[key]

    def _theme_evidence(theme) -> Evidence:
        key = f"theme:{theme.label}"
        if key not in evidence_by_key:
            e = Evidence(
                anomaly_id=anomaly.id,
                type="unstructured",
                source=theme.source_system,
                description=f'Theme "{theme.label}" — {theme.doc_count} records, {theme.spike_ratio:.1f}x baseline rate.',
                ref_text_evidence_ids=theme.excerpt_ids,
                theme_keywords=theme.keywords,
                spike_ratio=theme.spike_ratio,
            )
            db.add(e)
            db.flush()
            evidence_by_key[key] = e
        return evidence_by_key[key]

    persisted_hypotheses: list[Hypothesis] = []
    for hr in hypotheses_result:
        structured_evidence_id = _structured_evidence(hr.structured).id if hr.structured else None
        unstructured_evidence_id = _theme_evidence(hr.theme).id if hr.theme else None
        h = Hypothesis(
            anomaly_id=anomaly.id,
            cause_category=hr.cause_category,
            cause_display=hr.cause_display,
            confidence=hr.confidence,
            rank=hr.rank,
            status=hr.status,
            structured_evidence_id=structured_evidence_id,
            unstructured_evidence_id=unstructured_evidence_id,
            disambiguation_gap=hr.disambiguation_gap,
        )
        db.add(h)
        db.flush()
        persisted_hypotheses.append(h)

    # --- Stage 4: Recommendation ----------------------------------------------------------
    evidence_pack = [
        EvidencePackItem(
            evidence_id=e.id,
            type=e.type,
            description=e.description,
            excerpts=_excerpts_for(db, e),
        )
        for e in evidence_by_key.values()
    ]

    scope = ", ".join(f"{k}={v}" for k, v in primary_dims.items()) if primary_dims else "all segments"
    problem_statement = (
        f"{metric.name} deviated {sig.magnitude_pct:+.1f}% from its expected trend-and-seasonal baseline "
        f"over {window_start.isoformat()} to {window_end.isoformat()} (z={sig.z_score:.2f}), concentrated in {scope}."
    )

    is_validated = anomaly_status == "validated"
    cause_text, confidence_text, generated_by = generate_cause_and_confidence(
        pack=evidence_pack,
        cause_display=top.cause_display,
        confidence=top.confidence,
        is_validated=is_validated,
        is_multi_hypothesis=not is_validated,
    )

    if is_validated:
        playbook = playbooks.match_playbook(db, top.cause_category)
        if playbook:
            action_statement = " ".join(f"{i}. {a}" for i, a in enumerate(playbook.actions, start=1))
            routed_to = router.resolve_department(playbook, metric.department)
        else:
            action_statement = "No vetted playbook exists yet for this cause category — routed for manual triage."
            routed_to = metric.department
    else:
        gaps = [h.disambiguation_gap for h in hypotheses_result if h.disambiguation_gap]
        action_statement = "To resolve this: " + " ".join(f"({i}) {g}" for i, g in enumerate(gaps, start=1))
        routed_to = metric.department

    citations = sorted(set(cause_text.citations_used) | set(confidence_text.citations_used))
    stripped = cause_text.stripped + confidence_text.stripped

    report = Report(
        anomaly_id=anomaly.id,
        hypothesis_id=persisted_hypotheses[0].id,
        status=anomaly_status,
        problem_statement=problem_statement,
        cause_statement=cause_text.text,
        confidence_statement=confidence_text.text,
        action_statement=action_statement,
        citations=citations,
        stripped_claims=stripped,
        routed_to=routed_to,
        generated_by=generated_by,
    )
    db.add(report)
    db.commit()

    _emit(
        on_stage,
        "recommendation",
        True,
        action_statement if is_validated else "Evidence gaps named — no playbook attempted for an unvalidated cause.",
    )

    event(logger, logging.INFO, "detection_completed", metric=metric.key, status=anomaly_status, anomaly_id=anomaly.id, generated_by=generated_by)
    return {"status": anomaly_status, "anomaly_id": anomaly.id, "report_id": report.id}


def _excerpts_for(db: Session, evidence: Evidence) -> list[str]:
    if not evidence.ref_text_evidence_ids:
        return []
    from app.models import TextEvidence

    rows = db.query(TextEvidence).filter(TextEvidence.id.in_(evidence.ref_text_evidence_ids)).all()
    return [r.text for r in rows]
