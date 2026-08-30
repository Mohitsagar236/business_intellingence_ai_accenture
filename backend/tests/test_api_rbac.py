"""
HTTP-level RBAC tests — the first tests in this suite to actually drive requests through
FastAPI's routing/dependency layer (via TestClient) rather than calling pipeline functions
directly. Confirms `require_roles` and the per-department report scoping in
`app/api/reports.py` are enforced by the server itself, not just hidden in the UI — a client
calling the API directly with a valid token for the wrong role/department must still be
rejected or filtered.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _token(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- unauthenticated access -------------------------------------------------------------


def test_unauthenticated_request_is_rejected(client):
    resp = client.get("/api/reports")
    assert resp.status_code == 401


def test_invalid_token_is_rejected(client):
    resp = client.get("/api/reports", headers=_auth("not-a-real-token"))
    assert resp.status_code == 401


# --- role gates on write/admin endpoints ------------------------------------------------


def test_analyst_blocked_from_admin_endpoint(client):
    token = _token(client, "analyst", "analyst123")
    resp = client.get("/api/admin/playbooks", headers=_auth(token))
    assert resp.status_code == 403


def test_admin_can_reach_admin_endpoint(client):
    token = _token(client, "admin", "admin123")
    resp = client.get("/api/admin/playbooks", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


def test_executive_blocked_from_write_endpoint(client):
    token = _token(client, "exec", "exec123")
    resp = client.post(
        "/api/metrics",
        headers=_auth(token),
        json={"key": "new_metric", "name": "New Metric", "department": "Ops", "unit": "USD", "aggregation": "sum", "dimensions": []},
    )
    assert resp.status_code == 403


def test_executive_blocked_from_run_detection(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, "exec", "exec123")
    resp = client.post(f"/api/metrics/{metric.id}/run-detection", headers=_auth(token))
    assert resp.status_code == 403


def test_exec_can_read_reports(client):
    token = _token(client, "exec", "exec123")
    resp = client.get("/api/reports", headers=_auth(token))
    assert resp.status_code == 200


# --- department isolation for dept_head ---------------------------------------------------


def test_depthead_sees_only_their_own_department(client):
    token = _token(client, "depthead", "depthead123")  # department = "Support"
    resp = client.get("/api/reports", headers=_auth(token))
    assert resp.status_code == 200
    departments = {r["routed_to"] for r in resp.json()}
    assert departments <= {"Support"}
    assert "Sales" not in departments


def test_depthead_cannot_escape_their_department_via_query_param(client):
    # The billing-outage scenario routes to "Sales" — a dept_head in "Support" must not be
    # able to read it just by passing a different department in the query string.
    token = _token(client, "depthead", "depthead123")
    resp = client.get("/api/reports", params={"department": "Sales"}, headers=_auth(token))
    assert resp.status_code == 200
    departments = {r["routed_to"] for r in resp.json()}
    assert "Sales" not in departments


def test_depthead_gets_403_on_other_departments_report_detail(client, db_session):
    from app.models import Report

    sales_report = db_session.query(Report).filter(Report.routed_to == "Sales").first()
    assert sales_report is not None, "fixture must contain a Sales-routed report to test against"
    token = _token(client, "depthead", "depthead123")
    resp = client.get(f"/api/reports/{sales_report.id}", headers=_auth(token))
    assert resp.status_code == 403


def test_depthead_can_read_their_own_departments_report_detail(client, db_session):
    from app.models import Report

    support_report = db_session.query(Report).filter(Report.routed_to == "Support").first()
    assert support_report is not None, "fixture must contain a Support-routed report to test against"
    token = _token(client, "depthead", "depthead123")
    resp = client.get(f"/api/reports/{support_report.id}", headers=_auth(token))
    assert resp.status_code == 200


def test_depthead_blocked_from_other_departments_anomaly_detail(client, db_session):
    # This is the path the real UI actually uses to view a report (ReportView.tsx reads the
    # anomaly detail's embedded `report`, not /api/reports/{id}) — must be scoped the same way.
    from app.models import Report

    sales_report = db_session.query(Report).filter(Report.routed_to == "Sales").first()
    token = _token(client, "depthead", "depthead123")
    resp = client.get(f"/api/anomalies/{sales_report.anomaly_id}", headers=_auth(token))
    assert resp.status_code == 403


def test_depthead_can_view_their_own_departments_anomaly_detail(client, db_session):
    from app.models import Report

    support_report = db_session.query(Report).filter(Report.routed_to == "Support").first()
    token = _token(client, "depthead", "depthead123")
    resp = client.get(f"/api/anomalies/{support_report.anomaly_id}", headers=_auth(token))
    assert resp.status_code == 200


# --- analyst upload permission (P1-1) -----------------------------------------------------


def _csv_upload(client: TestClient, token: str, metric_id: int, tag: str = "x") -> object:
    # `tag` disambiguates the (metric, entity, timestamp) identity across calls sharing the
    # same session-scoped DB — cross-upload duplicate detection means two calls with the
    # literal same dates would otherwise see the second as "already on file" and skip it,
    # which would be a false failure of these tests, not a real RBAC problem.
    csv_bytes = f"date,value\n2026-0{tag}-01,111\n2026-0{tag}-02,222\n".encode()
    return client.post(
        f"/api/metrics/{metric_id}/observations/upload",
        headers=_auth(token),
        files={"file": ("obs.csv", csv_bytes, "text/csv")},
    )


@pytest.mark.parametrize("username,password,tag", [("analyst", "analyst123", "3"), ("admin", "admin123", "4")])
def test_upload_allowed_for_analyst_and_admin(client, db_session, username, password, tag):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, username, password)
    resp = _csv_upload(client, token, metric.id, tag)
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows_inserted"] == 2
    assert resp.json()["duplicates_skipped"] == 0


@pytest.mark.parametrize("username,password", [("depthead", "depthead123"), ("exec", "exec123")])
def test_upload_forbidden_for_depthead_and_exec(client, db_session, username, password):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, username, password)
    resp = _csv_upload(client, token, metric.id, "5")
    assert resp.status_code == 403


def test_observations_template_allowed_for_analyst(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, "analyst", "analyst123")
    resp = client.get(f"/api/metrics/{metric.id}/observations/template", headers=_auth(token))
    assert resp.status_code == 200


def test_observations_template_forbidden_for_depthead(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, "depthead", "depthead123")
    resp = client.get(f"/api/metrics/{metric.id}/observations/template", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.parametrize("username,password", [("analyst", "analyst123"), ("admin", "admin123")])
def test_text_evidence_upload_allowed_for_analyst_and_admin(client, username, password):
    token = _token(client, username, password)
    csv_bytes = b"date,text\n2026-02-01,Customer called about a late delivery.\n"
    resp = client.post("/api/text-evidence/upload", headers=_auth(token), files={"file": ("t.csv", csv_bytes, "text/csv")})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("username,password", [("depthead", "depthead123"), ("exec", "exec123")])
def test_text_evidence_upload_forbidden_for_depthead_and_exec(client, username, password):
    token = _token(client, username, password)
    csv_bytes = b"date,text\n2026-02-01,Customer called about a late delivery.\n"
    resp = client.post("/api/text-evidence/upload", headers=_auth(token), files={"file": ("t.csv", csv_bytes, "text/csv")})
    assert resp.status_code == 403


def test_analyst_still_cannot_create_or_delete_metrics(client, db_session):
    # Upload permission must not have widened into metric management — that stays admin-only.
    from app.models import Metric

    token = _token(client, "analyst", "analyst123")
    resp = client.post(
        "/api/metrics",
        headers=_auth(token),
        json={"key": "analyst_should_not_create_this", "name": "X", "department": "Ops", "unit": "USD", "aggregation": "sum", "dimensions": []},
    )
    assert resp.status_code == 403

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    resp = client.delete(f"/api/metrics/{metric.id}", headers=_auth(token))
    assert resp.status_code == 403


# --- async detection job (P0-3 pipeline-progress polling) --------------------------------


def _poll_job(client: TestClient, token: str, job_id: str, timeout_s: float = 5.0) -> dict:
    import time

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = client.get(f"/api/metrics/detections/{job_id}", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] != "running":
            return body
        time.sleep(0.05)
    raise AssertionError(f"detection job {job_id} did not finish within {timeout_s}s")


def test_detection_job_reports_real_stages_for_validated_scenario(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, "analyst", "analyst123")

    start_resp = client.post(f"/api/metrics/{metric.id}/detections", headers=_auth(token))
    assert start_resp.status_code == 200
    job_id = start_resp.json()["job_id"]

    final = _poll_job(client, token, job_id)
    assert final["status"] == "done"
    assert final["result"]["status"] == "validated"

    stages = [s["stage"] for s in final["stages"]]
    # Every named pipeline stage must actually have run and reported in order — none skipped,
    # none fabricated ahead of when the real code reached it.
    assert stages == [
        "data_quality",
        "baseline_analysis",
        "anomaly_detection",
        "segmentation",
        "structured_evidence",
        "nlp_evidence",
        "convergence",
        "recommendation",
    ]
    assert all(s["ok"] for s in final["stages"])


def test_detection_job_stops_at_suppression_stage(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "ticket_volume").one()
    token = _token(client, "analyst", "analyst123")

    start_resp = client.post(f"/api/metrics/{metric.id}/detections", headers=_auth(token))
    job_id = start_resp.json()["job_id"]

    final = _poll_job(client, token, job_id)
    assert final["status"] == "done"
    assert final["result"]["status"] == "suppressed_noise"

    stages = [s["stage"] for s in final["stages"]]
    # Suppressed at the significance check — segmentation/evidence/convergence never ran, so
    # they must never appear as completed stages.
    assert stages == ["data_quality", "baseline_analysis", "anomaly_detection"]
    assert stages[-1] == "anomaly_detection" and final["stages"][-1]["ok"] is False


def test_executive_blocked_from_starting_detection_job(client, db_session):
    from app.models import Metric

    metric = db_session.query(Metric).filter(Metric.key == "revenue").one()
    token = _token(client, "exec", "exec123")
    resp = client.post(f"/api/metrics/{metric.id}/detections", headers=_auth(token))
    assert resp.status_code == 403


def test_evidence_carries_real_date_windows_for_the_timeline(client, db_session):
    from app.models import Report

    sales_report = db_session.query(Report).filter(Report.routed_to == "Sales").first()
    token = _token(client, "admin", "admin123")
    resp = client.get(f"/api/anomalies/{sales_report.anomaly_id}", headers=_auth(token))
    assert resp.status_code == 200
    anomaly = resp.json()

    assert anomaly["evidence"], "the validated revenue scenario must carry evidence"
    for e in anomaly["evidence"]:
        assert e["window_start"] is not None
        assert e["window_end"] is not None
        assert e["window_start"] <= e["window_end"]
        if e["type"] == "structured":
            # This scenario's structured correlate is 0-day/simultaneous, so its window must
            # equal the anomaly's own window exactly (lag_days=0 shift is a no-op).
            assert e["window_start"] == anomaly["window_start"]
            assert e["window_end"] == anomaly["window_end"]


def test_admin_is_not_department_scoped(client):
    token = _token(client, "admin", "admin123")
    resp = client.get("/api/reports", headers=_auth(token))
    assert resp.status_code == 200
    departments = {r["routed_to"] for r in resp.json()}
    assert "Sales" in departments and "Support" in departments
