"""
Auth primitives — password hashing and JWT issuance/verification for the role-based login
(Design Doc §8, "RBAC on connectors/reports"; SRS §2.3 user classes).

Password hashing uses stdlib `hashlib.pbkdf2_hmac` (SHA-256, 260k iterations, a random salt
per password) rather than bcrypt/argon2 — no native/compiled dependency to install, and
260k-iteration PBKDF2-SHA256 is an OWASP-acceptable choice for a project at this scale.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os

import jwt

from app.config import get_settings

settings = get_settings()

_PBKDF2_ITERATIONS = 260_000
_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return base64.b64encode(salt + derived).decode("ascii")


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        raw = base64.b64decode(stored_hash)
    except Exception:
        return False
    salt, expected = raw[:16], raw[16:]
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(derived, expected)


def create_access_token(*, subject: str, role: str, expires_minutes: int = 60 * 12) -> str:
    now = dt.datetime.now(dt.UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (caught by the caller) on an invalid/expired token."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])
