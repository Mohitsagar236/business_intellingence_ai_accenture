"""
Stage 1 — Data Ingestion (SRS FR-1.1/1.2), for real uploaded files.

Accepts CSV or Excel. On any validation problem — a missing required column, an unparseable
date or value, an empty file — the whole upload is rejected with a clear error rather than
silently skipping bad rows. This is someone's real business data; a partial, silently-corrupted
import is worse than a rejected one they can fix and retry.
"""
from __future__ import annotations

import datetime as dt
import io
import logging
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.orm import Session

from app.logging_config import event
from app.models import Metric, Observation, TextEvidence
from app.pipeline.pii_redaction import redact

MAX_ROWS = 50_000
logger = logging.getLogger(__name__)


class IngestionError(ValueError):
    """A user-facing, already-readable validation failure — the API layer returns its message as-is."""


@dataclass
class UploadResult:
    rows_inserted: int
    date_range: tuple[dt.date, dt.date] | None
    warnings: list[str] = field(default_factory=list)
    duplicates_skipped: int = 0  # text evidence only — see validate_and_insert_text_evidence


def _read_tabular(file_bytes: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(file_bytes))
        elif lower.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            raise IngestionError(f"Unsupported file type '{filename}' — upload a .csv or .xlsx file.")
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError(f"Could not parse '{filename}' as a spreadsheet: {exc}") from exc

    df.columns = [str(c).strip().lower() for c in df.columns]
    if df.empty:
        raise IngestionError("The uploaded file has no data rows.")
    if len(df) > MAX_ROWS:
        raise IngestionError(f"The uploaded file has {len(df)} rows, over the {MAX_ROWS}-row limit for a single upload.")
    return df


def _parse_dates(df: pd.DataFrame, column: str = "date") -> pd.Series:
    parsed = pd.to_datetime(df[column], errors="coerce")
    bad = df[parsed.isna()]
    if not bad.empty:
        raise IngestionError(f"{len(bad)} row(s) have an unparseable '{column}' value — e.g. row {bad.index[0] + 2}: '{df.loc[bad.index[0], column]}'.")
    return parsed.dt.date


def _parse_numeric(df: pd.DataFrame, column: str) -> pd.Series:
    cleaned = df[column].astype(str).str.replace(r"[$,%]", "", regex=True).str.strip()
    parsed = pd.to_numeric(cleaned, errors="coerce")
    bad = df[parsed.isna()]
    if not bad.empty:
        raise IngestionError(f"{len(bad)} row(s) have a non-numeric '{column}' value — e.g. row {bad.index[0] + 2}: '{df.loc[bad.index[0], column]}'.")
    return parsed


def _entity_key(dims: dict[str, str]) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(dims.items()))


def _validate_no_missing_values(df: pd.DataFrame, columns: list[str]) -> None:
    for col in columns:
        bad = df[df[col].isna() | (df[col].astype(str).str.strip() == "")]
        if not bad.empty:
            raise IngestionError(
                f"{len(bad)} row(s) have a missing '{col}' value — e.g. row {bad.index[0] + 2}. "
                f"Every row must have a value for every declared dimension."
            )


def _validate_no_duplicate_rows(df: pd.DataFrame, dates: pd.Series, dim_columns: list[str]) -> None:
    key = pd.DataFrame({"date": dates.astype(str)})
    for d in dim_columns:
        key[d] = df[d].astype(str).str.strip()
    dup_mask = key.duplicated(keep=False)
    if dup_mask.any():
        first_idx = key[dup_mask].index[0]
        dim_desc = ", ".join(dim_columns) if dim_columns else "no dimensions"
        raise IngestionError(
            f"{int(dup_mask.sum())} row(s) are exact duplicates (same date + {dim_desc}) — "
            f"e.g. row {first_idx + 2}. Remove the duplicate rows and re-upload."
        )


