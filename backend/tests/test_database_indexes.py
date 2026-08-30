"""
Database index tests (final hardening pass, item 4). These assert the indexes exist in
SQLAlchemy's own schema metadata — not against SQLite's query planner output (EXPLAIN QUERY
PLAN), which would be brittle and wouldn't even prove anything about Postgres. Checking the
metadata is exactly what's portable across both backends: these are plain Index()/index=True
declarations with no dialect-specific options, so the same metadata drives table creation on
either engine.
"""
from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.db import Base


def _fresh_inspector():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return inspect(engine)


def test_schema_creation_succeeds_with_all_indexes():
    # If any Index()/index=True declaration were malformed, create_all() itself would raise.
    inspector = _fresh_inspector()
    assert "observations" in inspector.get_table_names()
    assert "audit_log" in inspector.get_table_names()


def _index_columns(inspector, table: str) -> list[tuple[str, ...]]:
    return [tuple(ix["column_names"]) for ix in inspector.get_indexes(table)]


def test_observation_has_a_composite_metric_id_timestamp_index():
    inspector = _fresh_inspector()
    assert ("metric_id", "timestamp") in _index_columns(inspector, "observations")


def test_report_has_a_composite_routed_to_created_at_index():
    inspector = _fresh_inspector()
    assert ("routed_to", "created_at") in _index_columns(inspector, "reports")


def test_anomaly_status_and_created_at_are_indexed():
    inspector = _fresh_inspector()
    columns = {c for cols in _index_columns(inspector, "anomalies") for c in cols}
    assert "status" in columns
    assert "created_at" in columns


def test_suppressed_log_created_at_is_indexed():
    inspector = _fresh_inspector()
    columns = {c for cols in _index_columns(inspector, "suppressed_log") for c in cols}
    assert "created_at" in columns


def test_metric_department_is_indexed():
    inspector = _fresh_inspector()
    columns = {c for cols in _index_columns(inspector, "metrics") for c in cols}
    assert "department" in columns


def test_audit_log_has_its_expected_indexes():
    inspector = _fresh_inspector()
    columns = {c for cols in _index_columns(inspector, "audit_log") for c in cols}
    assert {"created_at", "username", "action"} <= columns


def test_segment_dimension_and_value_are_deliberately_not_indexed():
    # No query anywhere filters or sorts on Segment.dimension/value directly — Segments are
    # always fetched via the already-indexed anomaly_id relationship and processed in Python
    # (segmentation.py, anomalies.py). An index here would never be used by any real query, so
    # it's deliberately absent rather than "indexed just in case".
    inspector = _fresh_inspector()
    columns = {c for cols in _index_columns(inspector, "segments") for c in cols}
    assert "dimension" not in columns
    assert "value" not in columns
