"""SQLAlchemy models — mirrors the conceptual data model in the Design Document (§5)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


class User(Base):
    """SRS §2.3 user classes, made concrete for role-based access control (Design Doc §8)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # analyst | dept_head | admin | executive
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    # Indexed: GET /api/metrics (list_metrics) orders every request by department, name.
    department: Mapped[str] = mapped_column(String(64), index=True)
    unit: Mapped[str] = mapped_column(String(16))
    seasonality_period: Mapped[int] = mapped_column(Integer, default=7)
    aggregation: Mapped[str] = mapped_column(String(8), default="sum")  # sum | mean — how segments roll up
    dimensions: Mapped[list] = mapped_column(JSON, default=list)  # declared segment dims, e.g. ["region", "product"]

    observations: Mapped[list["Observation"]] = relationship(back_populates="metric")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="metric")


class Observation(Base):
    """A single structured data point — the 'Observation Store' from the Design Doc (§3.1)."""

    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metrics.id"), index=True)
    entity: Mapped[str] = mapped_column(String(128), index=True)  # segment key, e.g. "region=North|product=Product A"
    segment_dims: Mapped[dict] = mapped_column(JSON)
    source_system: Mapped[str] = mapped_column(String(32))  # crm | erp | ticketing | finance | hr
    timestamp: Mapped[dt.date] = mapped_column(Date, index=True)
    value: Mapped[float] = mapped_column(Float)
    is_duplicate: Mapped[bool] = mapped_column(default=False)  # injected for the DQ-check scenario

    metric: Mapped["Metric"] = relationship(back_populates="observations")

    __table_args__ = (
        # Every real read of this table filters by metric_id and then either orders by or
        # range-filters on timestamp (series_utils.load_observations_df, noise_filter's window
        # query, metrics.py's delete-by-metric) — metric_id first (the equality filter) then
        # timestamp (the range/sort column) matches that access pattern directly. Plain btree,
        # identical on SQLite and Postgres.
        Index("ix_observations_metric_id_timestamp", "metric_id", "timestamp"),
    )


class TextEvidence(Base):
    """A single unstructured record — call note, ticket, survey response, or report excerpt."""

    __tablename__ = "text_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(String(32))  # ticketing | call_notes | survey | report
    segment_dims: Mapped[dict] = mapped_column(JSON)
    timestamp: Mapped[dt.date] = mapped_column(Date, index=True)
    text: Mapped[str] = mapped_column(Text)


class Anomaly(Base):
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metrics.id"), index=True)
    window_start: Mapped[dt.date] = mapped_column(Date)
    window_end: Mapped[dt.date] = mapped_column(Date)
    magnitude_pct: Mapped[float] = mapped_column(Float)  # % deviation from expected (trend+seasonal)
    significance_score: Mapped[float] = mapped_column(Float)  # sample-size-scaled z-score
    # Indexed: GET /api/anomalies?status= filters on this (anomalies.py::list_anomalies).
    status: Mapped[str] = mapped_column(String(24), index=True)
    # suppressed_noise | suppressed_dq | validated | ambiguous
    dq_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Indexed: list_anomalies (and _latest_activity/_bulk_latest_activity's window functions)
    # order by this on every call, filtered or not.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    metric: Mapped["Metric"] = relationship(back_populates="anomalies")
    segments: Mapped[list["Segment"]] = relationship(back_populates="anomaly", cascade="all, delete-orphan")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="anomaly", cascade="all, delete-orphan")
    hypotheses: Mapped[list["Hypothesis"]] = relationship(back_populates="anomaly", cascade="all, delete-orphan")
    report: Mapped["Report"] = relationship(back_populates="anomaly", uselist=False, cascade="all, delete-orphan")


