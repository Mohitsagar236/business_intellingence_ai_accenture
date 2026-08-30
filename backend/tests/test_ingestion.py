"""
Real-data ingestion — validates the CSV/Excel upload path (pipeline/ingestion.py) that
replaced the synthetic seed in the live app, plus the robustness guards it exposed
(series_utils.decompose / orchestrator.run_detection on sparse or empty metrics).
"""
import datetime as dt

import pytest

from app.models import Metric, Observation, TextEvidence
from app.pipeline.ingestion import IngestionError, validate_and_insert_observations, validate_and_insert_text_evidence
from app.pipeline.orchestrator import run_detection
from app.pipeline.series_utils import add_confidence_band, decompose


@pytest.fixture
def fresh_metric(db_session):
    metric = Metric(key="test_metric", name="Test Metric", department="Ops", unit="USD", aggregation="sum", dimensions=["region"])
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)
    yield metric
    db_session.query(Observation).filter(Observation.metric_id == metric.id).delete()
    db_session.delete(metric)
    db_session.commit()


def _csv(rows: list[str]) -> bytes:
    return "\n".join(rows).encode("utf-8")


def test_valid_observations_csv_is_inserted(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", "2026-01-01,100,North", "2026-01-02,110,North"])
    result = validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert result.rows_inserted == 2
    assert result.date_range == (dt.date(2026, 1, 1), dt.date(2026, 1, 2))

    rows = db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).all()
    assert len(rows) == 2
    assert rows[0].segment_dims == {"region": "North"}
    assert rows[0].entity == "region=North"


def test_missing_dimension_column_is_rejected(db_session, fresh_metric):
    csv_bytes = _csv(["date,value", "2026-01-01,100"])  # missing required 'region' column
    with pytest.raises(IngestionError, match="region"):
        validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")


