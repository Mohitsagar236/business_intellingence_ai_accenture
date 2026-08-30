"""
Demo accounts, one per SRS §2.3 user class. Credentials are intentionally simple and
documented in the README — this is a local reference implementation, not a production
identity system. Change `jwt_secret` and these passwords before exposing this anywhere.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password

USERS: list[dict] = [
    {
        "username": "analyst",
        "password": "analyst123",
        "display_name": "Alex Analyst",
        "role": "analyst",
        "department": None,
    },
    {
        "username": "depthead",
        "password": "depthead123",
        "display_name": "Dana Department-Head",
        "role": "dept_head",
        "department": "Support",
    },
    {
        "username": "admin",
        "password": "admin123",
        "display_name": "Priya Admin",
        "role": "admin",
        "department": None,
    },
    {
        "username": "exec",
        "password": "exec123",
        "display_name": "Evan Executive",
        "role": "executive",
        "department": None,
    },
]


def seed(session: Session) -> None:
    for entry in USERS:
        session.add(
            User(
                username=entry["username"],
                password_hash=hash_password(entry["password"]),
                display_name=entry["display_name"],
                role=entry["role"],
                department=entry["department"],
            )
        )
    session.commit()
