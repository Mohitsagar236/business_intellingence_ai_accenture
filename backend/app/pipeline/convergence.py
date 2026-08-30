"""
Stage 3c — Convergence Check (SRS FR-3.4/FR-3.5/FR-3.6, Design Doc §3.3).

A cause is only VALIDATED when a structured co-moving metric and an unstructured theme
spike agree — both scoped to the same segment and window, computed independently in
Stage 3b. If only one modality has signal, or several themes compete without a structured
anchor, the case is genuinely AMBIGUOUS: every surviving hypothesis is kept, ranked, and
given the specific evidence gap that would resolve it — never a single fabricated cause.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.pipeline.evidence_mining import StructuredCandidate, ThemeCandidate

CAUSE_DISPLAY = {
    "billing_system_outage": "Billing / payment-gateway outage",
    "product_regression": "Recent product regression (crash / login bug)",
    "staffing_shortfall": "Support queue staffing shortfall",
    "data_quality_issue": "Data-quality issue in a source system",
    "demand_variation": "Normal demand variation",
}

# keyword -> cause_category, checked against each theme's keyword list
_TAXONOMY: list[tuple[list[str], str]] = [
    (["payment", "checkout", "transaction", "gateway", "declined", "charged", "refund"], "billing_system_outage"),
    (["crash", "crashes", "login", "broken", "freeze", "freezes", "bug"], "product_regression"),
    (["wait", "waited", "hold", "queue", "agent", "callback", "availability", "sla"], "staffing_shortfall"),
]

# Which structured metrics plausibly corroborate which cause category. A correlation that
# clears the statistical bar but isn't semantically relevant to the theme's cause (e.g. Churn
# Rate happening to co-move with a CSAT dip caused by a staffing issue) is NOT convergence —
# correlation strength alone can't distinguish a real driver from a coincidence with this little
# data (see README assumptions log).
#
# Only mapped where the relationship is actually defensible given the metrics this project
# ingests (backend/app/data/synthetic.py) — not a generic textbook taxonomy:
#   - billing_system_outage -> payment_failure_rate: a payment-gateway outage mechanically
#     shows up as a spike in the payment failure rate. Direct, load-bearing driver.
#   - product_regression -> ticket_volume: a crash/login-bug regression drives more customers
#     to file support tickets — a real, already-ingested count metric, domain-plausible as a
#     corroborating (not just coincidental) signal for this cause category.
#   - staffing_shortfall has NO entry, deliberately: the only metric that would actually
#     confirm a staffing gap is agent headcount/schedule-adherence, which this dataset does not
#     ingest (see the module docstring and synthetic.py's own note). Adding some other metric
#     here as a stand-in would be exactly the kind of invented relationship this taxonomy is
#     supposed to guard against, and would quietly turn the CSAT scenario's genuine ambiguity
#     into a fabricated "validated" result — worse than leaving the gap honest.
#   - data_quality_issue and demand_variation aren't reachable through _TAXONOMY's keyword
#     classification at all (no theme is ever classified into either), so a structured-driver
#     mapping for them wouldn't do anything — data_quality_issue is decided entirely upstream
#     by the Stage 2 duplicate/DQ check, and demand_variation is a "no cause needed" label, not
#     an outcome this convergence step ever classifies a theme into.
#
# "demo_support_tickets" is the judge-demo dataset's own ticket-volume-equivalent metric (see
# app/data/demo_scenarios.py) — same real-world concept as "ticket_volume" (support tickets
# corroborating a product regression), just a differently-keyed metric because it lives in a
# separate dataset (real Kaggle Superstore revenue + a synthetic companion metric) from the
# pytest fixture's own synthetic "ticket_volume". Both are approved, neither replaces the other.
CAUSE_STRUCTURED_DRIVERS: dict[str, set[str]] = {
    "billing_system_outage": {"payment_failure_rate"},
    "product_regression": {"ticket_volume", "demo_support_tickets"},
}

DISAMBIGUATION_MESSAGES = {
    "billing_system_outage": "Connecting payment-gateway incident logs for this window would confirm or rule out an outage.",
    "product_regression": "Connecting deployment and error-log telemetry for this segment would confirm or rule out a recent regression.",
    "staffing_shortfall": "Connecting support agent headcount and schedule-adherence data (not currently ingested) would confirm or rule out a staffing gap.",
    "unclassified_theme": "The theme's language doesn't match a known cause category — a human reviewer tagging a few excerpts would let the taxonomy learn it.",
}


def classify_theme(theme: ThemeCandidate) -> str:
    haystack = " ".join(theme.keywords).lower()
    for keywords, category in _TAXONOMY:
        if any(kw in haystack for kw in keywords):
            return category
    return "unclassified_theme"


@dataclass
class HypothesisResult:
    cause_category: str
    cause_display: str
    confidence: float
    rank: int
    status: str  # validated | candidate
    structured: StructuredCandidate | None
    theme: ThemeCandidate | None
    disambiguation_gap: str | None


def _find_aligned_theme(
    structured: StructuredCandidate | None, themes: list[ThemeCandidate]
) -> tuple[str | None, ThemeCandidate | None]:
    """Checks EVERY discovered theme for taxonomy + structured-driver alignment — not just the
    highest-frequency one. A real convergence can sit on a lower-ranked theme (e.g. the
    dominant theme by volume is generic complaints, but a smaller, second theme is the one that
    actually matches the structured signal's cause category); only checking themes[0] would
    silently miss it and fall back to a false "ambiguous" instead of a true "validated".

    If more than one theme aligns (rare — two different themes both classifying into the same
    category the structured candidate corroborates), the one with the strongest thematic
    signal (spike_ratio) wins, consistent with how confidence already weighs theme strength
    below — not simply "whichever was ranked first".
    """
    if not structured or not themes:
        return None, None
    aligned = [
        (classify_theme(theme), theme)
        for theme in themes
        if structured.metric_key in CAUSE_STRUCTURED_DRIVERS.get(classify_theme(theme), set())
    ]
    if not aligned:
        return None, None
    aligned.sort(key=lambda pair: pair[1].spike_ratio, reverse=True)
    return aligned[0]


def run_convergence(
    structured: StructuredCandidate | None,
    themes: list[ThemeCandidate],
) -> list[HypothesisResult]:
    aligned_category, aligned_theme = _find_aligned_theme(structured, themes)

    if aligned_category and aligned_theme:
        confidence = min(0.97, 0.5 + 0.28 * min(abs(structured.correlation), 1.0) + 0.12 * min(aligned_theme.spike_ratio / 3, 1.0))
        return [
            HypothesisResult(
                cause_category=aligned_category,
                cause_display=CAUSE_DISPLAY.get(aligned_category, aligned_category.replace("_", " ").title()),
                confidence=round(confidence, 2),
                rank=1,
                status="validated",
                structured=structured,
                theme=aligned_theme,
                disambiguation_gap=None,
            )
        ]

    # No (aligned) convergence — build ranked, transparent candidate hypotheses instead of
    # guessing. A structured correlation that failed the alignment check above still shows up
    # here, but honestly labeled as unconfirmed rather than laundered into a false cause.
    candidates: list[HypothesisResult] = []

    if themes:
        for theme in themes[:3]:
            category = classify_theme(theme)
            confidence = round(min(0.6, 0.22 + 0.045 * theme.doc_count), 2)
            candidates.append(
                HypothesisResult(
                    cause_category=category,
                    cause_display=CAUSE_DISPLAY.get(category, category.replace("_", " ").title()),
                    confidence=confidence,
                    rank=0,
                    status="candidate",
                    structured=None,
                    theme=theme,
                    disambiguation_gap=DISAMBIGUATION_MESSAGES.get(category, DISAMBIGUATION_MESSAGES["unclassified_theme"]),
                )
            )
    if structured:
        candidates.append(
            HypothesisResult(
                cause_category=f"correlated_signal_{structured.metric_key}",
                cause_display=f"Correlated with {structured.metric_name} — cause unconfirmed",
                confidence=round(min(0.55, 0.3 + 0.25 * min(abs(structured.correlation), 1.0)), 2),
                rank=0,
                status="candidate",
                structured=structured,
                theme=None,
                disambiguation_gap=(
                    "No thematically-relevant ticket, call-note, or survey evidence corroborates this correlation in the "
                    "same segment and window — with this little data, a co-moving metric alone could be coincidental. "
                    "Reviewing that segment's raw records directly would confirm it."
                ),
            )
        )
    if not candidates:
        candidates.append(
            HypothesisResult(
                cause_category="insufficient_evidence",
                cause_display="No converging evidence found",
                confidence=0.2,
                rank=0,
                status="candidate",
                structured=None,
                theme=None,
                disambiguation_gap=(
                    "Neither a correlated structured metric nor a thematic spike in unstructured text was found "
                    "for this segment and window — a broader data source may be needed to explain the anomaly."
                ),
            )
        )

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    for i, c in enumerate(candidates, start=1):
        c.rank = i
    return candidates
