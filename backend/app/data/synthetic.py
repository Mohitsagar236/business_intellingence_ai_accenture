"""
Synthetic data generator — TEST FIXTURE ONLY as of the real-data-ingestion change.

The running app no longer seeds itself from this (see scripts/seed_and_run.py) — real KPI
data comes in via CSV/Excel upload through the Data page (pipeline/ingestion.py). This module
is kept because tests/conftest.py relies on it: it's a known, deterministic dataset with known
correct pipeline outcomes (see the four scenarios below), which is what lets test_pipeline.py
assert the pipeline reaches the *right* answer, not just "doesn't crash." Treat it as pytest
fixture data, not application code.

Generates 365 days of segmented KPI observations (trend + weekly/yearly seasonality + noise)
and a matching corpus of unstructured text records, with four deliberately injected scenarios
in the most recent 10-day window so every branch of the pipeline is exercised:

  Scenario A (mirrors SRS Appendix A, UC-1) — Revenue drop in South/Product B, converging
    with a payment-failure-rate spike and a "payment failed" ticket theme -> validated cause.
  Scenario B (mirrors UC-2) — CSAT decline in East/Chat with two partially-supported,
    non-converging causes (product-bug theme vs. staffing theme, neither with a structured
    correlate) -> genuinely ambiguous, two ranked hypotheses.
  Scenario C (mirrors UC-3) — a small Ticket Volume blip for Product C that stays inside the
    sample-size-scaled confidence band -> suppressed as noise.
  Scenario D (extra) — duplicated Observation rows for Churn Rate/West on one day, simulating
    a sync error -> suppressed for a data-quality reason before any statistical test runs.

Note: an HR system / agent-headcount metric is deliberately never generated. Its absence is
what gives the Ambiguous Case Handler (FR-3.6) a real, nameable disambiguation gap in Scenario B,
rather than a scripted one.
"""
from __future__ import annotations

import datetime as dt
import math

import numpy as np
from sqlalchemy.orm import Session

from app.models import Metric, Observation, TextEvidence
from app.pipeline.pii_redaction import redact

SEED = 42
END_DATE = dt.date(2026, 8, 25)
NUM_DAYS = 365
START_DATE = END_DATE - dt.timedelta(days=NUM_DAYS - 1)
ANOMALY_WINDOW_DAYS = 10
WINDOW_START = END_DATE - dt.timedelta(days=ANOMALY_WINDOW_DAYS - 1)

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Product A", "Product B", "Product C"]
CHANNELS = ["Phone", "Chat", "Email"]

rng = np.random.default_rng(SEED)


def _date_range() -> list[dt.date]:
    return [START_DATE + dt.timedelta(days=i) for i in range(NUM_DAYS)]


def _series(
    baseline: float,
    trend_per_day: float,
    weekly_amp: float,
    yearly_amp: float,
    noise_std: float,
    weekday_phase: float = 0.0,
) -> np.ndarray:
    days = _date_range()
    idx = np.arange(NUM_DAYS)
    weekday = np.array([d.weekday() for d in days])
    day_of_year = np.array([d.timetuple().tm_yday for d in days])

    trend = trend_per_day * idx
    weekly = weekly_amp * np.sin(2 * math.pi * (weekday + weekday_phase) / 7)
    yearly = yearly_amp * np.sin(2 * math.pi * day_of_year / 365)
    noise = rng.normal(0, noise_std, size=NUM_DAYS)
    return baseline + trend + weekly + yearly + noise


def _entity_key(**dims: str) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(dims.items()))


def _apply_window_shift(values: np.ndarray, pct_shift: float) -> np.ndarray:
    """Applies a % shift to the values inside the anomaly window only."""
    days = _date_range()
    out = values.copy()
    for i, d in enumerate(days):
        if WINDOW_START <= d <= END_DATE:
            out[i] = out[i] * (1 + pct_shift)
    return out


# --------------------------------------------------------------------------------------
# Text corpus
# --------------------------------------------------------------------------------------

_GENERIC_TEMPLATES = [
    "Customer asked about {product} pricing options, resolved on first contact.",
    "Requested an invoice copy for last month's {product} purchase.",
    "Asked how to update billing address on file.",
    "General usage question about {product} resolved quickly via {channel}.",
    "Positive feedback shared about the {channel} support experience.",
    "Requested to update contact email on file.",
    "Asked about upgrade options for {product}.",
    "Inquiry about subscription renewal date for {product}.",
    "Customer thanked the {channel} agent for a fast resolution.",
    "Requested a feature walkthrough for {product}.",
    # Raw agent notes occasionally carry PII straight from the call — these exist so the
    # Stage 1 redaction pass (pipeline/pii_redaction.py) has something real to catch.
    "Customer confirmed callback number 415-555-0182 for {product} follow-up.",
    "Sent the requested receipt to jane.doe@example.com per customer request.",
    "Verified last 4 of card ending in 4242 4242 4242 4242 before processing the {product} refund.",
]

