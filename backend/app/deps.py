"""FastAPI dependencies for authentication and role gating."""
from __future__ import annotations

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.db import get_db
from app.logging_config import event
from app.models import User
from app.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)

ROLES = ("analyst", "dept_head", "admin", "executive")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = db.query(User).filter(User.username == payload.get("sub")).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")
    return user


def require_roles(*allowed: str):
    def _check(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if user.role not in allowed:
            event(logger, logging.WARNING, "authorization_denied", username=user.username, role=user.role, requires=",".join(allowed))
            record_audit(
                db,
                username=user.username,
                role=user.role,
                action="authorization_denied",
                success=False,
                detail=f"requires: {', '.join(allowed)}",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted to perform this action (requires: {', '.join(allowed)})",
            )
        return user

    return _check
