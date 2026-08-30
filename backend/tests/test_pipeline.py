"""
Verifies the four built-in synthetic scenarios each resolve to the pipeline outcome the
SRS specifies (Appendix A, UC-1/2/3, plus the extra data-quality case) — not just that the
pipeline runs without error.
"""
from app.models import Metric
from app.pipeline.orchestrator import run_detection


def _run(db_session, key: str) -> dict:
    metric = db_session.query(Metric).filter(Metric.key == key).one()
    return run_detection(db_session, metric)


def test_revenue_validates_billing_outage(db_session):
    result = _run(db_session, "revenue")
    assert result["status"] == "validated"

    from app.models import Anomaly

    anomaly = db_session.get(Anomaly, result["anomaly_id"])
    top = sorted(anomaly.hypotheses, key=lambda h: h.rank)[0]
    assert top.status == "validated"
    assert top.cause_category == "billing_system_outage"
    # A validated hypothesis must carry both evidence links — the root-cause evidence chain
    # (frontend RootCauseChain) draws directly from these ids to connect the diagram nodes.
    assert top.structured_evidence_id is not None
    assert top.unstructured_evidence_id is not None
    assert anomaly.report.citations, "validated report must cite at least one evidence id"
    for evidence_id in anomaly.report.citations:
        assert evidence_id in {e.id for e in anomaly.evidence}
    # The test suite must never depend on a live LLM call — conftest forces both API keys
    # empty, so every report in this run must come from the deterministic template writer.
    assert anomaly.report.generated_by == "template"


def test_csat_is_genuinely_ambiguous(db_session):
    result = _run(db_session, "csat")
    assert result["status"] == "ambiguous"

    from app.models import Anomaly

    anomaly = db_session.get(Anomaly, result["anomaly_id"])
    hyps = sorted(anomaly.hypotheses, key=lambda h: h.rank)
    assert len(hyps) >= 2, "a genuinely ambiguous case must keep multiple ranked hypotheses"
    assert all(h.status == "candidate" for h in hyps)
    assert all(h.disambiguation_gap for h in hyps), "every candidate must name what would resolve it"
    # No single hypothesis may be laundered into false certainty.
    assert all(h.confidence < 0.7 for h in hyps)


def test_ticket_volume_suppressed_as_noise(db_session):
    result = _run(db_session, "ticket_volume")
    assert result["status"] == "suppressed_noise"
    assert abs(result["z_score"]) < 2.0

    from app.models import Anomaly

    assert db_session.query(Anomaly).filter(Anomaly.metric_id == db_session.query(Metric).filter(Metric.key == "ticket_volume").one().id).count() == 0


def test_churn_suppressed_for_data_quality(db_session):
    result = _run(db_session, "churn_rate")
    assert result["status"] == "suppressed_data_quality"

    from app.models import SuppressedLog

    log = db_session.get(SuppressedLog, result["suppressed_log_id"])
    assert log.reason == "data_quality"


def test_grounding_guard_never_cites_outside_evidence_pack(db_session):
    """Every citation in every generated report must resolve to a real Evidence row for that
    anomaly — the core anti-hallucination guarantee (FR-4.3)."""
    from app.models import Report

    for report in db_session.query(Report).all():
        valid_ids = {e.id for e in report.anomaly.evidence}
        assert set(report.citations).issubset(valid_ids)
