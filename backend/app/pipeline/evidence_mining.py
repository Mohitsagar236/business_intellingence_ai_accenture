"""
Stage 3b — Parallel Evidence Mining (SRS FR-3.2/FR-3.3, Design Doc §3.3).

Structured correlator: searches every other metric for a co-moving signal in the same
segment, with a small lag search so the timing offset ("did it move before or after?")
is captured, not just the correlation strength.

Unstructured theme miner: scoped to the same segment and a window around the anomaly,
clusters text into themes via TF-IDF + NMF and reports each theme with its keywords and
citable excerpts. (Design Doc names sentence-transformers/BERTopic; substituted here with
TF-IDF+NMF — see the assumptions log in README — no model download required, same job:
group co-occurring language into named themes with evidence excerpts.)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Metric, TextEvidence
from app.pipeline.series_utils import aggregate_daily, decompose, filter_by_dims, load_observations_df

settings = get_settings()

TEXT_WINDOW_BUFFER_DAYS = 7  # how far outside the anomaly window unstructured evidence is still considered "in-window"


@dataclass
class StructuredCandidate:
    metric_key: str
    metric_name: str
    correlation: float
    lag_days: int
    description: str


@dataclass
class ThemeCandidate:
    label: str
    keywords: list[str]
    doc_count: int
    spike_ratio: float
    excerpt_ids: list[int]
    excerpts: list[str] = field(default_factory=list)
    source_system: str = "ticketing"  # dominant TextEvidence.source_system among this theme's own records


def _metric_dimension_keys(db: Session, metric: Metric) -> set[str]:
    raw = load_observations_df(db, metric.id)
    if raw.empty:
        return set()
    return {k for dims in raw["segment_dims"] for k in dims.keys()}


def benjamini_hochberg_reject(p_values: list[float], alpha: float) -> list[bool]:
    """Benjamini-Hochberg step-up FDR procedure — returns a same-length mask of which
    hypotheses are declared significant at the given `alpha`.

    Sort p-values ascending; find the largest rank k where p_(k) <= (k/m)*alpha; declare every
    hypothesis at rank <= k significant. Chosen over a Bonferroni correction because this
    search is *exploratory candidate discovery* (every other metric x every lag, tens of tests
    per anomaly) rather than a fixed set of pre-registered hypotheses where any single false
    positive would be costly — FDR controls the expected proportion of false discoveries among
    what's reported, which stays usable as the number of candidate metrics grows, whereas
    Bonferroni's family-wise correction (alpha/m) becomes so conservative with this few data
    points per window that it would suppress real signals along with spurious ones.
    """
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    threshold_rank = 0
    for rank, idx in enumerate(order, start=1):
        if p_values[idx] <= (rank / m) * alpha:
            threshold_rank = rank
    reject = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= threshold_rank:
            reject[idx] = True
    return reject


def find_structured_correlate(
    db: Session,
    target_metric: Metric,
    target_series: pd.DataFrame,  # decomposed series for the target, already segment-filtered
    segment_dims: dict[str, str],
    window_start: dt.date,
    window_end: dt.date,
    all_metrics: list[Metric],
) -> StructuredCandidate | None:
    """Searches every other metric x every lag for a co-moving signal — a real multiple-
    comparison problem (see benjamini_hochberg_reject above). Every (metric, lag) pair tested
    gets a real p-value (scipy.stats.pearsonr, not just a raw |r| cutoff); only pairs that
    clear BOTH the existing correlation-magnitude bar AND FDR-corrected significance are
    eligible, and the strongest (by |r|) eligible pair is returned — lowering the raw
    correlation_threshold would not address the underlying problem (a spurious correlation
    from testing many candidates), so that threshold is kept as-is and the correction is
    layered on top of it.
    """
    comparison_start = window_start - dt.timedelta(days=14)
    comparison_end = window_end + dt.timedelta(days=settings.max_lag_days)

    target_window = target_series[(target_series["date"] >= comparison_start) & (target_series["date"] <= comparison_end)]
    target_resid = target_window.set_index("date")["resid"]

    tested: list[tuple[Metric, float, float, int, str]] = []  # (metric, r, p_value, lag, scope)

    for candidate_metric in all_metrics:
        if candidate_metric.id == target_metric.id:
            continue

        candidate_dim_keys = _metric_dimension_keys(db, candidate_metric)
        overlap = {k: v for k, v in segment_dims.items() if k in candidate_dim_keys}

        raw = load_observations_df(db, candidate_metric.id)
        if raw.empty:
            continue
        filtered = filter_by_dims(raw, overlap if overlap else None)
        if filtered.empty:
            # The candidate metric exists but has no data at all for this specific segment
            # (e.g. it tracks a different set of dimension values than the target) — distinct
            # from raw.empty above, and aggregate_daily's asfreq("D") raises on an empty frame
            # rather than returning one, so this must be checked before calling it.
            continue
        daily = aggregate_daily(filtered, candidate_metric.aggregation)
        if daily["value"].dropna().shape[0] < 2 * candidate_metric.seasonality_period:
            continue
        decomposed = decompose(daily, candidate_metric.seasonality_period)

        cand_window = decomposed[(decomposed["date"] >= comparison_start - dt.timedelta(days=settings.max_lag_days))
                                  & (decomposed["date"] <= comparison_end)]
        cand_resid = cand_window.set_index("date")["resid"]

        for lag in range(-settings.max_lag_days, settings.max_lag_days + 1):
            shifted_index = [d - dt.timedelta(days=lag) for d in target_resid.index]
            aligned_cand = cand_resid.reindex(shifted_index)
            pair = pd.DataFrame({"target": target_resid.values, "candidate": aligned_cand.values}).dropna()
            if len(pair) < 8:
                continue
            r, p_value = pearsonr(pair["target"], pair["candidate"])
            if np.isnan(r) or np.isnan(p_value):
                continue
            scope = ", ".join(f"{k}={v}" for k, v in overlap.items()) if overlap else "overall"
            tested.append((candidate_metric, float(r), float(p_value), lag, scope))

    if not tested:
        return None

    significant = benjamini_hochberg_reject([t[2] for t in tested], settings.fdr_alpha)
    eligible = [t for t, sig in zip(tested, significant) if sig and abs(t[1]) >= settings.correlation_threshold]
    if not eligible:
        return None

    candidate_metric, r, p_value, lag, scope = max(eligible, key=lambda t: abs(t[1]))
    timing = "leading" if lag > 0 else ("lagging" if lag < 0 else "simultaneous")
    return StructuredCandidate(
        metric_key=candidate_metric.key,
        metric_name=candidate_metric.name,
        correlation=r,
        lag_days=lag,
        description=(
            f"{candidate_metric.name} ({scope}) moved with r={r:.2f}, "
            f"{abs(lag)}d {timing} relative to the anomaly window (FDR-corrected p={p_value:.4f})."
        ),
    )


def mine_themes(
    db: Session,
    segment_dims: dict[str, str],
    window_start: dt.date,
    window_end: dt.date,
    max_themes: int = 2,
) -> list[ThemeCandidate]:
    all_text = db.query(TextEvidence).all()
    if not segment_dims:
        scoped = all_text
    else:
        scoped = [t for t in all_text if all(t.segment_dims.get(k) == v for k, v in segment_dims.items())]
    if not scoped:
        return []

    buffered_start = window_start - dt.timedelta(days=TEXT_WINDOW_BUFFER_DAYS)
    buffered_end = window_end + dt.timedelta(days=TEXT_WINDOW_BUFFER_DAYS)

    in_window = [t for t in scoped if window_start <= t.timestamp <= window_end]
    baseline = [t for t in scoped if not (buffered_start <= t.timestamp <= buffered_end)]

    window_days = max((window_end - window_start).days + 1, 1)
    if baseline:
        baseline_span = (max(t.timestamp for t in baseline) - min(t.timestamp for t in baseline)).days
        baseline_days = max(baseline_span, 1)
    else:
        baseline_days = 1
    baseline_rate = len(baseline) / baseline_days if baseline_days else 0.0
    window_rate = len(in_window) / window_days
    overall_spike_ratio = window_rate / baseline_rate if baseline_rate > 1e-6 else (float("inf") if window_rate > 0 else 0.0)

    min_docs = 5
    if len(in_window) < min_docs or overall_spike_ratio < settings.theme_spike_ratio_threshold:
        return []

    texts = [t.text for t in in_window]
    n_components = min(max_themes, max(1, len(texts) // 4))

    vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=200)
    tfidf = vectorizer.fit_transform(texts)
    if tfidf.shape[1] == 0:
        return []
    n_components = min(n_components, tfidf.shape[1], tfidf.shape[0])
    if n_components < 1:
        return []

    nmf = NMF(n_components=n_components, init="nndsvda", random_state=42, max_iter=400)
    doc_topic = nmf.fit_transform(tfidf)
    feature_names = np.array(vectorizer.get_feature_names_out())

    themes: list[ThemeCandidate] = []
    dominant_topic = doc_topic.argmax(axis=1)
    for topic_idx in range(n_components):
        member_positions = np.where(dominant_topic == topic_idx)[0]
        if len(member_positions) == 0:
            continue
        top_term_idx = nmf.components_[topic_idx].argsort()[::-1][:6]
        keywords = [feature_names[i] for i in top_term_idx if feature_names[i]]
        # representative excerpts: highest topic-weight docs within this theme
        weights = doc_topic[member_positions, topic_idx]
        order = member_positions[np.argsort(weights)[::-1]]
        top_docs = order[:3]
        excerpt_records = [in_window[i] for i in top_docs]
        theme_share = len(member_positions) / len(in_window)
        # Dominant source_system among this theme's own records — e.g. "demo_synthetic_support"
        # for demo-generated text vs. "ticketing" for a real upload, so the evidence panel shows
        # honest provenance instead of a hardcoded literal.
        member_sources = [in_window[i].source_system for i in member_positions]
        dominant_source = max(set(member_sources), key=member_sources.count)
        themes.append(
            ThemeCandidate(
                label=", ".join(keywords[:3]),
                keywords=keywords,
                doc_count=int(len(member_positions)),
                spike_ratio=round(overall_spike_ratio * theme_share * n_components, 2) if overall_spike_ratio != float("inf") else 999.0,
                excerpt_ids=[r.id for r in excerpt_records],
                excerpts=[r.text for r in excerpt_records],
                source_system=dominant_source,
            )
        )

    themes.sort(key=lambda t: t.doc_count, reverse=True)
    return themes