def test_unparseable_date_is_rejected(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", "not-a-date,100,North"])
    with pytest.raises(IngestionError, match="date"):
        validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")


def test_non_numeric_value_is_rejected(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", "2026-01-01,not-a-number,North"])
    with pytest.raises(IngestionError, match="value"):
        validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")


def test_missing_dimension_value_is_rejected(db_session, fresh_metric):
    # A blank 'region' cell must never silently become the literal string "nan" — reject the
    # whole file instead of writing a corrupted segment, per the "never silently corrupt
    # uploaded data" ingestion rule.
    csv_bytes = _csv(["date,value,region", "2026-01-01,100,North", "2026-01-02,110,"])
    with pytest.raises(IngestionError, match="missing"):
        validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 0


def test_duplicate_rows_are_rejected(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", "2026-01-01,100,North", "2026-01-01,105,North"])
    with pytest.raises(IngestionError, match="duplicate"):
        validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 0


def test_same_date_different_segment_is_not_a_duplicate(db_session, fresh_metric):
    # Same date but different dimension value is a legitimate distinct observation.
    csv_bytes = _csv(["date,value,region", "2026-01-01,100,North", "2026-01-01,50,South"])
    result = validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert result.rows_inserted == 2


def test_identical_file_uploaded_twice_is_all_duplicates(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", "2026-02-01,100,North", "2026-02-02,110,North"])
    first = validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert first.rows_inserted == 2
    assert first.duplicates_skipped == 0

    second = validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert second.rows_inserted == 0
    assert second.duplicates_skipped == 2
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 2


def test_mixed_batch_of_duplicate_and_new_rows_are_split_correctly(db_session, fresh_metric):
    validate_and_insert_observations(
        db_session, fresh_metric, _csv(["date,value,region", "2026-02-10,100,North"]), "obs.csv"
    )
    batch = _csv(
        [
            "date,value,region",
            "2026-02-10,100,North",  # duplicate of the row above
            "2026-02-11,105,North",  # new
        ]
    )
    result = validate_and_insert_observations(db_session, fresh_metric, batch, "obs.csv")
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 1
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 2


def test_same_value_different_date_is_not_a_cross_upload_duplicate(db_session, fresh_metric):
    validate_and_insert_observations(
        db_session, fresh_metric, _csv(["date,value,region", "2026-02-15,100,North"]), "obs.csv"
    )
    result = validate_and_insert_observations(
        db_session, fresh_metric, _csv(["date,value,region", "2026-02-16,100,North"]), "obs.csv"
    )
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 0
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 2


def test_same_date_different_segment_is_not_a_cross_upload_duplicate(db_session, fresh_metric):
    validate_and_insert_observations(
        db_session, fresh_metric, _csv(["date,value,region", "2026-02-20,100,North"]), "obs.csv"
    )
    result = validate_and_insert_observations(
        db_session, fresh_metric, _csv(["date,value,region", "2026-02-20,50,South"]), "obs.csv"
    )
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 0
    assert db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).count() == 2


def test_same_date_and_segment_on_a_different_metric_is_not_a_duplicate(db_session, fresh_metric):
    other = Metric(key="test_metric_other", name="Other Metric", department="Ops", unit="USD", aggregation="sum", dimensions=["region"])
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)
    try:
        validate_and_insert_observations(
            db_session, fresh_metric, _csv(["date,value,region", "2026-02-25,100,North"]), "obs.csv"
        )
        result = validate_and_insert_observations(
            db_session, other, _csv(["date,value,region", "2026-02-25,100,North"]), "obs.csv"
        )
        assert result.rows_inserted == 1
        assert result.duplicates_skipped == 0
    finally:
        db_session.query(Observation).filter(Observation.metric_id == other.id).delete()
        db_session.delete(other)
        db_session.commit()


def test_currency_formatted_value_is_cleaned_and_parsed(db_session, fresh_metric):
    csv_bytes = _csv(["date,value,region", '2026-01-01,"$1,234.56",North'])
    result = validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    assert result.rows_inserted == 1
    row = db_session.query(Observation).filter(Observation.metric_id == fresh_metric.id).one()
    assert row.value == 1234.56


def test_empty_file_is_rejected(db_session, fresh_metric):
    with pytest.raises(IngestionError, match="no data"):
        validate_and_insert_observations(db_session, fresh_metric, b"date,value,region\n", "obs.csv")


def test_unsupported_file_type_is_rejected(db_session, fresh_metric):
    with pytest.raises(IngestionError, match="Unsupported file type"):
        validate_and_insert_observations(db_session, fresh_metric, b"whatever", "obs.txt")


def test_text_evidence_upload_is_redacted_before_storage(db_session):
    csv_bytes = _csv(["date,text,region", '2026-01-01,"Reach me at jane@example.com about this.",North'])
    result = validate_and_insert_text_evidence(db_session, csv_bytes, "tickets.csv")
    assert result.rows_inserted == 1

    row = db_session.query(TextEvidence).order_by(TextEvidence.id.desc()).first()
    assert "jane@example.com" not in row.text
    assert "[REDACTED_EMAIL]" in row.text
    assert row.segment_dims == {"region": "North"}
    db_session.delete(row)
    db_session.commit()


def test_text_evidence_missing_required_column_rejected(db_session):
    with pytest.raises(IngestionError, match="text"):
        validate_and_insert_text_evidence(db_session, _csv(["date,region", "2026-01-01,North"]), "tickets.csv")


@pytest.fixture
def _cleanup_dup_test_rows(db_session):
    # Duplicate-detection tests use a dedicated source_system tag so they can't collide with
    # rows from other fixtures/tests that happen to share the same text — clean those up
    # afterward since db_session is session-scoped and shared across the whole test run.
    yield
    db_session.query(TextEvidence).filter(TextEvidence.source_system == "dup_test").delete()
    db_session.commit()


def test_identical_reupload_is_detected_as_duplicate(db_session, _cleanup_dup_test_rows):
    # The exact same file uploaded twice — the accidental re-upload case the feature exists for.
    csv_bytes = _csv(["date,text,source_system,region", '2026-01-01,"Delivery was late again.",dup_test,North'])
    first = validate_and_insert_text_evidence(db_session, csv_bytes, "tickets.csv")
    assert first.rows_inserted == 1
    assert first.duplicates_skipped == 0

    second = validate_and_insert_text_evidence(db_session, csv_bytes, "tickets.csv")
    assert second.rows_inserted == 0
    assert second.duplicates_skipped == 1
    assert db_session.query(TextEvidence).filter(TextEvidence.source_system == "dup_test").count() == 1


def test_same_text_different_date_is_not_a_duplicate(db_session, _cleanup_dup_test_rows):
    # A genuinely separate observation — same wording, different day — must be accepted, not
    # collapsed into the first one.
    validate_and_insert_text_evidence(
        db_session, _csv(["date,text,source_system,region", '2026-01-01,"Delivery was late again.",dup_test,North']), "tickets.csv"
    )
    result = validate_and_insert_text_evidence(
        db_session, _csv(["date,text,source_system,region", '2026-01-05,"Delivery was late again.",dup_test,North']), "tickets.csv"
    )
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 0
    assert db_session.query(TextEvidence).filter(TextEvidence.source_system == "dup_test").count() == 2


def test_same_text_different_source_is_not_a_duplicate(db_session, _cleanup_dup_test_rows):
    # Same wording and date, but a different source system — e.g. the same sentence logged by a
    # survey AND independently by a support ticket on the same day — is a separate observation.
    validate_and_insert_text_evidence(
        db_session, _csv(["date,text,source_system,region", '2026-01-01,"Delivery was late again.",dup_test,North']), "tickets.csv"
    )
    result = validate_and_insert_text_evidence(
        db_session, _csv(["date,text,source_system,region", '2026-01-01,"Delivery was late again.",dup_test_2,North']), "tickets.csv"
    )
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 0
    db_session.query(TextEvidence).filter(TextEvidence.source_system == "dup_test_2").delete()
    db_session.commit()


def test_mixed_batch_accepts_new_rows_and_reports_duplicates(db_session, _cleanup_dup_test_rows):
    validate_and_insert_text_evidence(
        db_session, _csv(["date,text,source_system,region", '2026-01-01,"Delivery was late again.",dup_test,North']), "tickets.csv"
    )
    batch = _csv(
        [
            "date,text,source_system,region",
            '2026-01-01,"Delivery was late again.",dup_test,North',  # duplicate of the row above
            '2026-01-02,"Refund took too long to process.",dup_test,North',  # new
        ]
    )
    result = validate_and_insert_text_evidence(db_session, batch, "tickets.csv")
    assert result.rows_inserted == 1
    assert result.duplicates_skipped == 1
    assert db_session.query(TextEvidence).filter(TextEvidence.source_system == "dup_test").count() == 2


# --- robustness: real uploads won't guarantee 2 full seasonal cycles of history ---


def test_decompose_does_not_crash_on_short_series():
    import pandas as pd

    df = pd.DataFrame({"date": [dt.date(2026, 1, 1), dt.date(2026, 1, 2), dt.date(2026, 1, 3)], "value": [10.0, 12.0, 11.0]})
    out = decompose(df, period=7)  # far fewer than 2*7 rows
    assert list(out["trend"]) == [10.0, 12.0, 11.0]
    assert list(out["seasonal"]) == [0.0, 0.0, 0.0]


def test_confidence_band_widens_with_residual_noise():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    dates = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    quiet = pd.DataFrame({"date": dates, "value": 100 + rng.normal(0, 0.5, 30)})
    noisy = pd.DataFrame({"date": dates, "value": 100 + rng.normal(0, 10, 30)})

    quiet_band = add_confidence_band(decompose(quiet, period=7), z_threshold=2.0, exclude_last_n=5)
    noisy_band = add_confidence_band(decompose(noisy, period=7), z_threshold=2.0, exclude_last_n=5)

    quiet_width = (quiet_band["ci_upper"] - quiet_band["ci_lower"]).iloc[0]
    noisy_width = (noisy_band["ci_upper"] - noisy_band["ci_lower"]).iloc[0]
    assert noisy_width > quiet_width
    # The band must be centered on trend+seasonal, not on the raw actual value.
    baseline = quiet_band["trend"] + quiet_band["seasonal"]
    assert quiet_band["ci_upper"].iloc[0] > baseline.iloc[0] > quiet_band["ci_lower"].iloc[0]


def test_run_detection_on_metric_with_no_observations_returns_no_data(db_session, fresh_metric):
    result = run_detection(db_session, fresh_metric)
    assert result["status"] == "no_data"


def test_run_detection_on_sparse_metric_does_not_500(db_session, fresh_metric):
    csv_bytes = _csv(
        ["date,value,region"]
        + [f"2026-01-{d:02d},{100 + d},North" for d in range(1, 6)]  # only 5 days of history
    )
    validate_and_insert_observations(db_session, fresh_metric, csv_bytes, "obs.csv")
    result = run_detection(db_session, fresh_metric)
    # Not enough history to ever be "significant" — but it must resolve cleanly, not raise.
    assert result["status"] in ("suppressed_noise", "suppressed_data_quality", "no_data")