def validate_and_insert_observations(db: Session, metric: Metric, file_bytes: bytes, filename: str) -> UploadResult:
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    event(logger, logging.INFO, "ingestion_upload_started", metric=metric.key, file_type=file_type)

    try:
        df = _read_tabular(file_bytes, filename)

        required = {"date", "value", *metric.dimensions}
        missing = required - set(df.columns)
        if missing:
            raise IngestionError(
                f"Missing required column(s): {', '.join(sorted(missing))}. "
                f"This metric expects: date, value{''.join(f', {d}' for d in metric.dimensions)}."
            )

        _validate_no_missing_values(df, list(metric.dimensions))
        dates = _parse_dates(df)
        values = _parse_numeric(df, "value")
        _validate_no_duplicate_rows(df, dates, list(metric.dimensions))
        source = df["source_system"].astype(str) if "source_system" in df.columns else pd.Series(["uploaded"] * len(df))

        # Cross-upload duplicate detection: the app's own established identity for "the same
        # observation" is (metric, entity, timestamp) — this is exactly what noise_filter.py's
        # data-quality gate groups on to detect sync errors (more than one row for the same
        # entity/day). Re-uploading a file the DB already has rows for must not silently double
        # the data; skip-and-count here, the same partial-accept shape as text evidence, rather
        # than rejecting the whole file — a mixed upload of old + genuinely new rows is a normal
        # "append more data" case, not an error.
        unique_dates = set(dates.unique())
        existing_keys = {
            (entity, timestamp)
            for entity, timestamp in db.query(Observation.entity, Observation.timestamp)
            .filter(Observation.metric_id == metric.id, Observation.timestamp.in_(unique_dates))
            .all()
        }

        warnings: list[str] = []
        count = 0
        duplicates = 0
        for i in range(len(df)):
            dims = {d: str(df.iloc[i][d]).strip() for d in metric.dimensions}
            entity = _entity_key(dims)
            row_timestamp = dates.iloc[i]
            key = (entity, row_timestamp)
            if key in existing_keys:
                duplicates += 1
                continue
            existing_keys.add(key)  # also catches a duplicate landing twice within THIS file
            db.add(
                Observation(
                    metric_id=metric.id,
                    entity=entity,
                    segment_dims=dims,
                    source_system=str(source.iloc[i]) or "uploaded",
                    timestamp=row_timestamp,
                    value=float(values.iloc[i]),
                )
            )
            count += 1
        db.commit()
    except IngestionError as exc:
        # The message is already a sanitized, user-facing validation reason (e.g. "3 rows have
        # an unparseable 'date' value") — never the raw file contents.
        event(logger, logging.WARNING, "ingestion_failed", metric=metric.key, rows_accepted=0, reason=str(exc))
        raise

    event(logger, logging.INFO, "ingestion_succeeded", metric=metric.key, rows_accepted=count, duplicates_skipped=duplicates)
    return UploadResult(rows_inserted=count, date_range=(min(dates), max(dates)), warnings=warnings, duplicates_skipped=duplicates)


def _text_evidence_signature(text: str, timestamp: dt.date, source_system: str, dims: dict[str, str]) -> tuple:
    """Duplicate key for TextEvidence: same (redacted) text + same date + same source + same
    segment. Deliberately does NOT key on text alone — two different customers, or the same
    customer on two different days, can legitimately write the same sentence ("delivery was
    late") and that must stay two separate pieces of evidence, not get collapsed into one. This
    only catches the "the same record landed twice" case: identical content, identical
    date/source/segment — the shape of an accidental re-upload, not a coincidence of wording."""
    return (text, timestamp, source_system, tuple(sorted(dims.items())))


def validate_and_insert_text_evidence(db: Session, file_bytes: bytes, filename: str) -> UploadResult:
    file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
    event(logger, logging.INFO, "ingestion_upload_started", source="text_evidence", file_type=file_type)

    try:
        df = _read_tabular(file_bytes, filename)

        required = {"date", "text"}
        missing = required - set(df.columns)
        if missing:
            raise IngestionError(f"Missing required column(s): {', '.join(sorted(missing))}. Expected at least: date, text.")

        dates = _parse_dates(df)
        texts = df["text"].astype(str).str.strip()
        empty_text_rows = texts[texts == ""]
        if not empty_text_rows.empty:
            raise IngestionError(f"{len(empty_text_rows)} row(s) have an empty 'text' value — e.g. row {empty_text_rows.index[0] + 2}.")

        source = df["source_system"].astype(str) if "source_system" in df.columns else pd.Series(["uploaded"] * len(df))
        dim_columns = [c for c in df.columns if c not in {"date", "text", "source_system"}]

        # Duplicate detection (see _text_evidence_signature for the exact definition): accidental
        # re-uploads are skipped and counted, not silently merged and not a whole-file rejection
        # — text evidence is lower-stakes than a financial Observation, and a partial accept
        # ("your 40 new tickets were added, 3 looked like repeats of what's already here") is
        # more useful here than forcing a re-upload of an otherwise-good file.
        unique_dates = set(dates.unique())
        existing_rows = db.query(TextEvidence).filter(TextEvidence.timestamp.in_(unique_dates)).all()
        seen_signatures = {
            _text_evidence_signature(r.text, r.timestamp, r.source_system, r.segment_dims) for r in existing_rows
        }

        count = 0
        duplicates = 0
        for i in range(len(df)):
            dims = {c: str(df.iloc[i][c]) for c in dim_columns if pd.notna(df.iloc[i][c]) and str(df.iloc[i][c]).strip() != ""}
            redacted_text = redact(str(texts.iloc[i]))
            row_source = str(source.iloc[i]) or "uploaded"
            row_timestamp = dates.iloc[i]
            signature = _text_evidence_signature(redacted_text, row_timestamp, row_source, dims)
            if signature in seen_signatures:
                duplicates += 1
                continue
            seen_signatures.add(signature)  # also catches a duplicate landing twice within THIS file
            db.add(
                TextEvidence(
                    source_system=row_source,
                    segment_dims=dims,
                    timestamp=row_timestamp,
                    # Never log the text itself — it's redacted before storage, not before logging.
                    text=redacted_text,
                )
            )
            count += 1
        db.commit()
    except IngestionError as exc:
        event(logger, logging.WARNING, "ingestion_failed", source="text_evidence", rows_accepted=0, reason=str(exc))
        raise

    event(logger, logging.INFO, "ingestion_succeeded", source="text_evidence", rows_accepted=count, duplicates_skipped=duplicates)
    return UploadResult(rows_inserted=count, date_range=(min(dates), max(dates)), duplicates_skipped=duplicates)
