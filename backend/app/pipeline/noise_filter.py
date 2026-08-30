"""
Stage 2 — Noise Filtering (SRS §3.2, Design Doc §3.2).

1. Data-quality check: duplicate detection before any statistical test runs (FR-2.1).
2. STL decomposition of the metric's aggregate daily series into trend/seasonal/residual (FR-2.2).
3. A sample-size-scaled confidence-interval test on the residual within the candidate window,
   against the residual's historical standard error (FR-2.3).
4. Non-significant or DQ-flagged windows are suppressed and logged, never surfaced (FR-2.4).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Metric, Observation
from app.pipeline.series_utils import aggregate_daily, decompose, load_observations_df, window_stats_forecast

settings = get_settings()


@dataclass
class DQResult:
    ok: bool
    reason: str | None = None
    detail: str | None = None


@dataclass
class SignificanceResult:
    is_significant: bool
    z_score: float
    magnitude_pct: float
    window_mean_actual: float
    window_mean_expected: float
    sample_size: int
    series: pd.DataFrame  # date, value, trend, seasonal, resid — full history, for charting


def check_data_quality(db: Session, metric: Metric, window_start: dt.date, window_end: dt.date) -> DQResult:
    """Detects sync/duplicate errors: more than one observation for the same entity+day
    within the window is treated as a duplicate-record sync error (FR-2.1)."""
    rows = (
        db.query(Observation.entity, Observation.timestamp, func.count(Observation.id))
        .filter(Observation.metric_id == metric.id, Observation.timestamp.between(window_start, window_end))
        .group_by(Observation.entity, Observation.timestamp)
        .having(func.count(Observation.id) > 1)
        .all()
    )
    if rows:
        entity, day, count = rows[0]
        detail = (
            f"{len(rows)} entity/day combination(s) have duplicate records in the window "
            f"(e.g. '{entity}' on {day} has {count} rows) — likely a source-system sync error."
        )
        return DQResult(ok=False, reason="data_quality", detail=detail)
    return DQResult(ok=True)


def run_significance_check(db: Session, metric: Metric, window_start: dt.date, window_end: dt.date) -> SignificanceResult:
    raw = load_observations_df(db, metric.id)
    daily = aggregate_daily(raw, metric.aggregation)
    stats = window_stats_forecast(
        daily, window_start, window_end, metric.seasonality_period, settings.significance_z_threshold, settings.min_window_sample_size
    )
    # Full-series decomposition is only for charting — the stats above are forecast-based.
    decomposed = decompose(daily, metric.seasonality_period)

    return SignificanceResult(
        is_significant=stats["is_significant"],
        z_score=stats["z_score"],
        magnitude_pct=stats["magnitude_pct"],
        window_mean_actual=stats["window_mean_actual"],
        window_mean_expected=stats["window_mean_expected"],
        sample_size=stats["sample_size"],
        series=decomposed,
    )
