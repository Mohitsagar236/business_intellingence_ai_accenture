"""
Tests for the judge-demo dataset (app/data/demo_scenarios.py, scripts/seed_demo.py) — a THIRD
fixture alongside the empty-start production app and the pytest-only synthetic.py fixture, so
it gets its own isolated in-memory database rather than sharing the `db_session` fixture other
test files use (that one is pre-populated with app/data/synthetic.py's dataset, not this one).

Verifies the dataset is deterministic and reproducible offline (no Kaggle API / network calls),
contains the expected metrics/dimensions, and that all four scenarios resolve to the pipeline
outcome the demo is built to demonstrate — the same kind of "reaches the *right* answer, not
just runs" assertion test_pipeline.py makes for the synthetic fixture.
"""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data import demo_scenarios
from app.data.playbooks_seed import seed as seed_playbooks
from app.db import Base
from app.models import Metric, Observation, TextEvidence
from app.pipeline.orchestrator import run_detection


def _fresh_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


@pytest.fixture(scope="module")
def demo_db():
    """Session-scoped (module-level) so the four detection runs below share one seeded
    dataset — mirrors tests/test_pipeline.py's pattern against the synthetic fixture."""
    db = _fresh_db()
    seed_playbooks(db)
    demo_scenarios.generate(db)
    yield db
    db.close()


def test_kaggle_csv_is_present_and_parses_deterministically():
    rows_a = demo_scenarios._read_real_revenue_rows()
    rows_b = demo_scenarios._read_real_revenue_rows()
    assert len(rows_a) > 0, "kaggle_data/processed/revenue_by_region_category.csv must exist — run prepare_superstore.py"
    assert rows_a == rows_b, "reading the same prepared CSV twice must produce identical rows"
    assert all(isinstance(r["date"], dt.date) for r in rows_a)
    assert all(isinstance(r["value"], float) for r in rows_a)


def test_demo_dataset_contains_the_expected_metrics(demo_db):
    keys = {m.key for m in demo_db.query(Metric).all()}
    assert keys == {
        "demo_revenue_validated",
        "demo_revenue_ambiguous",
        "demo_revenue_suppressed",
        "demo_revenue_data_quality",
        "demo_support_tickets",
    }


def test_demo_metrics_declare_real_superstore_dimensions(demo_db):
    for key in ["demo_revenue_validated", "demo_revenue_ambiguous", "demo_revenue_suppressed", "demo_revenue_data_quality"]:
        metric = demo_db.query(Metric).filter(Metric.key == key).one()
        assert set(metric.dimensions) == {"region", "category"}
        regions = {o.segment_dims["region"] for o in demo_db.query(Observation).filter(Observation.metric_id == metric.id)}
        categories = {o.segment_dims["category"] for o in demo_db.query(Observation).filter(Observation.metric_id == metric.id)}
        # Real Kaggle Superstore values only — never invented dimension values.
        assert regions <= {"Central", "East", "South", "West"}
        assert categories <= {"Furniture", "Office Supplies", "Technology"}


def test_text_evidence_is_labeled_as_demo_synthetic_not_real(demo_db):
    rows = demo_db.query(TextEvidence).all()
    assert len(rows) > 0
    assert all(r.source_system == "demo_synthetic_support" for r in rows), (
        "every demo text-evidence row must be honestly labeled synthetic — never presented as real customer data"
    )


def test_revenue_observations_are_labeled_as_derived_from_kaggle(demo_db):
    rows = demo_db.query(Observation).join(Metric).filter(Metric.key == "demo_revenue_validated").all()
    assert all(r.source_system == "superstore_kaggle_derived" for r in rows)


def test_validated_scenario_resolves_to_validated(demo_db):
    metric = demo_db.query(Metric).filter(Metric.key == "demo_revenue_validated").one()
    result = run_detection(demo_db, metric)
    assert result["status"] == "validated"

    from app.models import Anomaly

    anomaly = demo_db.get(Anomaly, result["anomaly_id"])
    top = sorted(anomaly.hypotheses, key=lambda h: h.rank)[0]
    assert top.status == "validated"
    assert top.cause_category == "product_regression"
    # The structured driver must be the demo's OWN synthetic companion metric — not a real
    # Superstore column, and this must be visible in the persisted evidence for provenance.
    structured_evidence = [e for e in anomaly.evidence if e.type == "structured"][0]
    assert structured_evidence.source == "demo_support_tickets"
    unstructured_evidence = [e for e in anomaly.evidence if e.type == "unstructured"][0]
    assert unstructured_evidence.source == "demo_synthetic_support"


def test_ambiguous_scenario_resolves_to_ambiguous_with_named_gaps(demo_db):
    metric = demo_db.query(Metric).filter(Metric.key == "demo_revenue_ambiguous").one()
    result = run_detection(demo_db, metric)
    assert result["status"] == "ambiguous"

    from app.models import Anomaly

    anomaly = demo_db.get(Anomaly, result["anomaly_id"])
    hyps = sorted(anomaly.hypotheses, key=lambda h: h.rank)
    assert len(hyps) >= 2, "a genuinely ambiguous case must keep multiple ranked hypotheses"
    assert all(h.status == "candidate" for h in hyps)
    assert all(h.disambiguation_gap for h in hyps)
    # No hypothesis may be laundered into a false single answer.
    assert not any(h.status == "validated" for h in hyps)


def test_suppressed_scenario_produces_no_business_report(demo_db):
    metric = demo_db.query(Metric).filter(Metric.key == "demo_revenue_suppressed").one()
    result = run_detection(demo_db, metric)
    assert result["status"] in ("suppressed_noise", "suppressed_data_quality")

    from app.models import Anomaly

    assert demo_db.query(Anomaly).filter(Anomaly.metric_id == metric.id).count() == 0, (
        "a suppressed scenario must never produce an Anomaly/Report row"
    )


def test_data_quality_scenario_is_suppressed_before_any_significance_test(demo_db):
    metric = demo_db.query(Metric).filter(Metric.key == "demo_revenue_data_quality").one()
    result = run_detection(demo_db, metric)
    assert result["status"] == "suppressed_data_quality"

    from app.models import SuppressedLog

    log = demo_db.get(SuppressedLog, result["suppressed_log_id"])
    assert log.reason == "data_quality"


def test_reset_and_reload_reproduces_identical_results():
    """The judge demo must be repeatable: dropping and reseeding must reproduce the exact same
    analytical outcome every time — no dependency on wall-clock time, random LLM behavior, or
    network availability (see scripts/seed_demo.py's own docstring)."""
    results = []
    for _ in range(2):
        db = _fresh_db()
        seed_playbooks(db)
        demo_scenarios.generate(db)
        run = {}
        for key in ["demo_revenue_validated", "demo_revenue_ambiguous", "demo_revenue_suppressed", "demo_revenue_data_quality"]:
            metric = db.query(Metric).filter(Metric.key == key).one()
            run[key] = run_detection(db, metric)["status"]
        results.append(run)
        db.close()

    assert results[0] == results[1], f"reseeding produced different outcomes: {results[0]} vs {results[1]}"
    assert results[0] == {
        "demo_revenue_validated": "validated",
        "demo_revenue_ambiguous": "ambiguous",
        "demo_revenue_suppressed": "suppressed_noise",
        "demo_revenue_data_quality": "suppressed_data_quality",
    }
