"""
Logging/observability tests (P1-2). Uses pytest's `caplog` fixture — never asserts against
real log files — and checks for the presence of the right *event name*, not exact message
formatting, since the human-readable "key=value" tail is meant to stay easy to extend.
"""
from __future__ import annotations

import logging

import httpx
import pytest


def _token(client, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_successful_detection_emits_logs(db_session, caplog):
    from app.models import Metric
    from app.pipeline.orchestrator import run_detection

    caplog.set_level(logging.INFO, logger="app")
    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    result = run_detection(db_session, metric)
    assert result["status"] == "validated"

    messages = [r.message for r in caplog.records]
    assert any("detection_started" in m and "metric=revenue" in m for m in messages)
    assert any("detection_completed" in m and "status=validated" in m for m in messages)
    assert any("segmentation_completed" in m for m in messages)
    assert any("convergence_completed" in m for m in messages)


def test_suppressed_detection_emits_suppressed_log_not_a_fabricated_success(db_session, caplog):
    from app.models import Metric
    from app.pipeline.orchestrator import run_detection

    caplog.set_level(logging.INFO, logger="app")
    metric = db_session.query(Metric).filter(Metric.key == "ticket_volume").one()
    result = run_detection(db_session, metric)
    assert result["status"] == "suppressed_noise"

    messages = [r.message for r in caplog.records]
    assert any("detection_suppressed" in m and "reason=not_significant" in m for m in messages)
    assert not any("detection_completed" in m for m in messages)


def test_deterministic_writer_fallback_is_logged(db_session, caplog):
    # conftest forces both LLM API keys empty for the whole suite, so every narrative call
    # here takes the "no LLM configured" fallback path — this must not be silent.
    from app.models import Metric
    from app.pipeline.orchestrator import run_detection

    caplog.set_level(logging.INFO, logger="app")
    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    run_detection(db_session, metric)

    messages = [r.message for r in caplog.records]
    assert any("narrative_no_llm_configured" in m for m in messages)
    assert any("deterministic_writer_fallback" in m for m in messages)


def test_failed_llm_call_emits_a_warning_log(monkeypatch, caplog):
    from app.pipeline import narrative

    monkeypatch.setattr(narrative.settings, "openrouter_api_key", "sk-or-v1-fake-test-key")

    def raise_timeout(*args, **kwargs):
        raise httpx.ConnectTimeout("simulated failure — no real network call is made")

    monkeypatch.setattr(httpx, "post", raise_timeout)

    caplog.set_level(logging.WARNING, logger="app")
    result = narrative._call_via_openrouter("dummy prompt — never logged")
    assert result is None

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "llm_generation_failed" in record.message
    assert "provider=openrouter" in record.message
    assert "reason=timeout" in record.message
    # The prompt and any exception body text must never appear in the log line.
    assert "dummy prompt" not in record.message


def test_unauthorized_access_emits_an_authorization_log(client, caplog):
    caplog.set_level(logging.WARNING, logger="app")
    token = _token(client, "analyst", "analyst123")
    resp = client.get("/api/admin/playbooks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403

    messages = [r.message for r in caplog.records]
    assert any("authorization_denied" in m and "username=analyst" in m for m in messages)


def test_login_failure_and_success_are_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="app")

    bad = client.post("/api/auth/login", json={"username": "analyst", "password": "wrong-password"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"username": "analyst", "password": "analyst123"})
    assert good.status_code == 200

    messages = [r.message for r in caplog.records]
    assert any("login_failed" in m and "username=analyst" in m for m in messages)
    assert any("login_success" in m and "username=analyst" in m and "role=analyst" in m for m in messages)
    # The password must never appear anywhere in the captured log output.
    assert not any("wrong-password" in m for m in messages)
    assert not any("analyst123" in m for m in messages)


def test_ingestion_success_and_failure_are_logged(db_session, caplog):
    from app.models import Metric, Observation
    from app.pipeline.ingestion import IngestionError, validate_and_insert_observations

    metric = Metric(key="logging_test_metric", name="Logging Test Metric", department="Ops", unit="USD", aggregation="sum", dimensions=[])
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)

    caplog.set_level(logging.INFO, logger="app")
    try:
        validate_and_insert_observations(db_session, metric, b"date,value\n2026-03-01,10\n2026-03-02,20\n", "obs.csv")
        with pytest.raises(IngestionError):
            validate_and_insert_observations(db_session, metric, b"date,value\n2026-03-03,not-a-number\n", "obs.csv")
    finally:
        db_session.query(Observation).filter(Observation.metric_id == metric.id).delete()
        db_session.delete(metric)
        db_session.commit()

    messages = [r.message for r in caplog.records]
    assert any("ingestion_succeeded" in m and "rows_accepted=2" in m for m in messages)
    assert any("ingestion_failed" in m and "reason=" in m for m in messages)
