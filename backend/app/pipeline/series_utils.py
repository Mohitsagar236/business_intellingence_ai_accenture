"""Shared helpers for loading and decomposing observation series — used by both the
metric-level Noise Filtering stage and the per-segment Root-Cause stage."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
from scipy.stats import theilslopes
from sqlalchemy.orm import Session
from statsmodels.tsa.seasonal import STL

from app.models import Observation


def load_observations_df(db: Session, metric_id: int) -> pd.DataFrame:
    rows = (
        db.query(Observation.timestamp, Observation.value, Observation.segment_dims)
        .filter(Observation.metric_id == metric_id)
        .order_by(Observation.timestamp)
        .all()
    )
    return pd.DataFrame(rows, columns=["date", "value", "segment_dims"])


def filter_by_dims(df: pd.DataFrame, dims_filter: dict[str, str] | None) -> pd.DataFrame:
    if not dims_filter:
        return df
    mask = df["segment_dims"].apply(lambda d: all(d.get(k) == v for k, v in dims_filter.items()))
    return df[mask]


def aggregate_daily(df: pd.DataFrame, aggregation: str) -> pd.DataFrame:
    agg_fn = "sum" if aggregation == "sum" else "mean"
    out = df.groupby("date", as_index=False)["value"].agg(agg_fn)
    out = out.set_index("date").asfreq("D")
    out["value"] = out["value"].interpolate().bfill().ffill()
    return out.reset_index()


def decompose(df: pd.DataFrame, period: int) -> pd.DataFrame:
    """Full-series STL fit — for charting (trend/seasonal/resid across the whole timeline)
    and for cross-metric correlation, where boundary bias affects both series symmetrically."""
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date

    if len(out) < 2 * period:
        # STL requires at least two full cycles; a real upload won't guarantee that the way the
        # 365-day synthetic dataset always did. Degenerate passthrough rather than raising —
        # the chart just shows raw values with no trend/seasonal/residual split yet.
        out["trend"] = out["value"]
        out["seasonal"] = 0.0
        out["resid"] = 0.0
        return out

    series = pd.Series(df["value"].values, index=pd.DatetimeIndex(df["date"]))
    result = STL(series, period=period, robust=True).fit()
    out["trend"] = result.trend.values
    out["seasonal"] = result.seasonal.values
    out["resid"] = result.resid.values
    return out


def add_confidence_band(df: pd.DataFrame, z_threshold: float, exclude_last_n: int) -> pd.DataFrame:
    """Adds a ci_upper/ci_lower band around trend+seasonal, for the KPI chart's confidence
    interval — computed from the residual standard deviation over history only (excluding the
    most recent `exclude_last_n` days), using the same z_threshold the significance test
    itself gates on, so the band drawn on the chart is the same boundary the pipeline treats
    as "normal variation," not a frontend-invented interval."""
    out = df.copy()
    baseline = out["trend"] + out["seasonal"]
    hist_resid = out["resid"].iloc[:-exclude_last_n] if 0 < exclude_last_n < len(out) else out["resid"]
    std = float(hist_resid.std(ddof=1)) if len(hist_resid) > 1 else 0.0
    out["ci_upper"] = baseline + z_threshold * std
    out["ci_lower"] = baseline - z_threshold * std
    return out


def window_stats_forecast(
    df: pd.DataFrame, window_start: dt.date, window_end: dt.date, period: int, z_threshold: float, min_n: int
) -> dict:
    """Sample-size-scaled significance test for the window, computed by *forecasting* into it
    rather than fitting a decomposition across it.

    Fitting STL across an anomaly at the very end of a series lets the trend component flex to
    partially absorb the shift (a boundary artifact) — understating how anomalous the window
    really is. Instead: fit STL on history strictly before the window, linearly extrapolate the
    trend forward, tile the seasonal component forward by its period, and compare the window's
    actual values against that forecast. The historical residual's standard deviation, scaled by
    sqrt(window size), gives the standard error for the z-test.
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    hist = df[df["date"] < window_start].reset_index(drop=True)
    window = df[(df["date"] >= window_start) & (df["date"] <= window_end)].reset_index(drop=True)
    n = len(window)

    if len(hist) < 2 * period or n == 0:
        return {
            "z_score": 0.0,
            "sample_size": n,
            "magnitude_pct": 0.0,
            "window_mean_actual": float(window["value"].mean()) if n else 0.0,
            "window_mean_expected": 0.0,
            "is_significant": False,
        }

    hist_series = pd.Series(hist["value"].values, index=pd.DatetimeIndex(hist["date"]))
    hist_fit = STL(hist_series, period=period, robust=True).fit()
    hist_seasonal = hist_fit.seasonal.values
    hist_resid = hist_fit.resid.values

    # The expected level is estimated directly from deseasonalized history with a robust
    # (Theil-Sen) slope, not from STL's own fitted trend tail — STL's trend can wobble at ITS
    # boundary (the day right before the window) the same way it wobbles at the anomaly's
    # boundary, and Theil-Sen's median-of-slopes is far less swayed by that than OLS would be.
    deseasonalized = hist["value"].values - hist_seasonal
    lookback = min(len(deseasonalized), period * 8)
    y = deseasonalized[-lookback:]
    x = np.arange(lookback)
    slope, intercept, _, _ = theilslopes(y, x)
    future_x = np.arange(lookback, lookback + n)
    level_forecast = slope * future_x + intercept

    # Seasonal is exactly periodic: day i of the window repeats the seasonal value from
    # the same position in the last full cycle of history.
    last_cycle = hist_seasonal[-period:]
    seasonal_forecast = np.array([last_cycle[i % period] for i in range(n)])

    expected = level_forecast + seasonal_forecast
    actual = window["value"].values
    residual_window = actual - expected

    hist_std = float(np.std(hist_resid, ddof=1)) if len(hist_resid) > 1 else 0.0
    hist_std = hist_std or 1e-6
    standard_error = hist_std / np.sqrt(n)
    z = float(residual_window.mean() / standard_error) if standard_error else 0.0

    expected_mean = float(expected.mean())
    actual_mean = float(actual.mean())
    magnitude_pct = ((actual_mean - expected_mean) / expected_mean * 100) if expected_mean else 0.0

    return {
        "z_score": z,
        "sample_size": n,
        "magnitude_pct": magnitude_pct,
        "window_mean_actual": actual_mean,
        "window_mean_expected": expected_mean,
        "is_significant": abs(z) >= z_threshold and n >= min_n,
    }
