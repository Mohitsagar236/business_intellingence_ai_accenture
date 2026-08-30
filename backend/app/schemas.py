"""Pydantic response schemas — the API's external contract."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    username: str
    display_name: str
    role: str
    department: str | None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MetricCreateIn(BaseModel):
    key: str
    name: str
    department: str
    unit: str
    aggregation: str = "sum"  # sum | mean
    seasonality_period: int = 7
    dimensions: list[str] = []


class UploadResultOut(BaseModel):
    rows_inserted: int
    date_range_start: dt.date | None
    date_range_end: dt.date | None
    warnings: list[str] = []
    duplicates_skipped: int = 0


class MetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    key: str
    name: str
    department: str
    unit: str
    aggregation: str
    dimensions: list[str]
    seasonality_period: int


class MetricStatusOut(MetricOut):
    latest_status: str | None  # validated | ambiguous | suppressed_noise | suppressed_data_quality | unknown
    latest_anomaly_id: int | None
    latest_checked_at: dt.datetime | None


class SeriesPointOut(BaseModel):
    date: dt.date
    value: float
    trend: float
    seasonal: float
    resid: float
    ci_upper: float
    ci_lower: float


class MetricDetailOut(MetricStatusOut):
    series: list[SeriesPointOut]
    anomalies: list["AnomalySummaryOut"]
    insufficient_history: bool = False
    observation_count: int = 0


class SegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    dimension: str
    value: str
    contribution_score: float
    is_primary: bool


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    source: str
    description: str
    correlation: float | None
    lag_days: int | None
    theme_keywords: list[str] | None
    spike_ratio: float | None
    excerpts: list[str] = []
    # Real date range this piece of evidence spans — for structured evidence, the anomaly
    # window shifted by lag_days; for unstructured, the min/max timestamp of the referenced
    # TextEvidence rows. Populated in app/api/anomalies.py, used by the frontend evidence
    # timeline so it plots only real dates, never fabricated ones.
    window_start: dt.date | None = None
    window_end: dt.date | None = None


class HypothesisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cause_category: str
    cause_display: str
    confidence: float
    rank: int
    status: str
    disambiguation_gap: str | None
    structured_evidence_id: int | None
    unstructured_evidence_id: int | None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    problem_statement: str
    cause_statement: str
    confidence_statement: str
    action_statement: str
    citations: list[int]
    stripped_claims: list[str]
    routed_to: str
    generated_by: str
    created_at: dt.datetime


class AnomalySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_id: int
    window_start: dt.date
    window_end: dt.date
    magnitude_pct: float
    significance_score: float
    status: str
    created_at: dt.datetime


class AnomalyDetailOut(AnomalySummaryOut):
    metric: MetricOut
    segments: list[SegmentOut]
    evidence: list[EvidenceOut]
    hypotheses: list[HypothesisOut]
    report: ReportOut | None


class ReportListItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    anomaly_id: int
    status: str
    routed_to: str
    created_at: dt.datetime
    metric_name: str
    problem_statement: str


class SuppressedLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    metric_id: int
    metric_name: str
    window_start: dt.date
    window_end: dt.date
    reason: str
    detail: str
    z_score: float | None
    created_at: dt.datetime


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: dt.datetime
    username: str | None
    role: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    success: bool
    detail: str | None


class PlaybookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cause_category: str
    title: str
    owner_department: str
    actions: list[str]
    version: int


class RunDetectionOut(BaseModel):
    status: str
    anomaly_id: int | None = None
    report_id: int | None = None
    suppressed_log_id: int | None = None
    detail: str | None = None
    z_score: float | None = None


class DetectionStageOut(BaseModel):
    stage: str
    ok: bool
    detail: str | None = None


class DetectionJobOut(BaseModel):
    job_id: str
    status: str  # running | done | failed
    stages: list[DetectionStageOut]
    result: RunDetectionOut | None = None
    error: str | None = None
