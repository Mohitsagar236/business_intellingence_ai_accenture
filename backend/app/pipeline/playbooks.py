"""Stage 4a — Playbook Matching (SRS FR-4.1)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Playbook


def match_playbook(db: Session, cause_category: str) -> Playbook | None:
    return db.query(Playbook).filter(Playbook.cause_category == cause_category).one_or_none()
