"""Stage 3a — Segmentation (SRS FR-3.1, Design Doc §3.3). Slices a confirmed anomaly by each
of the metric's dimensions (region, product, channel, ...) and ranks the resulting segments by
how strongly each one, on its own, exhibits the same deviation — so evidence mining downstream
knows exactly which slice of the world to scope its search to."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Metric
from app.pipeline.series_utils import aggregate_daily, filter_by_dims, load_observations_df, window_stats_forecast

settings = get_settings()


@dataclass
class SegmentResult:
    dimension: str
    value: str
    contribution_score: float  # |z-score| of this segment in isolation — comparable across dimensions
    magnitude_pct: float
    sample_size: int
    signed_z: float = 0.0  # kept internal to segmentation's own direction check, not exposed via the API
    is_primary: bool = False


def _contributes_to_anomaly(signed_z: float, sample_size: int, anomaly_magnitude_pct: float) -> bool:
    """A segment is a genuine contributor to the parent anomaly only if BOTH:

    1. Direction agrees — its own deviation moves the same way as the parent KPI's (a segment
       that moved *opposite* the aggregate is offsetting the anomaly, not driving it, no matter
       how large its magnitude — e.g. a segment whose revenue rose 20% cannot be "the driver"
       of an overall revenue decline).
    2. It clears the same significance bar the anomaly itself had to clear (settings.
       significance_z_threshold) with enough sample (settings.min_window_sample_size) — reusing
       the pipeline's own existing statistical bar rather than a second, unexplained threshold,
       so a segment doesn't get called "dominant" on magnitude alone with only a couple of days
       of data behind it.

    Returns False (no forced primary) when neither condition holds — an honest "no segment
    contributes suffiently" is preferable to naming one anyway.
    """
    if anomaly_magnitude_pct == 0 or signed_z == 0:
        return False
    same_direction = (signed_z < 0) == (anomaly_magnitude_pct < 0)
    meets_bar = abs(signed_z) >= settings.significance_z_threshold and sample_size >= settings.min_window_sample_size
    return same_direction and meets_bar


def run_segmentation(
    db: Session, metric: Metric, window_start: dt.date, window_end: dt.date, anomaly_magnitude_pct: float
) -> list[SegmentResult]:
    raw = load_observations_df(db, metric.id)
    if raw.empty:
        return []

    dimension_keys = sorted({k for dims in raw["segment_dims"] for k in dims.keys()})
    results: list[SegmentResult] = []

    for dim in dimension_keys:
        values = sorted({dims.get(dim) for dims in raw["segment_dims"] if dim in dims})
        for value in values:
            sub = filter_by_dims(raw, {dim: value})
            if sub.empty:
                continue
            daily = aggregate_daily(sub, metric.aggregation)
            if daily["value"].dropna().shape[0] < 2 * metric.seasonality_period:
                continue  # not enough history in this slice to decompose meaningfully
            stats = window_stats_forecast(
                daily, window_start, window_end, metric.seasonality_period, settings.significance_z_threshold, settings.min_window_sample_size
            )
            results.append(
                SegmentResult(
                    dimension=dim,
                    value=value,
                    contribution_score=abs(stats["z_score"]),
                    magnitude_pct=stats["magnitude_pct"],
                    sample_size=stats["sample_size"],
                    signed_z=stats["z_score"],
                )
            )

    # Within each dimension, EVERY segment that actually contributes (right direction, clears
    # the significance bar) is marked primary — not just a forced single top-by-|z| pick. That
    # means zero, one, or several segments can end up primary per dimension: zero when nothing
    # in that dimension meaningfully explains the anomaly (a real, honest outcome — see
    # _contributes_to_anomaly), several when multiple segments genuinely co-drive it.
    by_dimension: dict[str, list[SegmentResult]] = {}
    for r in results:
        by_dimension.setdefault(r.dimension, []).append(r)
    for dim_results in by_dimension.values():
        dim_results.sort(key=lambda r: r.contribution_score, reverse=True)
        for r in dim_results:
            r.is_primary = _contributes_to_anomaly(r.signed_z, r.sample_size, anomaly_magnitude_pct)

    results.sort(key=lambda r: r.contribution_score, reverse=True)
    return results


def primary_segment_dims(segments: list[SegmentResult]) -> dict[str, str]:
    """Builds a {dimension: value} filter for scoping evidence mining — one value per
    dimension, e.g. {"region": "South", "product": "Product B"}.

    More than one segment in the same dimension can be marked is_primary (several can
    genuinely co-drive the anomaly — see run_segmentation) but evidence mining needs exactly
    one concrete value per dimension to scope its search to. Picking the STRONGEST contributor
    (highest contribution_score) in each dimension explicitly here — rather than a plain dict
    comprehension, which would silently keep whichever segment happened to be iterated last —
    makes that choice deterministic instead of an accident of iteration order. A prior version
    did exactly that and could scope evidence mining to a segment that only marginally cleared
    the bar while the real dominant one in that dimension got silently dropped."""
    strongest: dict[str, SegmentResult] = {}
    for s in segments:
        if not s.is_primary:
            continue
        current = strongest.get(s.dimension)
        if current is None or s.contribution_score > current.contribution_score:
            strongest[s.dimension] = s
    return {dim: s.value for dim, s in strongest.items()}
