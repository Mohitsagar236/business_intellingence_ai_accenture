"""
P1-3 — tests for the four root-cause correctness/trust improvements:

1. convergence.py no longer only checks themes[0] (app/pipeline/convergence.py::_find_aligned_theme)
2. CAUSE_STRUCTURED_DRIVERS gained a defensible product_regression -> ticket_volume mapping
3. segmentation.py requires direction agreement + a real significance bar before naming a
   segment "primary" (app/pipeline/segmentation.py::_contributes_to_anomaly)
4. evidence_mining.py's structured-correlation search is FDR-corrected
   (app/pipeline/evidence_mining.py::benjamini_hochberg_reject)

Every test here is a deterministic unit/integration test against these specific functions —
no dependency on the synthetic 365-day fixture's random draws, so these stay stable regardless
of anything that fixture's own random-noise parameters ever do.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from app.pipeline.convergence import CAUSE_STRUCTURED_DRIVERS, _find_aligned_theme, run_convergence
from app.pipeline.evidence_mining import StructuredCandidate, ThemeCandidate, benjamini_hochberg_reject
from app.pipeline.segmentation import SegmentResult, _contributes_to_anomaly, primary_segment_dims, run_segmentation

# --- shared fixtures for the theme/taxonomy tests -----------------------------------------

BILLING_KEYWORDS = ["payment", "checkout", "declined", "gateway"]
PRODUCT_KEYWORDS = ["crash", "login", "broken"]
STAFFING_KEYWORDS = ["wait", "queue", "hold"]
UNRELATED_KEYWORDS = ["invoice", "renewal", "upgrade"]  # matches no category -> "unclassified_theme"


def _structured(metric_key: str = "payment_failure_rate", r: float = -0.6, lag: int = 0) -> StructuredCandidate:
    return StructuredCandidate(metric_key=metric_key, metric_name=metric_key, correlation=r, lag_days=lag, description=f"{metric_key} moved")


def _theme(keywords: list[str], doc_count: int = 10, spike_ratio: float = 2.0) -> ThemeCandidate:
    return ThemeCandidate(label=", ".join(keywords[:2]), keywords=keywords, doc_count=doc_count, spike_ratio=spike_ratio, excerpt_ids=[1, 2])


# ============================================================================================
# 1. themes[0] limitation
# ============================================================================================


def test_convergence_detected_when_relevant_theme_is_ranked_first():
    structured = _structured()
    themes = [_theme(BILLING_KEYWORDS), _theme(UNRELATED_KEYWORDS), _theme(STAFFING_KEYWORDS)]
    result = run_convergence(structured, themes)
    assert result[0].status == "validated"
    assert result[0].cause_category == "billing_system_outage"


def test_convergence_detected_when_relevant_theme_is_ranked_second():
    structured = _structured()
    themes = [_theme(UNRELATED_KEYWORDS), _theme(BILLING_KEYWORDS), _theme(STAFFING_KEYWORDS)]
    result = run_convergence(structured, themes)
    assert result[0].status == "validated"
    assert result[0].cause_category == "billing_system_outage"


def test_convergence_detected_when_relevant_theme_is_ranked_third():
    structured = _structured()
    themes = [_theme(UNRELATED_KEYWORDS), _theme(STAFFING_KEYWORDS), _theme(BILLING_KEYWORDS)]
    result = run_convergence(structured, themes)
    assert result[0].status == "validated"
    assert result[0].cause_category == "billing_system_outage"


def test_irrelevant_themes_before_the_relevant_one_do_not_block_convergence():
    structured = _structured(metric_key="ticket_volume")
    themes = [_theme(UNRELATED_KEYWORDS), _theme(STAFFING_KEYWORDS), _theme(BILLING_KEYWORDS), _theme(PRODUCT_KEYWORDS)]
    result = run_convergence(structured, themes)
    assert result[0].status == "validated"
    assert result[0].cause_category == "product_regression"


def test_no_validation_when_no_theme_matches_the_structured_drivers_category():
    structured = _structured()  # payment_failure_rate -> only corroborates billing_system_outage
    themes = [_theme(STAFFING_KEYWORDS), _theme(PRODUCT_KEYWORDS), _theme(UNRELATED_KEYWORDS)]
    result = run_convergence(structured, themes)
    assert all(h.status == "candidate" for h in result)
    assert not any(h.status == "validated" for h in result)


def test_find_aligned_theme_prefers_stronger_spike_when_multiple_align():
    # Contrived: two themes both classify into billing_system_outage; the one with the
    # stronger spike_ratio should be the one convergence reports on, not just the first found.
    structured = _structured()
    weak = _theme(BILLING_KEYWORDS, spike_ratio=1.8)
    strong = _theme(["checkout", "declined"], spike_ratio=4.5)
    category, theme = _find_aligned_theme(structured, [weak, strong])
    assert category == "billing_system_outage"
    assert theme is strong


# ============================================================================================
# 2. Expanded causal-driver taxonomy
# ============================================================================================


def test_taxonomy_has_defensible_mappings_only():
    # billing_system_outage and product_regression are backed by real, ingested metrics.
    assert CAUSE_STRUCTURED_DRIVERS["billing_system_outage"] == {"payment_failure_rate"}
    # ticket_volume is the pytest fixture's own metric; demo_support_tickets is the judge-demo
    # dataset's equivalent (app/data/demo_scenarios.py) — same real-world concept, two datasets.
    assert CAUSE_STRUCTURED_DRIVERS["product_regression"] == {"ticket_volume", "demo_support_tickets"}
    # staffing_shortfall intentionally has no structured driver — no headcount metric exists,
    # and inventing one would fabricate convergence instead of leaving an honest gap.
    assert CAUSE_STRUCTURED_DRIVERS.get("staffing_shortfall", set()) == set()


def test_approved_driver_with_matching_category_is_allowed_as_evidence():
    structured = _structured(metric_key="ticket_volume", r=0.7)
    themes = [_theme(PRODUCT_KEYWORDS, spike_ratio=3.0)]
    result = run_convergence(structured, themes)
    assert result[0].status == "validated"
    assert result[0].cause_category == "product_regression"
    assert result[0].structured is structured


def test_unapproved_driver_is_rejected_even_with_a_matching_theme_category():
    # churn_rate is not an approved driver for ANY category — a strong raw correlation must
    # not be laundered into validated evidence just because a theme happens to classify.
    structured = _structured(metric_key="churn_rate", r=0.95)
    themes = [_theme(BILLING_KEYWORDS, spike_ratio=5.0)]
    result = run_convergence(structured, themes)
    assert not any(h.status == "validated" for h in result)
    # The unapproved correlation still surfaces, but honestly labeled as unconfirmed.
    assert any(h.cause_category.startswith("correlated_signal_") for h in result)


# ============================================================================================
# 3. Segmentation direction + significance
# ============================================================================================


@pytest.mark.parametrize(
    "signed_z,sample_size,anomaly_magnitude_pct,expected,case",
    [
        (-3.0, 10, -10.0, True, "negative KPI + negative segment -> valid contributor"),
        (3.0, 10, -10.0, False, "negative KPI + positive segment -> not a negative driver"),
        (3.0, 10, 10.0, True, "positive KPI + positive segment -> valid contributor"),
        (-3.0, 10, 10.0, False, "positive KPI + negative segment -> not a positive driver"),
        (-1.0, 10, -10.0, False, "below the significance threshold -> no significant segment"),
        (-5.0, 3, -10.0, False, "sample size below min_window_sample_size -> not primary"),
    ],
)
def test_contributes_to_anomaly_direction_and_significance(signed_z, sample_size, anomaly_magnitude_pct, expected, case):
    assert _contributes_to_anomaly(signed_z, sample_size, anomaly_magnitude_pct) is expected, case


def _seed_flat_series(db_session, metric, region: str, days: list[dt.date], base: float, noise_std: float, window_shift_pct: float, window_start: dt.date, seed: int):
    from app.models import Observation

    # NEVER derive the seed from Python's built-in hash() of a string — it's randomized per
    # process by default (PYTHONHASHSEED), which silently made this fixture non-deterministic
    # across runs. Every call site below passes an explicit integer instead.
    rng = np.random.default_rng(seed)
    for d in days:
        value = base + rng.normal(0, noise_std)
        if d >= window_start:
            value *= 1 + window_shift_pct
        db_session.add(
            Observation(
                metric_id=metric.id,
                entity=f"region={region}",
                segment_dims={"region": region},
                source_system="test",
                timestamp=d,
                value=max(0.0, float(value)),
            )
        )


@pytest.fixture
def seg_test_metric(db_session):
    from app.models import Metric, Observation

    metric = Metric(key="seg_test_metric", name="Segmentation Test Metric", department="Ops", unit="USD", aggregation="sum", dimensions=["region"], seasonality_period=7)
    db_session.add(metric)
    db_session.commit()
    db_session.refresh(metric)
    yield metric
    db_session.query(Observation).filter(Observation.metric_id == metric.id).delete()
    db_session.delete(metric)
    db_session.commit()


def test_two_strong_segments_both_marked_as_contributors(db_session, seg_test_metric):
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(35)]
    window_start = days[-7]
    # Regions A and B both drop sharply in the window; region C stays flat. Seeds 2/4/14 are
    # pinned deliberately — window_stats_forecast's z-test is noisy with only 4 history cycles
    # behind it (28 days at period=7), so an arbitrary seed can spuriously cross the
    # significance bar on pure noise alone; these three were verified to keep C's *unshifted*
    # window comfortably below threshold (|z| < 0.3) while A/B's -50% shift is unambiguous
    # regardless of seed (|z| in the hundreds).
    _seed_flat_series(db_session, seg_test_metric, "A", days, base=1000.0, noise_std=8.0, window_shift_pct=-0.5, window_start=window_start, seed=2)
    _seed_flat_series(db_session, seg_test_metric, "B", days, base=1000.0, noise_std=8.0, window_shift_pct=-0.5, window_start=window_start, seed=4)
    _seed_flat_series(db_session, seg_test_metric, "C", days, base=1000.0, noise_std=8.0, window_shift_pct=0.0, window_start=window_start, seed=14)
    db_session.commit()

    results = run_segmentation(db_session, seg_test_metric, window_start, days[-1], anomaly_magnitude_pct=-30.0)
    primary = {r.value for r in results if r.is_primary}
    assert primary == {"A", "B"}, f"expected both A and B as contributors, got {primary}"


def test_no_segment_contributes_when_none_show_a_significant_deviation(db_session, seg_test_metric):
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(35)]
    window_start = days[-7]
    # Neither region deviates in the window — a caller passing a nonzero parent magnitude here
    # (as if the aggregate showed something diffuse) must still get NO forced primary segment.
    # Seeds 2/14 verified flat (see the seed comment above).
    _seed_flat_series(db_session, seg_test_metric, "A", days, base=1000.0, noise_std=8.0, window_shift_pct=0.0, window_start=window_start, seed=2)
    _seed_flat_series(db_session, seg_test_metric, "B", days, base=1000.0, noise_std=8.0, window_shift_pct=0.0, window_start=window_start, seed=14)
    db_session.commit()

    results = run_segmentation(db_session, seg_test_metric, window_start, days[-1], anomaly_magnitude_pct=-8.0)
    assert not any(r.is_primary for r in results), "no segment should be forced primary without real evidence"


def test_primary_segment_dims_picks_the_strongest_when_two_qualify_in_one_dimension():
    # Found via app/data/demo_scenarios.py's ambiguous scenario: when a second segment in the
    # SAME dimension also clears the significance bar (e.g. both Furniture and Technology
    # qualify as primary categories), primary_segment_dims() must deterministically keep the
    # stronger one for scoping evidence mining — a plain {s.dimension: s.value for ...} dict
    # comprehension instead kept whichever was iterated last, which silently scoped the entire
    # evidence search to the WRONG category (the weaker, uninjected one) in that real scenario.
    segments = [
        SegmentResult(dimension="region", value="West", contribution_score=9.2, magnitude_pct=-10, sample_size=10, signed_z=-9.2, is_primary=True),
        SegmentResult(dimension="category", value="Furniture", contribution_score=7.99, magnitude_pct=-10, sample_size=10, signed_z=-7.99, is_primary=True),
        SegmentResult(dimension="category", value="Technology", contribution_score=2.57, magnitude_pct=-10, sample_size=10, signed_z=-2.57, is_primary=True),
    ]
    assert primary_segment_dims(segments) == {"region": "West", "category": "Furniture"}


# ============================================================================================
# 4. Multiple-comparison correction (Benjamini-Hochberg)
# ============================================================================================


def test_benjamini_hochberg_rejects_a_lone_borderline_pvalue_among_many_tests():
    # One p-value that clears the naive alpha=0.05 bar on its own, surrounded by many
    # uninformative (near-uniform) p-values — exactly the "many metrics x lags" scenario.
    p_values = [0.04] + list(np.linspace(0.10, 0.95, 29))
    reject = benjamini_hochberg_reject(p_values, alpha=0.05)
    assert reject[0] is False, "a single p=0.04 among 30 tests must not survive FDR correction uncorrected"
    assert not any(reject[1:])


def test_benjamini_hochberg_accepts_a_genuinely_strong_signal():
    # A very strong signal (p=0.0001) among the same size family of noise p-values should
    # still survive correction — the method must not reject everything indiscriminately.
    p_values = [0.0001] + list(np.linspace(0.10, 0.95, 29))
    reject = benjamini_hochberg_reject(p_values, alpha=0.05)
    assert reject[0] is True
    assert not any(reject[1:])


def test_benjamini_hochberg_step_up_procedure_on_a_worked_example():
    # 8 sorted p-values, alpha=0.05 -> BH critical value at rank i is (i/8)*0.05:
    # rank 1: 0.001 <= 0.00625 (pass) | rank 2: 0.008 <= 0.0125 (pass)
    # rank 3: 0.039 <= 0.01875 (fail) | ranks 4-8 all fail their (higher) critical values too.
    # The step-up procedure takes the LARGEST passing rank (here, 2), rejecting ranks 1-2 only.
    p_values = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    reject = benjamini_hochberg_reject(p_values, alpha=0.05)
    assert reject == [True, True, False, False, False, False, False, False]


def test_find_structured_correlate_rejects_spurious_correlation_after_correction(db_session):
    """Builds many candidate metrics whose noise happens to correlate weakly-to-moderately
    with the target purely by chance, plus one metric with a real, strong, designed signal —
    verifies the spurious ones don't get reported as evidence even if any single one alone
    would have cleared the old raw-|r| >= correlation_threshold bar, while the real one does."""
    from app.models import Metric, Observation
    from app.pipeline.evidence_mining import find_structured_correlate
    from app.pipeline.series_utils import aggregate_daily, decompose, load_observations_df

    target = Metric(key="fdr_target", name="FDR Target", department="Ops", unit="USD", aggregation="sum", dimensions=[], seasonality_period=7)
    db_session.add(target)
    db_session.flush()

    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(40)]
    window_start, window_end = days[-10], days[-1]
    rng = np.random.default_rng(7)

    target_values = 1000.0 + rng.normal(0, 15, len(days))
    for d, v in zip(days, target_values):
        db_session.add(Observation(metric_id=target.id, entity="e", segment_dims={}, source_system="test", timestamp=d, value=float(v)))
    db_session.commit()

    # Compute the target's own *actual* residual (the same series find_structured_correlate
    # itself would use) so the "real driver" below tracks something genuinely present in the
    # target's data across the whole comparison span — not an approximation confined to the
    # 10-day anomaly window, which would get diluted by the ~17 independent-noise days also
    # inside the comparison range (window_start-14 .. window_end+max_lag_days) and might not
    # actually produce a strong correlation over that fuller span.
    raw = load_observations_df(db_session, target.id)
    daily = aggregate_daily(raw, "sum")
    target_series = decompose(daily, 7)
    target_resid_by_date = dict(zip(target_series["date"], target_series["resid"]))

    all_metrics = [target]
    # 15 unrelated candidate metrics — random noise, no real relationship to the target at all.
    for i in range(15):
        cand = Metric(key=f"noise_metric_{i}", name=f"Noise {i}", department="Ops", unit="USD", aggregation="sum", dimensions=[], seasonality_period=7)
        db_session.add(cand)
        db_session.flush()
        cand_rng = np.random.default_rng(100 + i)
        cand_values = 500.0 + cand_rng.normal(0, 20, len(days))
        for d, v in zip(days, cand_values):
            db_session.add(Observation(metric_id=cand.id, entity="e", segment_dims={}, source_system="test", timestamp=d, value=float(v)))
        all_metrics.append(cand)

    # One real driver: its value is a small amount of its own noise plus a scaled copy of the
    # target's actual residual at every date across the full series — a genuinely strong,
    # designed correlation, not confined to (and diluted around) just the anomaly window.
    real_driver = Metric(key="real_driver", name="Real Driver", department="Ops", unit="USD", aggregation="sum", dimensions=[], seasonality_period=7)
    db_session.add(real_driver)
    db_session.flush()
    driver_rng = np.random.default_rng(999)
    for d in days:
        v = 500.0 + driver_rng.normal(0, 3) + 2.0 * target_resid_by_date[d]
        db_session.add(Observation(metric_id=real_driver.id, entity="e", segment_dims={}, source_system="test", timestamp=d, value=float(v)))
    all_metrics.append(real_driver)

    db_session.commit()

    result = find_structured_correlate(db_session, target, target_series, {}, window_start, window_end, all_metrics)

    try:
        assert result is not None, "the genuinely strong, designed correlation must still be detected"
        assert result.metric_key == "real_driver"
    finally:
        for m in all_metrics:
            db_session.query(Observation).filter(Observation.metric_id == m.id).delete()
            db_session.delete(m)
        db_session.commit()
