"""
Stage 4d — Intelligent Routing (SRS FR-4.4).

No live Slack/email credentials are available in this environment, so "dispatch" means
setting the report's routed_to department, which the frontend surfaces as a per-department
inbox (Dashboard/Admin filter). The function is isolated so a real email/Slack sender can
be substituted here later without touching the orchestrator.
"""
from __future__ import annotations

from app.models import Playbook


def resolve_department(playbook: Playbook | None, fallback_department: str) -> str:
    if playbook:
        return playbook.owner_department
    return fallback_department