_SCENARIO_A_TEMPLATES = [
    "Customer reports payment failed at checkout for {product} — transaction declined without reason.",
    "Unable to complete purchase, checkout page throws a payment error repeatedly.",
    "Card was charged but order still shows payment failed status, requesting refund.",
    "Multiple customers in the South region reporting checkout payment failures since this morning.",
    "Escalation: batch of failed payment transactions traced to a gateway timeout.",
    "Payment gateway returning errors intermittently during checkout for {product}.",
]

_SCENARIO_B_BUG_TEMPLATES = [
    "App crashes immediately after opening the {product} dashboard.",
    "Login broken — customer unable to authenticate via the {channel} widget.",
    "Reported repeated app crash when switching between account tabs.",
    "{channel} widget fails to load, customer had to retry login three times.",
    "Mobile app freezes and closes unexpectedly after the latest update.",
]

_SCENARIO_B_STAFFING_TEMPLATES = [
    "Customer waited over 40 minutes for a {channel} agent, extremely frustrated.",
    "Long hold times reported again — East region {channel} queue backed up.",
    "Agent availability low, customer disconnected after a long wait.",
    "Complaint about being unable to reach any agent during {channel} hours.",
    "{channel} queue wait time exceeded SLA, customer requested a callback.",
]


def _add_text(session: Session, templates: list[str], n: int, date_pool: list[dt.date], **dims: str) -> None:
    for _ in range(n):
        template = templates[rng.integers(0, len(templates))]
        text = template.format(product=dims.get("product", "Product"), channel=dims.get("channel", "Support"))
        date = date_pool[rng.integers(0, len(date_pool))]
        # Redact before the record is ever persisted — Stage 1 ingestion, not a display-time filter.
        session.add(TextEvidence(source_system="ticketing", segment_dims=dims, timestamp=date, text=redact(text)))


