"""
PII redaction — Design Doc §8: "A PII-redaction pass on unstructured text before it enters
the evidence index." Applied at ingestion time (Stage 1), before a TextEvidence row is ever
persisted, so no raw PII reaches storage, the theme miner, or a generated report.

Regex-based rather than an NER model: the categories that actually show up in support-ticket
text (emails, phone numbers, card numbers, SSNs) are pattern-shaped, and a deterministic pass
is auditable — a reviewer can see exactly what triggers a redaction, unlike a black-box model.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    # Credit-card-shaped runs (13-16 digits, optionally grouped) checked before phone numbers,
    # since a card number would otherwise also match the looser phone pattern below.
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
]


def redact(text: str) -> str:
    """Replaces detected PII with a labeled placeholder, preserving sentence structure so the
    text is still usable for theme mining. Order matters: card numbers are matched before the
    looser phone pattern so a 16-digit card isn't partially swallowed as a phone number."""
    redacted = text
    for label, pattern in _PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{label}]", redacted)
    return redacted
