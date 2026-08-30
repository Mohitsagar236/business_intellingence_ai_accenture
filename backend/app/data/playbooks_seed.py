"""Vetted playbook library — Stage 4a (Playbook Matching, FR-4.1) looks up by cause_category."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Playbook

PLAYBOOKS: list[dict] = [
    {
        "cause_category": "billing_system_outage",
        "title": "Billing / payment-gateway outage response",
        "owner_department": "Sales",
        "actions": [
            "Page the payments on-call engineer to confirm gateway health and open an incident.",
            "Post a status update to affected customers in the impacted region/product.",
            "Waive late fees and proactively retry failed transactions once the gateway recovers.",
            "Reconcile the affected transaction batch with Finance within 24 hours.",
        ],
    },
    {
        "cause_category": "product_regression",
        "title": "Recent-release product regression triage",
        "owner_department": "Engineering",
        "actions": [
            "Check the deploy log for releases in the affected window and identify the likely commit.",
            "Reproduce the reported crash/login failure on the affected platform.",
            "Ship a hotfix or roll back the suspect release.",
            "Notify Support with a canned response for affected customers.",
        ],
    },
    {
        "cause_category": "staffing_shortfall",
        "title": "Support queue staffing shortfall response",
        "owner_department": "Support",
        "actions": [
            "Pull current agent headcount and schedule adherence for the affected channel/region.",
            "Reallocate agents from lower-volume channels for the remainder of the shift.",
            "Enable overflow routing or a callback queue to cut wait times.",
            "Review shift scheduling for the affected region for the coming week.",
        ],
    },
    {
        "cause_category": "data_quality_issue",
        "title": "Source-system data-quality remediation",
        "owner_department": "Data Engineering",
        "actions": [
            "Identify the sync job or connector that produced the duplicate/invalid records.",
            "Purge or de-duplicate the affected rows before they reach reporting.",
            "Add a validation rule to the ingestion pipeline to catch recurrence.",
            "Notify the metric owner that the affected window's figures were corrected.",
        ],
    },
    {
        "cause_category": "demand_variation",
        "title": "Normal demand variation — no action required",
        "owner_department": "Operations",
        "actions": [
            "No intervention needed; the deviation is within expected seasonal variation.",
            "Continue routine monitoring.",
        ],
    },
]


def seed(session: Session) -> None:
    for entry in PLAYBOOKS:
        session.add(Playbook(**entry))
    session.commit()
