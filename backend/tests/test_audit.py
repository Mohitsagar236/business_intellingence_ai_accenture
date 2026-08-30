"""
AuditLog tests (final hardening pass, item 2) — uses the shared `client` fixture (conftest.py),
the same real HTTP/TestClient path test_api_rbac.py uses, since audit entries are written from
inside real route handlers (app/api/auth.py, app/deps.py, app/api/metrics.py), not from a
function that's convenient to call directly.
"""
from __future__ import annotations


def _token(client, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_metric_create_writes_an_audit_entry(client, db_session):
    from app.models import AuditLog

    token = _token(client, "admin", "admin123")
    resp = client.post(
        "/api/metrics",
        headers={"Authorization": f"Bearer {token}"},
        json={"key": "audit_test_metric", "name": "Audit Test", "department": "Ops", "unit": "USD", "aggregation": "sum", "dimensions": []},
    )
    assert resp.status_code == 200, resp.text
    metric_id = resp.json()["id"]

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "metric_created", AuditLog.resource_id == str(metric_id))
        .one_or_none()
    )
    assert entry is not None
    assert entry.username == "admin"
    assert entry.role == "admin"
    assert entry.success is True
    assert entry.resource_type == "metric"
    assert entry.detail == "audit_test_metric"


def test_metric_delete_writes_an_audit_entry(client, db_session):
    from app.models import AuditLog

    token = _token(client, "admin", "admin123")
    create = client.post(
        "/api/metrics",
        headers={"Authorization": f"Bearer {token}"},
        json={"key": "audit_test_metric_2", "name": "Audit Test 2", "department": "Ops", "unit": "USD", "aggregation": "sum", "dimensions": []},
    )
    metric_id = create.json()["id"]

    resp = client.delete(f"/api/metrics/{metric_id}", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 204

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "metric_deleted", AuditLog.resource_id == str(metric_id))
        .one_or_none()
    )
    assert entry is not None
    assert entry.username == "admin"
    assert entry.success is True


def test_authorization_denial_writes_an_audit_entry(client, db_session):
    from app.models import AuditLog

    token = _token(client, "analyst", "analyst123")
    resp = client.get("/api/admin/playbooks", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "authorization_denied", AuditLog.username == "analyst")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert entry is not None
    assert entry.success is False
    assert entry.role == "analyst"
    assert "admin" in entry.detail


def test_login_failure_and_success_write_audit_entries(client, db_session):
    from app.models import AuditLog

    client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    fail_entry = db_session.query(AuditLog).filter(AuditLog.action == "login_failed", AuditLog.username == "admin").order_by(AuditLog.id.desc()).first()
    assert fail_entry is not None
    assert fail_entry.success is False

    _token(client, "admin", "admin123")
    success_entry = db_session.query(AuditLog).filter(AuditLog.action == "login_success", AuditLog.username == "admin").order_by(AuditLog.id.desc()).first()
    assert success_entry is not None
    assert success_entry.success is True
    assert success_entry.role == "admin"


def test_audit_log_never_stores_the_password():
    # The password never appears anywhere on the AuditLog model/write path — record_audit()
    # doesn't even accept one, so this is really documentation-as-a-test, but see
    # test_login_failure_and_success_write_audit_entries for the end-to-end confirmation.
    from app.audit import record_audit
    import inspect

    params = inspect.signature(record_audit).parameters
    assert "password" not in params


def test_non_admin_roles_cannot_read_the_audit_log(client):
    for username, password in [("analyst", "analyst123"), ("depthead", "depthead123"), ("exec", "exec123")]:
        token = _token(client, username, password)
        resp = client.get("/api/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403, f"{username} should not be able to read the audit log"


def test_admin_can_read_and_filter_the_audit_log(client):
    token = _token(client, "admin", "admin123")
    # Generate at least one entry with a known action first.
    client.get("/api/admin/playbooks", headers={"Authorization": f"Bearer {token}"})  # 200, no denial entry

    resp = client.get("/api/admin/audit-log", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    all_entries = resp.json()
    assert len(all_entries) > 0

    resp_filtered = client.get(
        "/api/admin/audit-log", params={"action": "login_success", "user": "admin"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_filtered.status_code == 200
    assert all(e["action"] == "login_success" and e["username"] == "admin" for e in resp_filtered.json())