def generate(session: Session) -> None:
    """Populates Metric, Observation, and TextEvidence tables. Idempotent-ish: caller should
    ensure tables are empty first (the seed script drops/recreates the DB)."""

    days = _date_range()

    metrics = {
        "revenue": Metric(key="revenue", name="Revenue", department="Sales", unit="USD", aggregation="sum"),
        "payment_failure_rate": Metric(
            key="payment_failure_rate", name="Payment Failure Rate", department="Finance", unit="%", aggregation="mean"
        ),
        "csat": Metric(key="csat", name="Customer Satisfaction (CSAT)", department="Support", unit="score", aggregation="mean"),
        "ticket_volume": Metric(key="ticket_volume", name="Ticket Volume", department="Support", unit="count", aggregation="sum"),
        "churn_rate": Metric(key="churn_rate", name="Churn Rate", department="Customer Success", unit="%", aggregation="mean"),
    }
    for m in metrics.values():
        session.add(m)
    session.flush()

    # ---- Revenue: region x product --------------------------------------------------
    region_mult = {"North": 1.2, "South": 1.0, "East": 0.9, "West": 0.8}
    product_mult = {"Product A": 1.3, "Product B": 1.0, "Product C": 0.7}
    for region in REGIONS:
        for product in PRODUCTS:
            base = 8000 * region_mult[region] * product_mult[product]
            values = _series(baseline=base, trend_per_day=1.5, weekly_amp=base * 0.12, yearly_amp=base * 0.08, noise_std=base * 0.05)
            if region == "South" and product == "Product B":
                values = _apply_window_shift(values, pct_shift=-0.35)  # Scenario A
            entity = _entity_key(region=region, product=product)
            for d, v in zip(days, values):
                session.add(
                    Observation(
                        metric_id=metrics["revenue"].id,
                        entity=entity,
                        segment_dims={"region": region, "product": product},
                        source_system="crm",
                        timestamp=d,
                        value=max(0.0, float(v)),
                    )
                )

    # ---- Payment failure rate: region x product (driver metric for Scenario A) ------
    for region in REGIONS:
        for product in PRODUCTS:
            base = 1.8
            values = _series(baseline=base, trend_per_day=0.0, weekly_amp=0.3, yearly_amp=0.2, noise_std=0.35)
            if region == "South" and product == "Product B":
                values = _apply_window_shift(values, pct_shift=1.6)  # sharp spike, same window as Scenario A
            entity = _entity_key(region=region, product=product)
            for d, v in zip(days, values):
                session.add(
                    Observation(
                        metric_id=metrics["payment_failure_rate"].id,
                        entity=entity,
                        segment_dims={"region": region, "product": product},
                        source_system="finance",
                        timestamp=d,
                        value=max(0.0, min(100.0, float(v))),
                    )
                )

    # ---- CSAT: region x channel -------------------------------------------------------
    for region in REGIONS:
        for channel in CHANNELS:
            base = 82.0
            values = _series(baseline=base, trend_per_day=0.0, weekly_amp=2.0, yearly_amp=1.5, noise_std=2.2)
            if region == "East" and channel == "Chat":
                values = _apply_window_shift(values, pct_shift=-0.15)  # Scenario B
            entity = _entity_key(region=region, channel=channel)
            for d, v in zip(days, values):
                session.add(
                    Observation(
                        metric_id=metrics["csat"].id,
                        entity=entity,
                        segment_dims={"region": region, "channel": channel},
                        source_system="ticketing",
                        timestamp=d,
                        value=max(0.0, min(100.0, float(v))),
                    )
                )

    # ---- Ticket volume: product only (Scenario C — noise, stays within CI) -----------
    for product in PRODUCTS:
        base = 140 * product_mult[product]
        # Product C runs a naturally noisier queue, so a modest recent bump reads as normal variation.
        noise_std = base * (0.34 if product == "Product C" else 0.08)
        values = _series(baseline=base, trend_per_day=0.05, weekly_amp=base * 0.18, yearly_amp=base * 0.05, noise_std=noise_std)
        # No shift is injected for Product C: its naturally wider noise band already produces
        # a window that *looks* like a ~10% uptick but stays inside the confidence interval —
        # exactly the "normal variation" case Stage 2 is supposed to suppress (SRS Appendix A, UC-3).
        entity = _entity_key(product=product)
        for d, v in zip(days, values):
            session.add(
                Observation(
                    metric_id=metrics["ticket_volume"].id,
                    entity=entity,
                    segment_dims={"product": product},
                    source_system="ticketing",
                    timestamp=d,
                    value=max(0.0, round(float(v))),
                )
            )

    # ---- Churn rate: region only (Scenario D — duplicate rows, DQ-suppressed) --------
    for region in REGIONS:
        base = 2.4
        values = _series(baseline=base, trend_per_day=0.0, weekly_amp=0.1, yearly_amp=0.3, noise_std=0.25)
        entity = _entity_key(region=region)
        for d, v in zip(days, values):
            session.add(
                Observation(
                    metric_id=metrics["churn_rate"].id,
                    entity=entity,
                    segment_dims={"region": region},
                    source_system="hr",
                    timestamp=d,
                    value=max(0.0, float(v)),
                )
            )
            if region == "West" and d == END_DATE - dt.timedelta(days=3):
                # Sync error: the same day's reading gets double-counted, distorting the
                # aggregate for that date. The DQ check (not the significance test) must catch this.
                session.add(
                    Observation(
                        metric_id=metrics["churn_rate"].id,
                        entity=entity,
                        segment_dims={"region": region},
                        source_system="hr",
                        timestamp=d,
                        value=max(0.0, float(v)),
                        is_duplicate=True,
                    )
                )

    session.flush()

    # ---- Unstructured text corpus ------------------------------------------------------
    all_dates = days
    window_dates = [d for d in days if WINDOW_START <= d <= END_DATE]

    # Generic background noise across every segment and the full year, so theme mining has
    # a realistic corpus to filter down from rather than a hand-picked signal.
    for region in REGIONS:
        for product in PRODUCTS:
            _add_text(session, _GENERIC_TEMPLATES, n=6, date_pool=all_dates, region=region, product=product)
    for region in REGIONS:
        for channel in CHANNELS:
            _add_text(session, _GENERIC_TEMPLATES, n=6, date_pool=all_dates, region=region, channel=channel)

    # Scenario A — payment-failure theme, concentrated in South/Product B during the window.
    _add_text(session, _SCENARIO_A_TEMPLATES, n=14, date_pool=window_dates, region="South", product="Product B")

    # Scenario B — two competing themes in East/Chat during the window, neither dominant.
    _add_text(session, _SCENARIO_B_BUG_TEMPLATES, n=9, date_pool=window_dates, region="East", channel="Chat")
    _add_text(session, _SCENARIO_B_STAFFING_TEMPLATES, n=8, date_pool=window_dates, region="East", channel="Chat")

    session.commit()