class Segment(Base):
    """Stage 3a — per-dimension slice of an anomaly, ranked by contribution."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), index=True)
    dimension: Mapped[str] = mapped_column(String(32))  # region | product | channel
    value: Mapped[str] = mapped_column(String(64))
    contribution_score: Mapped[float] = mapped_column(Float)
    is_primary: Mapped[bool] = mapped_column(default=False)

    anomaly: Mapped["Anomaly"] = relationship(back_populates="segments")


class Evidence(Base):
    """Stage 3b — one piece of structured or unstructured evidence gathered for an anomaly."""

    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # structured | unstructured
    source: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    ref_metric_id: Mapped[int | None] = mapped_column(ForeignKey("metrics.id"), nullable=True)
    ref_text_evidence_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correlation: Mapped[float | None] = mapped_column(Float, nullable=True)
    lag_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    theme_keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    spike_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)

    anomaly: Mapped["Anomaly"] = relationship(back_populates="evidence")


class Hypothesis(Base):
    """Stage 3c output — a candidate (or the validated) root cause."""

    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), index=True)
    cause_category: Mapped[str] = mapped_column(String(64))
    cause_display: Mapped[str] = mapped_column(String(256))
    confidence: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # validated | candidate
    structured_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    unstructured_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    disambiguation_gap: Mapped[str | None] = mapped_column(Text, nullable=True)

    anomaly: Mapped["Anomaly"] = relationship(back_populates="hypotheses")


class Playbook(Base):
    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cause_category: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(256))
    owner_department: Mapped[str] = mapped_column(String(64))
    actions: Mapped[list] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Report(Base):
    """Stage 4 output — the department-ready diagnosis."""

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomalies.id"), unique=True, index=True)
    hypothesis_id: Mapped[int | None] = mapped_column(ForeignKey("hypotheses.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16))  # validated | ambiguous
    problem_statement: Mapped[str] = mapped_column(Text)
    cause_statement: Mapped[str] = mapped_column(Text)
    confidence_statement: Mapped[str] = mapped_column(Text)
    action_statement: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON)  # evidence ids actually cited & verified grounded
    stripped_claims: Mapped[list] = mapped_column(JSON, default=list)  # ungrounded sentences the guard removed
    routed_to: Mapped[str] = mapped_column(String(64))
    generated_by: Mapped[str] = mapped_column(String(32), default="claude")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)

    anomaly: Mapped["Anomaly"] = relationship(back_populates="report")

    __table_args__ = (
        # routed_to is the field a dept_head's server-side authorization scoping filters on for
        # EVERY request (app/api/reports.py — see the P0-2 department-isolation fix), always
        # followed by ORDER BY created_at DESC — the single most security-relevant query
        # pattern in the app, not just a performance nicety.
        Index("ix_reports_routed_to_created_at", "routed_to", "created_at"),
    )


class SuppressedLog(Base):
    """Everything Stage 2 filters out — logged silently, never surfaced as a report (FR-2.4/2.5)."""

    __tablename__ = "suppressed_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("metrics.id"), index=True)
    window_start: Mapped[dt.date] = mapped_column(Date)
    window_end: Mapped[dt.date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(24))  # not_significant | data_quality
    detail: Mapped[str] = mapped_column(Text)
    z_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Indexed: admin.py::list_suppressed_log orders the whole table by this on every call.
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)

    metric: Mapped["Metric"] = relationship()


class AuditLog(Base):
    """Persistent security/business accountability trail — distinct from the operational
    logging in app/logging_config.py (which is for debugging, not kept in the database, and
    not filterable by an admin). Only security- or accountability-relevant actions land here
    (login outcomes, authorization denials, metric create/delete) — never every pipeline event;
    see app/audit.py for the single write path and the explicit list of what's recorded.

    Never store: passwords, JWTs/API keys, raw customer text, or anything beyond short,
    already-safe metadata in `detail`."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    # Denormalized (not a User FK) deliberately — an audit entry must stay readable and stable
    # even if the user is later deleted or renamed; it's a record of what happened, not a live
    # reference.
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "login_success", "metric_created"
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(default=True)
    detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
