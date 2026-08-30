import re

from app.models import TextEvidence
from app.pipeline.pii_redaction import redact

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\b")


def test_redacts_email():
    out = redact("Sent the receipt to jane.doe@example.com per request.")
    assert "jane.doe@example.com" not in out
    assert "[REDACTED_EMAIL]" in out


def test_redacts_phone():
    out = redact("Callback number is 415-555-0182 for follow-up.")
    assert "415-555-0182" not in out
    assert "[REDACTED_PHONE]" in out


def test_redacts_card_number():
    out = redact("Card ending in 4242 4242 4242 4242 was verified.")
    assert "4242 4242 4242 4242" not in out
    assert "[REDACTED_CARD]" in out


def test_leaves_non_pii_text_untouched():
    text = "App crashes immediately after opening the Product B dashboard."
    assert redact(text) == text


def test_no_pii_survives_into_the_stored_dataset(db_session):
    """End-to-end guarantee: whatever templates synthetic.py adds in the future, nothing
    matching an email/phone/card pattern should ever reach the TextEvidence table."""
    for row in db_session.query(TextEvidence).all():
        assert not _EMAIL_RE.search(row.text), row.text
        assert not _PHONE_RE.search(row.text), row.text
        assert not _CARD_RE.search(row.text), row.text
